"""MOP crop-pipeline vision probe: SAM 3.1 locates, code crops, Spark judges.

Second vision re-probe. Full-frame vision failed (gate 2/10, 64% per-label,
strong ON bias, Q8 inconsistent on 07). This probe tests the intended
pipeline: SAM 3.1 locates breakers, code crops them, muse-spark-1.3 judges
one crop at a time (handle at LEFT or RIGHT end of its window).

Scope limits (hard):
  - Read-only wrt backend/, frontend/, data/, tests/. No commit / push.
  - No new requirements, no installs. Runs under the repo .venv as
    .\\.venv\\Scripts\\python.exe scripts\\probe_mop_vision_crops.py
  - Credentials: META_API_KEY from the environment only; NEVER printed.
    Every printed line passes through _scrub().
  - Same base URL + Bearer auth as backend.llm_providers.MetaProvider.
  - The ONLY allowed network destination is api.meta.ai. No docs fetches
    anywhere in this script (SAM request shape reuses the first probe's
    documented shape; the URL host is asserted before every SAM call).
  - Budget: at most 70 Meta API calls total (plan: 10 SAM + up to 50 crop
    calls + 2 consistency = 62 base; one retry allowed ONLY on timeout and
    it counts toward the budget; the Budget guard stops past 70), 120 s timeout.
  - pathlib for all paths; temp files in the system temp folder only.
  - timestamps.json (CONFIRMED) + MOP v1.3 are the ONLY ground truth.
  - Verdicts exactly as the last re-probe, including NO_ANSWER (empty,
    timeout, or parse_error; never equals any expected_verdict).
  - Box assignment per column: 4 boxes -> direct top-to-bottom assign;
    1 box -> aspect-checked fixed-fraction split (quad 0.00-0.40, singles
    0.41-0.60 / 0.61-0.80 / 0.81-1.00); anything else -> column UNKNOWN.
  - Debug image per frame (SAM boxes + labeled crop rects) in temp.

Usage (from the repo root):
    .\\.venv\\Scripts\\python.exe scripts\\probe_mop_vision_crops.py
    .\\.venv\\Scripts\\python.exe scripts\\probe_mop_vision_crops.py --preflight
    ... --tmpdir <path>   # override the temp base (must exist, be writable,
                          # and lie outside the repo; default is system temp)

Exit codes: 0 = gate PASS, 1 = gate FAIL (probe completed),
            2 = blocked (precondition / budget failure).
"""

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402  (repo dependency; never installed by this script)

from backend.llm_providers import MetaProvider  # noqa: E402  (read-only import)

TIMEOUT_S = 120.0
MAX_TOKENS = 4000
MAX_CALLS = 70

SPARK_MODEL = "muse-spark-1.3"
SAM_MODEL = "sam-3.1"

CROP_PROMPT = (
    "This is a close-up photo of one circuit breaker. In the middle there is "
    "a rectangular window with a handle inside it, and the handle has a number "
    "printed on it. Is the handle at the LEFT end or the RIGHT end of the "
    "window, as seen in this photo? If the handle or the window is not clearly "
    "visible, or something covers it, answer UNKNOWN. Return only JSON: "
    '{"handle": "LEFT|RIGHT|UNKNOWN", "notes": "short reason"}.'
)

LEFT_ORDER = ["QUAD_L", "Q5", "Q7", "Q9"]
RIGHT_ORDER = ["QUAD_R", "Q6", "Q8", "BYP"]
SCORED = ("Q5", "Q7", "Q9", "Q8", "BYP")
LEFT_COL = ("Q5", "Q7", "Q9")
CROP_PAD = 0.05

PRICE_IN = 1.25  # USD per M tokens, Spark in
PRICE_OUT = 4.25  # USD per M tokens, Spark out

BOX_RE = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")


class BlockedError(Exception):
    """Precondition / budget / environment failure: exit 2."""


class Budget:
    """Counts Meta API calls; refuses the call that would exceed the cap."""

    def __init__(self, maximum):
        self.used = 0
        self.maximum = maximum

    def take(self, label):
        if self.used >= self.maximum:
            raise BlockedError(
                "STOP: Meta call budget would be exceeded "
                f"({self.used}/{self.maximum}) at {label}; no request sent."
            )
        self.used += 1
        return self.used


CALL_LOG = []  # per call: kind/label/status/usage/error/latency_s/finish_reason/reasoning_tokens/timeout


def _scrub(text):
    """Redact the key value from anything about to be printed."""
    key = os.environ.get("META_API_KEY", "")
    if key and len(key) >= 4:
        text = text.replace(key, "[REDACTED]")
    return text


def _say(text):
    print(_scrub(str(text)), flush=True)


def _usage_of(data):
    if isinstance(data, dict) and isinstance(data.get("usage"), dict):
        return data["usage"]
    return {}


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


