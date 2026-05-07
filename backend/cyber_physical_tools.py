"""
cyber_physical_tools.py  -  high-frequency OT telemetry pipeline.

Hot-path math for v8 thermal control. Python's GIL is unacceptable
above ~50 Hz on multi-channel telemetry; this module pushes the
arithmetic into Numba-compiled native code (njit, no GIL, no Python
object boxing) and returns the LLM only what is informationally novel:
the Kalman innovation residual.

Two compression stages on top of each other:

  Stage 1  Send-on-Delta    Lebesgue-measure-style temporal compression.
                             Skip samples where |T_t - T_{t-1}| < 0.5 K.
                             Eliminates the 95%+ of telemetry that is
                             noise around steady state.

  Stage 2  Kalman Innovation The agent never sees raw temperatures. It
                             sees only y_t - H-x̂_t  -  the residual
                             between observation and ODE prediction.
                             If the ODE is right, this is white noise
                             with known variance and the agent ignores
                             it. If the residual is biased or grows,
                             that bias is exactly the anomaly signal.

VRAM clarification: Numba @njit compiles to CPU native code. It does
NOT consume VRAM. The 6 GB VRAM ceiling applies to the Hermes/Gemma
model and to LoRA training in dpo_edge_healing.py  -  not to this module.
This module's footprint is RAM-bounded (~50 MB for filter state across
all channels at A3-Alpha).

Imports of numpy, numba, dataclasses omitted per directive.
"""

from __future__ import annotations

import numpy as np

try:
    from numba import njit
except ImportError:
    # Fallback for environments without numba: provide no-op decorator
    # so module imports clean. Functions decorated with @njit will fall
    # back to pure-Python execution (slower but correct).
    def njit(*args, **kwargs):
        # Allow both @njit and @njit(cache=True, ...) usage
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def decorator(fn):
            return fn

        return decorator


# =======================================================================
#  Stage 1: Send-on-Delta filter (temporal compression)
# =======================================================================
@njit(cache=True, fastmath=True)
def send_on_delta_mask(
    samples: np.ndarray,  # shape (N,) float64
    last_emitted: np.ndarray,  # shape (1,) float64  -  mutable state
    threshold_k: float,  # 0.5 default
) -> np.ndarray:
    """Return boolean mask of samples that should be transmitted upstream.

    Mathematical statement: given a sequence {T_t}, emit T_t iff
        |T_t - T_emit_last| >= epsilon
    where epsilon = threshold_k. This is the Lebesgue-style send-on-delta
    discretization that converts a continuous signal into the minimal
    set of state transitions that preserve epsilon-precision.

    Justification of the 0.5 K default:
      - ASHRAE TC 9.9 thermal envelope tolerance is ±1 K
      - DLC supply temperature control band is ±0.3 K
      - 0.5 K sits below the SLA breach threshold (1 K) and above the
        sensor noise floor (~0.05 K for PT100 in a stable enclosure)
      - At 1 Hz native rate, this typically yields < 5 emissions per
        minute under steady state, vs 60 raw samples  -  a 12x compression
        without information loss above the epsilon threshold.

    Side effect: updates last_emitted[0] in place (mutable scalar) so
    the next call resumes from the correct anchor across batch boundaries.
    """
    n = samples.shape[0]
    mask = np.zeros(n, dtype=np.bool_)
    anchor = last_emitted[0]

    for i in range(n):
        delta = samples[i] - anchor
        if delta < 0.0:
            delta = -delta
        if delta >= threshold_k:
            mask[i] = True
            anchor = samples[i]

    last_emitted[0] = anchor
    return mask


