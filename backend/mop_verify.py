"""MOP photo verification: SAM locates breakers, Spark judges crops.

HACKATHON feature (Shift Agentic Investigator). Production port of the
scripts/probe_mop_vision_crops.py pipeline that passed 10/10 frames and
45/45 labels: SAM 3.1 locates breakers, code assigns boxes per column
(4 boxes sorted top to bottom, or 1 column box split by fixed fractions
after an aspect check), crops the operated labels at native size, and
muse-spark-1.3 judges each crop (handle at the LEFT or RIGHT end of
its window). Panel geometry lives in data/panel_training.json.

Verdicts are computed in code, never from the model. A photo is never
just described: verify_photo always checks it against the expected
state of one MOP step (step_id 0 means the initial state). Sessions
gate step advance: the next step is allowed only after MATCH on the
current step.

Meta budget per verify_photo call: 1 SAM + up to 5 parallel crops +
at most 5 retries (one retry only on timeout, shared budget). One
daily-cap attempt is recorded right before the SAM call; input
validation happens before any recording.
"""

from __future__ import annotations

import base64
import io
import json
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageDraw, ImageFont

try:  # package import (backend.mop_verify)
    from .copilot_limits import record_meta_attempt
    from .llm_providers import MetaProvider
except ImportError:  # top-level import, as backend/main.py does it
    from copilot_limits import record_meta_attempt  # type: ignore[no-redef]
    from llm_providers import MetaProvider  # type: ignore[no-redef]

MOP_VERSION = "1.3"
SAM_MODEL = "sam-3.1"
SPARK_MODEL = "muse-spark-1.3"
SAM_CONCEPT = "circuit breaker"
MAX_TOKENS = 4000
TIMEOUT_S = 120.0
MAX_RETRIES_PER_VERIFY = 5
CROP_JPEG_QUALITY = 95

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MOP_PATH = DATA_DIR / "mop_ups_bypass.json"
GEOMETRY_PATH = DATA_DIR / "panel_training.json"

CROP_PROMPT = (
    "This is a close-up photo of one circuit breaker. In the middle there is "
    "a rectangular window with a handle inside it, and the handle has a number "
    "printed on it. Is the handle at the LEFT end or the RIGHT end of the "
    "window, as seen in this photo? If the handle or the window is not clearly "
    "visible, or something covers it, answer UNKNOWN. Return only JSON: "
    '{"handle": "LEFT|RIGHT|UNKNOWN", "notes": "short reason"}.'
)

BOX_RE = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")

_CLAIM_Q_RE = re.compile(
    r"\bq\s*([1-9]|one|two|three|four|five|six|seven|eight|nine)\b", re.IGNORECASE
)
_CLAIM_BYP_RE = re.compile(r"\bb\s*y\s*p\b", re.IGNORECASE)
_CLAIM_CLOSED_RE = re.compile(r"\bclosed?\b", re.IGNORECASE)
_CLAIM_OPEN_RE = re.compile(r"\bopened?\b", re.IGNORECASE)
_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

SamClient = Callable[[bytes], list[tuple[int, int, int, int]]]
SparkClient = Callable[[bytes], str]
_T = TypeVar("_T")

_default_sam_client: SamClient | None = None
_default_spark_client: SparkClient | None = None


class MopInputError(Exception):
    """Bad verify input (step, image, claim shape). Maps to HTTP 400."""


class MopDataError(Exception):
    """Bundled MOP/geometry data is missing or corrupt. Never client input."""


class MopUpstreamError(Exception):
    """Meta transport/HTTP failure that is not a timeout. Maps to NO_ANSWER."""