def _post(url, headers, payload, budget, label, kind):
    """One logical Meta call: one attempt plus ONE retry on timeout only.

    Every attempt takes budget (retries count). Returns (status, data, error,
    attempts) where attempts holds this call's CALL_LOG entries in order.
    """
    if urlparse(url).hostname != urlparse(MetaProvider().api_url).hostname:
        raise BlockedError(f"refusing non-api.meta.ai destination: {url}")
    entries = []
    for attempt in (1, 2):
        tag = label if attempt == 1 else f"{label} (retry)"
        n = budget.take(tag)
        _say(f"[call {n}/{budget.maximum}] {tag}")
        t0 = time.perf_counter()
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=TIMEOUT_S)
        except Exception as exc:
            dt = time.perf_counter() - t0
            timed_out = (
                isinstance(exc, httpx.TimeoutException) or "timeout" in type(exc).__name__.lower()
            )
            err = f"{type(exc).__name__}: {exc}"
            entry = {
                "kind": kind,
                "label": tag,
                "status": None,
                "usage": {},
                "error": err,
                "latency_s": round(dt, 1),
                "finish_reason": None,
                "reasoning_tokens": None,
                "timeout": timed_out,
            }
            CALL_LOG.append(entry)
            entries.append(entry)
            if timed_out:
                _say(f"TIMEOUT after {dt:.1f}s: {tag} (counts toward the budget)")
                if attempt == 1:
                    _say(f"RETRY once: {label}")
                    continue
            return None, None, err, entries
        dt = time.perf_counter() - t0
        try:
            data = resp.json()
        except Exception:
            data = None
        if resp.status_code != 200 or not data:
            err = (
                f"HTTP {resp.status_code}: {(resp.text or '')[:200]}"
                if resp.status_code != 200
                else "HTTP 200 with empty/non-JSON body"
            )
            entry = {
                "kind": kind,
                "label": tag,
                "status": resp.status_code,
                "usage": {},
                "error": err,
                "latency_s": round(dt, 1),
                "finish_reason": None,
                "reasoning_tokens": None,
                "timeout": False,
            }
            CALL_LOG.append(entry)
            entries.append(entry)
            return resp.status_code, data, err, entries
        entry = {
            "kind": kind,
            "label": tag,
            "status": 200,
            "usage": _usage_of(data),
            "error": "",
            "latency_s": round(dt, 1),
            "finish_reason": _finish_reason_of(data),
            "reasoning_tokens": _reasoning_of(data),
            "timeout": False,
        }
        CALL_LOG.append(entry)
        entries.append(entry)
        return resp.status_code, data, "", entries
    return None, None, "internal: retry loop fell through", entries


def _api_headers():
    provider = MetaProvider()
    return provider, {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {provider.api_key}",
    }


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


# ---------------------------------------------------------------- Step 0


def step0():
    """Preconditions. Raises BlockedError (exit 2) if any fails. Zero network."""
    _say("=== STEP 0 preconditions ===")
    key_set = bool(os.environ.get("META_API_KEY"))
    _say(f"META_API_KEY set: {key_set}")
    if not key_set:
        raise BlockedError("META_API_KEY is not set; no request attempted.")

    mop = json.loads((ROOT / "data" / "mop_ups_bypass.json").read_text(encoding="utf-8"))
    _say(f"mop_id={mop['mop_id']} version={mop['version']} steps={len(mop['steps'])}")
    if mop["version"] != "1.3" or len(mop["steps"]) != 5:
        raise BlockedError("need MOP version 1.3 with 5 steps")

    photos = ROOT / "scripts" / "probe_photos"
    ts = json.loads((photos / "timestamps.json").read_text(encoding="utf-8"))
    _say(f"timestamps status={ts['status']} frames={len(ts['frames'])}")
    if ts["status"] != "CONFIRMED":
        raise BlockedError(f"timestamps status is {ts['status']!r}, need CONFIRMED")
    missing = [f["file"] for f in ts["frames"] if not (photos / f["file"]).exists()]
    if missing:
        raise BlockedError(f"frames missing: {missing}")

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
    try:
        from PIL import Image  # noqa: F401 - required, never installed
    except Exception as exc:
        raise BlockedError(f"Pillow is required for crops: {type(exc).__name__}") from exc
    _say("STEP 0: all preconditions hold")
    return mop, ts


# ------------------------------------------------------- Geometry + crops


EXPECTED_COL_ASPECT = 0.47
ASPECT_TOL = 0.15
SPLIT_FRACS = (("quad", 0.00, 0.40), ("s1", 0.41, 0.60), ("s2", 0.61, 0.80), ("s3", 0.81, 1.00))


def _split_columns(boxes):
    """Split boxes into (left, right) by the largest center-x gap.

    Returns (None, None) when fewer than 2 boxes make a split impossible.
    """
    if len(boxes) < 2:
        return None, None
    by_x = sorted((((b[0] + b[2]) / 2.0), b) for b in boxes)
    gaps = [by_x[i + 1][0] - by_x[i][0] for i in range(len(by_x) - 1)]
    cut = gaps.index(max(gaps)) + 1
    return [b for _, b in by_x[:cut]], [b for _, b in by_x[cut:]]


def _column_aspect(box):
    return (box[2] - box[0]) / max(1, box[3] - box[1])


def _split_column_box(box):
    """Split one whole-column box into quad + 3 single bands (fractions of height)."""
    x1, y1, x2, y2 = (int(v) for v in box[:4])
    h = max(1, y2 - y1)
    return {
        name: (x1, y1 + int(round(f0 * h)), x2, y1 + int(round(f1 * h)))
        for name, f0, f1 in SPLIT_FRACS
    }


