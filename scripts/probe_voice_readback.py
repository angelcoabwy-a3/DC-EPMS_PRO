"""Voice readback phrasing probe (Shift Agentic Investigator).

HACKATHON probe-only task. Decides which spoken readback phrasing works
best with Muse Voice Transcribe, BEFORE wiring voice into the MOP
Verification view. Nothing is wired here; the parser is never changed.

Scope limits (hard):
  - Read-only wrt backend/, frontend/, data/, tests/. timestamps.json is
    read-only (it is the ONLY source of expected texts for the
    real-voice files). No commit / push.
  - No new requirements, no installs. Runs under the repo .venv as
    .\\.venv\\Scripts\\python.exe scripts\\probe_voice_readback.py
  - Credentials: META_API_KEY from the environment only; NEVER printed.
    Every printed line passes through _scrub().
  - The ONLY allowed network destination is api.meta.ai. The request
    shape is copied EXACTLY from scripts/probe_mop_vision.py step5:
    POST https://api.meta.ai/v1/asr/transcribe, model
    muse-voice-transcribe-1.0, multipart ("request" JSON part with
    mode=PUSH_TO_TALK + model + audioEncoding=WAV, "audio" WAV part),
    Bearer auth. Any deviation -> stop and report (exit 2).
  - Budget: at most 12 transcription calls total, one attempt per call,
    no retries, 60 s timeout per call. The Budget guard stops before
    any call that would exceed the cap.
  - Claim verdicts come ONLY from the imported backend parser
    (backend.mop_verify._parse_claim). It is never copied or changed.
    The "would pass if on/off" column is a report-only heuristic.
  - Converted WAVs land under the system temp folder only (never in
    the repo). Preflight makes zero network calls.

Usage (from the repo root):
    .\\.venv\\Scripts\\python.exe scripts\\probe_voice_readback.py              # full probe
    .\\.venv\\Scripts\\python.exe scripts\\probe_voice_readback.py --preflight  # local only, 0 calls

Exit codes: 0 = probe completed (PASS/FAIL is per file, in the report),
            2 = blocked (precondition / budget / endpoint mismatch).
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402  (repo dependency; never installed by this script)

from backend.llm_providers import MetaProvider  # noqa: E402  (read-only import)
from backend.mop_verify import _parse_claim  # noqa: E402  (operator-claim parser, read-only use)

TIMEOUT_S = 60.0
MAX_CALLS = 12
STT_MODEL = "muse-voice-transcribe-1.0"
EXPECTED_URL = "https://api.meta.ai/v1/asr/transcribe"

PHOTOS = ROOT / "scripts" / "probe_photos"
TS_PATH = PHOTOS / "timestamps.json"

# Input order = task listing order. expected_text None => from timestamps.json.
# (filename, source, expected_text, expected_label, expected_state, convert)
SYNTHETIC = [
    ("readback_step1_byp_on.wav", "synthetic", "Step one. B. Y. P. On.", "BYP", "CLOSED", False),
    (
        "readback_step2_q8_closed.wav",
        "synthetic",
        "Step two. Q eight. Closed.",
        "Q8",
        "CLOSED",
        False,
    ),
    ("readback_step2_q8_on.wav", "synthetic", "Step two. Q eight. On.", "Q8", "CLOSED", False),
]
REAL_M4A = [
    ("readback_initial.m4a", "real", None, "Q8", "OPEN", True),
    ("readback_step1.m4a", "real", None, "BYP", "CLOSED", True),
    ("readback_step2.m4a", "real", None, "Q8", "CLOSED", True),
]
REAL_EXTRA_STEM = "readback_step2_q8_on_real"
REAL_EXTRA_EXPECTED = "Step two. Q eight. On."

CALL_LOG = []  # per call: label/status/latency_s/error


class BlockedError(Exception):
    """Precondition / budget / environment failure: exit 2."""


class Budget:
    """Counts transcription calls; refuses the call that would exceed the cap."""

    def __init__(self, maximum):
        self.used = 0
        self.maximum = maximum

    def take(self, label):
        if self.used >= self.maximum:
            raise BlockedError(
                "STOP: transcription budget would be exceeded "
                f"({self.used}/{self.maximum}) at {label}; no request sent."
            )
        self.used += 1
        return self.used


def _scrub(text):
    """Redact the key value from anything about to be printed."""
    key = os.environ.get("META_API_KEY", "")
    if key and len(key) >= 4:
        text = text.replace(key, "[REDACTED]")
    return text


def _say(text):
    print(_scrub(str(text)), flush=True)


def _resolve_tmp_base():
    """Writable temp base: system temp outside the repo, else probe_photos/ (git-ignored).

    Each candidate is verified BEFORE anything is created under it, so a
    bad base can never litter the repo. Both locations are task-allowed.
    """
    cands = []
    for var in ("TMPDIR", "TEMP", "TMP"):
        val = os.environ.get(var)
        if val:
            cands.append(Path(val))
    with contextlib.suppress(Exception):
        cands.append(Path(tempfile.gettempdir()))
    for cand in cands:
        try:
            if not cand.exists():
                continue
            if cand.resolve() == ROOT.resolve() or ROOT.resolve() in cand.resolve().parents:
                continue
            probe = cand / ".voice_readback_write_test.tmp"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
            return cand
        except Exception:
            continue
    fallback = PHOTOS / "_tmp_voice_readback"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
        probe = fallback / ".voice_readback_write_test.tmp"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        _say(f"note: system temp unusable; using task-allowed {fallback.relative_to(ROOT)}/")
        return fallback
    except Exception as exc:
        raise BlockedError(
            f"no writable temp base (system temp + probe_photos fallback failed: {exc})"
        ) from exc


def _make_tmpdir():
    return Path(tempfile.mkdtemp(prefix="voice_readback_", dir=str(_resolve_tmp_base())))


def _m4a_to_wav(src, dst):
    """Same conversion as probe_mop_vision.py; validates WAV params."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg not on PATH"
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        "24000",
        "-c:a",
        "pcm_s16le",
        "-map_metadata",
        "-1",
        str(dst),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:
        return False, f"ffmpeg failed: {type(exc).__name__}: {exc}"
    if proc.returncode != 0 or not dst.exists():
        return False, f"ffmpeg exit={proc.returncode}: {(proc.stderr or '')[-200:]}"
    try:
        info = _wav_info(dst)
    except Exception as exc:
        return False, f"WAV unreadable: {type(exc).__name__}: {exc}"
    if (info["channels"], info["sampwidth"], info["rate"]) != (1, 2, 24000):
        return (
            False,
            f"WAV params {(info['channels'], info['sampwidth'], info['rate'])}, need (1, 2, 24000)",
        )
    return True, f"WAV mono/16-bit/24kHz ({dst.stat().st_size // 1024} KB)"


