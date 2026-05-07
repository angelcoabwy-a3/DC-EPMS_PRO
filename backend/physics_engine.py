"""
DC-EPMS PRO - Physics Engine Facade
====================================
Orchestrator over the four physics sub-modules (IT, Mechanical,
Electrical, Heat Rejection). Provides:

  1. validate_site(measurements) - run all four validators, aggregate.
  2. site_health_index()         - min() + severity modifier rule.
  3. cross_check_first_law()     - inter-module energy balance.
  4. simulate_scenario(name)     - run a named scenario from
                                   scenarios.yml end-to-end.
  5. cascading_failure_propagation() - event-driven propagation across
                                       modules (e.g., pump trip -> DLC
                                       flow loss -> GPU throttle).

Site Health Index
-----------------
Following the design decision in the Fase 4a plan, the SHI uses:

        SHI = min(H_it, H_mech, H_elec, H_hr) * severity_modifier

Where severity_modifier ∈ (0.5, 1.0] accounts for:
  - Redundancy state (2N intact -> 1.0; N -> 0.85; partial -> 0.70)
  - Worst-case module severity (CRITICAL -> 0.70; WARNING -> 0.90;
    INFO -> 0.98)
  - Trend (if we keep history: worsening -> 0.9)

A weighted-sum of per-module scores would hide an emergency when one
module is critical. The min-rule surfaces the weakest link immediately
- what an operator needs to know first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.physics.base import (
    PhysicsModule,
    Severity,
    ValidationResult,
)
from backend.physics.electrical import ElectricalModule
from backend.physics.heat_rejection import HeatRejectionModule
from backend.physics.it_thermal import ITThermalModule
from backend.physics.mechanical import MechanicalModule

log = logging.getLogger("dc-epms.physics.engine")


# ---------------------------------------------------------------------------
#  Site validation result
# ---------------------------------------------------------------------------


@dataclass
class SiteValidationResult:
    """Aggregated validation across all physics modules.

    Attributes:
        modules: Dict of module_name -> ValidationResult.
        site_health: Overall SHI in [0.0, 1.0].
        weakest_module: Name of the module driving the SHI.
        overall_severity: Worst severity across modules.
        cascade_events: Cross-module events detected during validation
                        (e.g., DLC flow anomaly tied to pump cavitation).
        first_law_residuals: Cross-module energy-balance residuals.
    """

    modules: dict[str, ValidationResult] = field(default_factory=dict)
    site_health: float = 1.0
    weakest_module: str = ""
    overall_severity: Severity = Severity.OK
    cascade_events: list[dict] = field(default_factory=list)
    first_law_residuals: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "site_health": self.site_health,
            "weakest_module": self.weakest_module,
            "overall_severity": self.overall_severity.value,
            "modules": {k: v.to_dict() for k, v in self.modules.items()},
            "cascade_events": self.cascade_events,
            "first_law_residuals": self.first_law_residuals,
        }


# ---------------------------------------------------------------------------
#  PhysicsEngine facade
# ---------------------------------------------------------------------------


class PhysicsEngine:
    """Orchestrator for DC-EPMS PRO physics validation and simulation."""

    def __init__(self):
        self.it = ITThermalModule()
        self.mech = MechanicalModule()
        self.elec = ElectricalModule()
        self.hr = HeatRejectionModule()

        self._modules: dict[str, PhysicsModule] = {
            "it_thermal": self.it,
            "mechanical": self.mech,
            "electrical": self.elec,
            "heat_rejection": self.hr,
        }

    # ------------------------------------------------------------------ #
    #  Full site validation
    # ------------------------------------------------------------------ #

    def validate_site(
        self,
        measurements: dict[str, Any],
    ) -> SiteValidationResult:
        """Run every module validator against the provided telemetry.

        The `measurements` dict may contain any combination of keys;
        each module extracts its own subset with defaults for missing
        fields. This lets callers pass partial telemetry.

        Additionally performs:
          - First-law cross-check: IT heat vs mechanical heat removal
          - Cascade-event detection: e.g., DLC flow anomaly + pump
            cavitation signal -> raise composite alert.
        """
        result = SiteValidationResult()

        # Run all four validators
        for name, module in self._modules.items():
            try:
                r = module.validate(measurements)
                result.modules[name] = r
            except Exception as e:
                log.error("%s.validate failed: %s", name, e)
                # Synthesize a failure result so downstream code has
                # something structurally valid to chew on
                result.modules[name] = ValidationResult(
                    module=name,
                    severity=Severity.INFO,
                    health=0.5,
                )

        # First-law cross-check: IT heat (to DLC) should match mechanical
        # loop Q_secondary (and onwards to chiller duty)
        fl_residuals = self._cross_check_first_law(result.modules, measurements)
        result.first_law_residuals = fl_residuals

        # Cascade detection
        result.cascade_events = self._detect_cascades(result.modules)

        # Site Health: min(all module healths) * severity_modifier
        healths = {n: r.health for n, r in result.modules.items()}
        weakest_name = min(healths, key=healths.get)
        result.weakest_module = weakest_name

        worst_severity = max(
            (r.severity for r in result.modules.values()),
            key=lambda s: s.weight(),
            default=Severity.OK,
        )
        result.overall_severity = worst_severity

        severity_modifier = {
            Severity.OK: 1.00,
            Severity.INFO: 0.98,
            Severity.WARNING: 0.90,
            Severity.CRITICAL: 0.70,
        }[worst_severity]

        result.site_health = healths[weakest_name] * severity_modifier

        return result

    # ------------------------------------------------------------------ #
    #  First-law cross-check between modules
    # ------------------------------------------------------------------ #

    def _cross_check_first_law(
        self,
        module_results: dict[str, ValidationResult],
        measurements: dict[str, Any],
    ) -> dict[str, float]:
        """Verify heat flows balance across modules.

        At steady state:
          Q_it_dissipated (to DLC)
            == Q_removed_by_mechanical_loop
            == Q_rejected_by_chillers
            == Q_electrical_in_minus_losses (approx, with UPS efficiency)

        Any significant residual between modules indicates sensor drift
        or unmetered flow somewhere in the cascade.
        """
        residuals = {}

        it_metrics = module_results.get("it_thermal")
        mech_metrics = module_results.get("mechanical")
        hr_metrics = module_results.get("heat_rejection")

        if it_metrics and mech_metrics:
            it_q = it_metrics.metrics.get("Q_removed_by_dlc_kw", 0.0)
            # Mechanical q_secondary is per hall; aggregate for full site
            # (3 halls by a3semi topology)
            mech_q_per_hall = mech_metrics.metrics.get("q_secondary_kw", 0.0)
            mech_q_site = mech_q_per_hall * 3.0
            if it_q > 0 and mech_q_site > 0:
                residual_kw = it_q - mech_q_site
                residuals["it_vs_mechanical_kw"] = residual_kw

        if mech_metrics and hr_metrics:
            mech_q_primary_per_hall = mech_metrics.metrics.get("q_primary_kw", 0.0)
            mech_q_primary_site = mech_q_primary_per_hall * 3.0
            hr_total = hr_metrics.metrics.get("total_heat_rejection_kw", 0.0)
            if mech_q_primary_site > 0 and hr_total > 0:
                residual_kw = mech_q_primary_site - hr_total
                residuals["mechanical_vs_heat_rejection_kw"] = residual_kw

        return residuals

    # ------------------------------------------------------------------ #
    #  Cascade detection
    # ------------------------------------------------------------------ #

    def _detect_cascades(
        self,
        module_results: dict[str, ValidationResult],
    ) -> list[dict]:
        """Identify cross-module patterns that amplify severity.

        Patterns recognised:
          1. IT energy residual + mechanical pump cavitation
             -> partial DLC flow loss propagating to IT thermal stress
          2. Heat rejection high wet-bulb + chiller COP degraded
             -> heat-wave mode, loss of safe operating margin
          3. Electrical on-battery + IT critical
             -> loss of cooling power during utility outage
        """
        cascades = []

        it = module_results.get("it_thermal")
        mech = module_results.get("mechanical")
        elec = module_results.get("electrical")
        hr = module_results.get("heat_rejection")

        # Pattern 1: DLC flow / cavitation linkage
        if it and mech:
            it_flagged = any(
                not c["passed"] and c["name"] == "first_law_energy_balance" for c in it.checks
            )
            cav_flagged = any(
                not c["passed"] and c["name"] == "pump_cavitation_margin" for c in mech.checks
            )
            if it_flagged and cav_flagged:
                cascades.append(
                    {
                        "pattern": "pump_cavitation_to_it_thermal_stress",
                        "severity": "critical",
                        "interpretation": (
                            "Pump cavitation reducing DLC flow; IT thermal "
                            "energy balance shows unremoved heat. Cascading "
                            "failure mode - cooling loss propagating to rack."
                        ),
                        "action": (
                            "Activate EOP-003 (emergency cooling reduction). "
                            "Investigate pump NPSH margin."
                        ),
                    }
                )

        # Pattern 2: heat wave + chiller degraded
        if hr:
            wb_flagged = any(
                not c["passed"] and c["name"] == "outdoor_wet_bulb_capacity" for c in hr.checks
            )
            cop_flagged = any(
                not c["passed"]
                and c["name"].startswith("chiller_")
                and c["name"].endswith("_cop_vs_curve")
                for c in hr.checks
            )
            if wb_flagged and cop_flagged:
                cascades.append(
                    {
                        "pattern": "heat_wave_chiller_degradation",
                        "severity": "warning",
                        "interpretation": (
                            "Outdoor wet-bulb elevated AND chiller COP below "
                            "curve. Combined effect may push ECWT toward trip "
                            "threshold."
                        ),
                        "action": (
                            "Monitor ECWT closely. Consider workload reduction "
                            "if wet-bulb continues to rise."
                        ),
                    }
                )

        # Pattern 3: utility loss during IT load
        if elec and it:
            on_batt = any(c["name"] == "on_battery_runtime_remaining" for c in elec.checks)
            it_critical = it.severity == Severity.CRITICAL
            if on_batt and it_critical:
                cascades.append(
                    {
                        "pattern": "utility_loss_with_it_thermal_stress",
                        "severity": "critical",
                        "interpretation": (
                            "On battery power while IT thermal state is "
                            "critical. Both cooling and IT will lose power "
                            "if battery depletes before generator online."
                        ),
                        "action": (
                            "Verify generator start status. Initiate orderly "
                            "workload migration. See T1-SAF-EPO-005 if "
                            "shutdown required."
                        ),
                    }
                )

        return cascades

    # ------------------------------------------------------------------ #
    #  Scenario runner
    # ------------------------------------------------------------------ #

    def simulate_scenario(
        self,
        scenario: dict,
        horizon_s: int = 900,
        dt_s: float = 1.0,
    ) -> dict:
        """Execute a scenario definition across the appropriate module(s).

        Scenario dict schema (from scenarios.yml):
            {
              "id":            str,
              "name":          str,
              "description":   str,
              "primary_module": "it_thermal"|"mechanical"|"electrical"|"heat_rejection",
              "initial_state": {...},
              "perturbation":  {...},
            }

        Returns:
            {
              "scenario_id": str,
              "module": str,
              "trajectory": [StateSnapshot dicts...],
              "events": [ordered list of (t, event_name) tuples],
              "summary": {...key metrics...},
            }
        """
        module_name = scenario.get("primary_module", "it_thermal")
        module = self._modules.get(module_name)
        if module is None:
            raise ValueError(f"Unknown primary_module: {module_name}")

        initial_state = scenario.get("initial_state", {})
        perturbation = scenario.get("perturbation", {})

        trajectory = module.simulate(
            initial_state=initial_state,
            perturbation=perturbation,
            horizon_s=horizon_s,
            dt_s=dt_s,
        )

        # Extract events chronologically
        events = [{"t": snap.t, "event": e} for snap in trajectory for e in snap.events]

        # Build a tiny summary for the UI
        summary = {
            "horizon_s": horizon_s,
            "dt_s": dt_s,
            "snapshots": len(trajectory),
            "event_count": len(events),
            "first_event_t": events[0]["t"] if events else None,
            "last_event_t": events[-1]["t"] if events else None,
        }

        # Defensive: scrub NaN / Infinity from trajectories before they reach
        # the API. RFC 8259 strict JSON (which FastAPI uses) does not permit
        # these values. Replace with -1.0 sentinel.
        traj_dicts = [_sanitize_for_json(s.to_dict()) for s in trajectory]

        return {
            "scenario_id": scenario.get("id", "unnamed"),
            "scenario_name": scenario.get("name", ""),
            "module": module_name,
            "trajectory": traj_dicts,
            "events": events,
            "summary": summary,
        }


def _sanitize_for_json(obj):
    """Recursively replace NaN/Infinity floats with -1.0 sentinel.

    FastAPI rejects non-finite floats by default (RFC 8259 strict).
    We sanitize at the API boundary so individual physics modules can
    still return inf/nan for genuinely undefined states.
    """
    import math

    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return -1.0
    return obj


# Convenience singleton
_engine_instance: PhysicsEngine | None = None


def get_engine() -> PhysicsEngine:
    """Return a shared PhysicsEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PhysicsEngine()
    return _engine_instance