def _assign_column(boxes):
    """Assign one column. Returns (roles, method, detail).

    roles maps quad/s1/s2/s3 -> box ({} when the column goes UNKNOWN).
    method is '4 boxes', 'split', or 'UNKNOWN'.
    """
    if len(boxes) == 4:
        ordered = sorted(boxes, key=lambda b: (b[1] + b[3]) / 2.0)
        roles = dict(zip(("quad", "s1", "s2", "s3"), ordered, strict=False))
        aspects = ",".join(f"{_column_aspect(b):.3f}" for b in ordered)
        return roles, "4 boxes", f"box aspects {aspects}"
    if len(boxes) == 1:
        aspect = _column_aspect(boxes[0])
        if abs(aspect - EXPECTED_COL_ASPECT) / EXPECTED_COL_ASPECT > ASPECT_TOL:
            return (
                {},
                "UNKNOWN",
                (f"aspect {aspect:.3f} differs >15% from {EXPECTED_COL_ASPECT}: no split"),
            )
        return _split_column_box(boxes[0]), "split", f"aspect {aspect:.3f}"
    return {}, "UNKNOWN", f"box count {len(boxes)}: no assignment guessed"


def _crop_with_pad(img, box, pad=CROP_PAD):
    """Crop box with fractional padding, clamped to the image. Native size."""
    w, h = img.size
    x1, y1, x2, y2 = (int(v) for v in box[:4])
    bw, bh = max(1, x2 - x1), max(1, y2 - y1)
    nx1 = max(0, int(x1 - pad * bw))
    ny1 = max(0, int(y1 - pad * bh))
    nx2 = min(w, int(x2 + pad * bw))
    ny2 = min(h, int(y2 + pad * bh))
    return img.crop((nx1, ny1, nx2, ny2)), (nx1, ny1, nx2, ny2)


# ------------------------------------------------------- SAM + Spark calls


def _send_sam(image_path, budget, label):
    """Original frame + concept 'circuit breaker' to sam-3.1 (Responses API)."""
    provider, headers = _api_headers()
    url = f"{provider.api_url}/responses"
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
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
    return _post(url, headers, payload, budget, label, "sam")  # (status, data, error, attempts)


def _parse_boxes(data):
    """All <|box;...|> detections in a SAM response. Box = (x1,y1,x2,y2,w,h)."""
    return [tuple(int(v) for v in m) for m in BOX_RE.findall(json.dumps(data))]


def _send_crop(crop_path, budget, label):
    """One crop to muse-spark-1.3 with the exact crop prompt, nothing else."""
    provider, headers = _api_headers()
    url = f"{provider.api_url}/chat/completions"
    b64 = base64.b64encode(crop_path.read_bytes()).decode("ascii")
    payload = {
        "model": SPARK_MODEL,
        "max_tokens": MAX_TOKENS,
        "reasoning_effort": "low",
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": CROP_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
    }
    status, data, error, attempts = _post(url, headers, payload, budget, label, "spark")
    base = {
        "latency_s": round(sum((e.get("latency_s") or 0) for e in attempts), 1),
        "finish_reason": _finish_reason_of(data),
        "reasoning_tokens": _reasoning_of(data),
        "timeout": any(e.get("timeout") for e in attempts),
        "retries": max(0, len(attempts) - 1),
    }
    if error or data is None:
        return {"text": "", "error": error, "usage": {}, **base}
    try:
        text = data["choices"][0].get("message", {}).get("content") or ""
    except (KeyError, IndexError, TypeError, AttributeError):
        text = ""
    if not isinstance(text, str):
        text = ""
    return {"text": text, "error": "", "usage": _usage_of(data), **base}


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


def _parse_crop_answer(text):
    """Returns (handle, parse_error). handle in LEFT/RIGHT/UNKNOWN or None."""
    obj, err = _extract_json(text)
    if obj is None:
        return None, err
    if not isinstance(obj, dict):
        return None, "top-level JSON is not an object"
    raw = obj.get("handle")
    if not isinstance(raw, str):
        return None, "handle key missing or not a string"
    value = raw.strip().upper()
    if value not in ("LEFT", "RIGHT", "UNKNOWN"):
        return None, f"handle value {raw!r} not in enum"
    return value, ""


def _map_handle(label, handle):
    """LEFT/RIGHT (as seen) -> OPEN/CLOSED by column physics."""
    if handle == "UNKNOWN":
        return "UNKNOWN"
    if label in LEFT_COL:
        return "CLOSED" if handle == "RIGHT" else "OPEN"
    return "CLOSED" if handle == "LEFT" else "OPEN"


# ------------------------------------------------------- Frame pipeline


def _expected_state(frame, mop):
    cas = frame["checked_against_step"]
    if cas == "initial_state":
        return mop["initial_state"]
    return next(s for s in mop["steps"] if s["step_id"] == cas)["expected_state"]


def _frame_verdict(frame, mop, labels):
    """Same rules as the last re-probe. labels: scored -> result dict."""
    if any(r["no_answer"] for r in labels.values()):
        return "NO_ANSWER", []
    if any(r["mapped"] in ("UNKNOWN", "MISSING") for r in labels.values()):
        return "UNCERTAIN", []
    expected = _expected_state(frame, mop)
    differing = sorted(label for label in SCORED if labels[label]["mapped"] != expected[label])
    return ("MISMATCH" if differing else "MATCH"), differing


