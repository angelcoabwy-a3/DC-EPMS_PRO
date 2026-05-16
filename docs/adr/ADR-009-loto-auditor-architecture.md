# ADR-009: LOTO Auditor Agent Architecture

- Status: Proposed
- Date: 2026-05-06
- Deciders: Wilmer Y. Angel Beltran (CET, Lead Architect)
- Sprint: Batch 4 (Phase V9 Pillar 4 deliverable)
- Tags: agent, safety, loto, deterministic-sandbox, audit-trail

## Context and Problem Statement

A3-Alpha Toronto Area requires a paranoid validation layer for every LOTO procedure execution to satisfy four operational realities at once:

1. **CSA Z462-24 + NFPA 70E + Ontario ESC 28** require documented procedure validation before electrical work begins. Manual review by a qualified CET takes 20-40 minutes per procedure and is error-prone under shift-handover pressure.
2. **2N redundancy survival** must be verified before LOTO is applied to any single-path component. A CET reviewing a procedure does not have time to mentally simulate "if I de-energize ups_a, does Path B still cover all loads?" with full topological precision.
3. **Building D 800VDC** introduces capacitor discharge requirements (NEC 460.6, 60s minimum) and Cat 4 PPE mandates. Existing procedures written for 480 VAC do NOT automatically translate.
4. **IEC 62443 zone-and-conduit segregation** (per ADR-006 Deterministic Sandbox) forbids any AI agent from executing actions on the BMS. All AI must remain read-only, draft-only, pending-approval-only.

The question: how do we automate procedure validation while preserving deterministic, auditable, human-in-the-loop discipline?

## Decision

Implement `LotoAuditorAgent` as a **deterministic, read-only validator** with a **6-pillar audit pipeline**, persisting reports to PostgreSQL in `pending_approval` state per ADR-006.

### Core architectural choices

- **Deterministic logic over LLM inference for core pillars.** Pillars 1-6 use pure Python rules cross-referencing existing modules (site_model, graphrag_service, physics_engine, witness_engine). No LLM is in the validation path. LLM is optional, opt-in via `include_llm_summary=true`, and adds only a human-readable executive summary at the end. This makes the agent **defendible in panel review**: every PASS/WARN/HARD_FAIL has a Python file and line number behind it, not a model hallucination.

- **6 pillars, each independently testable.** Topology, redundancy, capacitor discharge, witness gate, sequential order, PPE category. A failure in one pillar does NOT abort the others. Each pillar method is wrapped in try/except with isolated error capture, so the report is always produced.

- **Pydantic models with explicit field constraints.** SHI bounds 0.0-1.0, voltage non-negative, decision_time_ms positive. Catches bugs at API boundary before they corrupt audit trail.

- **PostgreSQL JSONB for report persistence.** Avoids schema thrash when pillars evolve. Adds partial indexes for the most common queries (pending_approval dashboard, hard_fail alerts).

- **State machine constrained to ADR-006.** Initial state is `pending_approval`. Only explicit CET approval (via witness_engine) can transition to `approved`. The agent does not own the transition. The transition is a separate endpoint requiring witness identity collision protection.

## Considered Alternatives

### Alternative 1: Pure LLM-based validation (rejected)

Use Gemma local + Claude Sonnet to read the procedure YAML and the site_model, then have the LLM rate the procedure quality.

Rejected because:

- Hallucination risk on safety-critical citations (e.g. LLM might cite "NEC 470.6" instead of "NEC 460.6")
- No deterministic reproducibility for audit trail
- Inability to defend the verdict in panel: "the model said so" is not Tier IV documentation
- Slow latency (~5-10s per pillar, blocking shift handover)

### Alternative 2: Embed validation logic in procedure_engine (rejected)

Add the 6 pillars as preconditions in the existing procedure_engine state machine.

Rejected because:

- Mixes concerns: procedure_engine is execution-time state, LOTO Auditor is design-time validation
- Couples agent to procedure_engine evolution: future state machine changes break the auditor
- Makes the auditor non-reusable for ad-hoc audits ("I want to audit MOP-001 against ats_a without actually executing it")

### Alternative 3: External validation via DSPy program (deferred)

Use DSPy's signature-based validation with an LLM backbone to ingest the procedure YAML and produce structured outputs.

