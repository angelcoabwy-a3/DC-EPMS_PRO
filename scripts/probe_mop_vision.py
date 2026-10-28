"""MOP photo verification + voice readback probe (Shift Agentic Investigator).

HACKATHON probe-only task. Decides whether MOP photo verification (vision)
and voice readback stay in the project.

Scope limits (hard):
  - Read-only wrt backend/, frontend/, data/, tests/. No commit / push.
  - No new requirements, no installs. Runs under the repo .venv as
    .\\.venv\\Scripts\\python.exe scripts\\probe_mop_vision.py
  - Credentials: META_API_KEY from the environment only; NEVER printed.
    Every printed line passes through _scrub().
  - Same base URL + Bearer auth as backend.llm_providers.MetaProvider.
  - Budget: at most 20 Meta API calls total, max_tokens 4000 per chat call,
    one attempt per call, no retries, 120 s timeout. The Budget guard stops
    before any call that would exceed the cap.
  - Verdict NO_ANSWER (empty text, timeout, parse_error) never equals any
    expected_verdict. UNCERTAIN comes only from a parsed answer.
  - pathlib for all paths; temp files under tempfile.gettempdir() only.
  - timestamps.json is the ONLY source of ground truth / expected verdicts.

Usage (from the repo root):
    .\\.venv\\Scripts\\python.exe scripts\\probe_mop_vision.py              # full probe
    .\\.venv\\Scripts\\python.exe scripts\\probe_mop_vision.py --preflight  # local only, 0 Meta calls
    ... --tmpdir <path>   # override the temp base (must exist, be writable,
                          # and lie outside the repo; default is system temp)
    ... --only a,b        # run only stages control,vision,consistency,sam,voice
    ... --spent N         # N Meta calls already spent earlier (budget base)

Exit codes: 0 = gate PASS, 1 = gate FAIL (probe completed),
            2 = blocked (precondition / budget / resize failure).
"""

import base64
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402  (repo dependency; never installed by this script)

from backend.llm_providers import MetaProvider  # noqa: E402  (read-only import)

TIMEOUT_S = 120.0
MAX_TOKENS = 4000
MAX_CALLS = 20

MODEL_13 = "muse-spark-1.3"
MODEL_11 = "muse-spark-1.1"
CONTROL_TEXT = "What single color is this image?"

VISION_PROMPT = (
    "This photo shows a residential electrical panel used as a training panel. "
    "Each breaker has a paper label next to it: Q1 to Q9 and BYP. "
    "On this panel a handle points toward the center of the panel when ON: "
    "to the right in the left column, to the left in the right column. "
    "Report every label you can read. "
    'Return only JSON: {"breakers": {"<label>": "ON|OFF|UNKNOWN", ...}, '
    '"notes": "short reason for any UNKNOWN"}. '
    "Use UNKNOWN if a label or its handle is not clearly visible, partly covered, "
    "or blurred. Do not guess."
)

SAM_DOCS_URL = "https://dev.meta.ai/docs/sam/overview"
SAM_SEGMENTING_URL = "https://dev.meta.ai/docs/sam/segmenting"  # request shape only
STT_DOCS_URL = "https://dev.meta.ai/docs/speech-to-text"
STT_MODEL = "muse-voice-transcribe-1.0"
SAM_MODEL = "sam-3.1"

COLOR_WORDS = (
    "red",
    "orange",
    "yellow",
    "green",
    "blue",
    "indigo",
    "violet",
    "black",
    "white",
    "gray",
    "grey",
    "brown",
    "pink",
    "purple",
)
HEDGE_WORDS = (
    "can't",
    "cannot",
    "no image",
    "don't see",
    "do not see",
    "unable",
    "without",
    "not provided",
    "didn't receive",
)


class BlockedError(Exception):
    """Precondition / budget / environment failure: exit 2."""


class Budget:
    """Counts Meta API calls; refuses the call that would exceed the cap."""

    def __init__(self, maximum, already_spent=0):
        self.used = already_spent
        self.maximum = maximum

    def take(self, label):
        if self.used >= self.maximum:
            raise BlockedError(
                "STOP: Meta call budget would be exceeded "
                f"({self.used}/{self.maximum}) at {label}; no request sent."
            )
        self.used += 1
        return self.used


CALL_LOG = []  # per call: label/status/usage/cost/error/latency_s/finish_reason/reasoning_tokens/timeout


def _scrub(text):
    """Redact the key value from anything about to be printed."""
    key = os.environ.get("META_API_KEY", "")
    if key and len(key) >= 4:
        text = text.replace(key, "[REDACTED]")
    return text


def _say(text):
    print(_scrub(str(text)), flush=True)


def _endpoint():
    """Same base URL and auth header MetaProvider already uses."""
    provider = MetaProvider()
    url = f"{provider.api_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {provider.api_key}",
    }
    return provider, url, headers


def _usage_of(data):
    if isinstance(data, dict) and isinstance(data.get("usage"), dict):
        return data["usage"]
    return {}


def _cost_of(data):
    """Estimated cost per call, only if the API returns it."""
    if not isinstance(data, dict):
        return None
    for key in ("cost", "estimated_cost", "estimatedCost", "price", "total_cost"):
        if data.get(key) is not None:
            return {key: data[key]}
    usage = data.get("usage")
    if isinstance(usage, dict):
        for key in ("cost", "estimated_cost", "estimatedCost", "price"):
            if usage.get(key) is not None:
                return {f"usage.{key}": usage[key]}
    return None


def _finish_reason_of(data):
    try:
        return data["choices"][0].get("finish_reason")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def _reasoning_of(data):
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return None
    det = usage.get("completion_tokens_details")
    if not isinstance(det, dict):
        return None
    return det.get("reasoning_tokens")