def _label_font(size=64):
    from PIL import ImageFont

    for path in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\calibri.ttf"):
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _save_debug_image(src, sam_boxes, crop_rects, dst):
    """Debug overlay: SAM boxes red, sent crop rects green + labeled."""
    from PIL import Image, ImageDraw

    img = Image.open(src).convert("RGB")
    draw = ImageDraw.Draw(img)
    for x1, y1, x2, y2 in sam_boxes:
        draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=5)
    font = _label_font()
    for label, (x1, y1, x2, y2) in crop_rects:
        draw.rectangle([x1, y1, x2, y2], outline=(0, 255, 0), width=5)
        anchor = (x1 + 10, max(0, y1 - 84))
        bbox = draw.textbbox(anchor, label, font=font)
        pad = 8
        draw.rectangle([bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad], fill=(0, 0, 0))
        draw.text(anchor, label, font=font, fill=(0, 255, 0))
    img.save(dst, "JPEG", quality=90)


def _judge_crop(label, crop_path, crop_dims, box, budget, call_label):
    ans = _send_crop(crop_path, budget, call_label)
    text = ans["text"]
    if ans["error"] or not text.strip():
        handle, parse_error = None, (ans["error"] or "empty answer text")
        no_answer = True
    else:
        handle, parse_error = _parse_crop_answer(text)
        no_answer = handle is None
    mapped = _map_handle(label, handle) if not no_answer else "NO_ANSWER"
    return {
        "raw": text,
        "handle": handle,
        "parse_error": parse_error,
        "call_error": ans["error"],
        "mapped": mapped,
        "no_answer": no_answer,
        "latency_s": ans["latency_s"],
        "finish_reason": ans["finish_reason"],
        "usage": ans["usage"],
        "reasoning_tokens": ans["reasoning_tokens"],
        "timeout": ans["timeout"],
        "retries": ans["retries"],
        "crop": crop_path.name,
        "crop_dims": crop_dims,
        "box": box[:4],
    }


