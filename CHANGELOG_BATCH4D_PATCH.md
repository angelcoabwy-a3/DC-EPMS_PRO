# CHANGELOG.md Patch for Batch 4.D + DC-EPMS-024 Closure

This file contains markdown sections to **paste into the existing
`CHANGELOG.md`** at the top of the `[Unreleased]` section (or under a
new `[v0.7.0-batch4]` heading if you want to tag).

The patch documents the complete Batch 4 deliverable (A+B+C+D) and
mitigates DC-EPMS-024 in the bug registry.

---

## SECTION 1 — Add to `[Unreleased]` or `[v0.7.0-batch4]`

```markdown
### Added

- **Batch 4.D** (commit `<SHA after apply>`): LOTO Auditor closure.
  - `backend/loto_auditor_repository.py` (267 lines): asyncpg-backed
    PostgreSQL persistence with idempotent INSERT ON CONFLICT save,
    AuditNotFoundError exception for explicit FastAPI 404 mapping,
    MockLotoAuditRepository for tests.
  - `backend/loto_auditor_report_renderer.py` (347 lines): pure-function
    markdown renderer producing per-pillar sections, citations table,
    provenance trace, ADR-006 PENDING APPROVAL banner. Output universal
    (HMI marked.js, email/Slack copy-paste, future PDF via pandoc V10).
  - `backend/loto_auditor_routes.py` (332 lines): FastAPI router with
    4 endpoints (POST /api/loto/audit, GET /api/loto/audit/{audit_id},
    GET /api/loto/audit/{audit_id}/markdown, GET /api/loto/audits/recent).
    Exports `register_loto_auditor()` for 1-line main.py wiring.
  - `backend/loto_auditor_agent.py` (PATCH +149 lines): final
    NotImplementedError stub (`_render_llm_summary`) replaced with full
    httpx implementation calling LM Studio gemma-4-e2b-it at
    `127.0.0.1:1234` with 8s timeout failsafe. Optional `cmms_service`
    constructor parameter enables Pillar 2 `_check_overlapping_maintenance`
    to query CMMS when injected (backwards-compat: defaults to None).
  - `tests/test_loto_auditor_e2e.py` (NEW, 7 integration tests):
    FastAPI TestClient + MockLotoAuditRepository + mock subsystems.
    Covers POST happy path, GET retrieval, 404 handling, malformed input
    (422), markdown endpoint with all 6 pillar sections rendered, pure
    markdown renderer test.

- **Batch 4.C** (commit `bb4a26b`): LOTO Auditor Pillars 4+5+6 implementation.
  - Pillar 4 (Witness Gate): LOTO Level classification per voltage/caps,
    requires_witness scan, witness_engine identity collision check.
  - Pillar 5 (Hybrid Sequential Order): step-phase classification,
    ELECTRICAL→HYDRAULIC→PURGE order verification, mandatory purge for
    cooling targets.
  - Pillar 6 (PPE Category): NFPA 70E §130 voltage matrix, procedure
    text parsing with roman numeral support, HARD_FAIL on under-PPE.
  - +14 unit tests (testall 405).

- **Batch 4.B** (commit `f0d373e`): LOTO Auditor Pillars 1+2+3 implementation.
  - Pillar 1 (Topology Impact Radius): site_model + GraphRAG cross-check.
  - Pillar 2 (2N Redundancy Survival): physics_engine pre/post-LOTO SHI.
  - Pillar 3 (Capacitor Discharge): NEC 460.6 60s wait + voltmeter check.
  - +18 unit tests (testall 391).

- **Batch 4.A** (commit `d4a5ac8`): LOTO Auditor skeleton + models + DB schema.
  - 437-line Pydantic models, 479-line agent skeleton with 6 pillar stubs,
    PostgreSQL migration `2026_05_W2_loto_audits.sql`, ADR-009.
  - +21 unit tests (testall 373).

### Changed

- `backend/loto_auditor_agent.py` constructor now accepts optional
  `cmms_service` parameter for Pillar 2 overlapping_maintenance check.
  All Batch 4.B/4.C tests remain GREEN with default None.

- `git config --local i18n.commitencoding utf-8` and
  `i18n.logoutputencoding utf-8` set on repo (DC-EPMS-024 mitigation).

### Fixed

- **DC-EPMS-024** (commit `<SHA after apply>`): mojibake in commit messages
  when `apply_batch*.ps1` orchestrators contained Unicode characters
  (e.g. "trifásico" appearing as "trifÃ¡sico" in commit bb4a26b).
  Mitigations applied:
  1. Phase 0 of `apply_batch4d.ps1` sets git's UTF-8 commitencoding.
  2. All future apply_batch*.ps1 commit messages are ASCII-only by policy.
  3. The historical mojibake in bb4a26b commit message persists (cosmetic
     only - the source code in that commit has correct encoding).
```

---

## SECTION 2 — Update Bug Registry table

Find the bug registry table (DC-EPMS-001 through DC-EPMS-023) and **add a
new row at the bottom**:

```markdown
| DC-EPMS-024 | LOW | MITIGATED in Batch 4.D | Mojibake "trifÃ¡sico" in commit message of bb4a26b due to PowerShell `Set-Content -Encoding UTF8` interacting with git's default Windows-1252 commit encoding. Code source had correct UTF-8 encoding throughout. Mitigation 1: `git config --local i18n.commitencoding utf-8` set during Batch 4.D Phase 0. Mitigation 2: ASCII-only commit messages mandated for all future `apply_batch*.ps1` orchestrators. Historical commit bb4a26b not amended (cosmetic only). |
```

---

## SECTION 3 — Add to Sprint Status section

Find the "Sprints Completed" or "Phase V9 Status" section and **add**:

```markdown
- **Batch 4 LOTO Auditor Agent** (CLOSED 2026-05-08):
  Full V9 Pillar 4 deliverable (Operational Rigor and Cyberphysical
  Isolation). Paranoid validator with 6-pillar audit pipeline:
  topology + 2N redundancy + capacitor discharge + witness gate +
  hybrid sequential order + PPE category. FastAPI endpoint, PostgreSQL
  persistence, markdown renderer, optional LM Studio LLM summary.
  60 tests across 4 sub-batches (4.A through 4.D). 7 ADRs total
  (added ADR-009).
```

---

## SECTION 4 — Tag recommendation (optional)

After applying Batch 4.D, you may want to tag the milestone:

```bash
git tag -a v0.7.0-batch4 -m "Batch 4 closure: LOTO Auditor fully operational"
```

This creates a clear marker that the V9 Pillar 4 deliverable is complete.