def _post_json(url, headers, payload, budget, label):
    """One Meta JSON call. No retries. Returns (status, data, error)."""
    n = budget.take(label)
    _say(f"[call {n}/{budget.maximum}] {label}")
    t0 = time.perf_counter()
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=TIMEOUT_S)
    except Exception as exc:
        dt = time.perf_counter() - t0
        timed_out = (
            isinstance(exc, httpx.TimeoutException) or "timeout" in type(exc).__name__.lower()
        )
        err = f"{type(exc).__name__}: {exc}"
        CALL_LOG.append(
            {
                "label": label,
                "status": None,
                "usage": {},
                "cost": None,
                "error": err,
                "latency_s": round(dt, 1),
                "finish_reason": None,
                "reasoning_tokens": None,
                "timeout": timed_out,
            }
        )
        if timed_out:
            _say(f"TIMEOUT after {dt:.1f}s: {label} (counts toward the budget)")
        return None, None, err
    dt = time.perf_counter() - t0
    try:
        data = resp.json()
    except Exception:
        data = None
    if resp.status_code != 200:
        body = (resp.text or "")[:200]
        CALL_LOG.append(
            {
                "label": label,
                "status": resp.status_code,
                "usage": {},
                "cost": None,
                "error": f"HTTP {resp.status_code}: {body}",
                "latency_s": round(dt, 1),
                "finish_reason": None,
                "reasoning_tokens": None,
                "timeout": False,
            }
        )
        return resp.status_code, data, f"HTTP {resp.status_code}: {body}"
    if not data:
        CALL_LOG.append(
            {
                "label": label,
                "status": resp.status_code,
                "usage": {},
                "cost": None,
                "error": "HTTP 200 with empty/non-JSON body",
                "latency_s": round(dt, 1),
                "finish_reason": None,
                "reasoning_tokens": None,
                "timeout": False,
            }
        )
        return resp.status_code, data, "HTTP 200 with empty/non-JSON body"
    CALL_LOG.append(
        {
            "label": label,
            "status": 200,
            "usage": _usage_of(data),
            "cost": _cost_of(data),
            "error": "",
            "latency_s": round(dt, 1),
            "finish_reason": _finish_reason_of(data),
            "reasoning_tokens": _reasoning_of(data),
            "timeout": False,
        }
    )
    return resp.status_code, data, ""


def _assistant_text(data):
    """Split choices[0].message content from empty-content diagnostics."""
    try:
        choice = data["choices"][0]
        msg = choice.get("message") or {}
        keys = sorted(msg.keys())
    except (KeyError, IndexError, TypeError, AttributeError):
        return "", "ERROR no choices[0].message in response"
    text = msg.get("content") or ""
    if isinstance(text, str) and text.strip():
        return text, None
    usage = data.get("usage")
    if isinstance(usage, dict) and usage:
        use = (
            f"usage prompt={usage.get('prompt_tokens')} "
            f"completion={usage.get('completion_tokens')} "
            f"total={usage.get('total_tokens')}"
        )
    else:
        use = "usage not included"
    return "", (f"EMPTY finish_reason={choice.get('finish_reason')} message_keys={keys} {use}")


def _chat(model, messages, budget, label):
    """One non-streaming chat call (max_tokens 4000, no retries).

    reasoning_effort=low is sent explicitly; the API accepts it (HTTP 200
    with reasoning_tokens in usage on the first probe's calls).
    """
    _, url, headers = _endpoint()
    payload = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "reasoning_effort": "low",
        "stream": False,
        "messages": messages,
    }
    status, data, error = _post_json(url, headers, payload, budget, label)
    last = CALL_LOG[-1] if CALL_LOG else {}
    base = {
        "latency_s": last.get("latency_s"),
        "finish_reason": last.get("finish_reason"),
        "reasoning_tokens": last.get("reasoning_tokens"),
        "timeout": last.get("timeout", False),
    }
    if error or data is None:
        return {"text": "", "diag": None, "error": error, "usage": {}, **base}
    text, diag = _assistant_text(data)
    return {"text": text, "diag": diag, "error": "", "usage": _usage_of(data), **base}


def _red_png(width=512, height=512):
    """Solid-red PNG (RGB color type 2, no alpha) via stdlib only."""

    def chunk(chunk_type, data):
        head = struct.pack(">I", len(data)) + chunk_type + data
        return head + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _validate_red_png(png, width=512, height=512):
    """Local stdlib validation: size, RGB, pixel (0,0) == (255,0,0)."""
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        return False, "bad PNG signature"
    pos = 8
    ihdr = None
    idat = b""
    while pos + 8 <= len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        ctype = png[pos + 4 : pos + 8]
        data = png[pos + 8 : pos + 8 + length]
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", data)
        elif ctype == b"IDAT":
            idat += data
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if ihdr is None:
        return False, "IHDR missing"
    w, h, depth, ctype_n, _, _, _ = ihdr
    if (w, h, depth, ctype_n) != (width, height, 8, 2):
        return False, f"IHDR={w}x{h} depth={depth} ctype={ctype_n}"
    raw = zlib.decompress(idat)
    stride = 1 + width * 3
    if len(raw) < stride or raw[0] != 0:
        return False, "first scanline unreadable"
    px = tuple(raw[1:4])
    if px != (255, 0, 0):
        return False, f"pixel(0,0)={px}"
    return True, f"{w}x{h} RGB pixel(0,0)=(255,0,0)"


def _strip_tags(html):
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def _resolve_tmp_base(override):
    """Writable temp base outside the repo (tempfile still creates the dir)."""
    if override:
        cand = Path(override)
        problems = []
        if not cand.exists():
            problems.append("does not exist")
        try:
            if cand.resolve() == ROOT.resolve() or ROOT.resolve() in cand.resolve().parents:
                problems.append("is inside the repo")
        except Exception:
            problems.append("unresolvable")
        if not problems:
            try:
                probe = cand / ".probe_write_test.tmp"
                probe.write_text("x", encoding="utf-8")
                probe.unlink()
            except Exception as exc:
                problems.append(f"not writable ({type(exc).__name__})")
        if problems:
            raise BlockedError(f"--tmpdir {cand}: {'; '.join(problems)}")
        return cand
    cands = [Path(tempfile.gettempdir())]
    for var in ("TEMP", "TMP", "TMPDIR"):
        val = os.environ.get(var)
        if val:
            cands.append(Path(val))
    for cand in cands:
        try:
            if not cand.exists():
                continue
            resolved = cand.resolve()
            if resolved == ROOT.resolve() or ROOT.resolve() in resolved.parents:
                continue
            probe = cand / ".probe_write_test.tmp"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
            return cand
        except Exception:
            continue
    raise BlockedError(
        "no writable temp folder outside the repo "
        f"(tried {[str(c) for c in cands]}); refusing the repo."
    )


def _make_tmpdir(prefix, override):
    tmpdir = Path(tempfile.mkdtemp(prefix=prefix, dir=str(_resolve_tmp_base(override))))
    try:
        tmpdir.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return tmpdir
    raise BlockedError(f"temp dir resolved inside the repo: {tmpdir}")


def _tmpdir_override(argv):
    if "--tmpdir" in argv:
        idx = argv.index("--tmpdir")
        if idx + 1 >= len(argv):
            raise BlockedError("--tmpdir needs a path argument")
        return argv[idx + 1]
    return None


STAGES = ("control", "vision", "consistency", "sam", "voice")


def _only_stages(argv):
    if "--only" not in argv:
        return None
    idx = argv.index("--only")
    if idx + 1 >= len(argv):
        raise BlockedError("--only needs a comma-separated stage list")
    stages = [s.strip() for s in argv[idx + 1].split(",") if s.strip()]
    unknown = [s for s in stages if s not in STAGES]
    if not stages or unknown:
        raise BlockedError(f"--only must be a subset of {','.join(STAGES)}")
    return stages


