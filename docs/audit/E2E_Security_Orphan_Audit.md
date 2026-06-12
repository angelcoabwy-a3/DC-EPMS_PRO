# E2E Security, RBAC & Dead-Code Audit

- **Type**: read-only static audit. No source files were modified (this report is the only new file).
- **Date**: 2026-05-17. **Scope**: post G1-G6 ProcedureGenerator sprint.
- **Method**: cross-referenced `frontend/*.html` against `frontend/assets/**/*.js`;
  enumerated FastAPI route decorators across `backend/`; pattern-scanned for orphans,
  `innerHTML` sinks and credential literals. `vulture` is **not installed** in the venv,
  so backend dead-code detection is grep + import-graph reasoning, not a full pass.

## Closure status (2026-05-24 v0.17.0 cycle)

| Finding | Status | Closure |
|---|---|---|
| **CRITICAL × 3** (F3-1 / F3-2 / F3-3 RBAC gaps) | ✅ CLOSED | `b34efb1` (2026-05-17) |
| **F1-1** Riva ASR ghost button | ✅ CLOSED | v0.17.0 cycle -- button `hidden` with HTML comment + `data-feature-pending="riva-asr"` marker; handlers already null-safe |
| **F3-6** dev DB password literal | ✅ CLOSED | v0.17.0 cycle -- `docker-compose.yml` header expanded with explicit DEV-ONLY CREDENTIAL POLICY block + override mechanism documented (env vars OR `.env` file) |
| **F2-3** `write_procedure_yaml` orphan | 🟡 DEFER | Acceptable per audit ("intentional for now, production-orphan until draft store lands"). Tracked in V11 roadmap (draft persistence) |
| **F3-4** RBAC coverage of remaining mutating endpoints | ✅ CLOSED | `d3e333e` (2026-05-17) claim-based RBAC gates across 14 mutating endpoints; superseded in depth by Epic 10 (2026-06): `5a8252e` JWT IAM core (4 roles), `a68381e` Maker-Checker dual-JWT on procedure sign, `58f648a` frontend auth gate + API middleware |
| **F3-5** 73 `.innerHTML =` sinks | ✅ CLOSED | `5ed2409` shared `core/sanitize.js` (allowlist sanitizer for LLM-authored payloads) + `81a8909` shared `escapeHTML` consolidation; discipline codified as skill `S-SEC-01` (sanitizeHTML for LLM surfaces, escapeHTML for interpolated data) with per-view XSS vitest coverage |
| **CLEANUP × 6** | (per individual finding) | mostly handled in `d495c7b` dead-code eradication |

DEFERRED items are NOT regressions — they are explicit scope decisions
documented for traceability.

**WARNING-tier triage closed 2026-06-12 (MVP S4 bug closeout):** of the
4 original WARNINGs, F1-1 / F3-6 / F3-4 / F3-5 are CLOSED with the
commit evidence above. The single remaining open item is **F2-3**
(intentional production-orphan until a procedure draft store lands —
post-MVP scope).

## Severity legend

- **[CRITICAL]** — security exposure or a defect that breaks a contract. Fix before any non-local deploy.
- **[WARNING]** — real risk / debt that should be scheduled.
- **[CLEANUP]** — dead weight; safe to delete, no functional impact.

## Summary matrix

| Phase | [CRITICAL] | [WARNING] | [CLEANUP] |
|---|:--:|:--:|:--:|
| 1 - Frontend dead-ends | 0 | 1 | 3 |
| 2 - Backend orphans | 0 | 1 | 3 |
| 3 - Security & RBAC | 3 | 2 | 0 |
| **Total** | **3** | **4** | **6** |

---

## PHASE 1 - Frontend dead-end analysis