def _wav_info(path):
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        nframes = w.getnframes()
        return {
            "channels": w.getnchannels(),
            "sampwidth": w.getsampwidth(),
            "rate": rate,
            "duration_s": round(nframes / rate, 2) if rate else 0.0,
        }


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _would_pass_onoff(transcript, exp_label, exp_state):
    """Report-only heuristic for FAIL rows (NOT the parser verdict).

    Literal task rule: yes iff the transcript contains the correct label
    and the word on/off with the expected meaning (CLOSED<->on,
    OPEN<->off on this training panel). Label matching mirrors the prior
    probe's transcription-quality heuristic in
    scripts/probe_mop_vision.py::_label_state_captured, never the backend
    parser. Verdicts always come from the imported _parse_claim.
    """
    t = (transcript or "").lower()
    nospace = re.sub(r"\s+", "", t)
    if exp_label == "Q8":
        label_hit = bool(re.search(r"q\s*8", t)) or (bool(re.search(r"\bq\b", t)) and "eight" in t)
    elif exp_label == "BYP":
        label_hit = ("byp" in nospace) or ("bypass" in t)
    else:
        label_hit = False
    if exp_state == "CLOSED":
        word_hit = bool(re.search(r"\bon\b", t))
    elif exp_state == "OPEN":
        word_hit = bool(re.search(r"\boff\b", t))
    else:
        word_hit = False
    return bool(label_hit and word_hit)