def _spent(argv):
    if "--spent" not in argv:
        return 0
    idx = argv.index("--spent")
    try:
        n = int(argv[idx + 1])
    except (IndexError, ValueError) as err:
        raise BlockedError("--spent needs an integer") from err
    if n < 0 or n >= MAX_CALLS:
        raise BlockedError(f"--spent must be in 0..{MAX_CALLS - 1}")
    return n


def _fetch_docs(url):
    """GET a docs page. dev.meta.ai is not a Meta API call (no budget)."""
    try:
        resp = httpx.get(url, timeout=20.0, follow_redirects=True)
    except Exception as exc:
        return None, f"{url} unreachable: {type(exc).__name__}"
    if resp.status_code != 200 or not (resp.text or "").strip():
        return None, f"{url} HTTP {resp.status_code}"
    return resp.text, ""


# ---------------------------------------------------------------- Step 0


def step0():
    """Preconditions. Raises BlockedError (exit 2) if any fails."""
    _say("=== STEP 0 preconditions ===")
    key_set = bool(os.environ.get("META_API_KEY"))
    _say(f"META_API_KEY set: {key_set}")
    if not key_set:
        raise BlockedError("META_API_KEY is not set; no request attempted.")

    mop_path = ROOT / "data" / "mop_ups_bypass.json"
    mop = json.loads(mop_path.read_text(encoding="utf-8"))
    n_steps = len(mop["steps"])
    _say(f"mop_id={mop['mop_id']} version={mop['version']} steps={n_steps}")
    if mop["version"] != "1.3" or n_steps != 5:
        raise BlockedError(f"need version 1.3 + 5 steps, got {mop['version']} + {n_steps}")

    photos = ROOT / "scripts" / "probe_photos"
    ts = json.loads((photos / "timestamps.json").read_text(encoding="utf-8"))
    _say(f"timestamps status={ts['status']} frames={len(ts['frames'])}")
    if ts["status"] != "CONFIRMED":
        raise BlockedError(f"timestamps status is {ts['status']!r}, need CONFIRMED")
    missing = []
    for frame in ts["frames"]:
        if not (photos / frame["file"]).exists():
            missing.append(frame["file"])
        audio = frame.get("readback_audio")
        if audio and not (photos / audio).exists():
            missing.append(audio)
    if missing:
        raise BlockedError(f"files listed in timestamps.json missing: {missing}")
    _say(
        f"all listed files present ({len(ts['frames'])} frames + "
        f"{sum(1 for f in ts['frames'] if f.get('readback_audio'))} audio)"
    )

    git_base = ["git", "-c", f"safe.directory={ROOT.as_posix()}"]
    try:
        ignored = True
        for probe_file in (
            "scripts/probe_photos/timestamps.json",
            "scripts/probe_photos/01_initial.jpg",
        ):
            ign = subprocess.run(
                [*git_base, "check-ignore", "-q", probe_file],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            ignored = ignored and (ign.returncode == 0)
        lst = subprocess.run(
            [*git_base, "ls-files", "scripts/probe_photos/"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as err:
        raise BlockedError("git binary not found; cannot confirm ignore status.") from err
    tracked = lst.stdout.strip().splitlines() if lst.returncode == 0 else None
    _say(f"git: probe_photos ignored={ignored} tracked_files={tracked}")
    if not ignored or tracked is None or len(tracked) != 0:
        raise BlockedError("scripts/probe_photos/ must be ignored with 0 tracked files.")
    _say("STEP 0: all preconditions hold")
    return mop, ts


# ---------------------------------------------------------------- Step 1


def step1_text_only_observation(answer):
    found = [c for c in COLOR_WORDS if c in answer.lower()]
    hedged = any(h in answer.lower() for h in HEDGE_WORDS)
    return found, (bool(found) and not hedged)


def step1(budget, tmpdir):
    """Control tests: red PNG with image, then same text without image."""
    _say("=== STEP 1 control tests ===")
    png = _red_png(512, 512)
    ok, detail = _validate_red_png(png)
    _say(f"local red-PNG validation: {'OK' if ok else 'FAIL'} ({detail})")
    if not ok:
        raise BlockedError(f"local red-PNG validation failed: {detail}")
    red_path = tmpdir / "control_red_512.png"
    red_path.write_bytes(png)

    png_b64 = base64.b64encode(png).decode("ascii")
    with_image = _chat(
        MODEL_13,
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": CONTROL_TEXT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
                ],
            }
        ],
        budget,
        "control/with-image muse-spark-1.3",
    )
    if with_image["error"]:
        _say(f"control/with-image ERROR: {with_image['error']}")
        img_pass = False
    else:
        _say(f"control/with-image answer: {with_image['text']!r}")
        if with_image["diag"]:
            _say(f"control/with-image diag: {with_image['diag']}")
        img_pass = "red" in with_image["text"].lower()
    _say(
        f"control/with-image: {'PASS' if img_pass else 'FAIL'} "
        "(PASS only if the answer contains 'red')"
    )

    text_only = _chat(
        MODEL_13, [{"role": "user", "content": CONTROL_TEXT}], budget, "control/text-only"
    )
    if text_only["error"]:
        _say(f"control/text-only ERROR: {text_only['error']}")
        found, confident = [], False
    else:
        _say(f"control/text-only answer: {text_only['text']!r}")
        if text_only["diag"]:
            _say(f"control/text-only diag: {text_only['diag']}")
        found, confident = step1_text_only_observation(text_only["text"])
    _say(f"control/text-only color words={found} confident_color={confident}")
    if confident:
        _say(
            "NOTE: text-only run also named a color with confidence; "
            "images may not have been reaching the model in earlier tests."
        )
    return {
        "with_image_pass": img_pass,
        "with_image_answer": with_image["text"],
        "text_only_answer": text_only["text"],
        "text_only_confident_color": confident,
    }


# ---------------------------------------------------------------- Step 2


def step2(ts, tmpdir):
    """Resized copies (long side <= 1600 px) in the temp folder."""
    _say("=== STEP 2 photo size ===")
    photos = ROOT / "scripts" / "probe_photos"
    resized = {}
    try:
        from PIL import Image
    except Exception as exc:
        Image = None
        _say(f"Pillow not importable: {type(exc).__name__}")
    if Image is not None:
        _say("resize engine: Pillow")
        for frame in ts["frames"]:
            src = photos / frame["file"]
            with Image.open(src) as img:
                orig = img.size
                img = img.convert("RGB")
                img.thumbnail((1600, 1600))
                dst = tmpdir / f"resized_{frame['file']}"
                img.save(dst, "JPEG", quality=90)
                new = img.size
            resized[frame["file"]] = {
                "path": dst,
                "orig": orig,
                "new": new,
                "bytes": dst.stat().st_size,
            }
            _say(
                f"{frame['file']}: {orig[0]}x{orig[1]} -> "
                f"{new[0]}x{new[1]} ({dst.stat().st_size // 1024} KB)"
            )
        return resized
    for tool in ("ffmpeg", "magick", "convert"):
        if shutil.which(tool):
            raise BlockedError(
                f"resize via {tool} not wired in this probe and "
                "Pillow is absent; stopping per Step 2."
            )
    raise BlockedError(
        "no Pillow / ffmpeg / ImageMagick: originals are 2160x3840 "
        "and the image size limit could not be verified locally; "
        "stopping per Step 2 without sending originals."
    )


