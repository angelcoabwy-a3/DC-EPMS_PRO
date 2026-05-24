"""
tests/test_agent_continuity.py
==============================
Tests for H13 — Apply Continuity Harness.

Strict TDD discipline: this file is the RED phase. All tests fail until
`backend/agent_continuity.py` exists and `ProcedureArchitectAgent` exposes
the `checkpoint_store` + `resume_from_checkpoint` hooks.

Coverage:

  Block A — `CheckpointStore` (JSONL append-only persistence).
  Block B — `ProcedureArchitectAgent` pre/post-LLM checkpoint emission.
  Block C — `resume_from_checkpoint` recovery flow (3 paths).
  Block D — Acceptance: simulated crash mid-generation + recovery.

Pattern: mirrors `backend.agent_harness.AgentStateStore` for consistency
with the existing H05 store (path semantics, threading.Lock, corrupt-line
tolerance) — a deliberate alignment so operators learn one persistence
shape, not two.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from backend.agent_continuity import (
    PHASE_POST_LLM,
    PHASE_PRE_LLM,
    Checkpoint,
    CheckpointStore,
)
from backend.agents.procedure_architect import (
    DOC_TYPE_MOP,
    DOC_TYPE_SOP,
    ProcedureArchitectAgent,
    ProcedureDraft,
)


# ─── Test fixtures ────────────────────────────────────────────────────────
@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """Isolated checkpoint JSONL file per test."""
    return tmp_path / "checkpoints.jsonl"


@pytest.fixture
def store(store_path: Path) -> CheckpointStore:
    return CheckpointStore(store_path)


class _FakeLLM:
    """Minimal duck-typed Gemma client. Records calls so tests can
    assert the resume flow re-dispatched (or did not)."""

    def __init__(self, response_text: str = "## Test MOP body\n\nLOTO + PPE + CSA Z462."):
        self._response = response_text
        self.calls: list[dict[str, Any]] = []

    async def complete_gemma(self, prompt: str, max_tokens: int = 800) -> str:
        self.calls.append({"prompt": prompt, "max_tokens": max_tokens})
        return self._response


class _CrashingLLM:
    """Duck-typed Gemma client that raises on the first call but
    succeeds on the second — for the crash + recovery acceptance test."""

    def __init__(self, response_text: str = "## Recovered body"):
        self._response = response_text
        self.call_count = 0

    async def complete_gemma(self, prompt: str, max_tokens: int = 800) -> str:
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("simulated network blip mid-generation")
        return self._response


# ─── Block A — CheckpointStore unit tests ─────────────────────────────────
class TestCheckpointStore:

    def test_record_appends_single_jsonl_line(self, store: CheckpointStore, store_path: Path):
        cid = store.record(
            draft_id="draft-001",
            phase=PHASE_PRE_LLM,
            payload={"doc_type": "MOP", "context": "ATS commutation"},
        )

        assert isinstance(cid, str)
        assert len(cid) > 0
        text = store_path.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["draft_id"] == "draft-001"
        assert row["phase"] == PHASE_PRE_LLM
        assert row["payload"]["doc_type"] == "MOP"
        assert row["checkpoint_id"] == cid

    def test_record_appends_multiple_records(self, store: CheckpointStore, store_path: Path):
        store.record(draft_id="d1", phase=PHASE_PRE_LLM, payload={"step": 1})
        store.record(draft_id="d1", phase=PHASE_POST_LLM, payload={"step": 2})
        store.record(draft_id="d2", phase=PHASE_PRE_LLM, payload={"step": 3})

        text = store_path.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        assert len(lines) == 3

    def test_latest_for_draft_returns_most_recent(self, store: CheckpointStore):
        store.record(draft_id="d1", phase=PHASE_PRE_LLM, payload={"step": 1})
        store.record(draft_id="d1", phase=PHASE_POST_LLM, payload={"step": 2})

        latest = store.latest_for_draft("d1")

        assert latest is not None
        assert isinstance(latest, Checkpoint)
        assert latest.draft_id == "d1"
        assert latest.phase == PHASE_POST_LLM
        assert latest.payload["step"] == 2

    def test_latest_for_draft_filters_by_draft_id(self, store: CheckpointStore):
        store.record(draft_id="d1", phase=PHASE_PRE_LLM, payload={"who": "d1"})
        store.record(draft_id="d2", phase=PHASE_PRE_LLM, payload={"who": "d2"})

        d1_latest = store.latest_for_draft("d1")
        d2_latest = store.latest_for_draft("d2")

        assert d1_latest is not None
        assert d1_latest.payload["who"] == "d1"
        assert d2_latest is not None
        assert d2_latest.payload["who"] == "d2"

    def test_latest_for_draft_returns_none_for_unknown(self, store: CheckpointStore):
        assert store.latest_for_draft("nonexistent") is None

    def test_latest_for_unknown_in_empty_store_returns_none(self, store: CheckpointStore):
        # File doesn't exist yet — must not raise.
        assert store.latest_for_draft("anything") is None

    def test_handles_corrupt_jsonl_lines(self, store: CheckpointStore, store_path: Path):
        store.record(draft_id="d1", phase=PHASE_PRE_LLM, payload={"ok": True})
        # Inject a partial-write simulation (process kill mid-flush).
        with store_path.open("a", encoding="utf-8") as fh:
            fh.write("{this-is-not-json\n")
        store.record(draft_id="d1", phase=PHASE_POST_LLM, payload={"ok": True})

        latest = store.latest_for_draft("d1")
        assert latest is not None
        assert latest.phase == PHASE_POST_LLM

    def test_iter_for_draft_returns_chronological(self, store: CheckpointStore):
        store.record(draft_id="d1", phase=PHASE_PRE_LLM, payload={"i": 1})
        store.record(draft_id="d2", phase=PHASE_PRE_LLM, payload={"i": 2})
        store.record(draft_id="d1", phase=PHASE_POST_LLM, payload={"i": 3})

        d1_history = store.iter_for_draft("d1")
        assert [c.phase for c in d1_history] == [PHASE_PRE_LLM, PHASE_POST_LLM]
        assert [c.payload["i"] for c in d1_history] == [1, 3]

    def test_record_rejects_unknown_phase(self, store: CheckpointStore):
        with pytest.raises(ValueError, match="unknown checkpoint phase"):
            store.record(draft_id="d1", phase="not_a_real_phase", payload={})

    def test_clear_truncates_backing_file(self, store: CheckpointStore, store_path: Path):
        store.record(draft_id="d1", phase=PHASE_PRE_LLM, payload={})
        assert store_path.exists()
        store.clear()
        assert not store_path.exists()


# ─── Block B — ProcedureArchitectAgent checkpoint hooks ───────────────────
class TestArchitectGenerateCheckpoints:

    def test_generate_skips_checkpointing_when_store_is_none(self):
        # Agent without store must still work (backwards compat).
        agent = ProcedureArchitectAgent(llm_client=_FakeLLM(), checkpoint_store=None)
        draft = asyncio.run(agent.generate(
            doc_type=DOC_TYPE_SOP,
            context="Generic SOP",
        ))
        assert isinstance(draft, ProcedureDraft)
        # No assertion on store — there is none. The point is "no crash".

    def test_generate_writes_pre_llm_checkpoint(self, store: CheckpointStore):
        agent = ProcedureArchitectAgent(
            llm_client=_FakeLLM(),
            checkpoint_store=store,
        )

        draft = asyncio.run(agent.generate(
            doc_type=DOC_TYPE_MOP,
            context="UPS-A bypass test",
            asset_id="ups_a",
        ))

        history = store.iter_for_draft(draft.draft_id)
        assert any(c.phase == PHASE_PRE_LLM for c in history)
        pre = next(c for c in history if c.phase == PHASE_PRE_LLM)
        # pre_llm checkpoint must carry enough state to re-dispatch the LLM.
        assert pre.payload["doc_type"] == DOC_TYPE_MOP
        assert pre.payload["context"] == "UPS-A bypass test"
        assert pre.payload["asset_id"] == "ups_a"
        assert "prompt" in pre.payload
        assert len(pre.payload["prompt"]) > 0

    def test_generate_writes_post_llm_checkpoint_on_success(self, store: CheckpointStore):
        agent = ProcedureArchitectAgent(
            llm_client=_FakeLLM(response_text="## Body content"),
            checkpoint_store=store,
        )

        draft = asyncio.run(agent.generate(
            doc_type=DOC_TYPE_SOP,
            context="SOP rounds",
        ))

        history = store.iter_for_draft(draft.draft_id)
        phases = [c.phase for c in history]
        assert PHASE_PRE_LLM in phases
        assert PHASE_POST_LLM in phases
        post = next(c for c in history if c.phase == PHASE_POST_LLM)
        # post_llm carries the full reconstructible draft.
        assert post.payload["content"] == "## Body content"
        assert post.payload["llm_present"] is True
        assert post.payload["doc_type"] == DOC_TYPE_SOP

    def test_generate_writes_post_llm_checkpoint_on_llm_failure(self, store: CheckpointStore):
        # If the LLM throws, generate() falls back to the deterministic
        # skeleton AND still emits a post_llm checkpoint (so resume sees
        # a completed phase, not a half-stuck pre_llm).
        class _RaisingLLM:
            async def complete_gemma(self, prompt: str, max_tokens: int = 800) -> str:
                raise RuntimeError("LLM exploded")

        agent = ProcedureArchitectAgent(
            llm_client=_RaisingLLM(),
            checkpoint_store=store,
        )

        draft = asyncio.run(agent.generate(
            doc_type=DOC_TYPE_MOP,
            context="ATS test",
        ))

        history = store.iter_for_draft(draft.draft_id)
        assert any(c.phase == PHASE_POST_LLM for c in history)
        post = next(c for c in history if c.phase == PHASE_POST_LLM)
        # Existing ProcedureDraft.llm_present contract: True iff an LLM
        # was wired AND dispatch was attempted -- independent of whether
        # the call succeeded or fell back to skeleton. H13 must preserve.
        assert post.payload["llm_present"] is True
        # The content should still be the deterministic skeleton because
        # the LLM raised, so the operator sees a structured but TBD body.
        assert "_TBD_" in post.payload["content"]


# ─── Block C — resume_from_checkpoint recovery flow ───────────────────────
class TestArchitectResumeFromCheckpoint:

    def test_resume_with_no_checkpoint_returns_none(self, store: CheckpointStore):
        agent = ProcedureArchitectAgent(
            llm_client=_FakeLLM(),
            checkpoint_store=store,
        )
        result = asyncio.run(agent.resume_from_checkpoint("nonexistent-draft"))
        assert result is None

    def test_resume_from_post_llm_returns_draft_without_llm_call(
        self, store: CheckpointStore,
    ):
        # Pre-populate store with a completed post_llm checkpoint.
        store.record(
            draft_id="d-recovered",
            phase=PHASE_PRE_LLM,
            payload={
                "doc_type": DOC_TYPE_SOP,
                "context": "SOP rounds",
                "asset_id": None,
                "metadata": {},
                "prompt": "(elided)",
            },
        )
        store.record(
            draft_id="d-recovered",
            phase=PHASE_POST_LLM,
            payload={
                "doc_type": DOC_TYPE_SOP,
                "context": "SOP rounds",
                "asset_id": None,
                "metadata": {},
                "content": "## Already done\n",
                "llm_present": True,
                "generated_at": 1716595200.0,
            },
        )

        llm = _FakeLLM()
        agent = ProcedureArchitectAgent(llm_client=llm, checkpoint_store=store)

        recovered = asyncio.run(agent.resume_from_checkpoint("d-recovered"))

        assert recovered is not None
        assert isinstance(recovered, ProcedureDraft)
        assert recovered.draft_id == "d-recovered"
        assert recovered.content == "## Already done\n"
        # Critical: LLM must NOT be re-dispatched — the work is already done.
        assert llm.calls == []

    def test_resume_from_pre_llm_only_reruns_llm(self, store: CheckpointStore):
        # Pre-populate ONLY the pre_llm checkpoint (simulates crash before
        # LLM responded).
        store.record(
            draft_id="d-partial",
            phase=PHASE_PRE_LLM,
            payload={
                "doc_type": DOC_TYPE_MOP,
                "context": "UPS bypass",
                "asset_id": "ups_a",
                "metadata": {"pue": 1.32},
                "prompt": "(hermetic prompt)",
            },
        )

        llm = _FakeLLM(response_text="## Resumed MOP content (LOTO, PPE, CSA Z462)")
        agent = ProcedureArchitectAgent(llm_client=llm, checkpoint_store=store)

        recovered = asyncio.run(agent.resume_from_checkpoint("d-partial"))

        assert recovered is not None
        assert recovered.draft_id == "d-partial"
        assert recovered.content == "## Resumed MOP content (LOTO, PPE, CSA Z462)"
        assert recovered.metadata == {"pue": 1.32}
        # LLM must be re-dispatched exactly once.
        assert len(llm.calls) == 1
        # Resume must persist a post_llm checkpoint so a second crash
        # does not re-trigger the LLM call.
        history = store.iter_for_draft("d-partial")
        assert any(c.phase == PHASE_POST_LLM for c in history)


# ─── Block D — Acceptance: crash + recovery ───────────────────────────────
class TestCrashAndRecoveryAcceptance:

    def test_crash_mid_generation_recovers_via_resume(self, store: CheckpointStore):
        """End-to-end: generate() crashes BEFORE the LLM resolves -> only
        the pre_llm checkpoint is on disk -> a fresh agent process
        invokes resume_from_checkpoint(draft_id) and gets back a complete
        ProcedureDraft. No work lost."""

        # ─── Phase 1: original generation crashes ──
        # We force the crash by raising INSIDE the LLM call. The agent's
        # try/except will swallow the LLM error and fall back to skeleton,
        # so for this test we want the crash to escape `generate()`
        # entirely. We simulate that by using a checkpoint store that
        # records pre_llm, then manually verifying no post_llm exists.
        draft_id_captured = []

        class _HardCrashLLM:
            async def complete_gemma(self, prompt: str, max_tokens: int = 800) -> str:
                # Simulate a hard process-level interruption right after
                # pre_llm is checkpointed but before the LLM responds.
                # We raise BaseException so the agent's `except Exception`
                # does NOT catch it — this models "process killed".
                raise KeyboardInterrupt("simulated SIGKILL mid-LLM")

        agent_v1 = ProcedureArchitectAgent(
            llm_client=_HardCrashLLM(),
            checkpoint_store=store,
        )

        with pytest.raises(KeyboardInterrupt):
            asyncio.run(agent_v1.generate(
                doc_type=DOC_TYPE_MOP,
                context="Critical UPS-A bypass operation",
                asset_id="ups_a",
                metadata={"pue": 1.32, "load_kw": 142.0},
            ))

        # ─── Verify only pre_llm exists on disk ──
        # Find the draft_id by scanning the store. (In production, the
        # operator would supply the draft_id captured before the crash;
        # here we read it back from the checkpoint.)
        with store.path.open("r", encoding="utf-8") as fh:
            rows = [json.loads(ln) for ln in fh if ln.strip()]
        assert len(rows) == 1, f"expected only pre_llm row, got {len(rows)}"
        assert rows[0]["phase"] == PHASE_PRE_LLM
        recovered_draft_id = rows[0]["draft_id"]
        draft_id_captured.append(recovered_draft_id)

        # ─── Phase 2: fresh agent picks up + resumes ──
        agent_v2 = ProcedureArchitectAgent(
            llm_client=_FakeLLM(
                response_text=(
                    "## Recovered MOP\n\nLOTO + PPE + CSA Z462. "
                    "Vivo-Muerto-Vivo. Plan de Reversión. "
                    "Alcance Objetivo Impacto Riesgos Prerrequisitos "
                    "Pasos Secuenciales."
                ),
            ),
            checkpoint_store=store,
        )

        recovered = asyncio.run(agent_v2.resume_from_checkpoint(recovered_draft_id))

        assert recovered is not None
        assert recovered.draft_id == recovered_draft_id
        assert recovered.doc_type == DOC_TYPE_MOP
        assert recovered.context == "Critical UPS-A bypass operation"
        assert recovered.asset_id == "ups_a"
        assert recovered.metadata == {"pue": 1.32, "load_kw": 142.0}
        assert "Recovered MOP" in recovered.content

        # Store now has the post_llm checkpoint -- a second resume must
        # be idempotent (no second LLM call).
        llm_v3 = _FakeLLM(response_text="## SHOULD NOT BE CALLED")
        agent_v3 = ProcedureArchitectAgent(llm_client=llm_v3, checkpoint_store=store)
        re_recovered = asyncio.run(agent_v3.resume_from_checkpoint(recovered_draft_id))
        assert re_recovered is not None
        assert re_recovered.content == recovered.content
        assert llm_v3.calls == []