def _process_frame(frame, mop, photos, tmpdir, budget):
    """SAM -> assign -> crop -> judge. Returns the frame record."""
    from PIL import Image

    name = frame["file"]
    stem = Path(name).stem
    _say(f"--- {name} ---")
    src = photos / name
    status, data, error, sam_attempts = _send_sam(src, budget, f"sam/{name}")
    sam_total = round(sum((e.get("latency_s") or 0) for e in sam_attempts), 1)
    rec = {
        "file": name,
        "sam_error": error,
        "sam_latency_s": sam_total,
        "sam_retries": max(0, len(sam_attempts) - 1),
        "sam_usage": _usage_of(data),
        "boxes": [],
        "assignment": {},
        "methods": {},
        "method_details": {},
        "labels": {},
        "frame_latency_s": sam_total,
        "frame_parallel_s": sam_total,
        "debug": "",
    }
    if error or data is None:
        _say(f"SAM ERROR: {error} -> frame NO_ANSWER (no boxes to crop)")
        for label in SCORED:
            rec["labels"][label] = {
                "raw": "",
                "handle": None,
                "parse_error": "",
                "call_error": error,
                "mapped": "NO_ANSWER",
                "no_answer": True,
                "crop": "",
                "crop_dims": None,
                "box": None,
                "latency_s": None,
                "finish_reason": None,
                "usage": {},
                "reasoning_tokens": None,
                "timeout": False,
                "retries": 0,
            }
        rec["methods"] = {"left": "UNKNOWN", "right": "UNKNOWN"}
        rec["method_details"] = {"left": "SAM call failed", "right": "SAM call failed"}
        rec["verdict"], rec["differing"] = "NO_ANSWER", []
        debug_path = tmpdir / f"debug_{stem}.jpg"
        _save_debug_image(src, [], [], debug_path)
        rec["debug"] = str(debug_path)
        return rec
    boxes = _parse_boxes(data)
    rec["boxes"] = boxes
    _say(f"SAM boxes: {len(boxes)}")
    for i, (x1, y1, x2, y2, w, h) in enumerate(boxes):
        _say(f"  box{i}: x1={x1} y1={y1} x2={x2} y2={y2} (source {w}x{h})")
    left_boxes, right_boxes = _split_columns([b[:4] for b in boxes])
    methods, details, assignment = {}, {}, {}
    if left_boxes is None:
        methods = {"left": "UNKNOWN", "right": "UNKNOWN"}
        details = {
            "left": f"only {len(boxes)} box(es): cannot form columns",
            "right": f"only {len(boxes)} box(es): cannot form columns",
        }
    else:
        roles_l, methods["left"], details["left"] = _assign_column(left_boxes)
        roles_r, methods["right"], details["right"] = _assign_column(right_boxes)
        for label, role in (("QUAD_L", "quad"), ("Q5", "s1"), ("Q7", "s2"), ("Q9", "s3")):
            if role in roles_l:
                assignment[label] = roles_l[role]
        for label, role in (("QUAD_R", "quad"), ("Q6", "s1"), ("Q8", "s2"), ("BYP", "s3")):
            if role in roles_r:
                assignment[label] = roles_r[role]
    rec["methods"] = methods
    rec["method_details"] = details
    rec["assignment"] = assignment
    _say(f"left column: method={methods['left']} ({details['left']})")
    _say(f"right column: method={methods['right']} ({details['right']})")
    _say(
        "assignment: "
        + (
            ", ".join(
                f"{label}=box({b[0]},{b[1]},{b[2]},{b[3]})" for label, b in assignment.items()
            )
            or "none"
        )
    )
    for label in SCORED:
        if label not in assignment:
            side = "left" if label in LEFT_COL else "right"
            rec["labels"][label] = {
                "raw": "",
                "handle": None,
                "parse_error": "",
                "call_error": "",
                "mapped": "UNKNOWN",
                "no_answer": False,
                "geometric": True,
                "crop": "",
                "crop_dims": None,
                "box": None,
                "latency_s": None,
                "finish_reason": None,
                "usage": {},
                "reasoning_tokens": None,
                "timeout": False,
                "retries": 0,
            }
            _say(f"  {label}: no box ({side} column {methods[side]}) -> UNKNOWN, no crop sent")
    sent = []
    with Image.open(src) as img:
        img = img.convert("RGB")
        for label in SCORED:
            if label not in assignment:
                continue
            box = assignment[label]
            crop, used = _crop_with_pad(img, box)
            dst = tmpdir / f"crop_{stem}_{label}.jpg"
            crop.save(dst, "JPEG", quality=95)
            dims = crop.size
            sent.append((label, used))
            _say(
                f"crop {label}: box({box[0]},{box[1]},{box[2]},{box[3]}) "
                f"padded({used[0]},{used[1]},{used[2]},{used[3]}) -> "
                f"{dims[0]}x{dims[1]} native ({dst.stat().st_size // 1024} KB)"
            )
            res = _judge_crop(label, dst, dims, box, budget, f"spark/{stem}/{label}")
            rec["labels"][label] = res
            u = res["usage"]
            _say(f"  {label}: raw={res['raw']!r}")
            _say(
                f"  {label}: handle={res['handle']} mapped={res['mapped']} "
                f"latency_s={res['latency_s']} finish={res['finish_reason']} "
                f"prompt={u.get('prompt_tokens')} completion={u.get('completion_tokens')} "
                f"reasoning={res['reasoning_tokens']} retries={res['retries']}"
                + (f" parse_error={res['parse_error']}" if res["parse_error"] else "")
                + (f" call_error={res['call_error']}" if res["call_error"] else "")
            )
    debug_path = tmpdir / f"debug_{stem}.jpg"
    _save_debug_image(src, [b[:4] for b in boxes], sent, debug_path)
    rec["debug"] = str(debug_path)
    _say(f"debug image: {debug_path} ({len(sent)} crop rects labeled)")
    judged = [
        rec["labels"][label]["latency_s"] or 0
        for label in SCORED
        if rec["labels"][label].get("crop")
    ]
    rec["frame_latency_s"] = round(rec["sam_latency_s"] + sum(judged), 1)
    rec["frame_parallel_s"] = round(rec["sam_latency_s"] + (max(judged) if judged else 0), 1)
    rec["verdict"], rec["differing"] = _frame_verdict(frame, mop, rec["labels"])
    return rec


def _print_frame_summary(frame, mop, rec):
    truth = frame["ground_truth"]
    for label in SCORED:
        res = rec["labels"][label]
        if isinstance(truth, dict):
            want = truth[label]
            mark = "OK" if res["mapped"] == want else "WRONG"
        else:
            want = "n/a (frame truth is UNCERTAIN)"
            mark = "n/a"
        extra = " [no crop: box rule]" if res.get("geometric") else ""
        _say(f"  {label}: got={res['mapped']} want={want} -> {mark}{extra}")
    _say(
        f"computed verdict={rec['verdict']} differing={rec['differing'] or 'none'} "
        f"expected_verdict={frame['expected_verdict']}"
    )
    _say(f"column methods: left={rec['methods']['left']} right={rec['methods']['right']}")
    _say(f"frame latency sequential (verify_photo cost): {rec['frame_latency_s']:.1f}s")
    _say(f"frame latency parallel (SAM + max crop): {rec['frame_parallel_s']:.1f}s")
    _say(f"debug image: {rec['debug']}")


# ------------------------------------------------------- Report


