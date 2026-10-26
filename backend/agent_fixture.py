"""Raw-evidence fixture for the agentic investigator (hackathon).

ONLY raw material lives here: alarms, trends, breaker states, and
reference procedure texts. There is deliberately NO triage, NO priority,
NO story, and NO pre-tested hypotheses: correlation and conclusions are
the agent's job (tool loop) with the deterministic safety layer in
``copilot_agent.py`` having the last word on priority.

``true_cause`` is a test-oracle label for the offline suite. It is NEVER
returned by any tool and NEVER sent to the model.

Severity vocabulary is fixture-local: critical / high / medium / low /
info. The priority floor in ``copilot_agent.py`` keys off it.
"""

from __future__ import annotations

import copy

BASE_UTILITY = "2026-10-26T14:00:00+00:00"
BASE_COOLING = "2026-10-26T15:00:00+00:00"

SCENARIOS: dict = {
    "burst-utility-01": {
        "scenario_id": "burst-utility-01",
        "description": "Alarm burst around a utility feed disturbance.",
        "true_cause": "utility_loss",
        "alarms": [
            {
                "id": "U-01",
                "source": "ATS",
                "severity": "critical",
                "title": "Utility-A voltage loss detected",
                "timestamp": "2026-10-26T14:00:00+00:00",
                "t_offset_min": 0,
            },
            {
                "id": "U-02",
                "source": "ATS",
                "severity": "critical",
                "title": "ATS transfer to generator initiated",
                "timestamp": "2026-10-26T14:02:00+00:00",
                "t_offset_min": 2,
            },
            {
                "id": "U-03",
                "source": "UPS",
                "severity": "high",
                "title": "UPS-A on battery, 12 min runtime estimated",
                "timestamp": "2026-10-26T14:03:00+00:00",
                "t_offset_min": 3,
            },
            {
                "id": "U-04",
                "source": "GENERATOR",
                "severity": "info",
                "title": "Generator-1 crank started",
                "timestamp": "2026-10-26T14:04:00+00:00",
                "t_offset_min": 4,
            },
            {
                "id": "U-05",
                "source": "GENERATOR",
                "severity": "medium",
                "title": "Generator-1 frequency stabilizing 59.8 Hz",
                "timestamp": "2026-10-26T14:06:00+00:00",
                "t_offset_min": 6,
            },
            {
                "id": "U-06",
                "source": "FIRE",
                "severity": "info",
                "title": "VESDA self-test during transfer completed",
                "timestamp": "2026-10-26T14:07:00+00:00",
                "t_offset_min": 7,
            },
        ],
        "trends": {
            "util-a-voltage-kv": {
                "unit": "kV",
                "samples": [
                    {"t": "2026-10-26T13:56:00+00:00", "value": 27.5},
                    {"t": "2026-10-26T13:58:00+00:00", "value": 27.4},
                    {"t": "2026-10-26T14:00:00+00:00", "value": 12.1},
                    {"t": "2026-10-26T14:02:00+00:00", "value": 0.4},
                    {"t": "2026-10-26T14:04:00+00:00", "value": 0.0},
                ],
            },
            "ups-a-runtime-min": {
                "unit": "min",
                "samples": [
                    {"t": "2026-10-26T14:03:00+00:00", "value": 12.0},
                    {"t": "2026-10-26T14:05:00+00:00", "value": 11.0},
                    {"t": "2026-10-26T14:07:00+00:00", "value": 10.0},
                    {"t": "2026-10-26T14:09:00+00:00", "value": 9.0},
                ],
            },
        },
        "breakers": {
            "util-a-feeder": {"state": "open", "last_change": "2026-10-26T14:01:00+00:00"},
            "ats-a-main": {"state": "closed", "last_change": "2026-10-26T14:02:00+00:00"},
        },
    },
    "burst-cooling-02": {
        "scenario_id": "burst-cooling-02",
        "description": "Alarm burst around a chiller mechanical fault.",
        "true_cause": "cooling_loss",
        "alarms": [
            {
                "id": "C-01",
                "source": "PHYSICS",
                "severity": "critical",
                "title": "Chiller-2 pressure drop >15 percent",
                "timestamp": "2026-10-26T15:00:00+00:00",
                "t_offset_min": 0,
            },
            {
                "id": "C-02",
                "source": "PHYSICS",
                "severity": "medium",
                "title": "CRAH-03 outlet temp elevated 24.2C",
                "timestamp": "2026-10-26T15:03:00+00:00",
                "t_offset_min": 3,
            },
            {
                "id": "C-03",
                "source": "PHYSICS",
                "severity": "medium",
                "title": "CRAH-04 outlet temp elevated 23.8C",
                "timestamp": "2026-10-26T15:05:00+00:00",
                "t_offset_min": 5,
            },
            {
                "id": "C-04",
                "source": "BMS",
                "severity": "low",
                "title": "Chilled water setpoint adjusted +1C",
                "timestamp": "2026-10-26T15:06:00+00:00",
                "t_offset_min": 6,
            },
            {
                "id": "C-05",
                "source": "FIRE",
                "severity": "info",
                "title": "VESDA sensor array self-test passed",
                "timestamp": "2026-10-26T15:07:00+00:00",
                "t_offset_min": 7,
            },
        ],
        "trends": {
            "chiller-2-pressure-kpa": {
                "unit": "kPa",
                "samples": [
                    {"t": "2026-10-26T14:56:00+00:00", "value": 820.0},
                    {"t": "2026-10-26T14:58:00+00:00", "value": 700.0},
                    {"t": "2026-10-26T15:00:00+00:00", "value": 610.0},
                    {"t": "2026-10-26T15:02:00+00:00", "value": 540.0},
                ],
            },
            "crah-03-outlet-c": {
                "unit": "C",
                "samples": [
                    {"t": "2026-10-26T14:59:00+00:00", "value": 21.5},
                    {"t": "2026-10-26T15:01:00+00:00", "value": 22.8},
                    {"t": "2026-10-26T15:03:00+00:00", "value": 23.9},
                    {"t": "2026-10-26T15:05:00+00:00", "value": 24.2},
                ],
            },
        },
        "breakers": {
            "chiller-2-feeder": {"state": "closed", "last_change": "2026-10-26T14:00:00+00:00"},
            "crah-03-feeder": {"state": "closed", "last_change": "2026-10-26T14:00:00+00:00"},
        },
    },
}