@lru_cache(maxsize=1)
def load_mop() -> dict:
    """MOP-UPS-BYP-DEMO-01 v1.3, validated. Cached; the file is frozen."""
    try:
        data = json.loads(MOP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MopDataError(f"cannot load {MOP_PATH.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise MopDataError(f"{MOP_PATH.name} is not an object")
    if data.get("version") != MOP_VERSION:
        raise MopDataError(f"{MOP_PATH.name} version {data.get('version')!r} != {MOP_VERSION}")
    if not isinstance(data.get("steps"), list) or not isinstance(data.get("initial_state"), dict):
        raise MopDataError(f"{MOP_PATH.name} missing steps/initial_state")
    return data


def _validated_geometry(data: dict) -> dict:
    """Reject a geometry file the pipeline cannot consume safely."""
    columns = data.get("columns")
    if not isinstance(columns, dict):
        raise MopDataError("panel_training.json: columns must be an object")
    for side in ("left", "right"):
        column = columns.get(side)
        if not isinstance(column, dict):
            raise MopDataError(f"panel_training.json: columns.{side} must be an object")
        labels = column.get("labels")
        singles = column.get("singles")
        if not isinstance(labels, list) or len(labels) != 4:
            raise MopDataError(f"panel_training.json: columns.{side}.labels must hold 4 labels")
        if not isinstance(singles, list) or len(singles) != 3:
            raise MopDataError(f"panel_training.json: columns.{side}.singles must hold 3 labels")
    fractions = data.get("split_fractions")
    if not isinstance(fractions, dict):
        raise MopDataError("panel_training.json: split_fractions must be an object")
    for role in ("quad", "s1", "s2", "s3"):
        band = fractions.get(role)
        if (
            not isinstance(band, list)
            or len(band) != 2
            or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in band)
            or not 0.0 <= band[0] < band[1] <= 1.0
        ):
            raise MopDataError(f"panel_training.json: split_fractions.{role} must be [f0, f1]")
    for key in ("expected_column_aspect", "aspect_tolerance", "crop_padding"):
        value = data.get(key)
        if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
            raise MopDataError(f"panel_training.json: {key} must be a positive number")
    mapping = data.get("handle_mapping")
    if not isinstance(mapping, dict):
        raise MopDataError("panel_training.json: handle_mapping must be an object")
    for side in ("left", "right"):
        side_map = mapping.get(side)
        if (
            not isinstance(side_map, dict)
            or set(side_map) != {"LEFT", "RIGHT"}
            or set(side_map.values()) != {"OPEN", "CLOSED"}
        ):
            raise MopDataError(f"panel_training.json: handle_mapping.{side} must map both ends")
    operated = data.get("operated_labels")
    if not isinstance(operated, list) or len(operated) != 5:
        raise MopDataError("panel_training.json: operated_labels must hold 5 labels")
    known = set(columns["left"]["singles"]) | set(columns["right"]["singles"])
    if any(label not in known for label in operated):
        raise MopDataError("panel_training.json: operated label outside column singles")
    if not isinstance(data.get("distractors"), list):
        raise MopDataError("panel_training.json: distractors must be a list")
    return data


@lru_cache(maxsize=1)
def load_geometry() -> dict:
    """Training-panel geometry, validated. Cached; the file is frozen."""
    try:
        data = json.loads(GEOMETRY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MopDataError(f"cannot load {GEOMETRY_PATH.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise MopDataError(f"{GEOMETRY_PATH.name} is not an object")
    return _validated_geometry(data)


def get_mop_steps() -> dict:
    """MOP steps for the UI (static data, no Meta call)."""
    mop = load_mop()
    geometry = load_geometry()
    steps = [
        {
            "step_id": step.get("step_id"),
            "panel_label": step.get("panel_label"),
            "action": step.get("action"),
            "expected_state": step.get("expected_state"),
            "hazard_if_wrong": step.get("hazard_if_wrong"),
        }
        for step in mop["steps"]
    ]
    return {
        "mop_id": mop.get("mop_id"),
        "version": mop.get("version"),
        "initial_state": mop.get("initial_state"),
        "operated_labels": list(geometry["operated_labels"]),
        "steps": steps,
    }


# ------------------------------------------------------- Meta clients


def _api_url_and_headers() -> tuple[str, dict]:
    provider = MetaProvider()
    if not provider.is_configured:
        raise MopUpstreamError("Meta API key not configured")
    return provider.api_url, {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {provider.api_key}",
    }


def _assert_api_host(url: str, base: str) -> None:
    if urlparse(url).hostname != urlparse(base).hostname:
        raise MopUpstreamError(f"refusing non-Meta destination: {url}")


def _sniff_mime(image_bytes: bytes) -> str:
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            fmt = (img.format or "").upper()
    except Exception:
        fmt = ""
    return "image/png" if fmt == "PNG" else "image/jpeg"


def _post_json(url: str, headers: dict, payload: dict) -> dict:
    """One POST, no retries here. Timeouts propagate; the rest wraps."""
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=TIMEOUT_S)
    except httpx.TimeoutException:
        raise
    except Exception as exc:
        raise MopUpstreamError(f"{type(exc).__name__}: {exc}") from exc
    if resp.status_code != 200:
        raise MopUpstreamError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
    except Exception as exc:
        raise MopUpstreamError(f"non-JSON body: {exc}") from exc
    if not isinstance(data, dict):
        raise MopUpstreamError("JSON body is not an object")
    return data


def _real_sam_client(image_bytes: bytes) -> list[tuple[int, int, int, int]]:
    """Original frame + concept to SAM 3.1. Returns boxes, nothing else."""
    base, headers = _api_url_and_headers()
    url = f"{base}/responses"
    _assert_api_host(url, base)
    mime = _sniff_mime(image_bytes)
    payload = {
        "model": SAM_MODEL,
        "stream": False,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": SAM_CONCEPT},
                    {
                        "type": "input_image",
                        "image_url": (
                            f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
                        ),
                    },
                ],
            }
        ],
    }
    data = _post_json(url, headers, payload)
    return [
        (int(x1), int(y1), int(x2), int(y2))
        for x1, y1, x2, y2, _w, _h in BOX_RE.findall(json.dumps(data))
    ]