def _load_expected_map():
    """readback_audio -> readback_expected, from timestamps.json only."""
    try:
        ts = json.loads(TS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BlockedError(f"cannot load timestamps.json: {exc}") from exc
    mapping = {}
    for frame in ts.get("frames", []):
        audio = frame.get("readback_audio")
        expected = frame.get("readback_expected")
        if audio and isinstance(expected, str) and expected.strip():
            mapping[audio] = expected
    return mapping


def _build_inputs():
    """Ordered input specs; real-voice expected texts from timestamps.json."""
    expected_map = _load_expected_map()
    inputs = []
    for name, source, text, label, state, convert in SYNTHETIC:
        inputs.append(
            {
                "file": name,
                "source": source,
                "expected_text": text,
                "exp_label": label,
                "exp_state": state,
                "convert": convert,
            }
        )
    for name, source, _text, label, state, convert in REAL_M4A:
        inputs.append(
            {
                "file": name,
                "source": source,
                "expected_text": expected_map.get(name),
                "exp_label": label,
                "exp_state": state,
                "convert": convert,
            }
        )
    extras = sorted(PHOTOS.glob(REAL_EXTRA_STEM + ".*"))
    if extras:
        extra = extras[0]
        inputs.append(
            {
                "file": extra.name,
                "source": "real",
                "expected_text": REAL_EXTRA_EXPECTED,
                "exp_label": "Q8",
                "exp_state": "CLOSED",
                "convert": extra.suffix.lower() != ".wav",
            }
        )
        if len(extras) > 1:
            _say(f"note: {len(extras)} {REAL_EXTRA_STEM}.* files; using {extra.name}")
    else:
        _say(f"note: no {REAL_EXTRA_STEM}.* file present; skipping that input")
    return inputs


def _preflight(inputs, tmpdir):
    """Step 1. Local only: files, conversion, duration/format. No network."""
    _say("=== STEP 1 preflight (0 network calls) ===")
    prepared = []
    for spec in inputs:
        src = PHOTOS / spec["file"]
        row = dict(spec)
        row["wav_path"] = None
        row["preflight"] = ""
        row["playable"] = False
        if not src.exists():
            row["preflight"] = "MISSING"
            _say(f"{spec['file']}: MISSING")
            prepared.append(row)
            continue
        if spec["expected_text"] is None:
            row["preflight"] = "UNTESTABLE (no expected text in timestamps.json)"
            _say(
                f"{spec['file']}: present ({src.stat().st_size // 1024} KB) but UNTESTABLE: no expected text in timestamps.json"
            )
            prepared.append(row)
            continue
        if spec["convert"]:
            dst = tmpdir / (src.stem + ".wav")
            ok, detail = _m4a_to_wav(src, dst)
            if not ok:
                row["preflight"] = f"convert FAIL: {detail}"
                _say(f"{spec['file']}: convert -> FAIL ({detail})")
                prepared.append(row)
                continue
            info = _wav_info(dst)
            row["wav_path"] = dst
            row["wav_info"] = info
            row["playable"] = True
            row["preflight"] = f"convert OK: {detail}; duration {info['duration_s']} s"
            _say(
                f"{spec['file']} [{spec['source']}]: convert -> {detail}; duration {info['duration_s']} s; expected {spec['expected_text']!r}"
            )
            prepared.append(row)
        else:
            try:
                info = _wav_info(src)
            except Exception as exc:
                row["preflight"] = f"WAV unreadable: {type(exc).__name__}"
                _say(f"{spec['file']}: WAV unreadable ({type(exc).__name__})")
                prepared.append(row)
                continue
            row["wav_path"] = src
            row["wav_info"] = info
            row["playable"] = True
            flag = (
                ""
                if (info["channels"], info["sampwidth"], info["rate"]) == (1, 2, 24000)
                else " (NOTE: not mono/16-bit/24kHz; sent as-is)"
            )
            row["preflight"] = (
                f"WAV ch={info['channels']} sw={info['sampwidth']} rate={info['rate']} duration={info['duration_s']} s{flag}"
            )
            _say(
                f"{spec['file']} [{spec['source']}]: {row['preflight']}; expected {spec['expected_text']!r}"
            )
            prepared.append(row)
    _say("mp3 siblings in probe_photos/ are out of scope and ignored")
    if not prepared:
        raise BlockedError("preflight prepared 0 inputs; refusing an empty probe")
    return prepared


def _parser_mapping_probe():
    """Step 3 (second half). Empirical on/off mapping, via the imported parser only."""
    _say("=== parser on/off mapping (imported backend parser, no network) ===")
    for probe in (
        "Q8 on",
        "Q8 off",
        "BYP on",
        "BYP off",
        "Q8 closed",
        "Q8 open",
        "Q8 opened",
        "BYP closed",
        "BYP open",
        "BYP opened",
    ):
        _say(f"  _parse_claim({probe!r}) -> {_parse_claim(probe)}")


def _extract_transcript(data):
    """Same extraction as probe_mop_vision.py step5 (turns, then transcript/text)."""
    turns = data.get("turns") if isinstance(data, dict) else None
    parts = []
    if isinstance(turns, list):
        for turn in turns:
            if isinstance(turn, dict) and turn.get("transcript"):
                parts.append(str(turn["transcript"]))
    transcript = " / ".join(parts)
    source = "turns" if transcript else ""
    if not transcript and isinstance(data, dict):
        for key in ("transcript", "text"):
            if isinstance(data.get(key), str) and data[key].strip():
                transcript = data[key].strip()
                source = key
                break
    return transcript, source


def _transcribe_one(url, api_key, wav_path, budget, label):
    """One transcription POST. No retries. Returns (transcript, src, error)."""
    n = budget.take(label)
    _say(f"[call {n}/{budget.maximum}] {label}")
    request_part = json.dumps({"mode": "PUSH_TO_TALK", "model": STT_MODEL, "audioEncoding": "WAV"})
    t0 = time.perf_counter()
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            files=[
                ("request", (None, request_part, "application/json")),
                ("audio", (wav_path.name, wav_path.read_bytes(), "audio/wav")),
            ],
            timeout=TIMEOUT_S,
        )
    except Exception as exc:
        dt = time.perf_counter() - t0
        err = f"{type(exc).__name__}: {exc}"
        CALL_LOG.append({"label": label, "status": None, "latency_s": round(dt, 1), "error": err})
        _say(f"{label}: ERROR {err}")
        return "", "", err
    dt = time.perf_counter() - t0
    try:
        data = resp.json()
    except Exception:
        data = None
    if resp.status_code != 200 or not data:
        err = f"HTTP {resp.status_code}: {(resp.text or '')[:200]}"
        CALL_LOG.append(
            {"label": label, "status": resp.status_code, "latency_s": round(dt, 1), "error": err}
        )
        _say(f"{label}: ERROR {err}")
        return "", "", err
    CALL_LOG.append({"label": label, "status": 200, "latency_s": round(dt, 1), "error": ""})
    transcript, source = _extract_transcript(data)
    if not transcript:
        _say(
            f"{label}: HTTP 200 but no transcript field (keys={sorted(data) if isinstance(data, dict) else '?'})"
        )
        return "", "", "HTTP 200 with no transcript in body"
    _say(f"{label}: transcript ({source}) {transcript!r}")
    return transcript, source, ""