PROCEDURE_TEXT: dict = {
    "utility_loss": {
        "procedure_id": "MOP-ATS-MONTHLY-001",
        "title": "Loss of utility feed response",
        "steps": [
            "Confirm utility feed state and ATS position in person.",
            "Verify load is carried by the emergency source before any switching.",
            "Log all actions with timestamps for the shift record.",
        ],
    },
    "ats_transfer_fault": {
        "procedure_id": "MOP-ATS-MONTHLY-001",
        "title": "ATS transfer fault response",
        "steps": [
            "Confirm ATS position indication matches the actual lineup in person.",
            "Do not force a transfer while the fault is unconfirmed.",
            "Log all actions with timestamps for the shift record.",
        ],
    },
    "generator_fault": {
        "procedure_id": "NFPA110-TYPE10",
        "title": "Emergency generator fault response",
        "steps": [
            "Confirm fuel level, frequency, load, and coolant temperature in person.",
            "Keep the failed unit isolated until the fault is cleared.",
            "Log all actions with timestamps for the shift record.",
        ],
    },
    "ups_fault": {
        "procedure_id": "T4-MOP-UPS-001",
        "title": "UPS fault response",
        "steps": [
            "Confirm battery runtime remaining and battery voltage in person.",
            "Reduce non-critical load if runtime is short.",
            "Log all actions with timestamps for the shift record.",
        ],
    },
    "cooling_loss": {
        "procedure_id": "EOP-COOLING-LOSS-001",
        "title": "Cooling loss response",
        "steps": [
            "Confirm chiller pressure and CRAH outlet temperatures in person.",
            "Verify chilled water setpoint and standby cooling availability.",
            "Log all actions with timestamps for the shift record.",
        ],
    },
    "fire_event": {
        "procedure_id": "EOP-FIRE-001",
        "title": "Fire detection response",
        "steps": [
            "Confirm panel alarm state and area condition in person before resuming work.",
            "Do not silence panels until the area is verified clear.",
            "Log all actions with timestamps for the shift record.",
        ],
    },
}


def list_scenarios() -> list[str]:
    """Scenario ids available in the fixture."""
    return sorted(SCENARIOS.keys())


def get_alarms(scenario_id: str, window_minutes: float) -> list[dict]:
    """Raw alarms of one scenario inside the window (copies, never the store)."""
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        return []
    rows = [a for a in scenario["alarms"] if a["t_offset_min"] <= window_minutes]
    return copy.deepcopy(sorted(rows, key=lambda a: a["t_offset_min"]))


def get_trend(scenario_id: str, point_id: str) -> dict:
    """Short time series for one point (copy). Empty dict when unknown."""
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        return {}
    return copy.deepcopy(scenario["trends"].get(point_id, {}))


def get_breaker(scenario_id: str, breaker_id: str) -> dict:
    """Breaker state and last change time (copy). Empty dict when unknown."""
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        return {}
    return copy.deepcopy(scenario["breakers"].get(breaker_id, {}))


def get_procedure(event_type: str) -> dict:
    """Reference procedure text for one event type (copy). Empty dict when unknown."""
    return copy.deepcopy(PROCEDURE_TEXT.get(event_type, {}))