def _real_spark_client(crop_bytes: bytes) -> str:
    """One crop to muse-spark-1.3 with the exact crop prompt, nothing else."""
    base, headers = _api_url_and_headers()
    url = f"{base}/chat/completions"
    _assert_api_host(url, base)
    mime = _sniff_mime(crop_bytes)
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
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                f"data:{mime};base64,{base64.b64encode(crop_bytes).decode('ascii')}"
                            )
                        },
                    },
                ],
            }
        ],
    }
    data = _post_json(url, headers, payload)
    try:
        text = data["choices"][0].get("message", {}).get("content") or ""
    except (KeyError, IndexError, TypeError, AttributeError):
        text = ""
    return text if isinstance(text, str) else ""


class _RetryBudget:
    """Shared retry allowance for one verify call (thread-safe)."""

    def __init__(self, max_retries: int = MAX_RETRIES_PER_VERIFY):
        self._remaining = max_retries
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self._remaining <= 0:
                return False
            self._remaining -= 1
            return True


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, httpx.TimeoutException) or "timeout" in type(exc).__name__.lower()


def _run_callable(
    fn: Callable[[], _T], retry_budget: _RetryBudget
) -> tuple[_T | None, int, Exception | None]:
    """Run fn once; on timeout retry once iff the shared budget allows it.

    Returns (value, attempts, error). Non-timeout errors never retry.
    Never raises.
    """
    try:
        return fn(), 1, None
    except Exception as first:
        if not _is_timeout(first) or not retry_budget.take():
            return None, 1, first
        try:
            return fn(), 2, None
        except Exception as second:
            return None, 2, second


# ------------------------------------------------------- Parse + geometry


def _extract_json(text: str) -> tuple[dict | None, str]:
    stripped = (text or "").strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        return None, "no JSON object found in answer"
    try:
        parsed = json.loads(stripped[start : end + 1])
    except ValueError as exc:
        return None, f"JSON decode error: {exc}"
    if not isinstance(parsed, dict):
        return None, "top-level JSON is not an object"
    return parsed, ""


def _parse_crop_answer(text: str) -> tuple[str | None, str]:
    """Crop answer handle in LEFT/RIGHT/UNKNOWN, else (None, reason)."""
    obj, err = _extract_json(text)
    if obj is None:
        return None, err
    raw = obj.get("handle")
    if not isinstance(raw, str):
        return None, "handle key missing or not a string"
    value = raw.strip().upper()
    if value not in ("LEFT", "RIGHT", "UNKNOWN"):
        return None, f"handle value {raw!r} not in enum"
    return value, ""