# ---------------------------------------------------------------- Step 3


def _norm_label(label):
    return re.sub(r"[\s\-_]+", "", str(label).upper())


def _norm_state(value):
    v = str(value).strip().upper()
    if v in ("ON", "CLOSED"):
        return "CLOSED"
    if v in ("OFF", "OPEN"):
        return "OPEN"
    return "UNKNOWN"


def _extract_json(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None, "no JSON object found in answer"
    try:
        return json.loads(t[start : end + 1]), ""
    except json.JSONDecodeError as exc:
        return None, f"JSON decode error: {exc}"


def _score_frame(frame, mop, answer, call_error=""):
    """Score one vision answer in code. Never trusts a model verdict."""
    scored = [p["label"] for p in mop["panel"]]
    valid = {_norm_label(p["label"]) for p in mop["panel"]}
    valid |= {_norm_label(d["label"]) for d in mop.get("distractors", [])}
    distractors = {_norm_label(d["label"]) for d in mop.get("distractors", [])}

    parsed, parse_error = _extract_json(answer)
    if parsed is not None and not isinstance(parsed, dict):
        parsed, parse_error = None, "top-level JSON is not an object"
    no_answer = bool(call_error) or not (answer or "").strip() or parsed is None
    raw_breakers = {}
    notes = ""
    if parsed is not None:
        if isinstance(parsed.get("breakers"), dict):
            raw_breakers = parsed["breakers"]
        notes = str(parsed.get("notes", ""))[:300]

    mapped = {}
    for label, value in raw_breakers.items():
        mapped[_norm_label(label)] = _norm_state(value)

    hallucinations = sorted(label for label in mapped if label not in valid)
    distractor_report = {label: mapped[label] for label in sorted(mapped) if label in distractors}

    truth = frame["ground_truth"]
    per_label = {}
    if isinstance(truth, dict):
        for label in scored:
            got = mapped.get(label)
            per_label[label] = {
                "got": got if got else "MISSING",
                "want": truth[label],
                "correct": got == truth[label],
            }
    else:
        for label in scored:
            got = mapped.get(label)
            per_label[label] = {
                "got": got if got else "MISSING",
                "want": "n/a (frame truth is UNCERTAIN)",
                "correct": None,
            }

    cas = frame["checked_against_step"]
    if cas == "initial_state":
        expected = mop["initial_state"]
    else:
        expected = next(s for s in mop["steps"] if s["step_id"] == cas)["expected_state"]

    if no_answer:
        verdict, differing = "NO_ANSWER", []
    elif any(mapped.get(label, "MISSING") in ("UNKNOWN", "MISSING") for label in scored):
        verdict, differing = "UNCERTAIN", []
    else:
        differing = sorted(label for label in scored if mapped[label] != expected[label])
        verdict = "MISMATCH" if differing else "MATCH"

    return {
        "raw": answer,
        "parse_error": parse_error,
        "notes": notes,
        "mapped": mapped,
        "per_label": per_label,
        "distractors": distractor_report,
        "hallucinations": hallucinations,
        "verdict": verdict,
        "differing": differing,
        "no_answer": no_answer,
        "expected": expected,
        "expected_verdict": frame["expected_verdict"],
    }


def _attach_call(res, ans):
    """Copy per-call transport stats from a _chat answer onto a frame result."""
    res["diag"] = ans["diag"]
    res["call_error"] = ans["error"]
    res["latency_s"] = ans.get("latency_s")
    res["finish_reason"] = ans.get("finish_reason")
    res["usage"] = ans.get("usage") or {}
    res["reasoning_tokens"] = ans.get("reasoning_tokens")
    res["timeout"] = ans.get("timeout", False)
    return res


def _vision_call(image_path, model, budget, label):
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return _chat(
        model,
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
        budget,
        label,
    )


def _print_frame_result(name, result):
    r = result
    _say(f"--- {name} ---")
    _say(f"raw answer: {r['raw']!r}")
    if r.get("diag"):
        _say(f"diag: {r['diag']}")
    if r["parse_error"]:
        _say(f"parse: {r['parse_error']}")
    if r.get("call_error"):
        _say(f"call error: {r['call_error']}")
    u = r.get("usage") or {}
    _say(
        f"call: latency_s={r.get('latency_s')} "
        f"finish_reason={r.get('finish_reason')} "
        f"prompt={u.get('prompt_tokens')} "
        f"completion={u.get('completion_tokens')} "
        f"reasoning={r.get('reasoning_tokens')} "
        f"timeout={r.get('timeout', False)}"
    )
    for label, cell in r["per_label"].items():
        mark = "n/a" if cell["correct"] is None else ("OK" if cell["correct"] else "WRONG")
        _say(f"  {label}: got={cell['got']} want={cell['want']} -> {mark}")
    _say(f"distractors reported (not scored): {r['distractors'] or '{}'}")
    _say(f"hallucinated labels: {r['hallucinations'] or 'none'}")
    _say(
        f"computed verdict={r['verdict']} differing={r['differing'] or 'none'} "
        f"expected_verdict={r['expected_verdict']}"
    )


def step3(mop, ts, resized, budget):
    """Vision test: every frame on 1.3, then repeats on 1.1."""
    _say("=== STEP 3 vision test ===")
    primary, extra_11 = {}, {}
    for frame in ts["frames"]:
        name = frame["file"]
        ans = _vision_call(resized[name]["path"], MODEL_13, budget, f"vision/1.3/{name}")
        if ans["error"]:
            _say(f"--- {name} --- ERROR: {ans['error']}")
        res = _score_frame(
            frame, mop, ans["text"] if not ans["error"] else "", call_error=ans["error"]
        )
        _attach_call(res, ans)
        res["model"] = MODEL_13
        primary[name] = res
        _print_frame_result(f"{name} [{MODEL_13} primary]", res)

    for name in ("01_initial.jpg", "07_mismatch_after_step2.jpg", "08_uncertain.jpg"):
        frame = next(f for f in ts["frames"] if f["file"] == name)
        ans = _vision_call(resized[name]["path"], MODEL_11, budget, f"vision/1.1/{name}")
        res = _score_frame(
            frame, mop, ans["text"] if not ans["error"] else "", call_error=ans["error"]
        )
        _attach_call(res, ans)
        res["model"] = MODEL_11
        extra_11[name] = res
        _print_frame_result(f"{name} [{MODEL_11} repeat]", res)

    return {"primary": primary, "extra_11": extra_11}


def step3_consistency(mop, ts, resized, budget, primary07):
    """Two extra 07 runs on 1.3; compares every available run."""
    _say("=== STEP 3b 07 consistency ===")
    frame07 = next(f for f in ts["frames"] if f["file"] == "07_mismatch_after_step2.jpg")
    runs = {}
    if primary07 is not None:
        runs["run1_primary"] = primary07
    for i in (2, 3):
        ans = _vision_call(
            resized["07_mismatch_after_step2.jpg"]["path"],
            MODEL_13,
            budget,
            f"vision/1.3/07_mismatch_after_step2.jpg run{i}",
        )
        res = _score_frame(
            frame07, mop, ans["text"] if not ans["error"] else "", call_error=ans["error"]
        )
        _attach_call(res, ans)
        res["model"] = MODEL_13
        runs[f"run{i}"] = res
        _print_frame_result(f"07_mismatch_after_step2.jpg [{MODEL_13} run{i}]", res)
    snaps = [(r["verdict"], r["mapped"], r["differing"]) for r in runs.values()]
    consistent = len(snaps) > 1 and all(s == snaps[0] for s in snaps)
    _say(
        f"07 consistency across {len(snaps)} {MODEL_13} runs "
        f"({', '.join(runs)}): {'CONSISTENT' if consistent else 'INCONSISTENT'}"
    )
    return {"runs": runs, "consistent_07": consistent}


# ---------------------------------------------------------------- Step 4


def _confirm_sam_endpoint(provider):
    """Endpoint ONLY from the docs page. Returns (url, citation) or (None, why)."""
    body, error = _fetch_docs(SAM_DOCS_URL)
    if body is None:
        return None, f"SAM endpoint not confirmed from docs ({error})"
    text = _strip_tags(body)
    if SAM_MODEL not in text:
        return None, "SAM endpoint not confirmed from docs (no sam-3.1 on page)"
    direct = re.search(r"https://api\.meta\.ai/v1/responses\b", text)
    if direct:
        url = direct.group(0)
    elif "https://api.meta.ai/v1" in text and "/v1/responses" in text:
        url = "https://api.meta.ai/v1/responses"  # documented base + path
    else:
        return None, "SAM endpoint not confirmed from docs"
    if not url.startswith(provider.api_url):
        return None, (
            f"SAM endpoint not confirmed from docs "
            f"(docs say {url}, client base is {provider.api_url})"
        )
    at = text.find("/v1/responses")
    cite = text[max(0, at - 120) : at + 60].strip()
    return url, f"{SAM_DOCS_URL} :: ...{cite}... (+ model {SAM_MODEL})"


def _sam_output_preview(dump):
    """First output line with mask payloads stripped, truncated to 600 chars."""
    out_text = ""
    for match in re.finditer(r"<0f>.*?(?=<0f>|$)", dump):
        out_text = match.group(0)
        break
    return re.sub(r"<\|mask.*?\|\>", "<|mask...|>", out_text)[:600]


def step4(budget):
    """SAM 3.1: 01_initial + concept 'circuit breaker', iff docs-confirmed."""
    _say("=== STEP 4 SAM 3.1 ===")
    provider = MetaProvider()
    url, citation = _confirm_sam_endpoint(provider)
    if url is None:
        _say(citation)
        return {"ran": False, "reason": citation}
    _say(f"endpoint confirmed: {url}")
    _say(f"citation: {citation}")
    _say(
        f"request shape: Responses API input_text + input_image data URL "
        f"(per {SAM_SEGMENTING_URL}: image_url accepts a base64 data URL)"
    )

    src = ROOT / "scripts" / "probe_photos" / "01_initial.jpg"
    raw = src.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    payload = {
        "model": SAM_MODEL,
        "stream": False,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "circuit breaker"},
                    {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"},
                ],
            }
        ],
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {provider.api_key}"}
    status, data, error = _post_json(url, headers, payload, budget, "sam/01_initial")
    if error or data is None:
        _say(f"SAM call ERROR: {error}")
        return {
            "ran": True,
            "url": url,
            "citation": citation,
            "error": error,
            "detections": None,
            "boxes": [],
        }
    dump = json.dumps(data)
    boxes = re.findall(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>", dump)
    out_text = _sam_output_preview(dump)
    _say(f"SAM sent: 01_initial.jpg ({len(raw) // 1024} KB, original pixels)")
    _say(f"SAM detections (boxes): {len(boxes)}")
    for i, (x1, y1, x2, y2, w, h) in enumerate(boxes):
        _say(f"  box{i}: x1={x1} y1={y1} x2={x2} y2={y2} (source {w}x{h})")
    _say(f"SAM output_text (masks stripped, truncated): {out_text!r}")
    return {
        "ran": True,
        "url": url,
        "citation": citation,
        "error": "",
        "detections": len(boxes),
        "boxes": boxes,
        "sent_bytes": len(raw),
    }


# ---------------------------------------------------------------- Step 5


def _confirm_stt_endpoint(provider):
    """Endpoint ONLY from the docs page. Returns (url, citation) or (None, why)."""
    body, error = _fetch_docs(STT_DOCS_URL)
    if body is None:
        return None, f"voice skipped: could not read STT docs ({error})"
    text = _strip_tags(body)
    if STT_MODEL not in text:
        return None, (
            "voice skipped: model muse-voice-transcribe-1.0 not named on the STT docs page"
        )
    direct = re.search(r"https://api\.meta\.ai/v1/asr/transcribe\b", text)
    if not direct:
        return None, ("voice skipped: no transcribe endpoint documented on the STT docs page")
    url = direct.group(0)
    if not url.startswith(provider.api_url):
        return None, (f"voice skipped: docs say {url}, client base is {provider.api_url}")
    at = text.find("asr/transcribe")
    cite = text[max(0, at - 160) : at + 40].strip()
    return url, f"{STT_DOCS_URL} :: ...{cite}... (+ model {STT_MODEL})"


def _m4a_to_wav(src, dst):
    """Docs-specified conversion; validates WAV params with stdlib wave."""
    import wave

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
    with wave.open(str(dst), "rb") as wav:
        params = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate())
    if params != (1, 2, 24000):
        return False, f"WAV params {params}, need (1, 2, 24000)"
    return True, f"WAV mono/16-bit/24kHz ({dst.stat().st_size // 1024} KB)"


