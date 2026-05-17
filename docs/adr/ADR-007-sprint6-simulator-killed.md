# ADR-007: Kill Sprint 6 "DPO Spike From Scratch" — Reuse `dpo_edge_healing.py` Capture-Only

- Status: ACCEPTED — superseded in practice (see Amendment, 2026-05-17)
- Date: 2026-05-03 (decision taken during archaeological audit + roadmap re-plan, retroactively documented 2026-05-06 in Batch 3)
- Decision-maker: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
- Sprint: Affects S6 V9 W7-8 (DPO sprint)
- MADR template: https://adr.github.io/madr/

## Context

The original Sprint 6 plan in the V9 roadmap was a "DPO spike from scratch" — a 2-week effort to build a Direct Preference Optimization loop that would consume CET corrections to AI-drafted CMMS work orders and use them to fine-tune the local model.

The 2026-05-03 archaeological audit of the repository (Batches A+B+C) discovered an orphan file at `backend/dpo_edge_healing.py` containing **352 lines of high-quality code already written**:

- DPO training loop targeting Hermes-3-8B as base model
- LoRA adapter fine-tuning with bitsandbytes 4-bit quantization
- "HONEST VRAM ACCOUNTING" internal documentation block with empirically measured peak of ~3.3 GB, contradicting the spec's nominal 1.5 GB claim
- Three already-evaluated compute options (A: switch to smaller model; B: CPU bitsandbytes; C: cloud GPU) with rationale
- Zero references in `main.py` (orphan) — the file was written, validated locally, but never integrated into the agent surface

Building the same functionality "from scratch" would have been wasteful and would have ignored the empirical VRAM measurements that the orphan file already contains.

## Decision

**Kill the "spike from scratch" plan**. Integrate `dpo_edge_healing.py` directly into S6 with three structural decisions:

1. **Capture-only first, training second**. S6 implements only the *capture* path: a PostgreSQL table `dpo_pairs` that records `(original_draft, corrected_draft, rejection_reason, timestamp)` automatically when a CET rejects a CMMS draft via `/api/cmms/reject`. The training step is a separate **manual trigger** (`POST /api/dpo/recompile`).

2. **CPU bitsandbytes for training compute**. Per Decision D1 vote D-B (2026-05-03), the LoRA training runs on CPU with bitsandbytes 4-bit. Slow (overnight), but preserves edge-first autonomy and avoids the 3.3 GB GPU VRAM ceiling on the RTX 3060 6 GB.

3. **No nightly automation in V9**. The recompile is manual until `approval_rate` (computed from `cmms_drafts` table over rolling window) is empirically validated as a stable signal. Future automation candidate for V10 via APScheduler.

These choices preserve the Deterministic Sandbox (per ADR-006): the AI does not retrain itself autonomously; the CET pulls the lever.

## Consequences

### Positive

- **Time saved: ~7 to 9 days**. The orphan provides ~80 percent of the implementation. S6 budget drops from 2 weeks to 2 to 3 days, freeing time for the Pre-Operational Briefing sprint S5.5a/b (W6.5 + W7) and Building D YAML expansion.
- **Honest VRAM accounting carries forward**. The empirical 3.3 GB measurement is in the ADR record. When a Microsoft CO+I panel asks "why CPU instead of GPU for DPO?", the answer is structural and grounded: the 6 GB RTX 3060 cannot host base model + adapter + KV cache simultaneously without overflow.
- **Manual trigger is defensible**. The narrative for interview is "I wanted to validate `approval_rate` stability before automating nightly. Capture is in place; training is manual today; infrastructure is ready to automate with APScheduler in V10". This demonstrates operational caution appropriate to Tier IV.
- **Edge-local self-improvement preserved**. The DPO loop runs on the same machine as the rest of the stack. No cloud round-trip, no data egress.

### Negative / Trade-offs

