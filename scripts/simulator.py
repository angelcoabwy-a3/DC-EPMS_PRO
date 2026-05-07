"""
DC-EPMS PRO  -  Telemetry Simulator
===================================
Generates realistic Blackwell NVL72 telemetry and pushes it to PostgreSQL
via the /api/telemetry endpoint. Use for:
  - Dashboard demos without a physical facility
  - Smoke-testing the full stack
  - Generating incident scenarios for shift report testing

Physics model:
  - Fleet: 118 racks x 142 kW NVL72 = 16,756 kW nominal (±3%)
  - PUE: 1.10 base + thermal coupling + stochastic noise
  - Hall temp: slow walk 22-26C with daily variation
  - Scenarios: NORMAL | chillerFail | loseNorth | fireAlarm

Run:
    python scripts/simulator.py                 # run continuously
    python scripts/simulator.py --scenario chillerFail --duration 60
    python scripts/simulator.py --incidents     # also generate incidents
"""

from __future__ import annotations

import argparse
import asyncio
import math
import random
import sys
from datetime import UTC, datetime

try:
    import httpx
except ImportError:
    print("ERROR: httpx required. Install: pip install httpx")
    sys.exit(1)


BACKEND_URL = "http://localhost:8080"


class FacilitySimulator:
    """Physics-based Blackwell fleet simulator."""

    def __init__(self):
        self.tick = 0
        self.hall_temp = 22.6  # steady-state
        self.scenario = "NORMAL"
        self.scenario_ticks_remaining = 0

    def advance(self) -> dict:
        """Advance physics one tick (~5 seconds of simulated time)."""
        self.tick += 1

        # Decrement scenario countdown
        if self.scenario_ticks_remaining > 0:
            self.scenario_ticks_remaining -= 1
            if self.scenario_ticks_remaining == 0:
                self.scenario = "NORMAL"

        # -- IT load: 118 racks x 142 kW ± 3% ------------------
        variance = 1 + (random.random() - 0.5) * 0.06
        it_load_kw = round(118 * 142 * variance, 2)

        # -- Hall temperature: slow walk + scenario impact -----
        # Daily sinusoidal variation (24h period, ±0.5C)
        hour = datetime.now(UTC).hour + datetime.now(UTC).minute / 60
        diurnal = 0.5 * math.sin(2 * math.pi * hour / 24)

        # Random walk
        self.hall_temp += (random.random() - 0.5) * 0.1

        # Scenario impact
        if self.scenario == "chillerFail":
            # Temperature rises exponentially toward 35C
            delta = 35.0 - self.hall_temp
            self.hall_temp += delta * 0.08  # 8% of delta per tick
        elif self.scenario == "NORMAL":
            # Drift toward 22.6 setpoint
            self.hall_temp += (22.6 - self.hall_temp) * 0.05

        # Clamp
        self.hall_temp = max(18.0, min(40.0, self.hall_temp))
        hall_t = round(self.hall_temp + diurnal, 2)

        # -- PUE: 1.10 base + thermal coupling + noise ---------
        pue_thermal = max(0, (hall_t - 18) * 0.002)
        pue_edge = 0.005 if random.random() < 0.3 else 0  # simulated GPU load
        pue_stochastic = random.random() * 0.003
        pue = round(1.10 + pue_thermal + pue_edge + pue_stochastic, 4)

        # Scenario degradation
        if self.scenario == "chillerFail":
            pue += round((hall_t - 22) * 0.01, 4)

        # -- TTC calculation (exponential Newton model) --------
        ttc = None
        if hall_t < 35.0 and self.scenario == "chillerFail":
            tau = 53.3
            try:
                ratio = (35.0 - 30.0) / (hall_t - 30.0) if hall_t > 30 else None
                if ratio and 0 < ratio < 1:
                    ttc = round(-tau * math.log(ratio))
            except (ValueError, ZeroDivisionError):
                ttc = None

        return {
            "it_load_kw": it_load_kw,
            "pue": pue,
            "hall_temp_c": hall_t,
            "delta_t_c": round(hall_t - 18.0, 2),
            "ttc_seconds": ttc,
            "scenario": self.scenario,
            "rack_count": 118,
            "rack_tdp_kw": 142,
        }

    def trigger_scenario(self, name: str, duration_ticks: int = 30):
        """Trigger a scenario for N ticks."""
        self.scenario = name
        self.scenario_ticks_remaining = duration_ticks