| ID | Severity | Finding |
|---|---|---|
| F1-1 | [WARNING] | **`agent-voice` button - ghost listener candidate.** `index.html:327` renders a "Voice (Riva ASR)" button; `app.js:52` exposes a DOM accessor `agentVoice: () => $('agent-voice')` but Riva ASR is not an integrated dependency anywhere in the backend. The accessor exists; a functional click->ASR path is unconfirmed and almost certainly absent. Verify the binding or hide the button until Riva lands. |
| F1-2 | [CLEANUP] | **`frontend/site_topology_view.html`** is a standalone HTML file referenced **only** by `SPRINT_S1B_INTEGRATION.txt` (a doc). `index.html` is the SPA entry; this second HTML is not loaded by any route or script. Orphan file. |
| F1-3 | [CLEANUP] | **`frontend/assets/archive/app.js.legacy`** - an archived pre-pivot copy of `app.js` (carries the same `agentVoice` / `btn-mop-generate` code). Dead, shipped in the asset tree. |
| F1-4 | [CLEANUP] | **Orphaned JS functions - not exhaustively scanned.** A 100% "defined but never invoked" sweep of `frontend/assets/js/**` was not run (no JS dead-code linter wired). Recommend adding one (e.g. `eslint` `no-unused-vars` + `knip`) to CI-local. |

**Buttons - coverage note.** 70 `<button>` elements were enumerated in `index.html`. The
view-scoped buttons (`m-*`, `ta-*`, `ma-*`, `rack-heatmap-*`, `cam-*`, `sld-*`,
`topo-graph-*`, `st-*`, `m-procgen-*`) follow a consistent per-view `initXView()` binding
pattern and the G6 `m-procgen-*` set was verified wired (`_wireProcgen`). A button-by-button
100% cross-reference is **not** claimed here - `agent-voice` (F1-1) is the one concrete
suspect surfaced; a dedicated linter is the right tool for full coverage.

## PHASE 2 - Backend orphan sweep

