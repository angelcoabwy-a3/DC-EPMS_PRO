# Procedure Engine — Industry Field Notes

**Status:** Research / reference. **Not** a spec — the spec is the
shipped code under `backend/agents/procedure_architect.py` +
`backend/procedure_routes.py` + `frontend/assets/js/views/procedures.js`
+ `tests/test_procedure_architect.py` + `tests/frontend/procedures.test.js`.

This document is the operational-industry baseline that informed
Epic 6 (Procedure Architect). It's preserved as a field reference so
future contributors understand *why* the safety audit, the back-out
plan emphasis, and the per-template structure look the way they do.

Versioning: when the shipped code changes, this doc does **not** need
to update — the code is authoritative. Update this doc only when the
underlying industry standards move (e.g. CSA Z462-25 supersedes
Z462-24).

---

## 1. The four document classes — operational reality

Tier IV / Uptime Institute Tier III operations do not tolerate
documentation ambiguity. The four canonical document classes are not
interchangeable; each governs a distinct operational regime and a
distinct risk surface.

### A. SOP — Standard Operating Procedure
- **Regime:** routine, low-immediate-criticality, high-preventive-impact
  tasks. The goal is mitigating "maintenance drift" — the slow
  accumulation of small deviations that erode the baseline.
- **Standards alignment:** Uptime Institute Operational Sustainability
  guidelines + ASHRAE TC 9.9 for environmental control.
- **Examples (Path-C2):**
  - Thermographic + hygrometric inspection rounds of cold/hot aisles.
  - Manual air-purge of chilled-water loops.
  - Daily review of non-critical BMS/EPMS alarm log.
- **Audit-gate signal:** a SOP without a BMS/HMI verification term is
  flagged `caution` (not `hard_stop`) — the procedure isn't dangerous
  but the success criteria can't be checked.

### B. MOP — Method of Procedure
- **Regime:** any **state change** on infrastructure supporting
  critical load. Industry statistic frequently cited: >70 % of Tier IV
  outages during scheduled-maintenance windows trace back to MOP
  authoring or execution failure. **This is the load-bearing class.**
- **Standards alignment:** CSA Z462-24 (Canada) / NFPA 70E (US) for
  electrical safety in the workplace. Arc-flash boundaries (limited
  approach + restricted approach distances) and PPE categories MUST
  be named explicitly.
- **Examples (Path-C2):**
  - Critical load transfer from UPS A to UPS B via STS.
  - Electrical + mechanical isolation of a 2.5 MW diesel genset for
    fuel-injector change.
  - MV breaker maneuver on the main ATS.
- **Mitigating the blast radius:**
  - LOTO matrix — unambiguous lockout points per energy class
    (electrical / pneumatic / hydraulic).
  - **Back-out plan with a physical clock.** The deadline is not
    aspirational — it's bounded by something the operator can
    compute from a BMS readout. Examples:
    - Battery autonomy at current load (read `battery_runtime_min`
      before isolation).
    - Sync-check expiry window during a load transfer.
    - ASHRAE A2 inlet cap (35 °C) during a cooling-chain
      intervention.
    - Vendor rollback support window for a firmware upgrade.
- **Audit-gate signal:** a MOP missing ANY of LOTO / PPE / CSA Z462
  (or NFPA 70E equivalent) is `hard_stop`. The HMI hides the Sign
  button; the server-side `architect/sign` route re-audits and
  refuses with HTTP 403.

### C. EOP — Emergency Operating Procedure
- **Regime:** active runbook executed under stress. Loss of redundancy
  or imminent failure threatening computing SLAs. Psychological
  design matters — imperative instructions, short sentences, high-
  contrast typography, no explanatory prose.
- **Examples (Path-C2):**
  - Transition to thermal bypass after catastrophic CRAC/CRAH loss.
  - Genset start-failure during utility outage.
  - Accidental clean-agent (Inergen / FM200) discharge.
- **Two-phase structure (mandated):**
  1. **Immediate containment (first 5 minutes)** — actions to halt
     degradation. Memory or quick-reference grade.
  2. **Isolation + stabilisation** — separate the fault from the
     critical bus without disturbing healthy loops.
- **Audit-gate signal:** an EOP missing containment / isolation
  language is `caution` (an EOP without those concepts is missing
  half its purpose, but it doesn't endanger the operator the way an
  unsafe MOP does).

### D. EMP — Emergency Management Plan
- **Regime:** organisational / business — not equipment. Crisis
  logistics, BCP, environmental compliance (e.g. diesel spill),
  chain of command.
- **Standards alignment:** FEMA / Incident Command System (ICS).
- **Examples (Path-C2):**
  - External flooding from municipal infrastructure rupture.
  - Force-majeure event blocking shift relief.
  - Major diesel spill in the genset yard.
- **Required structure:** incident commander, communication cadence
  (15-minute report SLA for hyperscale tenants), pre-approved
  customer notification templates, external vendor dispatch protocol.
- **Audit-gate signal:** an EMP missing incident-command reference is
  `caution`.

---

## 2. Architecture context (as shipped)