def gate_and_report(mop, ts, records, q8_runs, budget, tmpdir):
    """Gate verdict + full report. Returns exit code (0 PASS / 1 FAIL)."""
    _say("=== GATE + REPORT ===")
    by_file = {r["file"]: r for r in records}
    frames_ok, frames_bad, mismatch_label_bad = 0, [], []
    for frame in ts["frames"]:
        rec = by_file[frame["file"]]
        ok = rec["verdict"] == frame["expected_verdict"] and rec["verdict"] != "NO_ANSWER"
        if (
            rec["verdict"] == "MISMATCH"
            and frame.get("mismatch_labels") is not None
            and set(rec["differing"]) != set(frame["mismatch_labels"])
        ):
            ok = False
            mismatch_label_bad.append(
                f"{frame['file']}: differing={rec['differing']} want={frame['mismatch_labels']}"
            )
        if ok:
            frames_ok += 1
        else:
            frames_bad.append(
                f"{frame['file']}: computed={rec['verdict']} expected={frame['expected_verdict']}"
            )
    gate_pass = not frames_bad and not mismatch_label_bad
    _say(f"frames verdict-match: {frames_ok}/{len(ts['frames'])}")
    for line in frames_bad + mismatch_label_bad:
        _say(f"  GATE GAP: {line}")
    _say(f"GATE: {'PASS' if gate_pass else 'FAIL'}")

    correct, total = 0, 0
    for frame in ts["frames"]:
        truth = frame["ground_truth"]
        if not isinstance(truth, dict):
            continue
        for label in SCORED:
            total += 1
            correct += 1 if by_file[frame["file"]]["labels"][label]["mapped"] == truth[label] else 0
    acc = (100.0 * correct / total) if total else 0.0
    _say(
        f"per-label accuracy: {correct}/{total} = {acc:.1f}% "
        "(08_uncertain excluded: no per-label truth)"
    )

    if q8_runs:
        snaps = [(r["mapped"], r["handle"]) for r in q8_runs]
        consistent = all(s == snaps[0] for s in snaps)
        _say(
            f"07 Q8 consistency (3x {SPARK_MODEL}): "
            f"{'CONSISTENT' if consistent else 'INCONSISTENT'} {[s[0] for s in snaps]}"
        )
    else:
        _say("07 Q8 consistency: n/a (no Q8 crop: frame 07 failed box assignment)")

    r08 = by_file["08_uncertain.jpg"]
    no_answer_08 = any(r["no_answer"] for r in r08["labels"].values())
    genuine08 = r08["verdict"] == "UNCERTAIN" and not no_answer_08
    geo08 = [
        f"{side} column {r08['methods'][side]} ({r08['method_details'][side]})"
        for side in ("left", "right")
        if r08["methods"][side] == "UNKNOWN"
    ]
    obs08 = [
        label
        for label in SCORED
        if r08["labels"][label].get("crop") and r08["labels"][label]["mapped"] == "UNKNOWN"
    ]
    if genuine08:
        parts = []
        if geo08:
            parts.append("ruled out by geometry: " + "; ".join(geo08))
        if obs08:
            parts.append("hand observed in crop(s): " + ",".join(obs08))
        _say(
            "08_uncertain result is GENUINE (UNCERTAIN via "
            + (" + ".join(parts) if parts else "unknown mechanism")
            + ")"
        )
    else:
        why08 = (
            "NO_ANSWER labels present" if no_answer_08 else f"verdict {r08['verdict']} != UNCERTAIN"
        )
        _say(f"08_uncertain result is VACUOUS ({why08})")

    no_answer_calls = [
        (e["label"], e.get("error") or "empty/unparseable answer")
        for e in CALL_LOG
        if e.get("status") != 200 or e.get("error")
    ]
    _say(f"failed calls (HTTP/timeout): {len(no_answer_calls)}")
    for label, err in no_answer_calls:
        _say(f"  {label}: {err}")

    _say(f"Meta calls used: {budget.used}/{budget.maximum}")
    timeouts = [e["label"] for e in CALL_LOG if e.get("timeout")]
    _say(f"timeouts: {timeouts or 'none'} (each counts toward the budget)")
    retries = [e["label"] for e in CALL_LOG if e["label"].endswith("(retry)")]
    _say(f"retries (timeout-only, counted): {len(retries)}")
    for label in retries:
        entry = next(e for e in CALL_LOG if e["label"] == label)
        _say(f"  retried: {label} -> {'success' if entry['status'] == 200 else entry['error']}")
    tot_p = tot_c = tot_t = tot_r = 0
    total_est = 0.0
    _say("--- SAM calls (listed separately, no list price) ---")
    for entry in CALL_LOG:
        if entry.get("kind") != "sam":
            continue
        u = entry.get("usage") or {}
        _say(
            f"  {entry['label']}: status={entry['status']} "
            f"latency_s={entry.get('latency_s')} usage={u or 'not returned'} "
            "cost_est=n/a (no SAM list price)"
            + (" TIMEOUT" if entry.get("timeout") else "")
            + (f" error={entry['error']}" if entry.get("error") else "")
        )
    _say("--- Spark calls ---")
    for entry in CALL_LOG:
        if entry.get("kind") != "spark":
            continue
        u = entry.get("usage") or {}
        tot_p += u.get("prompt_tokens") or 0
        tot_c += u.get("completion_tokens") or 0
        tot_t += u.get("total_tokens") or 0
        r_tok = entry.get("reasoning_tokens")
        tot_r += r_tok or 0
        if u.get("prompt_tokens") is not None and u.get("completion_tokens") is not None:
            est = u["prompt_tokens"] / 1e6 * PRICE_IN + u["completion_tokens"] / 1e6 * PRICE_OUT
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
        f"Spark token totals: prompt={tot_p} completion={tot_c} total={tot_t} "
        f"reasoning={tot_r} (sums only calls that returned usage)"
    )
    _say(
        f"COST ESTIMATE total (Spark): ${total_est:.4f} USD at list "
        f"${PRICE_IN}/M in + ${PRICE_OUT}/M out (estimate, not a billed amount)"
    )

    _say("--- verify_photo cost per frame (sequential vs parallel crops) ---")
    for rec in records:
        n_crops = sum(1 for label in SCORED if rec["labels"][label].get("crop"))
        _say(
            f"  {rec['file']}: {rec['frame_latency_s']:.1f}s seq / "
            f"{rec['frame_parallel_s']:.1f}s parallel ({n_crops} crops judged)"
        )
    _say("--- debug images ---")
    for rec in records:
        _say(f"  {rec['file']}: {rec['debug']}")

    created = sorted(p.name for p in tmpdir.iterdir())
    _say(f"temp dir: {tmpdir}")
    _say(f"temp files created ({len(created)}): {created}")
    _say("repo file created: scripts/probe_mop_vision_crops.py (this script)")
    return 0 if gate_pass else 1