def _label_state_captured(transcript, expected):
    t = (transcript or "").lower()
    nospace = re.sub(r"\s+", "", t)
    exp = (expected or "").lower()
    if "eight" in exp:
        label = "Q8"
        label_ok = (re.search(r"\bq\b", t) and "eight" in t) or bool(re.search(r"q\s*8", t))
        label_ok = bool(label_ok)
    elif "b y p" in exp or "byp" in exp.replace(" ", ""):
        label = "BYP"
        label_ok = "byp" in nospace or "bypass" in t or bool(re.search(r"\bb\s*y\s*p\b", t))
    else:
        label, label_ok = "?", False
    if "closed" in exp:
        state, state_ok = "CLOSED", ("closed" in t or bool(re.search(r"\bclose\b", t)))
    elif "open" in exp:
        state, state_ok = "OPEN", bool(re.search(r"\bopen\b", t))
    else:
        state, state_ok = "?", False
    return label, bool(label_ok), state, bool(state_ok)


def step5(ts, tmpdir, budget):
    """Voice readback transcription, iff a docs-confirmed endpoint exists."""
    _say("=== STEP 5 voice ===")
    provider = MetaProvider()
    url, citation = _confirm_stt_endpoint(provider)
    if url is None:
        _say(citation)
        return {"ran": False, "reason": citation, "files": {}}
    _say(f"endpoint confirmed: {url}")
    _say(f"citation: {citation}")
    _say(
        "request: multipart request(JSON model/mode/audioEncoding) + audio(WAV), "
        "mode=PUSH_TO_TALK (docs default for a controlled recording)"
    )

    photos = ROOT / "scripts" / "probe_photos"
    files = {}
    for frame in ts["frames"]:
        audio = frame.get("readback_audio")
        if not audio:
            continue
        wav = tmpdir / (Path(audio).stem + ".wav")
        ok, detail = _m4a_to_wav(photos / audio, wav)
        _say(f"{audio}: convert -> {detail}")
        if not ok:
            files[audio] = {"error": detail}
            continue
        request_part = json.dumps(
            {"mode": "PUSH_TO_TALK", "model": STT_MODEL, "audioEncoding": "WAV"}
        )
        try:
            n = budget.take(f"voice/{audio}")
        except BlockedError as exc:
            files[audio] = {"error": str(exc)}
            _say(str(exc))
            break
        _say(f"[call {n}/{budget.maximum}] voice/{audio}")
        try:
            resp = httpx.post(
                url,
                headers={"Authorization": f"Bearer {provider.api_key}"},
                files=[
                    ("request", (None, request_part, "application/json")),
                    ("audio", (wav.name, wav.read_bytes(), "audio/wav")),
                ],
                timeout=TIMEOUT_S,
            )
        except Exception as exc:
            files[audio] = {"error": f"{type(exc).__name__}: {exc}", "wav": str(wav)}
            CALL_LOG.append(
                {
                    "label": f"voice/{audio}",
                    "status": None,
                    "usage": {},
                    "cost": None,
                    "error": files[audio]["error"],
                }
            )
            _say(f"{audio}: ERROR {files[audio]['error']}")
            continue
        try:
            data = resp.json()
        except Exception:
            data = None
        if resp.status_code != 200 or not data:
            err = f"HTTP {resp.status_code}: {(resp.text or '')[:200]}"
            files[audio] = {"error": err, "wav": str(wav)}
            CALL_LOG.append(
                {
                    "label": f"voice/{audio}",
                    "status": resp.status_code,
                    "usage": {},
                    "cost": None,
                    "error": err,
                }
            )
            _say(f"{audio}: ERROR {err}")
            continue
        CALL_LOG.append(
            {
                "label": f"voice/{audio}",
                "status": 200,
                "usage": _usage_of(data),
                "cost": _cost_of(data),
                "error": "",
            }
        )
        turns = data.get("turns") if isinstance(data, dict) else None
        parts = []
        if isinstance(turns, list):
            for turn in turns:
                if isinstance(turn, dict) and turn.get("transcript"):
                    parts.append(str(turn["transcript"]))
        transcript = " / ".join(parts)
        if not transcript and isinstance(data, dict):
            for key in ("transcript", "text"):
                if isinstance(data.get(key), str) and data[key].strip():
                    transcript = data[key].strip()
                    break
        expected = frame.get("readback_expected", "")
        label, label_ok, state, state_ok = _label_state_captured(transcript, expected)
        files[audio] = {
            "transcript": transcript,
            "expected": expected,
            "label": label,
            "label_ok": label_ok,
            "state": state,
            "state_ok": state_ok,
            "wav": str(wav),
            "raw_keys": sorted(data.keys()),
        }
        _say(f"{audio}: transcript={transcript!r}")
        _say(f"{audio}: expected={expected!r}")
        _say(f"{audio}: label {label} captured={label_ok}, state {state} captured={state_ok}")
    return {"ran": True, "url": url, "citation": citation, "files": files}