```
   [ Operator request ]
            │
            ▼
 ┌──────────────────────┐
 │ Procedure Architect  │  ← byte-pinned system prompt (Epic 6 spec)
 │   .generate()        │     wrapped in Harness #17 hermetic envelope
 └──────────────────────┘
            │
            ▼  [ ProcedureDraft ]
 ┌──────────────────────┐
 │ audit_procedure_     │  ← deterministic regex pattern scan
 │   safety()           │     (S-DET-01 / ADR-006)
 └──────────────────────┘
   │                  │
   ▼ [hard_stop]      ▼ [approve / caution]
 [HMI hides Sign]   [HMI shows Sign button]
                       │
                       ▼
                 ┌────────────────┐
                 │ /architect/sign│  ← server-side re-audit
                 │                │     defence in depth
                 └────────────────┘
                       │
                       ▼  [if approve]
                 ┌────────────────┐
                 │ ForensicLedger │  ← HMAC-chained PROCEDURE_SIGNED
                 │   .append()    │     entry per ADR-011
                 └────────────────┘
```

Wire diagram matches the operational reality: the Architect authors,
the Safety Officer audits, and only the server-side gate writes to the
ledger. Two independent gates (HMI Sign-button render + server
re-audit) — same answer required.

---

## 3. Why the audit verdict is text-pattern (not LLM)

The audit gate every Architect draft crosses is intentionally
**deterministic** — pure-Python `re.search` against a per-template
required-terms list. An LLM-graded verdict was considered and
rejected for three reasons:

1. **ADR-006 alignment.** The reactive multi-agent fleet's verdicts
   are all deterministic before the LLM is consulted (the LLM emits
   the narrative, never the verdict). Pulling LLM grading into the
   Architect audit would break that doctrine.
2. **Cost + latency.** A pattern scan returns in microseconds; an
   LLM grade is hundreds of ms + cost. Audits run on every generate
   AND every sign — the cost stacks.
3. **Reproducibility.** A regex match is byte-stable. The same
   draft produces the same verdict on every audit, on every replay
   from the ledger, forever. An LLM grade drifts with model updates.

A scoped AST test (`test_audit_procedure_safety_imports_no_llm_modules`)
enforces this at the file level — any future PR that pulls
`complete_gemma` / `_llm_client` / OpenAI / Anthropic identifiers
into the `audit_procedure_safety` function body fails the test loudly.

---

## 4. Metadata enrichment (industry-notes follow-up)

The Architect request schema accepts an optional `metadata` dict
(typically `{pue, load_kw, criticality, battery_runtime_min, ...}`).
When supplied, the helper `_format_metadata_block` renders it as a
labelled `LIVE OPERATING METADATA` block inside the hermetic prompt
— sorted by key for byte-stable prompts across runs. The dict is
also persisted on the returned `ProcedureDraft` so the ledger entry
that signs the draft can audit which telemetry snapshot informed the
authoring.

HMI integration is left to the next iteration: the natural source is
a `GET /api/telemetry/latest` call on Generate-button click, threading
the snapshot into the POST body. Until that's wired, metadata is
operator-supplied via the HTTP API only (Phase 2 form has no field).

---

## 5. Future work (industry signals not yet implemented)

These come from the same industry-notes baseline and are queued for
later sprints:

- **Maker-Checker witness flow on MOP sign.** Industry practice for
  high-criticality MOPs is two signatures (the operator who drafts
  and the operator who validates). The repo already has
  `backend/witness_engine.py` from a prior sprint; integrating it on
  `/architect/sign` for `doc_type=MOP` is a one-route extension.
- **Auto re-prompt loop on hard_stop.** When the audit fires
  `hard_stop`, the HMI could surface a "Re-prompt with the missing
  terms" button that re-submits the request with the findings
  appended to the context. Closes the human-in-loop tighter.
- **Asset-context awareness.** When `asset_id` is set, the Architect
  could pull the asset's live telemetry + recent alarms + scheduled
  maintenance from CMMS and surface them in the metadata block.
  Biggest single quality jump for the LLM author.
- **Draft library + recall.** Approved drafts persist into a small
  named-template store so common procedures (UPS A battery PM) can
  be recalled instead of regenerated.
- **PDF export.** Operators sign on paper; the existing
  `backend/shift_report.py` shows the reportlab pattern.
- **Stale-verdict invalidation.** If the operator edits the textarea
  after a chip click, the displayed verdict from the previous
  Generate is stale. The HMI should clear the prior result on
  textarea edit, OR re-audit live (debounced).

---

## 6. Source standards (for future-PR grounding)

When updating the audit gate or the templates, cite these:

- **CSA Z462-24** — Workplace Electrical Safety (Canada).
- **NFPA 70E** — Electrical Safety in the Workplace (US equivalent).
  Either suffices for the MOP audit gate.
- **NEC 460.6** — Capacitor discharge requirements.
- **ASHRAE TC 9.9** — Environmental control for data centers
  (A1–A4 thermal envelopes; SOPs operate in the A2 band: 18–27 °C
  recommended, 10–35 °C allowable inlet).
- **Uptime Institute** — Operational Sustainability + Tier IV
  concurrent maintainability.
- **FEMA ICS** — Incident Command System; the EMP structure mirrors
  ICS roles (Incident Commander, Logistics, Communications).

---

*This document is updated only when the underlying industry
standards move. The implementation reality lives in the shipped code
— always read that first.*