def _report(prepared, budget, tmpdir):
    _say("=== REPORT ===")
    for row in prepared:
        _say(f"--- {row['file']} [{row['source']}] ---")
        _say(f"  expected text : {row.get('expected_text')!r}")
        _say(f"  expected claim: {row['exp_label']} {row['exp_state']}")
        _say(f"  preflight     : {row['preflight']}")
        if not row.get("transcribed"):
            _say(f"  transcript    : (none: {row.get('transcript_error', 'not attempted')})")
            _say("  parsed claim  : (none)")
            _say(f"  verdict       : {row.get('verdict', 'NOT RUN')}")
            continue
        _say(f"  transcript    : {row['transcript']!r} (via {row['transcript_src']})")
        _say(f"  exact match   : {row['exact']} (verbatim); normalized: {row['norm_match']}")
        if row["parsed"] is None:
            _say(
                "  parsed claim  : REJECTED (parser returned None; strict exactly-one-label + exactly-one-state rule)"
            )
        else:
            _say(f"  parsed claim  : {row['parsed']['label']} {row['parsed']['state']}")
        line = f"  verdict       : {row['verdict']}"
        if row["verdict"] == "FAIL":
            line += f"; would-pass-if-on/off: {'yes' if row['would_pass_onoff'] else 'no'}"
        _say(line)
    _say("=== STEP 4 reruns ===")
    _say("SKIPPED: no keyword/vocabulary/prompt-biasing parameter is available.")
    _say(
        "Why: the only allowed network destination is api.meta.ai, so the STT docs page was not fetched in this probe;"
    )
    _say(
        "the exact request shape from scripts/probe_mop_vision.py step5 documents only mode/model/audioEncoding."
    )
    _say(
        "The step-4 condition (exact parameter name + shape + docs section citation) is therefore unmet, so no rerun is justified."
    )
    skipped = [r["file"] for r in prepared if r.get("verdict") == "FAIL"]
    _say(
        f"reruns skipped for missing parameter (not budget): {skipped or 'none (no FAILs)'}"
        if skipped
        else "reruns skipped for missing parameter (not budget): none (no FAILs)"
    )
    _say(f"transcription calls used: {budget.used}/{budget.maximum}")
    for entry in CALL_LOG:
        _say(
            f"  {entry['label']}: status={entry['status']} latency_s={entry['latency_s']}"
            + (f" error={entry['error']}" if entry["error"] else "")
        )
    _say(f"temp dir: {tmpdir}")


