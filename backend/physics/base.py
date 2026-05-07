"""
DC-EPMS PRO - Physics Engine: Base Types and Contract
======================================================
Common data types and abstract base class for every physics sub-module.

Design principles
-----------------
1. Dual-mode contract:
     validate()   - algebraic steady-state, <10 ms, for live telemetry
     simulate()   - ODE integration, transient response, for scenarios
2. Every detection carries a "Physical Justification" payload (numbers +
   threshold + interpretation + suggested action) per Uptime Institute
   incident reporting guidance.
3. No neural networks. All validation comes from the first law of
   thermodynamics, fluid mechanics, or electrical engineering.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
#  Severity enumeration
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    """Severity classification per a3semi incident taxonomy."""

    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    def weight(self) -> float:
        """Numeric weight for severity arithmetic (0.0 = best, 1.0 = worst)."""
        return {
            Severity.OK: 0.0,
            Severity.INFO: 0.1,
            Severity.WARNING: 0.5,
            Severity.CRITICAL: 1.0,
        }[self]


# ---------------------------------------------------------------------------
#  Physical Justification block
# ---------------------------------------------------------------------------

@dataclass
class PhysicalJustification:
    """Structured explanation of a detection, embeddable in incident logs.

    Every field is populated with REAL NUMBERS, not prose. This is what
    makes the detection auditable and credible to facility engineers.

    Attributes:
        law: The physical law invoked (e.g. "first_law_energy_balance").
        measured: Dictionary of what was measured from telemetry.
        expected: Dictionary of what physics predicts.
        residual: Difference between measured and expected (measured - expected).
        threshold: Acceptable deviation before this is flagged.
        interpretation: Plain-language explanation of why this matters.
        suggested_action: Concrete next step for the operator.
    """

    law: str
    measured: dict[str, float] = field(default_factory=dict)
    expected: dict[str, float] = field(default_factory=dict)
    residual: dict[str, float] = field(default_factory=dict)
    threshold: dict[str, float] = field(default_factory=dict)
    interpretation: str = ""
    suggested_action: str = ""

    def to_dict(self) -> dict:
        return {
            "law": self.law,
            "measured": self.measured,
            "expected": self.expected,
            "residual": self.residual,
            "threshold": self.threshold,
            "interpretation": self.interpretation,
            "suggested_action": self.suggested_action,
        }


# ---------------------------------------------------------------------------
#  ValidationResult - returned by .validate()
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Outcome of a steady-state physics check on live telemetry.

    Attributes:
        module: Identifier of the producing module (e.g. "it_thermal").
        severity: Overall classification of the result.
        health: Module health score [0.0, 1.0]. 1.0 = nominal.
        checks: List of named sub-checks with pass/fail flags.
        justifications: List of PhysicalJustification for any failed check.
        metrics: Supplementary numeric metrics for dashboards.
    """

    module: str
    severity: Severity = Severity.OK
    health: float = 1.0
    checks: list[dict] = field(default_factory=list)
    justifications: list[PhysicalJustification] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def add_check(
        self,
        name: str,
        passed: bool,
        value: float,
        threshold: Optional[float] = None,
        unit: str = "",
    ) -> None:
        """Append a sub-check record to this result."""
        self.checks.append({
            "name": name,
            "passed": passed,
            "value": value,
            "threshold": threshold,
            "unit": unit,
        })

    def add_justification(self, j: PhysicalJustification) -> None:
        self.justifications.append(j)

    def escalate(self, severity: Severity) -> None:
        """Raise overall severity if new finding is worse than current."""
        if severity.weight() > self.severity.weight():
            self.severity = severity

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "severity": self.severity.value,
            "health": self.health,
            "checks": self.checks,
            "justifications": [j.to_dict() for j in self.justifications],
            "metrics": self.metrics,
        }


# ---------------------------------------------------------------------------
#  StateSnapshot - single time-step of a simulate() trajectory
# ---------------------------------------------------------------------------

@dataclass
class StateSnapshot:
    """One time step of a transient simulation trajectory.

    Attributes:
        t: Time since simulation start, in seconds.
        state: Dict of state variables (temperatures, flows, pressures...).
        events: List of discrete events triggered at this instant
                (e.g. "thermal_throttle_initiated", "cooling_reduced").
    """

    t: float
    state: dict[str, float] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "t": self.t,
            "state": self.state,
            "events": list(self.events),
        }


# ---------------------------------------------------------------------------
#  PhysicsModule abstract base class
# ---------------------------------------------------------------------------

class PhysicsModule(ABC):
    """Contract every physics sub-module must implement.

    A module encapsulates the governing equations for one subsystem
    (IT, mechanical, electrical, heat rejection). It provides both a
    fast steady-state validator for live telemetry and an ODE-based
    transient simulator for what-if scenario projection.

    Sub-classes must implement:
        module_name       - short identifier used in results and logs
        validate(...)     - algebraic telemetry check
        simulate(...)     - ODE integration

    Optional hooks (default no-op implementations provided):
        reset_defaults()  - clear any cached state
    """

    # Short, stable identifier (e.g. "it_thermal", "mechanical")
    module_name: str = "abstract"

    @abstractmethod
    def validate(
        self,
        measurements: dict[str, Any],
    ) -> ValidationResult:
        """Fast algebraic check against live telemetry.

        Expected to complete in <10 ms on CPU. Do not call numerical
        integrators here.

        Args:
            measurements: Current telemetry dict. Exact keys defined by
                          each concrete module's schema.

        Returns:
            ValidationResult with severity, health, checks, and any
            PhysicalJustification blocks for failed checks.
        """
        ...

    @abstractmethod
    def simulate(
        self,
        initial_state: dict[str, float],
        perturbation: dict[str, Any],
        horizon_s: int = 900,
        dt_s: float = 1.0,
    ) -> list[StateSnapshot]:
        """ODE-based transient simulation.

        Args:
            initial_state: State dict at t=0. Keys specific to each
                           module.
            perturbation: Fault definition to apply (scenarios.yml payload).
            horizon_s: Simulation duration in seconds. Default 15 min.
            dt_s: Output sampling interval. Default 1 s.

        Returns:
            List of StateSnapshot at dt_s intervals from t=0 to t=horizon_s.
        """
        ...

    def reset_defaults(self) -> None:
        """Reset any instance-level cached state. Default no-op."""
        pass