# ---------------------------------------------------------------- Report


def gate_and_report(mop, ts, step1_res, vision, sam, voice, budget, tmpdir):
    """Gate verdict + full report. Returns exit code (0 PASS / 1 FAIL)."""
    _say("=== GATE + REPORT ===")
    primary = vision["primary"]
    frames_ok, frames_bad, mismatch_label_bad = 0, [], []
    for frame in ts["frames"]:
        name = frame["file"]
        res = primary[name]
        ok = res["verdict"] == frame["expected_verdict"] and res["verdict"] != "NO_ANSWER"
        if (
            res["verdict"] == "MISMATCH"
            and frame.get("mismatch_labels") is not None
            and set(res["differing"]) != set(frame["mismatch_labels"])
        ):
            ok = False
            mismatch_label_bad.append(
                f"{name}: differing={res['differing']} want={frame['mismatch_labels']}"
            )
        if ok:
            frames_ok += 1
        else:
            frames_bad.append(
                f"{name}: computed={res['verdict']} expected={frame['expected_verdict']}"
            )
    gate_pass = not frames_bad and not mismatch_label_bad
    _say(f"frames verdict-match: {frames_ok}/{len(ts['frames'])}")
    for line in frames_bad + mismatch_label_bad:
        _say(f"  GATE GAP: {line}")
    _say(f"GATE: {'PASS' if gate_pass else 'FAIL'}")

    correct, total = 0, 0
    for _name, res in primary.items():
        for cell in res["per_label"].values():
            if cell["correct"] is None:
                continue
            total += 1
            correct += 1 if cell["correct"] else 0
    acc = (100.0 * correct / total) if total else 0.0
    _say(
        f"per-label accuracy ({MODEL_13} primary): {correct}/{total} = {acc:.1f}% "
        "(08_uncertain excluded: no per-label truth)"
    )
    _say(
        f"07 consistency (3x {MODEL_13}): "
        f"{'CONSISTENT' if vision['consistent_07'] else 'INCONSISTENT'}"
    )

    r08 = primary["08_uncertain.jpg"]
    scored08 = [p["label"] for p in mop["panel"]]
    pass08 = bool((r08["raw"] or "").strip()) and any(
        r08["mapped"].get(label) == "UNKNOWN" for label in scored08
    )
    _say(
        f"08_uncertain check: {'PASS' if pass08 else 'FAIL'} "
        "(PASS only if non-empty and a scored label is reported UNKNOWN)"
    )
    if pass08:
        _say("08_uncertain result is GENUINE (non-empty answer, real UNKNOWN reported)")
    else:
        why08 = (
            r08.get("call_error")
            or r08["parse_error"]
            or (
                "empty answer"
                if not (r08["raw"] or "").strip()
                else "no scored label reported UNKNOWN"
            )
        )
        _say(f"08_uncertain result is VACUOUS ({why08})")

    empty_runs = []
    for name, res in primary.items():
        if not (res["raw"] or "").strip():
            empty_runs.append((f"vision/1.3/{name}", res))
    for name, res in vision.get("extra_11", {}).items():
        if not (res["raw"] or "").strip():
            empty_runs.append((f"vision/1.1/{name}", res))
    for run, res in vision.get("consistency", {}).items():
        if run == "run1_primary":
            continue
        if not (res["raw"] or "").strip():
            empty_runs.append((f"vision/1.3/07_mismatch_after_step2.jpg {run}", res))
    if empty_runs:
        _say(f"EMPTY answers at max_tokens=4000: {len(empty_runs)}")
        for label, res in empty_runs:
            u = res.get("usage") or {}
            _say(
                f"  {label}: finish_reason={res.get('finish_reason')} "
                f"reasoning_tokens={res.get('reasoning_tokens')} usage={u or 'not returned'}"
            )
        _say("The cap is no longer the explanation for these empty answers.")
    else:
        _say("No empty answers at max_tokens=4000.")

    if voice is not None:
        r07 = primary["07_mismatch_after_step2.jpg"]
        photo_ok = r07["verdict"] == "MISMATCH" and set(r07["differing"]) == {"Q8"}
        v07 = (voice.get("files") or {}).get("readback_step2.m4a", {})
        voice_ok = bool(v07.get("label_ok")) and bool(v07.get("state_ok"))
        _say("voice-vs-photo 07: transcript claims Q8 closed, photo ground truth is Q8 open")
        _say(
            f"  voice side captured (label+state): "
            f"{voice_ok if voice.get('ran') else 'n/a (voice did not run)'}"
        )
        _say(f"  photo side captured (MISMATCH on Q8): {photo_ok}")
        _say(f"  both sides correct: {bool(voice.get('ran')) and voice_ok and photo_ok}")

    if step1_res is not None:
        _say(f"control/with-image: {'PASS' if step1_res['with_image_pass'] else 'FAIL'}")
    if sam is not None:
        if sam.get("ran") and not sam.get("error"):
            _say(f"SAM: {sam['detections']} detections for 'circuit breaker'")
        elif sam.get("ran"):
            _say(f"SAM: ran but errored: {sam.get('error')}")
        else:
            _say(f"SAM: {sam.get('reason')}")

    _say(f"Meta calls used: {budget.used}/{budget.maximum}")
    timeouts = [e["label"] for e in CALL_LOG if e.get("timeout")]
    _say(f"timeouts: {timeouts or 'none'} (each counts toward the budget)")
    tot_p = tot_c = tot_t = tot_r = 0
    total_est = 0.0
    for entry in CALL_LOG:
        u = entry.get("usage") or {}
        tot_p += u.get("prompt_tokens") or 0
        tot_c += u.get("completion_tokens") or 0
        tot_t += u.get("total_tokens") or 0
        r_tok = entry.get("reasoning_tokens")
        tot_r += r_tok or 0
        if u.get("prompt_tokens") is not None and u.get("completion_tokens") is not None:
            est = u["prompt_tokens"] / 1e6 * 1.25 + u["completion_tokens"] / 1e6 * 4.25
            total_est += est
            est_s = f"${est:.4f} EST"
        else:
            est_s = "n/a (no usage)"
        _say(
            f"  {entry['label']}: status={entry['status']} "
            f"latency_s={entry.get('latency_s')} "
            f"finish_reason={entry.get('finish_reason')} "
            f"prompt={u.get('prompt_tokens')} completion={u.get('completion_tokens')} "
            f"reasoning={r_tok} cost_est={est_s}"
            + (" TIMEOUT" if entry.get("timeout") else "")
            + (f" error={entry['error']}" if entry.get("error") else "")
        )
    _say(
        f"token totals: prompt={tot_p} completion={tot_c} total={tot_t} "
        f"reasoning={tot_r} (sums only calls that returned usage)"
    )
    _say(
        f"COST ESTIMATE total: ${total_est:.4f} USD at list $1.25/M in + "
        "$4.25/M out (estimate, not a billed amount)"
    )

    created = sorted(p.name for p in tmpdir.iterdir())
    _say(f"temp dir: {tmpdir}")
    _say(f"temp files created ({len(created)}): {created}")
    _say("repo file changed: scripts/probe_mop_vision.py (this script)")
    return 0 if gate_pass else 1