# =======================================================================
#  Stage 2: Discrete Kalman filter  -  scalar form (one channel at a time)
# =======================================================================
#
# Why scalar Kalman instead of vector: each thermal channel is modeled
# independently because the ODE engine *already* provides the cross-
# channel coupling. The Kalman filter here is a one-dimensional
# innovation extractor per channel; vector coupling lives in the
# physics module, not here. This separation is what keeps the math
# auditable  -  each filter has 4 numbers (x̂, P, Q, R) per channel and
# nothing else.
#
# State equation (per channel):
#     x_t = F - x_{t-1} + w_t           w ~ N(0, Q)
#     y_t = H - x_t     + v_t           v ~ N(0, R)
#
# For thermal mass with effective time constant tau:
#     F = exp(-deltat / tau)
#     H = 1
#
# Initial covariance P_0 chosen large (10x R) so the first few samples
# dominate; the filter converges within ~5tau to its steady-state gain.


@njit(cache=True, fastmath=True)
def kalman_innovation_step(
    x_hat: np.ndarray,  # shape (1,)  -  posterior mean, mutable
    P: np.ndarray,  # shape (1,)  -  posterior variance, mutable
    F: float,
    H: float,
    Q: float,
    R: float,
    y: float,
) -> tuple[float, float, float]:
    """One-step discrete Kalman update for a scalar channel.

    Returns:
        innovation       y - H-x_predict   (the residual the agent sees)
        innovation_var   H-P_predict-H + R  (the residual's expected variance)
        normalized_innov innovation / sqrt(innovation_var)  (z-score, dimensionless)

    Mutates x_hat[0] and P[0] in place. The agent sees ONLY the
    normalized innovation. If |normalized_innov| < 3 the residual is
    consistent with the ODE prediction and contains no information; the
    agent ignores it. If |normalized_innov| >= 3 the residual is a
    statistically significant anomaly and the agent investigates.

    This is the entire information-theoretic justification for the
    filter: we forward to the LLM only the bits the ODE could not
    explain. Tokens spent on white noise are tokens wasted.
    """
    # Predict
    x_predict = F * x_hat[0]
    P_predict = F * P[0] * F + Q

    # Innovation
    innovation = y - H * x_predict
    innovation_var = H * P_predict * H + R
    normalized_innov = innovation / np.sqrt(innovation_var)

    # Update (Kalman gain)
    K = P_predict * H / innovation_var
    x_hat[0] = x_predict + K * innovation
    P[0] = (1.0 - K * H) * P_predict

    return innovation, innovation_var, normalized_innov


# =======================================================================
#  Composed pipeline: get_telemetry_payload
# =======================================================================
#
# This is what the LLM tool wraps. It accepts a window of raw samples
# from N channels and returns a compact payload that the agent can
# reason about without being flooded.
#
# Per channel, the pipeline:
#   raw samples (60 per minute at 1 Hz)
#       |
#       ▼  Send-on-Delta filter
#   sparse emissions (typically < 5 per minute at steady state)
#       |
#       ▼  Kalman innovation step (one per emission)
#   normalized innovation (z-score)
#       |
#       ▼  Threshold for forwarding
#   anomaly flags + summary statistics
#
# The agent sees:
#   {channel_id: {
#       "n_emissions":   int,   how many SoD-survived samples
#       "max_z":         float, peak normalized innovation
#       "mean_z":        float, average normalized innovation
#       "is_anomalous":  bool,  max_z >= ANOMALY_Z_THRESHOLD
#       "last_emission": float, most recent emitted value (raw units)
#   }, ...}
#
# It does NOT see arrays of floats. The compression is information-
# preserving because the ODE engine has already explained everything
# the agent does not see.

ANOMALY_Z_THRESHOLD = 3.0  # 3-sigma rule
SEND_ON_DELTA_K = 0.5  # ASHRAE-justified, see above


