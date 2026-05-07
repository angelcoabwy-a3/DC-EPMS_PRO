"""
DC-EPMS PRO - Physics Engine Smoke Test
========================================
End-to-end demonstration of the Fase 4a physics modules.

Runs:
  1. Nominal validation on all 3 modules (IT / Mechanical / Electrical)
  2. Fault-injection validation (each module receives a bad measurement)
  3. Site Health Index calculation using min() rule
  4. 15-minute utility-loss simulation (electrical ODE)
  5. 15-minute total cooling loss simulation (IT thermal ODE)

Usage:
    python scripts/physics_smoke_test.py

Expected runtime: ~3 seconds on a modern CPU.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.physics import (
    ElectricalModule,
    ITThermalModule,
    MechanicalModule,
    Severity,
)


# --- Formatting helpers ----------------------------------------------------

def banner(text: str) -> None:
    print()
    print("=" * 70)
    print(f"  {text}")
    print("=" * 70)


def color_for_severity(s: Severity) -> str:
    # ANSI colors; on Windows PowerShell 7+ and most terminals this works
    return {
        Severity.OK: "\033[32m",        # green
        Severity.INFO: "\033[36m",      # cyan
        Severity.WARNING: "\033[33m",   # yellow
        Severity.CRITICAL: "\033[31m",  # red
    }.get(s, "")


def reset_color() -> str:
    return "\033[0m"


def print_result(label: str, r) -> None:
    col = color_for_severity(r.severity)
    print(
        f"{col}  {label:<14}{reset_color()} "
        f"severity={r.severity.value:<8} "
        f"health={r.health:.2f}  "
        f"checks={len(r.checks)} "
        f"justifications={len(r.justifications)}"
    )
    # Print failed checks
    for c in r.checks:
        if not c["passed"]:
            val = c["value"]
            thr = c["threshold"]
            unit = c.get("unit", "")
            thr_str = f"{thr:.2f}" if thr is not None else "n/a"
            print(
                f"    [FAIL] {c['name']:<40} "
                f"value={val:+.2f} {unit}  threshold={thr_str} {unit}"
            )


def print_justification(j) -> None:
    print(f"    Law: {j.law}")
    print(f"    Measured:    {j.measured}")
    print(f"    Expected:    {j.expected}")
    print(f"    Residual:    {j.residual}")
    print(f"    Threshold:   {j.threshold}")
    print(f"    Interpretation: {j.interpretation}")
    print(f"    Action:         {j.suggested_action}")


# --- Scenarios -------------------------------------------------------------

def scenario_nominal():
    banner("SCENARIO 1: Nominal telemetry (everything healthy)")
    it = ITThermalModule()
    mech = MechanicalModule()
    elec = ElectricalModule()

    # IT nominal: 118 racks at 142 kW, 100 L/min per rack, balanced
    r_it = it.validate({
        "rack_count": 118,
        "rack_tdp_kw": 142.0,
        "dlc_supply_c": 18.0,
        "dlc_return_c": 18.0 + 21.3,  # dT balanced at 100 L/min
        "dlc_flow_l_min": 100.0,
        "hall_inlet_c": 20.0,
        "gpu_tj_max_c": 70.0,
    })

    # Mechanical nominal: hall-level aggregate
    r_mech = mech.validate({
        "loop_flow_m3_s": 0.066,          # 4000 L/min per hall
        "loop_dp_measured_bar": 2.17,     # matches Darcy-Weisbach
        "loop_supply_c": 18.0,
        "loop_return_c": 40.0,
        "cdu_primary_in_c": 7.0,
        "cdu_primary_out_c": 27.0,        # balanced CDU
        "cdu_primary_flow_m3_s": 0.066,
        "pump_speed_hz": 60.0,
        "pump_suction_bar": 1.8,
        "pump_power_kw": 45.0,
    })

    # Electrical nominal: 50% load for peak efficiency
    r_elec = elec.validate({
        "utility_kw": 17_400.0,
        "facility_it_kw": 16_756.0,
        "ups_load_kw": 300.0,
        "ups_mode": "online",
        "ups_input_kw": 300.0 / 0.96,     # 96% efficiency peak
        "xfmr_load_kva": 1_800.0,
        "xfmr_top_oil_c": 65.0,
        "xfmr_winding_c": 98.7,           # matches C57.12 at 72% load
        "battery_soc": 1.0,
        "battery_vdc": 540.0,
        "battery_on_load": False,
    })

    print_result("IT thermal",  r_it)
    print_result("Mechanical",  r_mech)
    print_result("Electrical",  r_elec)

    site_health = min(r_it.health, r_mech.health, r_elec.health)
    weakest = min(
        [("IT", r_it.health), ("Mech", r_mech.health), ("Elec", r_elec.health)],
        key=lambda x: x[1],
    )
    print()
    print(f"  Site Health Index (min rule): {site_health:.2f}")
    print(f"  Weakest module:               {weakest[0]}")


def scenario_fault_injection():
    banner("SCENARIO 2: Fault injection across all 3 modules")

    it = ITThermalModule()
    mech = MechanicalModule()
    elec = ElectricalModule()

    # Fault 1: IT - DLC flow lost, GPU throttling
    print("\n  [IT] DLC flow halved + GPU approaching throttle")
    r_it = it.validate({
        "rack_count": 118,
        "rack_tdp_kw": 142.0,
        "dlc_supply_c": 18.0,
        "dlc_return_c": 65.0,  # way too hot
        "dlc_flow_l_min": 50.0,  # half nominal
        "hall_inlet_c": 26.0,   # above ops band
        "gpu_tj_max_c": 88.0,   # WARN range
    })
    print_result("IT thermal", r_it)
    if r_it.justifications:
        print(f"\n  Sample physical justification:")
        print_justification(r_it.justifications[0])

    # Fault 2: Mechanical - pump cavitation
    print("\n  [Mechanical] Pump suction below NPSH minimum")
    r_mech = mech.validate({
        "loop_flow_m3_s": 0.066,
        "loop_dp_measured_bar": 2.17,
        "loop_supply_c": 18.0,
        "loop_return_c": 40.0,
        "cdu_primary_in_c": 7.0,
        "cdu_primary_out_c": 27.0,
        "cdu_primary_flow_m3_s": 0.066,
        "pump_speed_hz": 60.0,
        "pump_suction_bar": 0.5,  # CRITICAL: below 1.2 bar NPSH
        "pump_power_kw": 45.0,
    })
    print_result("Mechanical", r_mech)

    # Fault 3: Electrical - transformer winding overtemp
    print("\n  [Electrical] Transformer winding above C57.12 limit")
    r_elec = elec.validate({
        "utility_kw": 17_400.0,
        "facility_it_kw": 16_756.0,
        "ups_load_kw": 300.0,
        "ups_mode": "online",
        "ups_input_kw": 300.0 / 0.96,
        "xfmr_load_kva": 2_200.0,
        "xfmr_top_oil_c": 95.0,
        "xfmr_winding_c": 140.0,  # above 130 C limit
        "battery_soc": 1.0,
        "battery_vdc": 540.0,
        "battery_on_load": False,
    })
    print_result("Electrical", r_elec)

    site_health = min(r_it.health, r_mech.health, r_elec.health)
    weakest = min(
        [("IT", r_it.health), ("Mech", r_mech.health), ("Elec", r_elec.health)],
        key=lambda x: x[1],
    )
    print()
    print(f"  Site Health Index (min rule): {site_health:.2f}")
    print(f"  Weakest module:               {weakest[0]}")


def scenario_utility_loss_sim():
    banner("SCENARIO 3: Utility loss simulation (electrical ODE, 15 min)")
    elec = ElectricalModule()

    print("  Running 15-min simulation...")
    print("  Utility fails at t=0 / Generator online at t=10 s / Load 600 kW")

    traj = elec.simulate(
        initial_state={"battery_soc": 1.0, "ups_load_kw": 600.0},
        perturbation={
            "utility_fail": True,
            "start_s": 0,
            "generator_start_s": 10.0,  # NFPA 110 Type 10
            "load_kw": 600.0,
        },
        horizon_s=900,
        dt_s=1.0,
    )

    print(f"\n  Generated {len(traj)} state snapshots")
    print()
    print(f"  {'Time':>8} {'SOC':>8} {'Vdc':>8} {'OnBatt':>8} {'Runtime':>10}")
    for i in [0, 5, 10, 30, 60, 120, 300, 600, 900]:
        if i < len(traj):
            s = traj[i]
            rt = s.state.get("runtime_remaining_min", float("inf"))
            rt_str = f"{rt:.1f}min" if rt != float("inf") else "inf"
            print(
                f"  {s.t:>7.0f}s "
                f"{s.state['battery_soc']:>7.2%} "
                f"{s.state['battery_vdc']:>6.1f} V "
                f"{'YES' if s.state['on_battery'] else 'NO':>7} "
                f"{rt_str:>10}"
            )

    events = [(snap.t, e) for snap in traj for e in snap.events]
    if events:
        print()
        print("  Events fired:")
        for t, e in events:
            print(f"    t={t:>5.0f}s  {e}")


def scenario_total_cooling_loss_sim():
    banner("SCENARIO 4: Total cooling loss (IT thermal ODE, 15 min)")
    it = ITThermalModule()

    print("  Cooling factor = 0.0 (total loss) from t=0 to t=900")
    print("  Expected: Time-to-critical (35C) ~44 s per thermal model")

    traj = it.simulate(
        initial_state={
            "hall_return_c": 22.0,
            "rack_count": 118,
            "rack_tdp_kw": 142.0,
            "dlc_supply_c": 18.0,
            "dlc_flow_l_min": 100.0,
        },
        perturbation={
            "cooling_factor": 0.0,
            "dlc_flow_factor": 0.0,
            "start_s": 0,
            "duration_s": 900,
        },
        horizon_s=300,
        dt_s=1.0,
    )

    print(f"\n  Generated {len(traj)} state snapshots")
    print()
    print(f"  {'Time':>8} {'HallAir':>10} {'GPU_Tj':>10} {'DLC_dT':>10}")
    for i in [0, 10, 30, 44, 60, 120, 180, 240, 300]:
        if i < len(traj):
            s = traj[i]
            print(
                f"  {s.t:>7.0f}s "
                f"{s.state['hall_air_c']:>8.1f} C "
                f"{s.state['gpu_tj_estimate_c']:>8.1f} C "
                f"{s.state['dlc_delta_T_k']:>8.1f} K"
            )

    # Analytic TTC calculation for comparison
    ttc = it.time_to_critical_s(
        current_temp_c=22.0,
        cooling_factor=0.0,
        critical_temp_c=35.0,
    )
    print()
    print(f"  Analytic TTC to 35 C:  {ttc:.1f} seconds")

    events = [(snap.t, e) for snap in traj for e in snap.events]
    if events:
        print()
        print("  Events fired:")
        for t, e in events[:10]:  # first 10
            print(f"    t={t:>5.0f}s  {e}")


def main():
    print()
    print("DC-EPMS PRO - Fase 4a Physics Smoke Test")
    print("A-Cubed Semiconductor Systems Inc.")

    scenario_nominal()
    scenario_fault_injection()
    scenario_utility_loss_sim()
    scenario_total_cooling_loss_sim()

    banner("Smoke test complete.")
    print()


if __name__ == "__main__":
    main()