# ---------------------------------------------------------------- Preflight


def preflight(tmp_override):
    """Local-only validation: 0 network calls. Raises BlockedError on failure."""
    _say("=== PREFLIGHT (0 network calls) ===")
    mop, ts = step0()
    tmpdir = _make_tmpdir("probe_mop_vision_preflight_", tmp_override)
    _say(f"temp dir: {tmpdir}")
    resized = step2(ts, tmpdir)
    assert len(resized) == len(ts["frames"]), "resize count mismatch"

    ok, detail = _validate_red_png(_red_png())
    assert ok, f"red png self-test: {detail}"
    _say(f"red-PNG self-test: OK ({detail})")
    bad, _ = _validate_red_png(b"not a png")
    assert not bad, "red png validator accepts garbage"
    _say("red-PNG validator rejects garbage: OK")

    frame01 = next(f for f in ts["frames"] if f["file"] == "01_initial.jpg")
    good = json.dumps(
        {
            "breakers": {
                "Q5": "ON",
                "Q7": "ON",
                "Q9": "ON",
                "Q8": "OFF",
                "BYP": "OFF",
                "Q1": "ON",
                "Q2": "ON",
            },
            "notes": "",
        }
    )
    res = _score_frame(frame01, mop, good)
    assert res["verdict"] == "MATCH", f"self-test MATCH: {res}"
    assert res["distractors"] == {"Q1": "CLOSED", "Q2": "CLOSED"}, res["distractors"]
    assert res["hallucinations"] == [], res["hallucinations"]
    assert all(c["correct"] for c in res["per_label"].values())
    _say("scoring self-test MATCH + distractors: OK")

    frame07 = next(f for f in ts["frames"] if f["file"] == "07_mismatch_after_step2.jpg")
    truth07 = json.dumps(
        {"breakers": {"Q5": "ON", "Q7": "ON", "Q9": "ON", "Q8": "OFF", "BYP": "ON"}, "notes": ""}
    )
    res = _score_frame(frame07, mop, truth07)
    assert res["verdict"] == "MISMATCH", res
    assert res["differing"] == ["Q8"], res
    _say("scoring self-test MISMATCH-on-Q8: OK")

    unk = json.dumps(
        {
            "breakers": {"Q5": "ON", "Q7": "ON", "Q9": "ON", "Q8": "UNKNOWN", "BYP": "OFF"},
            "notes": "blur",
        }
    )
    res = _score_frame(frame01, mop, unk)
    assert res["verdict"] == "UNCERTAIN", res
    _say("scoring self-test UNCERTAIN: OK")

    hal = json.dumps(
        {
            "breakers": {
                "Q5": "ON",
                "Q7": "ON",
                "Q9": "ON",
                "Q8": "OFF",
                "BYP": "OFF",
                "Q10": "ON",
            },
            "notes": "",
        }
    )
    res = _score_frame(frame01, mop, hal)
    assert res["hallucinations"] == ["Q10"], res["hallucinations"]
    _say("scoring self-test hallucination: OK")

    res = _score_frame(frame01, mop, "not json at all")
    assert res["verdict"] == "NO_ANSWER", res
    assert res["parse_error"], res
    _say("scoring self-test unparseable -> NO_ANSWER: OK")
    res = _score_frame(frame01, mop, "")
    assert res["verdict"] == "NO_ANSWER", res
    res = _score_frame(frame01, mop, good, call_error="ReadTimeout: timed out")
    assert res["verdict"] == "NO_ANSWER", res
    _say("scoring self-test empty/call-error -> NO_ANSWER: OK")
    sparse = json.dumps({"breakers": {"Q5": "ON"}, "notes": ""})
    res = _score_frame(frame01, mop, sparse)
    assert res["verdict"] == "UNCERTAIN", res
    assert not res["parse_error"], res
    _say("scoring self-test parsed-but-missing -> UNCERTAIN: OK")
    frame08 = next(f for f in ts["frames"] if f["file"] == "08_uncertain.jpg")
    res = _score_frame(frame08, mop, "")
    assert res["verdict"] == "NO_ANSWER", res
    _say("scoring self-test NO_ANSWER never equals UNCERTAIN: OK")
    unk08 = json.dumps(
        {
            "breakers": {"Q5": "ON", "Q7": "ON", "Q9": "ON", "Q8": "UNKNOWN", "BYP": "UNKNOWN"},
            "notes": "hand covers right column",
        }
    )
    res = _score_frame(frame08, mop, unk08)
    assert res["verdict"] == "UNCERTAIN", res
    _say("scoring self-test 08 genuine UNKNOWN -> UNCERTAIN: OK")

    label, lok, state, sok = _label_state_captured(
        "Step two. Q eight closed.", "Step two. Q eight closed."
    )
    assert (label, lok, state, sok) == ("Q8", True, "CLOSED", True)
    label, lok, state, sok = _label_state_captured(
        "Step one, bypass closed", "Step one. B Y P closed."
    )
    assert (label, lok, state, sok) == ("BYP", True, "CLOSED", True)
    _say("voice-capture self-test: OK")

    provider = MetaProvider()
    _say(f"Meta base_url (client default): {provider.api_url}")
    _say(
        "docs checks omitted: this run repeats neither SAM nor voice, "
        "and preflight makes zero network calls"
    )

    photos = ROOT / "scripts" / "probe_photos"
    wav = tmpdir / "preflight_check.wav"
    ok, detail = _m4a_to_wav(photos / "readback_initial.m4a", wav)
    _say(f"ffmpeg m4a->wav: {'OK' if ok else 'FAIL'} ({detail})")

    _say("PREFLIGHT OK: 0 network calls made")
    return 0


