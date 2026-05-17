"""
telemetry_simulator.py — synthetic Path C2 telemetry generator.

Sprint 5 backend Bite C1. Produces per-channel sample windows driven
by site_model.yml inventory (config/site_model.yml). Deterministic
when seeded; otherwise uses np.random.default_rng().

Channel coverage per component type (Phase 1 inventory today):

    it_rack              rack_inlet_T_c, gpu_Tj_c,
                         dlc_supply_T_c, dlc_return_T_c          (4 ch)
    chiller              chiller_LWT_c, chiller_cop              (2 ch)
    cdu                  cdu_supply_T_c, cdu_flow_lpm            (2 ch)
    ups                  voltage_v_phase_ab/bc/ca,
                         ups_soc_pct, batt_runtime_min           (5 ch)
    pump                 pump_NPSH_margin_m, pump_flow_gpm       (2 ch)
    cooling_tower_field  ecwt_c, outdoor_wet_bulb_c              (2 ch)

Channel IDs are SCOPED per component:  "<canonical_id>:<metric>"
so the same physical metric on different units stays distinct.

Vocabulary fence (CO+I panel-grade):
  Phase 1 components emit 3-phase AC voltage (480 VAC trifásico).
  Phase 2 components (future, when site_model.yml grows) will emit
  DC bus single channel (800 VDC unipolar TN-S). Schema fields are
  encoded so the polarity is unambiguous in every channel ID.

Steady-state baselines calibrated against:
  - NVIDIA GB200 NVL72 thermal envelope (rack_inlet 22 C, gpu_Tj 60-75 C)
  - ASHRAE TC 9.9 Class A2 (10-35 C operating)
  - Schneider Galaxy VX UPS SoC (95-100% nominal)
  - York YZ chiller LWT setpoint 6.7-7.2 C
  - PT100 noise floor R=0.05^2 K^2 (cyber_physical_tools tuning notes)

Anomaly injection API supports controlled deviation for tests and
live demos:

    sim.inject_anomaly("rack_a_01_05", "thermal_runaway",
                       magnitude=1.0, duration_samples=60)

Anomalies persist for `duration_samples` future calls to get_window()
then auto-clear. Tests use this to verify Pillar 4 / Kalman behavior
without waiting for natural anomalies.

C1 closure: this module is the SOURCE of synthetic samples. C2 will
add the Kalman+SoD pipeline (telemetry_pipeline.py) that consumes
get_window() and produces the actual {n_emissions, max_z, mean_z,
is_anomalous} payload. C1 emits a placeholder shape via
build_placeholder_payload() so the frontend Activity Strip already
flips Schema field to "channel_innovations" upon C1 deployment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import numpy as np

from backend.site_model import ComponentInfo, SiteModel

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
#  Path C2 Phase 1 baselines (mean, std)
# ─────────────────────────────────────────────────────────────────────
# Tuples are (baseline_mean, gaussian_std) — std calibrated against the
# physical noise floor of each sensor type.
PHASE1_BASELINES: dict[str, tuple[float, float]] = {
    # IT thermal — PT100 in stable enclosure, R=0.05 K
    "rack_inlet_T_c":      (22.0, 0.4),
    "gpu_Tj_c":            (68.0, 4.0),    # workload-driven, larger variance
    "dlc_supply_T_c":      (30.0, 0.3),    # pump-stabilized loop
    "dlc_return_T_c":      (45.0, 0.5),
    # Electrical — Schneider Galaxy VX class
    "voltage_v_phase_ab":  (480.0, 2.4),   # 0.5% regulation
    "voltage_v_phase_bc":  (480.0, 2.4),
    "voltage_v_phase_ca":  (480.0, 2.4),
    "ups_soc_pct":         (98.5, 0.5),
    "batt_runtime_min":    (15.0, 0.3),
    # Mechanical — York YZ chiller, CDU, pumps
    "chiller_LWT_c":       (6.8, 0.15),
    "chiller_cop":         (5.8, 0.2),
    "cdu_primary_supply_T_c":   (30.5, 0.25),  # BPHE facility (district CHW) side
    "cdu_secondary_supply_T_c": (32.0, 0.22),  # BPHE technology (clean coolant) side -> IT
    "cdu_flow_lpm":             (180.0, 5.0),  # secondary-loop flow; 142 LPM = starvation
    "cdu_filter_dp_kpa":        (22.0, 4.0),   # filter differential pressure (nominal 10-35 kPa)
    "pump_NPSH_margin_m":  (3.5, 0.15),
    "pump_flow_gpm":       (4500.0, 50.0),
    # Heat rejection — ECWT and weather-driven wet bulb
    "ecwt_c":              (24.0, 0.5),
    "outdoor_wet_bulb_c":  (15.0, 1.5),
}


# ─────────────────────────────────────────────────────────────────────
#  Anomaly profiles — delta_value applied to baseline when active
# ─────────────────────────────────────────────────────────────────────
ANOMALY_PROFILES: dict[str, dict[str, float]] = {
    "thermal_runaway": {
        "gpu_Tj_c": +25.0,
        "rack_inlet_T_c": +5.0,
        "dlc_return_T_c": +8.0,
    },
    "pump_cavitation": {
        "pump_NPSH_margin_m": -2.5,
        "pump_flow_gpm": -1500.0,
    },
    "phase_imbalance": {
        "voltage_v_phase_ab": +8.0,
        "voltage_v_phase_bc": -6.0,
        "voltage_v_phase_ca": -2.0,
    },
    "ups_drain": {
        "ups_soc_pct": -45.0,
        "batt_runtime_min": -10.0,
    },
    "chiller_degraded": {
        "chiller_LWT_c": +2.5,
        "chiller_cop": -1.4,
    },
    "cdu_flow_starvation": {
        "cdu_flow_lpm": -38.0,        # 180 LPM nominal -> 142 LPM secondary-loop starvation
        "cdu_filter_dp_kpa": +28.0,   # clogged filter element drives the flow loss
    },
    "gen_desync": {
        "genset_phase_angle_deg": +8.0,   # nominal 0 deg -> 8 deg, past the 5 deg fault gate
        "genset_freq_hz": +0.35,          # frequency slip accompanies loss of sync
        "genset_breaker_status": -1.0,    # protective SSCB trip on desynchronization
    },
}


# ─────────────────────────────────────────────────────────────────────
#  Multi-region generator synchronization profiles
# ─────────────────────────────────────────────────────────────────────
# Eliminates regional hardcoding. Toronto Path C2 baseline runs
# 480 V / 60.00 Hz (ANSI A-B-C phase rotation); EMEA deployment clusters
# run 416 V / 50.00 Hz (IEC R-Y-B). _gen_genset() reads the ACTIVE
# region. Values are (baseline_mean, gaussian_std) per channel.
REGION_PROFILES: dict[str, dict[str, tuple[float, float]]] = {
    "toronto_60hz": {
        "genset_voltage_v":       (480.0, 2.4),
        "genset_freq_hz":         (60.00, 0.02),
        "genset_phase_angle_deg": (0.0,   0.4),
        "phase_sequence_match":   (1.0,   0.02),
        "genset_breaker_status":  (1.0,   0.02),
    },
    "emea_50hz": {
        "genset_voltage_v":       (416.0, 2.1),
        "genset_freq_hz":         (50.00, 0.02),
        "genset_phase_angle_deg": (0.0,   0.4),
        "phase_sequence_match":   (1.0,   0.02),
        "genset_breaker_status":  (1.0,   0.02),
    },
}

DEFAULT_REGION = "toronto_60hz"
_active_region = DEFAULT_REGION


def set_region(region_key: str) -> None:
    """Select the active regional sync band. Raises ValueError on unknown key."""
    global _active_region
    if region_key not in REGION_PROFILES:
        raise ValueError(
            f"unknown region: {region_key}; valid: {sorted(REGION_PROFILES)}"
        )
    _active_region = region_key
    log.info("[telemetry_sim] active region set to %s", region_key)


def get_region() -> str:
    """Return the active regional sync band key."""
    return _active_region


@dataclass
class _AnomalyState:
    """In-flight anomaly affecting one component's channels."""
    component_id: str
    kind: str
    magnitude: float
    samples_remaining: int