class IncidentGenerator:
    """Produces realistic incidents based on current telemetry state."""

    TEMPLATES = [
        ("MORPHEUS", "info", "Modbus baseline traffic reset"),
        ("MORPHEUS", "warning", "Anomalous DNP3 traffic on SL-2 zone"),
        ("GEMINI_ER16", "warning", "Robot detected cable management issue Rack-B12"),
        ("GEMINI_ER16", "critical", "Moisture trace on raised floor tile F-47"),
        ("PHYSICS", "critical", "Chiller-2 pressure drop >15 percent"),
        ("PHYSICS", "warning", "CRAH-03 outlet temp elevated 24.2C"),
        ("UPS", "info", "UPS-A battery load test completed nominal"),
        ("UPS", "warning", "UPS-B battery voltage deviation 2.3%"),
        ("FIRE", "info", "VESDA sensor array self-test passed"),
    ]

    def __init__(self, counter_start: int = 1):
        self.counter = counter_start

    def generate(self, telemetry: dict) -> dict | None:
        """Randomly generate an incident (30% chance)."""
        if random.random() > 0.30:
            return None

        source, severity, title = random.choice(self.TEMPLATES)

        # Escalate severity if PUE critical
        if telemetry.get("pue", 0) > 1.40 and severity == "info":
            severity = "warning"

        self.counter += 1
        year = datetime.now(UTC).year
        incident_id = f"INC-{year}-{self.counter:04d}"

        return {
            "incident_id": incident_id,
            "source": source,
            "title": title,
            "detail": f"Auto-generated by simulator at tick. "
            f"PUE={telemetry.get('pue')} temp={telemetry.get('hall_temp_c')}C",
            "severity": severity,
            "status": "OPEN",
            "physics_json": str(
                {
                    "pue": telemetry.get("pue"),
                    "temp": telemetry.get("hall_temp_c"),
                    "scenario": telemetry.get("scenario"),
                }
            ).replace("'", '"'),
        }


async def push_telemetry(client: httpx.AsyncClient, point: dict) -> bool:
    try:
        resp = await client.post(
            f"{BACKEND_URL}/api/telemetry",
            json=point,
            timeout=5.0,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"  [telemetry] push failed: {e}")
        return False


async def push_incident(client: httpx.AsyncClient, incident: dict) -> bool:
    try:
        resp = await client.post(
            f"{BACKEND_URL}/api/incidents",
            json=incident,
            timeout=5.0,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"  [incident] push failed: {e}")
        return False


async def run(args):
    sim = FacilitySimulator()
    inc_gen = IncidentGenerator(counter_start=1000)

    if args.scenario:
        print(f"Triggering scenario: {args.scenario} for {args.duration} ticks")
        sim.trigger_scenario(args.scenario, args.duration)

    print(f"Backend: {BACKEND_URL}")
    print(f"Interval: {args.interval}s")
    print(f"Incidents: {'ON' if args.incidents else 'OFF'}")
    print("Press Ctrl+C to stop")
    print()
    print(f"{'tick':>5} {'scenario':>14} {'pue':>6} {'temp':>7} {'load':>10} {'ttc':>6}")
    print("-" * 62)

    async with httpx.AsyncClient() as client:
        try:
            while True:
                point = sim.advance()
                await push_telemetry(client, point)

                ttc_str = str(point.get("ttc_seconds") or " - ")
                print(
                    f"{sim.tick:>5} {point['scenario']:>14} "
                    f"{point['pue']:>6.3f} {point['hall_temp_c']:>5.1f}degC "
                    f"{point['it_load_kw']:>8,.0f}kW {ttc_str:>6}"
                )

                if args.incidents:
                    inc = inc_gen.generate(point)
                    if inc:
                        await push_incident(client, inc)
                        sev = inc["severity"].upper()
                        print(f"      ↳ incident {inc['incident_id']} [{sev}] {inc['title']}")

                await asyncio.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")


def main():
    global BACKEND_URL  # must be first - declared before any other reference

    p = argparse.ArgumentParser(description="DC-EPMS PRO telemetry simulator")
    p.add_argument(
        "--interval", type=float, default=5.0, help="Seconds between telemetry points (default 5)"
    )
    p.add_argument(
        "--scenario", choices=["chillerFail", "loseNorth", "fireAlarm"], help="Trigger scenario"
    )
    p.add_argument(
        "--duration", type=int, default=30, help="Scenario duration in ticks (default 30)"
    )
    p.add_argument("--incidents", action="store_true", help="Also generate incidents")
    p.add_argument("--backend", default=BACKEND_URL, help=f"Backend URL (default {BACKEND_URL})")
    args = p.parse_args()

    BACKEND_URL = args.backend

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