# ---------------------------------------------------------------- Main


def main(argv):
    try:
        tmp_override = _tmpdir_override(argv)
        only = _only_stages(argv)
        spent = _spent(argv)
    except BlockedError as exc:
        _say(f"BLOCKED: {exc}")
        return 2
    if "--preflight" in argv:
        try:
            return preflight(tmp_override)
        except BlockedError as exc:
            _say(f"BLOCKED: {exc}")
            return 2
    try:
        mop, ts = step0()
    except BlockedError as exc:
        _say(f"BLOCKED: {exc}")
        return 2
    provider = MetaProvider()
    _say(f"Meta base_url: {provider.api_url} (same as MetaProvider)")
    _say(
        f"META_MODEL env (display only; probe pins model names): {os.environ.get('META_MODEL', '')}"
    )
    budget = Budget(MAX_CALLS, already_spent=spent)
    if spent:
        _say(
            f"resuming: {spent} Meta call(s) already spent in an earlier "
            "invocation; no already-made call is repeated"
        )
    try:
        tmpdir = _make_tmpdir("probe_mop_vision_", tmp_override)
    except BlockedError as exc:
        _say(f"BLOCKED: {exc}")
        return 2
    _say(f"temp dir: {tmpdir}")
    selected = only or list(STAGES)
    results = {"argv": argv, "spent_before": spent}
    try:
        resized = None
        if "control" in selected:
            results["step1"] = step1(budget, tmpdir)
        if {"vision", "consistency"} & set(selected):
            resized = step2(ts, tmpdir)
        if "vision" in selected:
            results["vision_primary"] = step3(mop, ts, resized, budget)
        if "consistency" in selected:
            primary07 = (
                results.get("vision_primary", {})
                .get("primary", {})
                .get("07_mismatch_after_step2.jpg")
            )
            results["consistency"] = step3_consistency(mop, ts, resized, budget, primary07)
        if "sam" in selected:
            results["sam"] = step4(budget)
        if "voice" in selected:
            results["voice"] = step5(ts, tmpdir, budget)
    except BlockedError as exc:
        _say(f"BLOCKED: {exc}")
        _say(f"Meta calls used before stop: {budget.used}/{budget.maximum}")
        return 2
    (tmpdir / "probe_results.json").write_text(
        json.dumps(results, indent=2, default=str)[:200000], encoding="utf-8"
    )
    if "vision_primary" in results and "consistency" in results:
        vision_full = {
            "primary": results["vision_primary"]["primary"],
            "extra_11": results["vision_primary"]["extra_11"],
            "consistency": results["consistency"]["runs"],
            "consistent_07": results["consistency"]["consistent_07"],
        }
        return gate_and_report(
            mop,
            ts,
            results.get("step1"),
            vision_full,
            results.get("sam"),
            results.get("voice"),
            budget,
            tmpdir,
        )
    _say(f"PARTIAL run ({','.join(selected)}): no vision data, no gate here")
    _say(f"Meta calls used: {budget.used}/{budget.maximum} (incl. {spent} prior)")
    for entry in CALL_LOG:
        _say(
            f"  {entry['label']}: status={entry['status']} "
            f"usage={entry.get('usage') or 'not returned'} "
            f"cost={entry.get('cost') or 'not returned'}"
            + (f" error={entry['error']}" if entry.get("error") else "")
        )
    _say(f"temp dir: {tmpdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