def _split_columns(boxes: list) -> tuple[list | None, list | None]:
    """Split boxes into (left, right) by the largest center-x gap."""
    if len(boxes) < 2:
        return None, None
    by_x = sorted((((box[0] + box[2]) / 2.0), box) for box in boxes)
    gaps = [by_x[i + 1][0] - by_x[i][0] for i in range(len(by_x) - 1)]
    cut = gaps.index(max(gaps)) + 1
    return [box for _, box in by_x[:cut]], [box for _, box in by_x[cut:]]


def _column_aspect(box: list | tuple) -> float:
    return float((box[2] - box[0]) / max(1, box[3] - box[1]))


def _split_column_box(box: list | tuple, geometry: dict) -> dict:
    """Split one whole-column box into quad + 3 single bands by fractions."""
    x1, y1, x2, y2 = (int(v) for v in box[:4])
    height = max(1, y2 - y1)
    fractions = geometry["split_fractions"]
    return {
        role: (
            x1,
            y1 + int(round(fractions[role][0] * height)),
            x2,
            y1 + int(round(fractions[role][1] * height)),
        )
        for role in ("quad", "s1", "s2", "s3")
    }


def _assign_column(boxes: list, geometry: dict) -> tuple[dict, str, str]:
    """Assign one column. Returns (roles, method, detail).

    roles maps quad/s1/s2/s3 to a box ({} when the column goes UNKNOWN).
    method is '4 boxes', 'split', or 'UNKNOWN'. Never guesses.
    """
    if len(boxes) == 4:
        ordered = sorted(boxes, key=lambda box: (box[1] + box[3]) / 2.0)
        roles = dict(zip(("quad", "s1", "s2", "s3"), ordered, strict=True))
        aspects = ",".join(f"{_column_aspect(box):.3f}" for box in ordered)
        return roles, "4 boxes", f"box aspects {aspects}"
    if len(boxes) == 1:
        aspect = _column_aspect(boxes[0])
        expected = geometry["expected_column_aspect"]
        tolerance = geometry["aspect_tolerance"]
        if abs(aspect - expected) / expected > tolerance:
            return {}, "UNKNOWN", f"aspect {aspect:.3f} differs >15% from {expected}: no split"
        return _split_column_box(boxes[0], geometry), "split", f"aspect {aspect:.3f}"
    return {}, "UNKNOWN", f"box count {len(boxes)}: no assignment guessed"


def _crop_with_pad(img: Image.Image, box: list | tuple, pad: float) -> tuple[Image.Image, tuple]:
    """Crop a box with fractional padding, clamped. Native size, no resize."""
    width, height = img.size
    x1, y1, x2, y2 = (int(v) for v in box[:4])
    box_w, box_h = max(1, x2 - x1), max(1, y2 - y1)
    used = (
        max(0, int(x1 - pad * box_w)),
        max(0, int(y1 - pad * box_h)),
        min(width, int(x2 + pad * box_w)),
        min(height, int(y2 + pad * box_h)),
    )
    return img.crop(used), used


def _map_handle(label: str, handle: str, geometry: dict) -> str:
    """LEFT/RIGHT (as seen) to OPEN/CLOSED by column physics, from data."""
    if handle == "UNKNOWN":
        return "UNKNOWN"
    left_singles = geometry["columns"]["left"]["singles"]
    side = "left" if label in left_singles else "right"
    return str(geometry["handle_mapping"][side][handle])