# ---------------------------------------------------------------- Preflight


def preflight(tmp_override):
    """Local-only validation: 0 network calls. Raises BlockedError on failure."""
    _say("=== PREFLIGHT (0 network calls) ===")
    mop, ts = step0()
    tmpdir = _make_tmpdir("probe_mop_vision_crops_preflight_", tmp_override)
    _say(f"temp dir: {tmpdir}")

    from PIL import Image

    photos = ROOT / "scripts" / "probe_photos"
    for frame in ts["frames"]:
        with Image.open(photos / frame["file"]) as img:
            _say(f"{frame['file']}: {img.size[0]}x{img.size[1]} {img.mode}")
    _say(f"{len(ts['frames'])}/{len(ts['frames'])} originals open at full resolution")

    left = [(270, 800 + i * 330, 1010, 800 + i * 330 + 300) for i in range(4)]
    right = [(1150, 800 + i * 330, 1880, 800 + i * 330 + 300) for i in range(4)]
    col_l, col_r = _split_columns(left + right)
    assert col_l is not None, (col_l, col_r)
    assert len(col_l) == 4, (col_l, col_r)
    assert len(col_r) == 4, (col_l, col_r)
    roles, method, _ = _assign_column(col_l)
    assert method == "4 boxes"
    assert [roles[r] for r in ("quad", "s1", "s2", "s3")] == left
    roles, method, _ = _assign_column(col_r)
    assert method == "4 boxes"
    assert [roles[r] for r in ("quad", "s1", "s2", "s3")] == right
    _say("geometry self-test 8-box split + 4-box assign: OK")
    col_l, col_r = _split_columns([(300, 900, 1050, 2500), (1150, 900, 1900, 2500)])
    assert len(col_l) == 1, (col_l, col_r)
    assert len(col_r) == 1, (col_l, col_r)
    roles, method, detail = _assign_column(col_l)
    assert method == "split", (method, detail)
    assert set(roles) == {"quad", "s1", "s2", "s3"}, (method, detail)
    col_l, col_r = _split_columns([(300, 900, 1050, 2500)])
    assert col_l is None
    assert col_r is None
    roles, method, detail = _assign_column(left[:2])
    assert method == "UNKNOWN", (method, detail)
    assert not roles, (method, detail)
    roles, method, detail = _assign_column(left + right[:1])
    assert method == "UNKNOWN", (method, detail)
    assert not roles, (method, detail)
    _say("geometry self-test 1-box split + degenerate counts: OK")
    bands = _split_column_box((0, 0, 100, 1000))
    assert bands == {
        "quad": (0, 0, 100, 400),
        "s1": (0, 410, 100, 600),
        "s2": (0, 610, 100, 800),
        "s3": (0, 810, 100, 1000),
    }, bands
    _say("geometry self-test split fractions: OK")
    for width, want in (
        (47, "split"),
        (54, "split"),
        (55, "UNKNOWN"),
        (40, "split"),
        (39, "UNKNOWN"),
    ):
        _, method, _ = _assign_column([(0, 0, width, 100)])
        assert method == want, (width, method)
    _say("geometry self-test aspect 15% gate: OK")

    assert _map_handle("Q5", "RIGHT") == "CLOSED"
    assert _map_handle("Q7", "LEFT") == "OPEN"
    assert _map_handle("Q9", "RIGHT") == "CLOSED"
    assert _map_handle("Q8", "LEFT") == "CLOSED"
    assert _map_handle("BYP", "RIGHT") == "OPEN"
    assert _map_handle("Q8", "UNKNOWN") == "UNKNOWN"
    _say("mapping self-test column physics: OK")

    handle, err = _parse_crop_answer('```json\n{"handle": "LEFT", "notes": "x"}\n```')
    assert (handle, err) == ("LEFT", ""), (handle, err)
    handle, err = _parse_crop_answer('Here: {"handle": "right", "notes": ""} done')
    assert (handle, err) == ("RIGHT", ""), (handle, err)
    handle, err = _parse_crop_answer('{"handle": "MAYBE"}')
    assert handle is None, (handle, err)
    assert "enum" in err, (handle, err)
    handle, err = _parse_crop_answer('{"notes": "no handle"}')
    assert handle is None, (handle, err)
    assert "missing" in err, (handle, err)
    handle, err = _parse_crop_answer("no json here")
    assert handle is None, (handle, err)
    assert err, (handle, err)
    _say("parse self-test fences/enum/missing: OK")

    img = Image.new("RGB", (100, 100), (10, 20, 30))
    crop, used = _crop_with_pad(img, (20, 20, 60, 60))
    assert used == (18, 18, 62, 62), (used, crop.size)
    assert crop.size == (44, 44), (used, crop.size)
    crop, used = _crop_with_pad(img, (0, 0, 10, 10))
    assert used == (0, 0, 10, 10), used
    _say("crop self-test 5% padding + clamp: OK")

    dbg_src = tmpdir / "dbg_src.jpg"
    Image.new("RGB", (200, 200), (200, 200, 200)).save(dbg_src)
    dbg_dst = tmpdir / "dbg_test.jpg"
    _save_debug_image(dbg_src, [(10, 10, 90, 90)], [("Q5", (20, 20, 80, 80))], dbg_dst)
    assert dbg_dst.exists()
    assert dbg_dst.stat().st_size > 0
    _say("debug-image self-test: OK")

    real_post = httpx.post

    class _StubResp:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    plan = {"calls": 0}

    def _fake_timeout(*args, **kwargs):
        plan["calls"] += 1
        if plan["calls"] == 1:
            raise httpx.ReadTimeout("timed out")
        return _StubResp()

    httpx.post = _fake_timeout
    try:
        stub_budget = Budget(70)
        status, data, error, attempts = _post(
            "https://api.meta.ai/v1/chat/completions", {}, {}, stub_budget, "stub", "spark"
        )
    finally:
        httpx.post = real_post
        del CALL_LOG[:]
    assert status == 200, (status, error)
    assert error == "", (status, error)
    assert len(attempts) == 2, (status, error)
    assert stub_budget.used == 2
    assert attempts[0]["timeout"]
    assert not attempts[1]["timeout"]
    assert attempts[1]["label"].endswith("(retry)")
    _say("retry self-test timeout-then-success (stubbed, 0 network): OK")

    def _fake_conn(*args, **kwargs):
        raise httpx.ConnectError("boom")

    httpx.post = _fake_conn
    try:
        stub_budget = Budget(70)
        status, data, error, attempts = _post(
            "https://api.meta.ai/v1/chat/completions", {}, {}, stub_budget, "stub2", "spark"
        )
    finally:
        httpx.post = real_post
        del CALL_LOG[:]
    assert status is None, (status, attempts)
    assert len(attempts) == 1, (status, attempts)
    assert stub_budget.used == 1, (status, attempts)
    _say("retry self-test non-timeout error never retried (stubbed): OK")

    base = len(ts["frames"]) + len(ts["frames"]) * len(SCORED) + 2
    assert base <= MAX_CALLS, f"base plan {base} exceeds budget {MAX_CALLS}"
    _say(
        f"budget plan: {base} base calls + {MAX_CALLS - base} timeout-retry "
        f"headroom (guard stops past {MAX_CALLS})"
    )
    _say("PREFLIGHT OK: 0 network calls made")
    return 0