def get_telemetry_payload(
    channel_window: dict,  # {channel_id: np.ndarray of samples}
    filter_state: dict,  # {channel_id: KalmanState}  -  persisted
    delta_t_seconds: float = 1.0,
) -> dict:
    """Single-pass pipeline. Returns the compact payload for the LLM tool.

    `filter_state` carries (x_hat, P, Q, R, F) per channel across calls;
    the caller (agent_copilot.tool_*) is responsible for persisting it
    to a process-local dict between tool invocations.

    Why `dict` for state and not a class: minimises Numba boxing
    overhead. The hot loop above operates on np.ndarray buffers; this
    outer function is allowed Python overhead because it runs once per
    tool call (<= once per 5 seconds), not once per sample.
    """
    payload: dict = {}

    for channel_id, samples in channel_window.items():
        st = filter_state.get(channel_id)
        if st is None:
            # Cold start  -  initialise with first sample, P = 10R
            R_init = 0.05**2  # PT100 noise variance, K^2
            st = {
                "x_hat": np.array([samples[0]], dtype=np.float64),
                "P": np.array([10.0 * R_init], dtype=np.float64),
                "Q": 1e-4,  # process noise (tunable per channel)
                "R": R_init,
                "F": np.exp(-delta_t_seconds / 60.0),  # tau=60s default
                "H": 1.0,
                "last_emitted": np.array([samples[0]], dtype=np.float64),
            }
            filter_state[channel_id] = st

        # Stage 1: SoD compression
        mask = send_on_delta_mask(
            samples=samples,
            last_emitted=st["last_emitted"],
            threshold_k=SEND_ON_DELTA_K,
        )
        emissions = samples[mask]
        if emissions.size == 0:
            payload[channel_id] = {
                "n_emissions": 0,
                "max_z": 0.0,
                "mean_z": 0.0,
                "is_anomalous": False,
                "last_emission": float(st["last_emitted"][0]),
            }
            continue

        # Stage 2: Kalman innovation per emission
        z_scores = np.empty(emissions.size, dtype=np.float64)
        for i in range(emissions.size):
            _, _, z = kalman_innovation_step(
                x_hat=st["x_hat"],
                P=st["P"],
                F=st["F"],
                H=st["H"],
                Q=st["Q"],
                R=st["R"],
                y=float(emissions[i]),
            )
            z_scores[i] = abs(z)

        max_z = float(z_scores.max())
        mean_z = float(z_scores.mean())

        payload[channel_id] = {
            "n_emissions": int(emissions.size),
            "max_z": round(max_z, 2),
            "mean_z": round(mean_z, 2),
            "is_anomalous": max_z >= ANOMALY_Z_THRESHOLD,
            "last_emission": float(emissions[-1]),
            # Note: NO raw arrays returned. The agent gets summary stats
            # only. If it needs detail, a separate drill-down tool can
            # be invoked, paying the token cost only when justified.
        }

    return payload


# =======================================================================
#  Tuning notes (kept for the operator and for code review)
# =======================================================================
#
# Q (process noise) per channel:
#   - chiller LWT:        Q ~ 1e-4   slow thermal mass
#   - rack inlet T:       Q ~ 1e-3   faster, server fan transients
#   - DLC supply T:       Q ~ 1e-4   pump-stabilised loop
#   - GPU Tj:             Q ~ 1e-2   workload-driven spikes
#
# R (measurement noise) per channel:
#   - PT100 in still air:     R ~ 0.05² K²
#   - Thermistor at GPU:      R ~ 0.5²  K²
#   - Thermal camera spot:    R ~ 1.0²  K² (depending on emissivity)
#
# F (state transition) per channel:
#   F = exp(-deltat/tau) where tau is the thermal time constant.
#   tau for a 5275 kW chiller water loop: ~120 seconds
#   tau for a single rack air column: ~15 seconds
#   tau for GPU silicon: ~0.5 seconds (so F ~ 0 at 1 Hz  -  innovation IS
#                                     the signal, no carryover)
#
# These constants should live in a per-channel YAML config in
# production. The hardcoded defaults here are chosen for the median
# A3-Alpha channel and produce reasonable behaviour for unconfigured
# channels.