def _parse_claim(text: str | None) -> dict | None:
    """Operator claim ('Q8 closed') to {label, state} in code, else None.

    Strict: exactly one label (Q1-Q9 digit or word, or BYP) and exactly
    one state word, otherwise the claim is unparseable and ignored.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    labels = []
    for match in _CLAIM_Q_RE.finditer(text):
        token = match.group(1).lower()
        labels.append(f"Q{_NUMBER_WORDS.get(token, token)}")
    if _CLAIM_BYP_RE.search(text):
        labels.append("BYP")
    states = []
    if _CLAIM_CLOSED_RE.search(text):
        states.append("CLOSED")
    if _CLAIM_OPEN_RE.search(text):
        states.append("OPEN")
    if len(labels) != 1 or len(states) != 1:
        return None
    return {"label": labels[0], "state": states[0]}


# ------------------------------------------------------- Sessions


@dataclass
class MopSession:
    """In-memory MOP run: current step, verification history, photo."""

    session_id: str
    current_step: int = 0
    completed: bool = False
    history: list = field(default_factory=list)
    pending_image: bytes | None = None


_sessions: dict[str, MopSession] = {}
_sessions_lock = threading.Lock()


def get_session(session_id: str) -> MopSession:
    """Fetch a session, creating it at step 0 when missing."""
    with _sessions_lock:
        session = _sessions.get(session_id)
        if session is None:
            session = MopSession(session_id=session_id)
            _sessions[session_id] = session
        return session


def store_session_photo(session_id: str, image_bytes: bytes) -> MopSession:
    """Stage an uploaded photo on a session for later tool verification."""
    session = get_session(session_id)
    with _sessions_lock:
        session.pending_image = image_bytes
    return session


def reset_sessions_for_tests() -> None:
    """Clear all sessions. Tests and local verification only."""
    with _sessions_lock:
        _sessions.clear()


# ------------------------------------------------------- Verification


def validate_verify_inputs(step_id: int, image_bytes: bytes, session_id: str | None) -> None:
    """Pure input checks shared by the endpoint pre-guard and verify_photo."""
    if (
        isinstance(step_id, bool)
        or not isinstance(step_id, int)
        or step_id not in (0, 1, 2, 3, 4, 5)
    ):
        raise MopInputError(f"step_id must be an integer 0-5, got {step_id!r}")
    if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
        raise MopInputError("session_id must be a non-empty string when given")
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise MopInputError("image_bytes must be non-empty bytes")


def _decode_image(image_bytes: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(image_bytes)) as probe_image:
            probe_image.load()
            return probe_image.convert("RGB")
    except Exception as exc:
        raise MopInputError(f"image_bytes is not a decodable image: {exc}") from exc


def _expected_for_step(mop: dict, step_id: int) -> tuple[dict, str | None]:
    """Expected state + hazard for a step (0 means the initial state)."""
    if step_id == 0:
        return dict(mop["initial_state"]), None
    step = next(s for s in mop["steps"] if s.get("step_id") == step_id)
    return dict(step["expected_state"]), step.get("hazard_if_wrong")


def _coerce_boxes(raw: object) -> list[tuple[int, int, int, int]] | None:
    """Client boxes to int 4-tuples, or None when malformed."""
    if not isinstance(raw, list):
        return None
    boxes = []
    for box in raw:
        try:
            x1, y1, x2, y2 = (int(v) for v in box[:4])
        except (TypeError, ValueError, IndexError):
            return None
        boxes.append((x1, y1, x2, y2))
    return boxes


def _geometric_record() -> dict:
    return {
        "raw": "",
        "handle": None,
        "mapped": "UNKNOWN",
        "no_answer": False,
        "geometric": True,
        "parse_error": "",
        "call_error": "",
        "crop_box": None,
        "box": None,
        "latency_s": None,
    }


def _no_answer_record(call_error: str) -> dict:
    return {
        "raw": "",
        "handle": None,
        "mapped": "NO_ANSWER",
        "no_answer": True,
        "geometric": False,
        "parse_error": "",
        "call_error": call_error,
        "crop_box": None,
        "box": None,
        "latency_s": None,
    }


def verify_photo(
    step_id: int,
    image_bytes: bytes,
    operator_claim: str | None = None,
    session_id: str | None = None,
    sam_client: SamClient | None = None,
    spark_client: SparkClient | None = None,
) -> dict:
    """Verify a panel photo against one MOP step. Verdict computed in code.

    step_id 0 means the initial state. Records one daily-cap attempt
    right before the SAM call, after all input validation. With a
    session_id the verification is appended to history and a MATCH on
    the current step advances it; anything else blocks the next step.
    """
    validate_verify_inputs(step_id, image_bytes, session_id)
    if operator_claim is not None and not isinstance(operator_claim, str):
        raise MopInputError("operator_claim must be text when given")
    mop = load_mop()
    geometry = load_geometry()
    operated = list(geometry["operated_labels"])
    expected, hazard = _expected_for_step(mop, step_id)
    claim = _parse_claim(operator_claim)
    full = _decode_image(image_bytes)
    sam = sam_client if sam_client is not None else _default_sam_client or _real_sam_client
    spark = (
        spark_client if spark_client is not None else _default_spark_client or _real_spark_client
    )

    record_meta_attempt()
    started = time.perf_counter()
    retry_budget = _RetryBudget(MAX_RETRIES_PER_VERIFY)
    meta_calls = 0

    sam_raw, sam_attempts, sam_error = _run_callable(lambda: sam(image_bytes), retry_budget)
    meta_calls += sam_attempts
    boxes = _coerce_boxes(sam_raw) if sam_error is None else None

    readings: dict[str, dict] = {}
    methods: dict[str, dict] = {}
    crops: dict[str, tuple[bytes, tuple]] = {}
    if boxes is None:
        sam_failure = str(sam_error) if sam_error else "malformed SAM boxes"
        for label in operated:
            readings[label] = _no_answer_record(sam_failure)
        methods = {
            "left": {"method": "UNKNOWN", "detail": "SAM call failed"},
            "right": {"method": "UNKNOWN", "detail": "SAM call failed"},
        }
        box_list: list = []
    else:
        box_list = boxes
        left_boxes, right_boxes = _split_columns(boxes)
        assignment: dict[str, tuple] = {}
        if left_boxes is None or right_boxes is None:
            for side in ("left", "right"):
                methods[side] = {
                    "method": "UNKNOWN",
                    "detail": f"only {len(boxes)} box(es): cannot form columns",
                }
        else:
            roles_l, method_l, detail_l = _assign_column(left_boxes, geometry)
            roles_r, method_r, detail_r = _assign_column(right_boxes, geometry)
            methods = {
                "left": {"method": method_l, "detail": detail_l},
                "right": {"method": method_r, "detail": detail_r},
            }
            left_labels = geometry["columns"]["left"]["labels"]
            right_labels = geometry["columns"]["right"]["labels"]
            for role_label, role in zip(left_labels, ("quad", "s1", "s2", "s3"), strict=True):
                if role in roles_l:
                    assignment[role_label] = roles_l[role]
            for role_label, role in zip(right_labels, ("quad", "s1", "s2", "s3"), strict=True):
                if role in roles_r:
                    assignment[role_label] = roles_r[role]
        role_of = {}
        for side in ("left", "right"):
            for role_label, role in zip(
                geometry["columns"][side]["labels"], ("quad", "s1", "s2", "s3"), strict=True
            ):
                role_of[role_label] = (side, role)
        singles_of = {
            "left": geometry["columns"]["left"]["singles"],
            "right": geometry["columns"]["right"]["singles"],
        }
        label_box: dict[str, tuple] = {}
        for role_label, box in assignment.items():
            side, role = role_of[role_label]
            if role == "quad":
                continue
            label_box[singles_of[side][("s1", "s2", "s3").index(role)]] = box
        pad = geometry["crop_padding"]
        for label in operated:
            if label not in label_box:
                readings[label] = _geometric_record()
                continue
            crop_img, used = _crop_with_pad(full, label_box[label], pad)
            buf = io.BytesIO()
            crop_img.save(buf, "JPEG", quality=CROP_JPEG_QUALITY)
            crops[label] = (buf.getvalue(), used)

        def judge(label: str) -> tuple[str, dict]:
            crop_bytes, used = crops[label]
            started_label = time.perf_counter()
            text, attempts, error = _run_callable(lambda: spark(crop_bytes), retry_budget)
            record = {
                "raw": text or "",
                "handle": None,
                "mapped": "NO_ANSWER",
                "no_answer": True,
                "geometric": False,
                "parse_error": "",
                "call_error": str(error) if error else "",
                "crop_box": [int(v) for v in used],
                "box": [int(v) for v in label_box[label][:4]],
                "latency_s": round(time.perf_counter() - started_label, 1),
                "attempts": attempts,
            }
            if error is None and (text or "").strip():
                handle, parse_error = _parse_crop_answer(text or "")
                if handle is None:
                    record["parse_error"] = parse_error
                else:
                    record["handle"] = handle
                    record["mapped"] = _map_handle(label, handle, geometry)
                    record["no_answer"] = False
            elif error is None:
                record["parse_error"] = "empty answer text"
            return label, record

        if crops:
            with ThreadPoolExecutor(max_workers=5) as pool:
                for label, record in pool.map(judge, sorted(crops)):
                    readings[label] = record
                    meta_calls += record.pop("attempts")

    differing: list = []
    if any(record["no_answer"] for record in readings.values()):
        verdict = "NO_ANSWER"
    elif any(record["mapped"] in ("UNKNOWN", "MISSING") for record in readings.values()):
        verdict = "UNCERTAIN"
    else:
        differing = sorted(
            label for label in operated if readings[label]["mapped"] != expected[label]
        )
        verdict = "MISMATCH" if differing else "MATCH"

    contradiction: dict | None = None
    if claim is not None and claim["label"] in readings:
        observed = readings[claim["label"]]["mapped"]
        if observed in ("OPEN", "CLOSED") and observed != claim["state"]:
            contradiction = {
                "label": claim["label"],
                "claimed": claim["state"],
                "observed": observed,
            }

    latency_s = time.perf_counter() - started
    blocked = verdict != "MATCH"
    advanced = False
    session_view: dict | None = None
    if session_id is not None:
        session = get_session(session_id)
        with _sessions_lock:
            session.history.append(
                {
                    "step_id": step_id,
                    "verdict": verdict,
                    "differing_labels": list(differing),
                    "contradiction": contradiction,
                    "latency_s": latency_s,
                    "at": datetime.now(UTC).isoformat(),
                }
            )
            if step_id == session.current_step and verdict == "MATCH":
                advanced = True
                if session.current_step >= 5:
                    session.completed = True
                else:
                    session.current_step += 1
            session_view = {
                "session_id": session.session_id,
                "current_step": session.current_step,
                "completed": session.completed,
            }

    return {
        "mop_id": mop.get("mop_id"),
        "step_id": step_id,
        "verdict": verdict,
        "differing_labels": differing,
        "expected_state": expected,
        "hazard_if_wrong": hazard,
        "blocked": blocked,
        "advanced": advanced,
        "readings": readings,
        "sam_box_count": len(box_list),
        "sam_boxes": [[int(v) for v in box[:4]] for box in box_list],
        "column_methods": methods,
        "claim": claim,
        "contradiction": contradiction,
        "latency_s": latency_s,
        "models": {"sam": SAM_MODEL, "spark": SPARK_MODEL},
        "meta_calls_made": meta_calls,
        "session": session_view,
    }


# ------------------------------------------------------- Debug overlay


def _label_font(size: int = 64):
    for path in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\calibri.ttf"):
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_debug_overlay(image_bytes: bytes, sam_boxes: list, crop_rects: list) -> bytes:
    """Draw SAM boxes (red) + labeled crop rects (green). Returns JPEG bytes.

    sam_boxes: iterable of [x1, y1, x2, y2]. crop_rects: iterable of
    (label, [x1, y1, x2, y2]). Pure local helper for eyeball checks.
    """
    with Image.open(io.BytesIO(image_bytes)) as base:
        img = base.convert("RGB")
    draw = ImageDraw.Draw(img)
    for box in sam_boxes:
        x1, y1, x2, y2 = (int(v) for v in box[:4])
        draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=5)
    font = _label_font()
    for label, rect in crop_rects:
        x1, y1, x2, y2 = (int(v) for v in rect[:4])
        draw.rectangle([x1, y1, x2, y2], outline=(0, 255, 0), width=5)
        anchor = (x1 + 10, max(0, y1 - 84))
        bbox = draw.textbbox(anchor, str(label), font=font)
        pad = 8
        draw.rectangle([bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad], fill=(0, 0, 0))
        draw.text(anchor, str(label), font=font, fill=(0, 255, 0))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()