# ─────────────────────────────────────────────────────────────────────
#  Per-component-type generators
# ─────────────────────────────────────────────────────────────────────
def _noise(rng: np.random.Generator, key: str, n: int) -> np.ndarray:
    mean, std = PHASE1_BASELINES[key]
    return rng.normal(loc=mean, scale=std, size=n)


def _gen_it_rack(_comp: ComponentInfo, n: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    return {
        "rack_inlet_T_c":  _noise(rng, "rack_inlet_T_c", n),
        "gpu_Tj_c":        _noise(rng, "gpu_Tj_c", n),
        "dlc_supply_T_c":  _noise(rng, "dlc_supply_T_c", n),
        "dlc_return_T_c":  _noise(rng, "dlc_return_T_c", n),
    }


def _gen_chiller(_comp: ComponentInfo, n: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    return {
        "chiller_LWT_c":  _noise(rng, "chiller_LWT_c", n),
        "chiller_cop":    _noise(rng, "chiller_cop", n),
    }


def _gen_cdu(_comp: ComponentInfo, n: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    # CDU dual-loop hydraulics: the brazed-plate heat exchanger (BPHE)
    # thermally separates the facility (primary) loop from the technology
    # (secondary) loop that delivers clean coolant to the IT racks.
    return {
        "cdu_primary_supply_T_c":   _noise(rng, "cdu_primary_supply_T_c", n),
        "cdu_secondary_supply_T_c": _noise(rng, "cdu_secondary_supply_T_c", n),
        "cdu_flow_lpm":             _noise(rng, "cdu_flow_lpm", n),
        "cdu_filter_dp_kpa":        _noise(rng, "cdu_filter_dp_kpa", n),
    }


def _gen_ups(_comp: ComponentInfo, n: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    return {
        "voltage_v_phase_ab":  _noise(rng, "voltage_v_phase_ab", n),
        "voltage_v_phase_bc":  _noise(rng, "voltage_v_phase_bc", n),
        "voltage_v_phase_ca":  _noise(rng, "voltage_v_phase_ca", n),
        "ups_soc_pct":         _noise(rng, "ups_soc_pct", n),
        "batt_runtime_min":    _noise(rng, "batt_runtime_min", n),
    }


def _gen_pump(_comp: ComponentInfo, n: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    return {
        "pump_NPSH_margin_m":  _noise(rng, "pump_NPSH_margin_m", n),
        "pump_flow_gpm":       _noise(rng, "pump_flow_gpm", n),
    }


def _gen_cooling_tower_field(_comp: ComponentInfo, n: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    return {
        "ecwt_c":              _noise(rng, "ecwt_c", n),
        "outdoor_wet_bulb_c":  _noise(rng, "outdoor_wet_bulb_c", n),
    }


def _gen_genset(_comp: ComponentInfo, n: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    # Generator bus synchronization telemetry. Region-aware: emits the
    # 480 V/60 Hz (Toronto) or 416 V/50 Hz (EMEA) band per the ACTIVE
    # region. The 4 sync tracks + breaker status feed the Kalman pipeline,
    # whose z-score flags a desync fault when phase angle drifts past 5 deg.
    profile = REGION_PROFILES[_active_region]
    return {
        metric: rng.normal(loc=mean, scale=std, size=n)
        for metric, (mean, std) in profile.items()
    }


GeneratorFn = Callable[[ComponentInfo, int, np.random.Generator], dict[str, np.ndarray]]

_GENERATORS: dict[str, GeneratorFn] = {
    "it_rack":              _gen_it_rack,
    "chiller":              _gen_chiller,
    "cdu":                  _gen_cdu,
    "ups":                  _gen_ups,
    "pump":                 _gen_pump,
    "cooling_tower_field":  _gen_cooling_tower_field,
    "genset":               _gen_genset,
}


# Channel count per emitting type — used for inventory reporting without
# advancing the RNG state on init.
_CHANNELS_PER_TYPE: dict[str, int] = {
    "it_rack": 4,
    "chiller": 2,
    "cdu": 4,
    "ups": 5,
    "pump": 2,
    "cooling_tower_field": 2,
    "genset": 5,
}


# ─────────────────────────────────────────────────────────────────────
#  Simulator class
# ─────────────────────────────────────────────────────────────────────
class TelemetrySimulator:
    """Synthetic Path C2 telemetry generator backed by site_model.yml."""

    EMITTING_TYPES = frozenset(_GENERATORS.keys())

    def __init__(self, site_model: SiteModel, seed: int | None = None):
        self._site = site_model
        self._rng = np.random.default_rng(seed)
        self._anomalies: dict[str, _AnomalyState] = {}
        self._inventory: list[tuple[ComponentInfo, GeneratorFn]] = self._build_inventory()

        total_channels = sum(_CHANNELS_PER_TYPE[c.type] for c, _ in self._inventory)
        log.info(
            "[telemetry_sim] initialized: %d emitting components, %d channels (seed=%s)",
            len(self._inventory),
            total_channels,
            seed,
        )

    def _build_inventory(self) -> list[tuple[ComponentInfo, GeneratorFn]]:
        out: list[tuple[ComponentInfo, GeneratorFn]] = []
        for comp in self._site.list_components():
            gen = _GENERATORS.get(comp.type)
            if gen is not None:
                out.append((comp, gen))
        return out

    @property
    def channel_count(self) -> int:
        return sum(_CHANNELS_PER_TYPE[c.type] for c, _ in self._inventory)

    @property
    def component_count(self) -> int:
        return len(self._inventory)

    def get_window(self, dt_seconds: float = 1.0, n_samples: int = 5) -> dict[str, np.ndarray]:
        """Produce one window of n_samples per channel.

        Returns {channel_id: ndarray of shape (n_samples,) dtype float64}.
        Channel IDs are scoped: '<component_id>:<metric>'.

        Anomalies registered via inject_anomaly() are applied here as
        additive deltas to the baseline for affected channels. Each
        get_window call decrements the anomaly's samples_remaining
        counter by n_samples; auto-clears when counter <= 0.
        """
        del dt_seconds  # reserved for future time-correlated drift
        out: dict[str, np.ndarray] = {}
        expired: list[str] = []

        for comp, gen in self._inventory:
            channels = gen(comp, n_samples, self._rng)
            for metric, samples in channels.items():
                ch_id = f"{comp.canonical_id}:{metric}"
                state = self._anomalies.get(ch_id)
                if state is not None:
                    delta = ANOMALY_PROFILES.get(state.kind, {}).get(metric, 0.0)
                    if delta != 0.0:
                        samples = samples + delta * state.magnitude
                    state.samples_remaining -= n_samples
                    if state.samples_remaining <= 0:
                        expired.append(ch_id)
                out[ch_id] = samples

        for ch_id in expired:
            self._anomalies.pop(ch_id, None)

        return out

    def inject_anomaly(
        self,
        component_id: str,
        kind: str,
        magnitude: float = 1.0,
        duration_samples: int = 60,
    ) -> int:
        """Inject anomaly affecting all channels of a component.

        Returns the number of channels affected.

        kinds (see ANOMALY_PROFILES):
          thermal_runaway, pump_cavitation, phase_imbalance,
          ups_drain, chiller_degraded, cdu_flow_starvation,
          gen_desync.

        magnitude scales the profile delta (1.0 = full deviation).
        duration_samples controls persistence in get_window() calls.
        """
        if kind not in ANOMALY_PROFILES:
            raise ValueError(
                f"unknown anomaly kind: {kind}; "
                f"valid: {sorted(ANOMALY_PROFILES)}"
            )
        try:
            comp = self._site.get_component(component_id)
        except Exception as e:
            raise ValueError(f"component not found: {component_id}") from e

        gen = _GENERATORS.get(comp.type)
        if gen is None:
            log.warning(
                "[telemetry_sim] component %s type %s does not emit telemetry",
                component_id, comp.type,
            )
            return 0

        # Probe channel names without advancing RNG significantly
        sample_channels = gen(comp, 1, self._rng)
        affected = 0
        for metric in sample_channels.keys():
            if metric not in ANOMALY_PROFILES[kind]:
                continue  # this anomaly does not affect this metric
            ch_id = f"{component_id}:{metric}"
            self._anomalies[ch_id] = _AnomalyState(
                component_id=component_id,
                kind=kind,
                magnitude=magnitude,
                samples_remaining=duration_samples,
            )
            affected += 1

        log.info(
            "[telemetry_sim] injected %s on %s (mag=%.2f, %d samples, %d channels)",
            kind, component_id, magnitude, duration_samples, affected,
        )
        return affected

    def clear_anomalies(self) -> int:
        n = len(self._anomalies)
        self._anomalies.clear()
        return n


# ─────────────────────────────────────────────────────────────────────
#  Module-level singleton + factory
# ─────────────────────────────────────────────────────────────────────
_simulator: TelemetrySimulator | None = None


def get_simulator(
    site_model: SiteModel | None = None,
    seed: int | None = None,
) -> TelemetrySimulator:
    """Lazy singleton. First call must pass site_model."""
    global _simulator
    if _simulator is None:
        if site_model is None:
            raise RuntimeError(
                "telemetry_simulator not initialized; "
                "first call must pass site_model"
            )
        _simulator = TelemetrySimulator(site_model, seed=seed)
    return _simulator


def reset_simulator() -> None:
    """Test helper — discard singleton so tests get fresh instance."""
    global _simulator
    _simulator = None


# ─────────────────────────────────────────────────────────────────────
#  Frontend payload builder
# ─────────────────────────────────────────────────────────────────────
def build_placeholder_payload(window: dict[str, np.ndarray]) -> dict[str, dict]:
    """Convert raw simulator window to channel_innovations payload shape.

    C1: emits frontend-compatible placeholder payload. The Kalman+SoD
    pipeline (Bite C2, telemetry_pipeline.py) will replace this with
    real innovation residuals computed by cyber_physical_tools.

    Returns {channel_id: {n_emissions, max_z, mean_z, is_anomalous,
                          last_emission}}
    matching the contract that frontend/assets/js/core/telemetry_engine.js
    expects under SCHEMA_CHANNEL_INNOVATIONS.
    """
    out: dict[str, dict] = {}
    for ch_id, samples in window.items():
        if samples.size == 0:
            continue
        out[ch_id] = {
            "n_emissions": int(samples.size),
            "max_z": 0.0,            # C2: real Kalman z-score
            "mean_z": 0.0,           # C2: real Kalman mean z
            "is_anomalous": False,   # C2: max_z >= ANOMALY_Z_THRESHOLD
            "last_emission": float(samples[-1]),
        }
    return out