def main(argv):
    preflight_only = "--preflight" in argv
    try:
        tmpdir = _make_tmpdir()
        inputs = _build_inputs()
        prepared = _preflight(inputs, tmpdir)
        _parser_mapping_probe()
    except BlockedError as exc:
        _say(f"BLOCKED: {exc}")
        return 2
    if preflight_only:
        _say("PREFLIGHT OK: 0 network calls made")
        return 0

    # --- Step 2: transcribe each playable file once ---
    _say("=== STEP 2 transcribe (default settings, one attempt each) ===")
    if not os.environ.get("META_API_KEY"):
        _say("BLOCKED: META_API_KEY is not set; no request attempted.")
        return 2
    provider = MetaProvider()
    url = f"{provider.api_url}/asr/transcribe"
    if url != EXPECTED_URL or urlparse(url).hostname != "api.meta.ai":
        _say(
            f"BLOCKED: endpoint {url} != {EXPECTED_URL} (or non-api.meta.ai host); refusing to guess."
        )
        return 2
    _say(f"endpoint: {url} (exact match, api.meta.ai only)")
    _say(
        "request: multipart request(JSON mode/model/audioEncoding) + audio(WAV), mode=PUSH_TO_TALK"
    )
    budget = Budget(MAX_CALLS)
    for row in prepared:
        row["transcribed"] = False
        if not row["playable"]:
            row["verdict"] = "UNTESTABLE" if row["expected_text"] is None else "NOT RUN"
            row["transcript_error"] = row["preflight"]
            continue
        label = f"voice-readback/{row['file']}"
        try:
            transcript, source, error = _transcribe_one(
                url, provider.api_key, row["wav_path"], budget, label
            )
        except BlockedError as exc:
            _say(str(exc))
            row["verdict"] = "NOT RUN"
            row["transcript_error"] = str(exc)
            break
        if error:
            row["transcript_error"] = error
            row["verdict"] = "ERROR"
            continue
        row["transcribed"] = True
        row["transcript"] = transcript
        row["transcript_src"] = source
        # --- Step 3: claim parsing, via the imported backend parser ---
        row["parsed"] = _parse_claim(transcript)
        row["exact"] = transcript == (row["expected_text"] or "")
        row["norm_match"] = _norm(transcript) == _norm(row["expected_text"] or "")
        if row["parsed"] is not None and (
            row["parsed"].get("label") == row["exp_label"]
            and row["parsed"].get("state") == row["exp_state"]
        ):
            row["verdict"] = "PASS"
        else:
            row["verdict"] = "FAIL"
            row["would_pass_onoff"] = _would_pass_onoff(
                transcript, row["exp_label"], row["exp_state"]
            )
    _report(prepared, budget, tmpdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
