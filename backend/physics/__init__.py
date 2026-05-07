"""
DC-EPMS PRO - Physics Engine
=============================
Modular physics validators and simulators for the four sub-systems
of A3-Alpha Toronto Area:

- it_thermal       (White Space) - Blackwell NVL72 heat dissipation
- mechanical       (Mech Room)   - CDUs, primary/secondary loops, pumps
- electrical       (Elec Room)   - UPS, transformers, Joule losses
- heat_rejection   (Exterior)    - chillers + psychrometrics + wet bulb

Every module exposes the same contract (class `PhysicsModule`):

    validate(measurements: dict) -> ValidationResult
        # Fast algebraic steady-state check. <10 ms typical.

    simulate(initial_state: dict, perturbation: dict, horizon_s: int)
              -> list[StateSnapshot]
        # ODE integration using scipy.solve_ivp for transient response.
        # Returns a time series at 1-second resolution.

The `PhysicsEngine` facade in `physics_engine.py` orchestrates all
four modules and publishes:
  - Cascading-failure propagation across modules
  - First-law (energy-balance) cross-check between modules
  - Site Health Index (min() of per-module health + severity modifier)
"""
from __future__ import annotations

from backend.physics.base import (
    PhysicsModule,
    ValidationResult,
    StateSnapshot,
    Severity,
)
from backend.physics.it_thermal import ITThermalModule
from backend.physics.mechanical import MechanicalModule
from backend.physics.electrical import ElectricalModule
from backend.physics.heat_rejection import HeatRejectionModule

__all__ = [
    "PhysicsModule",
    "ValidationResult",
    "StateSnapshot",
    "Severity",
    "ITThermalModule",
    "MechanicalModule",
    "ElectricalModule",
    "HeatRejectionModule",
]