- **CPU training is slow**. Overnight is the realistic cadence. Acceptable because the cadence of CET rejections is itself slow (a handful per shift), and a multi-hour training window is normal for DPO at this scale.
- **The orphan file's quality must be re-verified before integration**. Risk: code that works locally may fail in container after Batch 2's CPU-only torch pin. Mitigation: S6 Hour 1 budget includes verification that the orphan still imports clean and the training step runs on the in-container torch.
- **No automated regression tracking** of approval_rate over time in V9. CET reads the metric in the briefing but no alerting if it degrades. V10 candidate.

## Alternatives Considered and Rejected

- **Spike from scratch as originally planned**. Rejected: ignores existing orphan code with empirical VRAM measurements. Wastes 7 to 9 days re-deriving what is already on disk.
- **Switch base model to Phi-2 or TinyLlama** (Option A in the orphan's documentation). Rejected: substantial quality loss for the CMMS drafting use case. Hermes-3-8B is calibrated to follow procedural patterns; smaller models confabulate more.
- **Cloud GPU training** (Option C). Rejected: breaks edge-first autonomy. Would require data egress of CMMS draft pairs to a cloud GPU — a privacy and IEC 62443 conduit problem.
- **Nightly automation now**. Rejected: premature optimization. The first month of capture data needs human review to validate that `approval_rate` is a meaningful signal before tying it to automated retraining.

## References

- `backend/dpo_edge_healing.py` — the orphan, 352 lines, target of S6 integration
- `02_STATUS_SUMMARY_REAL.md` Sec 13.1 (Decision 1 RESOLVED with vote 2B + D-B)
- `02_STATUS_SUMMARY_REAL.md` Sec 14.2 (Draft of ADR-005 to be written in S6 H6 with full DPO compute strategy treatment)
- ADR-005 (scheduled S6 H6) — the formal architectural commitment to CPU bitsandbytes; this ADR-007 only documents the high-level reuse decision
- ADR-006 (Deterministic Sandbox preserved by manual trigger)

## Verification (S6 entry criteria)

When S6 starts, verify the following against the orphan file:

- `dpo_edge_healing.py` imports clean inside the container with the CPU-only torch index used in Batch 2.
- The "HONEST VRAM ACCOUNTING" docblock is preserved verbatim and cited in ADR-005.
- A PostgreSQL migration creates the `dpo_pairs` table with `(id, original_draft TEXT, corrected_draft TEXT, rejection_reason TEXT, ts TIMESTAMPTZ)`.
- A `POST /api/dpo/capture` endpoint records pairs at CMMS rejection time; tests cover happy path and reject-with-no-reason fallback.
- A `POST /api/dpo/recompile` endpoint runs the LoRA fine-tune on captured pairs; bounded by a request timeout (long-running task pattern with status polling); manual-only invocation.

## V10 Future Work

- APScheduler nightly cron when `approval_rate >= 0.80` sustained for 30 days.
- Adapter versioning (every recompile produces a numbered adapter; CET can roll back).
- Automated A/B test of new adapter against baseline on held-out CET rejections.
- Telemetry: emit Prometheus metrics for DPO pair count, recompile duration, approval_rate over time.

## Amendment — 2026-05-17

This ADR's decision was **never executed**. The Sprint 6 slot was taken by
CMMS Core v1.0 (`v0.8.5`), and the `dpo_edge_healing.py` orphan was never wired
into the agent surface. On 2026-05-17, commit `d495c7b` **eradicated**
`backend/dpo_edge_healing.py` (352 LOC) as confirmed dead code during an SRE
tech-debt purge.

The decision recorded above is preserved as a historical design record. The
code remains recoverable from git history
(`git show d495c7b^:backend/dpo_edge_healing.py`). DPO edge-healing is now
tracked purely as a forward-looking epic in `docs/ROADMAP-V11.md` **T3.8**,
which notes that reviving it requires restoring or re-authoring the file.

The "HONEST VRAM ACCOUNTING" empirical measurement (~3.3 GB peak) cited in this
ADR's Consequences section remains valid and citable regardless of the file's
deletion.