| ID | Severity | Finding |
|---|---|---|
| F2-1 | [CLEANUP] | **`backend/dpo_edge_healing.py` (352 LOC) - confirmed orphan.** No `import` of it anywhere; the only references are string/comment mentions in `cmms_mcp.py` and `cyber_physical_tools.py`. Already documented (CLAUDE.md, ADR-007) as a V11 candidate. Either integrate or move to an `_orphan/` holding area. |
| F2-2 | [CLEANUP] | **`backend/cmms_mcp.py.design-artifact`** - a stale design-draft of `cmms_mcp.py` living in the import path's directory. Not a `.py`, never executed. Delete. |
| F2-3 | [WARNING] | **`procedure_generator.write_procedure_yaml` has no production caller.** Defined at `procedure_generator.py:868`; the only caller is `tests/test_procedure_generator.py`. The `/api/procedures/generate` route returns the dict and never persists it. Intentional for now (no draft store - C0/G5), but it is a production-orphan until a draft store lands. |
| F2-4 | [CLEANUP] | **Backend dead-code not fully swept.** `vulture` is absent from the venv; install it (`pip install vulture`, it is in the project's own Vision Deck #7 "CodeAuditor") and run `vulture backend/` for a complete unused-def/class list. |

**Stale models/enums.** No conclusively-dead Pydantic model or Enum was found - the G1-G6
additions (`AssetLevel`, `RedundancyTier`, `ProcedureClass`, the Arc-Flash `Asset` fields)
are all consumed. One item to watch: `cmms_models.PROCEDURE_CLASSES` still lists `DMOP`,
correctly kept (load-bearing - see DC-EPMS reconciliation), so not flagged.

## PHASE 3 - Security & RBAC penetration audit

### 3a. RBAC coverage of state-mutating endpoints

**Headline:** of ~26 state-mutating endpoints (`POST` / `PUT` / `DELETE` / `PATCH`),
**exactly one enforces a role check** - `POST /api/procedures/{id}/activate`
(`procedure_routes.py`, the G5 403 gate). Every other mutating endpoint is **un-authorized**.

Context (not an excuse, a fact for triage): the platform has **no authentication layer**
at all - no login, session, or token. So strictly, *no* endpoint is authenticated. RBAC
*authorization* exists only as the pure `cmms_models` gate functions, wired into the single
endpoint above. This is a known single-laptop-demo posture - but the audit must flag it.

| ID | Severity | Finding |
|---|---|---|
| F3-1 | [CRITICAL] | **`cmms_routes` approve/reject - "security-theatre" `actor_role`.** `ApproveRejectRequest` carries an `actor_role` field, but `approve_wo` / `reject_wo` (`cmms_routes.py:344-389`) **never read it** - they call `transition_status_async(wo_id, "approved", body.cet_id)` with no role check. `cmms_models.assert_can_approve_work_order` exists and is **never called**. A field that looks like an RBAC gate but is inert is worse than none - it misleads reviewers. Either wire the gate or remove the field. |
| F3-2 | [CRITICAL] | **`POST /api/bms/write` is fully open.** `main.py:2049` actuates the building-management write surface with no auth and no role check - the highest-blast-radius unprotected endpoint. |
| F3-3 | [CRITICAL] | **Procedure-execution + witness endpoints un-authorized.** `_proc_router` `{id}/start`, `/executions/{id}/advance`, `/executions/{id}/abort` and `_witness_router` `{id}/sign`, `{id}/reject` (`main.py:2275-2368`) gate on a free-text `operator` / `witness` string only. The witness routes do enforce *identity collision* (initiator != witness) but **not role** - anyone can sign. An ARMED-state procedure can be advanced by an unauthenticated caller. |
| F3-4 | [WARNING] | **Remaining mutating endpoints un-authorized** (acceptable for the demo, must change for prod): `cmms` `/work-orders` create + `/trigger-maintenance` + `PATCH /assets/{id}`; `loto_auditor` `/audit`; `agent_copilot` `/draft/{id}/approve|reject`; `main.py` `/api/incidents`, `/api/scenarios/{id}/run`, `/api/topology/whatif`, `/api/mops/generate`; `tech_assist` `/ingest-pdf`, `DELETE /documents/{id}`, `/closure/{wo}/dictate` (the last auto-creates follow-up WOs). Recommend an auth dependency + the RBAC gate applied router-wide. |

### 3b. XSS / DOM injection

| ID | Severity | Finding |
|---|---|---|
| F3-5 | [WARNING] | **73 `.innerHTML =` sinks** across 10 JS files (heaviest: `tech_assist.js` 28, `maintenance.js` 18). The views ship `_escape()` helpers and use them for interpolated data (verified on sampled paths incl. the G6 `_renderProcedureSteps`). Practical risk is **moderate, not low**: most data is backend-controlled (simulator/CMMS), but the agent-chat and tech-assist-troubleshoot panels render **LLM-generated** text via `innerHTML` - a model can emit markup. Recommend a systematic pass and a shared sanitiser for LLM output. No confirmed live XSS was found in the sample. |

### 3c. Hardcoded secrets

| ID | Severity | Finding |
|---|---|---|
| F3-6 | [WARNING] | **No secrets in `backend/*.py`** (literal-assignment scan clean). However the dev DB password `epms_dev_only_change_me` is committed in `docker-compose.yml`, `CLAUDE.md` and `scripts/_demo/README.md`. It is explicitly dev-only and the real credentials live in gitignored `config/.env` (per DC-EPMS-DB-001) - but a literal DB password in tracked files (its own value says "change_me") must be rotated and externalised before any non-local deployment. No JWT/API-key literals were found. |

---

## Recommended remediation order (when fixes are authorised)

1. **F3-1 / F3-2 / F3-3** - the un-authorized mutating endpoints. Either an auth
   dependency mounted router-wide, or at minimum wire `assert_can_approve_work_order`
   into `cmms` approve/reject and a role check onto `/api/bms/write` and the procedure
   execution routes. Until then, treat the platform as trusted-LAN-only.
2. **F3-5** - a shared output sanitiser for the LLM-rendering panels.
3. **F3-6** - externalise + rotate the dev DB password.
4. **F2-1 / F2-2 / F1-2 / F1-3** - delete or relocate the orphan files.
5. **F1-1 / F2-3** - resolve the ghost button and the unused writer (wire or remove).
6. Install `vulture` + a JS dead-code linter to make F1-4 / F2-4 continuously enforced.

**Nothing in this audit was fixed** - read-only, as directed. Await an explicit GO per item.