# ---------------------------------------------------------------- Main


def main(argv):
    try:
        tmp_override = _tmpdir_override(argv)
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
    _say("network allowlist: api.meta.ai only (asserted before every call)")
    budget = Budget(MAX_CALLS)
    try:
        tmpdir = _make_tmpdir("probe_mop_vision_crops_", tmp_override)
    except BlockedError as exc:
        _say(f"BLOCKED: {exc}")
        return 2
    _say(f"temp dir: {tmpdir}")
    photos = ROOT / "scripts" / "probe_photos"
    records = []
    try:
        for frame in ts["frames"]:
            rec = _process_frame(frame, mop, photos, tmpdir, budget)
            records.append(rec)
            _print_frame_summary(frame, mop, rec)
        _say("=== 07 Q8 consistency ===")
        rec07 = next(r for r in records if r["file"] == "07_mismatch_after_step2.jpg")
        q8_primary = rec07["labels"]["Q8"]
        q8_runs = []
        if q8_primary.get("crop"):
            q8_runs.append(q8_primary)
            crop_path = tmpdir / q8_primary["crop"]
            for i in (2, 3):
                res = _judge_crop(
                    "Q8",
                    crop_path,
                    q8_primary["crop_dims"],
                    q8_primary["box"],
                    budget,
                    f"spark/07_mismatch_after_step2/Q8 run{i}",
                )
                q8_runs.append(res)
                _say(
                    f"07 Q8 run{i}: raw={res['raw']!r} handle={res['handle']} "
                    f"mapped={res['mapped']} latency_s={res['latency_s']} "
                    f"finish={res['finish_reason']}"
                )
        else:
            _say("07 Q8 consistency: n/a (no Q8 crop: frame 07 failed box assignment)")
    except BlockedError as exc:
        _say(f"BLOCKED: {exc}")
        _say(f"Meta calls used before stop: {budget.used}/{budget.maximum}")
        return 2
    (tmpdir / "probe_results.json").write_text(
        json.dumps({"records": records, "calls": CALL_LOG}, indent=2, default=str)[:400000],
        encoding="utf-8",
    )
    return gate_and_report(mop, ts, records, q8_runs, budget, tmpdir)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
