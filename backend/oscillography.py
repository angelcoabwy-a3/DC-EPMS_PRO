"""
backend/oscillography.py
========================
L6 (2026-11-26) -- Disturbance recorder (DFR) of the simulated plant:
three-phase voltage waveforms at two points of each path, captured when
the electrical state of the path changes, measured as IEEE 1159 RMS
variations and exported as COMTRADE (IEEE C37.111-1999, ASCII).

  MV bus     13.8 kV, phase-to-neutral VA / VB / VC
  Load bus   480 V critical load bus (UPS output), VA / VB / VC

A record is SYNTHESISED from the state before and after the change
(source, UPS mode, load feed) and the kind of transition: collapse of a
bus that lost its source, a source appearing, an open-transition dead
time, a static-switch transfer notch, a utility sag, inverter harmonic
distortion. It is NOT a power-system simulation (no load flow, no
motor back-EMF, no fault currents).

Grounding (checked 2026-11-26):
- IEEE 1159-2009 Table 2: sag 0.1-0.9 pu, instantaneous 0.5-30 cycles,
  momentary 30 cycles-3 s; interruption < 0.1 pu, momentary 0.5 cycles
  to 3 s, temporary 3 s to 1 min.
- COMTRADE C37.111-1999 .cfg layout: station / device / revision year,
  channel counts, 13-field analog channel lines (An, ch_id, ph, ccbm,
  uu, a, b, skew, min, max, primary, secondary, PS), line frequency,
  sampling rates, first-sample and trigger times, file type, time
  multiplier. The 1999 revision has no time zone field: times are UTC.
Model values: 32 samples per cycle, 0.1 s pre-trigger and 0.3 s
post-trigger, bus collapse time constant, 3 ms static-switch transfer
(inside the < 4 ms of the operator specification), 100 ms open-transition
dead time, inverter fault harmonics.

PURE: no clock, no I/O. Vocabulary (S-VOCAB-01): AC points only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

NOMINAL_HZ = 60.0
SAMPLES_PER_CYCLE = 32
FS = NOMINAL_HZ * SAMPLES_PER_CYCLE          # 1920 samples/s
PRE_S = 0.1
POST_S = 0.3
COLLAPSE_TAU_S = 0.008                       # model
STATIC_XFER_S = 0.003                        # model, spec: < 4 ms
OPEN_TRANSITION_S = 0.100                    # model dead time
FAULT_HARMONICS = {5: 0.09, 7: 0.06, 11: 0.03}   # model, inverter fault
POINTS = {
    "MV": {"name": "MV BUS 13.8 kV", "unit": "kV", "vln_rms": 13.8 / math.sqrt(3),
           "primary": 13.8, "secondary": 0.12},
    "LD": {"name": "CRITICAL LOAD BUS 480 V", "unit": "V", "vln_rms": 480.0 / math.sqrt(3),
           "primary": 480.0, "secondary": 120.0},
}
PHASES = (("A", 0.0), ("B", -120.0), ("C", 120.0))
CHANNELS = tuple(f"{p}_V{ph}" for p in POINTS for ph, _ in PHASES)


@dataclass(frozen=True)
class PointState:
    """Steady condition of one point: amplitude in pu, frequency,
    harmonic content (order -> pu of fundamental)."""
    amp: float = 1.0
    hz: float = NOMINAL_HZ
    harmonics: tuple[tuple[int, float], ...] = ()


@dataclass(frozen=True)
class Transition:
    """What happens at t = 0: none, collapse, appear, gap (seconds of
    dead time, then post), notch (static switch), sag (depth pu for
    seconds, then back to pre), phase_step (degrees, no gap)."""
    kind: str = "none"
    seconds: float = 0.0
    depth: float = 0.0
    phase_deg: float = 0.0


@dataclass
class Record:
    record_id: str
    path: str
    ts: float
    trigger: str
    cause: list[str]
    pre: dict[str, PointState]
    post: dict[str, PointState]
    transitions: dict[str, Transition]
    samples: dict[str, list[float]] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


def _envelope(t: float, pre: PointState, post: PointState, tr: Transition) -> float:
    if t < 0:
        return pre.amp
    k = tr.kind
    if k == "collapse":
        return pre.amp * math.exp(-t / COLLAPSE_TAU_S) + post.amp * (1 - math.exp(-t / COLLAPSE_TAU_S))
    if k in ("gap", "notch"):
        return 0.0 if t < tr.seconds else post.amp
    if k == "sag":
        return tr.depth * pre.amp if t < tr.seconds else post.amp
    return post.amp


def _value(t: float, phase_deg: float, pre: PointState, post: PointState, tr: Transition,
           peak: float) -> float:
    st = pre if t < 0 else post
    hz = st.hz
    if t >= 0 and tr.kind == "sag" and t < tr.seconds:
        st = pre
    step = math.radians(tr.phase_deg) if (t >= 0 and tr.kind in ("phase_step", "appear", "gap")) else 0.0
    theta = 2 * math.pi * hz * t + math.radians(phase_deg) + step
    wave = math.sin(theta) + sum(k * math.sin(h * theta) for h, k in st.harmonics)
    return peak * _envelope(t, pre, post, tr) * wave


def synthesize(rec: Record) -> Record:
    n_pre = round(PRE_S * FS)
    n = n_pre + round(POST_S * FS)
    for point, meta in POINTS.items():
        peak = meta["vln_rms"] * math.sqrt(2)
        pre, post = rec.pre[point], rec.post[point]
        tr = rec.transitions.get(point, Transition())
        for ph, deg in PHASES:
            rec.samples[f"{point}_V{ph}"] = [
                round(_value((i - n_pre) / FS, deg, pre, post, tr, peak), 4) for i in range(n)
            ]
    rec.summary = summarize(rec)
    return rec


def _half_cycle_rms(xs: list[float]) -> list[float]:
    w = SAMPLES_PER_CYCLE // 2
    return [math.sqrt(sum(v * v for v in xs[i:i + 2 * w]) / (2 * w))
            for i in range(0, len(xs) - 2 * w + 1, w)]


def thd(xs: list[float]) -> float:
    """THD of one cycle (32 samples) by DFT, harmonics 2..13."""
    n = SAMPLES_PER_CYCLE
    seg = xs[-n:]

    def mag(h: int) -> float:
        re = sum(v * math.cos(2 * math.pi * h * i / n) for i, v in enumerate(seg))
        im = sum(v * math.sin(2 * math.pi * h * i / n) for i, v in enumerate(seg))
        return math.hypot(re, im)
    fund = mag(1)
    if fund < 1e-9:
        return 0.0
    return math.sqrt(sum(mag(h) ** 2 for h in range(2, 14))) / fund


def classify(min_pu: float, cycles: float, ongoing: bool) -> str:
    """IEEE 1159-2009 Table 2 category of the RMS variation."""
    if min_pu >= 0.9:
        return "no RMS variation"
    if cycles < 0.5:
        return "transient notch (below 0.5 cycle)"
    if min_pu < 0.1:
        base = "interruption"
        if ongoing:
            return f"{base} (still on at the end of the record)"
        return f"momentary {base}" if cycles / NOMINAL_HZ <= 3.0 else f"temporary {base}"
    base = "sag"
    if ongoing:
        return f"{base} (still on at the end of the record)"
    return f"instantaneous {base}" if cycles <= 30 else (
        f"momentary {base}" if cycles / NOMINAL_HZ <= 3.0 else f"temporary {base}")


def summarize(rec: Record) -> dict[str, Any]:
    out: dict[str, Any] = {}
    n_pre = round(PRE_S * FS)
    for point, meta in POINTS.items():
        nominal = meta["vln_rms"]
        post = {ph: rec.samples[f"{point}_V{ph}"][n_pre:] for ph, _ in PHASES}
        rms = [min(vals) / nominal for vals in zip(*[_half_cycle_rms(v) for v in post.values()],
                                                   strict=True)]
        below = [r < 0.9 for r in rms]
        min_pu = min(rms) if rms else 1.0
        cycles = sum(below) * 0.5
        # A gap shorter than the half-cycle window still shows in the samples.
        tr = rec.transitions.get(point, Transition())
        if tr.kind == "notch" and not any(below):
            cycles = tr.seconds * NOMINAL_HZ
            min_pu = 0.0
        ongoing = bool(below) and below[-1]
        restored = rec.pre[point].amp < 0.1 and rec.post[point].amp >= 0.9
        out[point] = {
            "min_pu": round(min_pu, 3),
            "below_0_9_ms": round(cycles / NOMINAL_HZ * 1000, 1),
            "class": "voltage restored (source closed onto a dead bus)" if restored
            else classify(min_pu, cycles, ongoing),
            "thd_pct": round(thd(post["A"]) * 100, 1),
            "transition": tr.kind,
            "transition_ms": round(tr.seconds * 1000, 1),
        }
    return out


def _stamp(ts: float) -> str:
    d = datetime.fromtimestamp(ts, UTC)
    return d.strftime("%d/%m/%Y,%H:%M:%S.") + f"{d.microsecond:06d}"


def to_comtrade(rec: Record, station: str = "A3-ALPHA-TORONTO") -> tuple[str, str]:
    """(cfg, dat) text of an ASCII COMTRADE C37.111-1999 record."""
    n = len(rec.samples[CHANNELS[0]])
    scale = {}
    lines = [f"{station},DFR-PATH-{rec.path.upper()},1999", f"{len(CHANNELS)},{len(CHANNELS)}A,0D"]
    for i, ch in enumerate(CHANNELS, start=1):
        point, ph = ch.split("_V")
        meta = POINTS[point]
        peak = max(1e-9, max(abs(v) for v in rec.samples[ch]))
        a = peak / 32000.0
        scale[ch] = a
        lines.append(f"{i},{ch},{ph},{meta['name']},{meta['unit']},{a:.9g},0,0,-32767,32767,"
                     f"{meta['primary']},{meta['secondary']},P")
    first = rec.ts - PRE_S
    lines += [f"{NOMINAL_HZ:g}", "1", f"{FS:g},{n}", _stamp(first), _stamp(rec.ts), "ASCII", "1"]
    cfg = "\r\n".join(lines) + "\r\n"
    rows = []
    for k in range(n):
        us = round(k / FS * 1e6)
        vals = ",".join(str(round(rec.samples[ch][k] / scale[ch])) for ch in CHANNELS)
        rows.append(f"{k + 1},{us},{vals}")
    return cfg, "\r\n".join(rows) + "\r\n"


def describe(rec: Record, *, samples: bool = False) -> dict[str, Any]:
    d = {
        "id": rec.record_id, "path": rec.path, "ts": round(rec.ts, 3), "trigger": rec.trigger,
        "cause": list(rec.cause), "summary": rec.summary,
        "fs": FS, "pre_s": PRE_S, "post_s": POST_S,
        "points": {p: {"name": m["name"], "unit": m["unit"], "vln_rms": round(m["vln_rms"], 4)}
                   for p, m in POINTS.items()},
        "pre": {p: {"amp": s.amp, "hz": s.hz} for p, s in rec.pre.items()},
        "post": {p: {"amp": s.amp, "hz": s.hz} for p, s in rec.post.items()},
        "model_note": "synthesised from the plant state change; model transition times",
    }
    if samples:
        d["channels"] = list(CHANNELS)
        d["samples"] = rec.samples
    return d


# ── State to waveform rules (used by the device controller) ────────
LOAD_INVERTER, LOAD_DISTORTED, LOAD_BYPASS, LOAD_MAINT, LOAD_LOST = (
    "inverter", "inverter_distorted", "static_bypass", "maintenance_bypass", "lost")


def point_states(mv_live: bool, mv_hz: float, load: str) -> dict[str, PointState]:
    mv = PointState(amp=1.0 if mv_live else 0.0, hz=mv_hz)
    if load == LOAD_LOST:
        ld = PointState(amp=0.0)
    elif load in (LOAD_BYPASS, LOAD_MAINT):
        ld = PointState(amp=mv.amp, hz=mv_hz)
    elif load == LOAD_DISTORTED:
        ld = PointState(harmonics=tuple(FAULT_HARMONICS.items()))
    else:
        ld = PointState()
    return {"MV": mv, "LD": ld}


def transitions(pre: dict[str, Any], post: dict[str, Any], *, closed_transition: bool = False,
                phase_deg: float = 0.0) -> dict[str, Transition]:
    """pre / post: {"source": UTILITY|GENERATORS|NONE, "load": kind}."""
    s0, s1 = pre["source"], post["source"]
    if s0 != "NONE" and s1 == "NONE":
        mv = Transition("collapse")
    elif s0 == "NONE" and s1 != "NONE":
        mv = Transition("appear", phase_deg=phase_deg)
    elif s0 != s1:
        mv = (Transition("phase_step", phase_deg=phase_deg) if closed_transition
              else Transition("gap", seconds=OPEN_TRANSITION_S, phase_deg=phase_deg))
    else:
        mv = Transition()
    l0, l1 = pre["load"], post["load"]
    follows = (LOAD_BYPASS, LOAD_MAINT)
    on_ups = (LOAD_INVERTER, LOAD_DISTORTED)
    if l0 == l1:
        ld = mv if l1 in follows else Transition()
    elif l1 == LOAD_LOST:
        ld = Transition("collapse")
    elif l0 == LOAD_LOST:
        ld = Transition("appear")
    elif l0 in on_ups and l1 in on_ups:
        ld = Transition()                       # distortion starts or clears
    elif (l0 in on_ups) != (l1 in on_ups):
        ld = Transition("notch", seconds=STATIC_XFER_S)   # static switch
    else:
        ld = Transition()                       # MBB make-before-break
    return {"MV": mv, "LD": ld}