Deferred to S4 (W3-4 EHS Auditor) for procedure-class taxonomies, classification, and recommendation. The LOTO Auditor stays deterministic. The split is intentional: deterministic for safety-critical validation, DSPy for educational and classification tasks.

## Consequences

### Positive

- Every audit verdict cites file path, line number, standard reference
- Sub-5s latency p95 (no LLM dependency for core)
- Reproducible: same procedure + same target + same telemetry snapshot = same audit
- Defensive: pillar isolation means partial failures still yield useful report
- Tier IV audit trail: every audit persisted with full report_json in PostgreSQL
- Reusable: any caller (HMI, CMMS, MCP server) can request audit without execution

### Negative

- More code to maintain than a "just ask the LLM" approach (~1500 lines for full Batch 4)
- Each pillar requires explicit logic for new component types (e.g. when Building D adds new equipment, Pillar 6 PPE matrix needs update)
- Six pillars are not independent of cross-cutting concerns: e.g. Pillar 1 informs Pillar 2 (the components affected determine whether redundancy survives)

### Risks and Mitigations

- **Risk**: Stale telemetry causes Pillar 2 to falsely pass. **Mitigation**: agent accepts `as_of_timestamp` parameter and reads TimescaleDB snapshot at that exact time.
- **Risk**: GraphRAG lazy-load slows first audit by 2-3s. **Mitigation**: pre-warm in `lifespan` startup (pattern from Batch 2 ChromaDB).
- **Risk**: Concurrent audits on same target produce conflicting reports. **Mitigation**: audit_id includes timestamp + uuid, both audits persist independently in PostgreSQL with no conflict.

## Implementation Phases (Atomic Batches)

| Sub-batch | Scope | Estimated effort |
|-----------|-------|------------------|
| 4.A | Models + DB schema + agent skeleton + 15+ unit tests | ~3-4h |
| 4.B | Pillars 1+2+3 (topology, redundancy, caps) | ~5h |
| 4.C | Pillars 4+5+6 (witness, order, PPE) | ~4h |
| 4.D | FastAPI endpoint + report renderer + integration tests | ~3h |

Total: ~15h, within Batch 4 estimate of 12-16h.

## Compliance Mapping

| Requirement | Standard | Pillar |
|-------------|----------|--------|
| LOTO procedure validation | CSA Z462-24, NFPA 70E §130 | All 6 |
| Capacitor discharge wait 60s | NEC 460.6 | Pillar 3 |
| Cat 4 PPE for 800 VDC | NFPA 70E Annex H | Pillar 6 |
| Witness gate for high-risk LOTO | a3semi internal SOP | Pillar 4 |
| Audit trail retention 7 years | CSA Z462-24 §4.3.4 | PostgreSQL persistence |
| Read-only AI authority | IEC 62443-3-3 SR 2.5 | ADR-006 enforcement |

## Future Enhancements (V10 Candidates)

- **ADR-010 candidate**: IEEE 1584-2018 arc flash physical calculator. Currently Pillar 6 reports `incident_energy_cal_cm2 = None` and uses voltage-only PPE category. V10 calculator would compute actual cal/cm² from short-circuit current + clearing time + working distance.
- Spanish localization of LOTO reports for Wilmer's CET training program
- Dynamic PPE matrix considering ambient temperature and clothing weight
- Voice synthesis of step-by-step LOTO instructions for hands-free CET

## References

- ADR-001: Dual-RAG Architecture (ChromaDB + GraphRAG)
- ADR-002: NetworkX in-memory for GraphRAG
- ADR-003: FAISS IndexFlatIP
- ADR-006: Deterministic Sandbox (read-only AI authority)
- NFPA 70E-2024 Standard for Electrical Safety in the Workplace, Section 130
- CSA Z462-24 Workplace Electrical Safety
- Ontario Electrical Safety Code 28th Edition
- NEC 460.6 Capacitor Discharge
- IEC 60947-2 Low-voltage switchgear
- IEEE 1584-2018 (referenced as deferred V10 work)

## Decision Authority

Approved as Proposed by Wilmer Y. Angel Beltran on 2026-05-06 in conjunction with Batch 4 sprint planning. ADR moves to status Accepted upon Batch 4.D delivery and successful 8/8 layer validation.
