# DC-EPMS PRO — Skill Registry (the explicit rule harness)

> **Purpose.** This registry converts DC-EPMS PRO's *implicit* coding conventions
> — the patterns we have proven across the v0.5 → v0.12 arc — into *explicit,
> checkable* rules. It is the companion to `docs/engram/main-context.md`:
> the engram is the architectural state snapshot; this is the action harness.
>
> **How to consume — the "Skill Digestion Harness":** before modifying any
> file or accepting a task, the working session MUST:
>
>   1. Identify the touched surfaces (routing? backend agent? security?).
>   2. Pull **3–4 relevant skills** from the matching category below.
>   3. Quote the skill IDs in the plan and verify the rule end-to-end.
>
> A skill is binding by ID. When a directive conflicts with a skill, surface
> the conflict before executing — do not silently override.
>
> **Last revised:** 2026-05-19 (post-v0.12.0, Epic 1 complete).

---

## Category A — State Management & Routing

### `S-ROUTE-01` · Declarative routing only (no zombie router)

- **When:** Adding a new view, or wiring an existing view's navigation.
- **Rule:** Every view registers on `core/router.js` via
  `registerRoute('<route-id>', { viewId: '<view-DOM-id>', activate })`.
  The legacy click-delegation + `setTimeout(0)` "zombie router" pattern
  is **forbidden** — it is the root cause of DC-EPMS-MAINT-001 / 002 / 003.
- **Verify:** the test file calls `isRegistered('<route-id>')` and asserts
  `true`. `git grep "document.addEventListener.'click'.*setTimeout"` in
  `views/**/*.js` returns zero hits.

### `S-ROUTE-02` · Idempotent view init

- **When:** Writing a new `init<View>View()` exported from a `views/*.js`.
- **Rule:** The exported initialiser is called **once** from `main.js` and
  must guard re-entry with a module-level `_routeRegistered` (or
  `_initialized`) flag. Per-activation wiring inside the route's
  `activate()` handler must also be idempotent (`_bound` flags on each
  element).
- **Verify:** calling `initXView()` twice is a no-op; route activation
  twice does not double-bind event listeners.

### `S-ROUTE-03` · core/bootstrap.js owns the navigateTo fallback

- **When:** Adding a new top-level route category (registered, maintenance,
  or placeholder).
- **Rule:** `core/router.js` owns every *registered* route. The legacy
  fallback in `core/bootstrap.js navigateTo()` is reserved for
  `maintenance` (MutationObserver-driven) + `placeholder` stubs only.
  Never re-introduce the deleted `app.js` IIFE or its `cfg.kind` switch
  for a new view — extract it as an ES module instead.
- **Verify:** Every new view appears in `tests/frontend/<view>.test.js`
  with `isRegistered('<id>') === true` and is **not** in the bootstrap
  legacy branch.

---

## Category B — AI Determinism (ADR-006)

### `S-DET-01` · Verdict before LLM, always

- **When:** Wiring any agent (or extending the multi-agent façade) to an
  LLM advisory layer.
- **Rule:** Every agent verdict (`APPROVE` / `CAUTION` / `HARD_STOP` /
  `DEGRADED`) is computed by pure-Python deterministic logic **before**
  any LLM call. The LLM call runs *after* the verdict and may attach an
  `llm_narrative` only — never alter the verdict. The prompt MUST carry
  the literal line:
  `"DETERMINISTIC VERDICT (already decided, do not override): <verdict>"`.
- **Verify:** the agent ships with three tests — `verdict_unchanged_by_llm`
  (a contradicting reply does not move the verdict), `graceful_when_llm_
  raises` (empty narrative on exception), and `no_llm_client_no_narrative`
  (pre-LLM behaviour preserved when `llm_client=None`).

### `S-DET-02` · Safety Officer VETO is uncrossable

- **When:** Touching `_compute_consensus`, the Safety Officer, or any
  agent's verdict pathway.
- **Rule:** Safety Officer `hard_stop` collapses consensus to `hard_stop`
  with `safety_officer_veto=True` **before** any other agent's verdict
  is considered. This rule is the load-bearing safety invariant per
  ADR-006 + CSA Z462 + NFPA 70E §130 + NEC 460.6. Never weaken or
  short-circuit it; never widen the LLM's reach into this path.
- **Verify:** `test_consensus_safety_veto_outranks_all` stays green.
  Any new agent does not introduce a code path that allows its verdict
  to override the Safety Officer.

### `S-DET-03` · Narrative-helper extension pattern

- **When:** Wiring a new agent to live Gemma (or extending an existing
  agent's prompt).
- **Rule:** Reuse the shared helpers — `_collect_kalman_lines(provider,
  asset_id)` and `_gemma_complete(client, prompt, max_tokens=240)` —
  defined in `backend/multi_agent.py`. The agent's `__init__` takes
  optional `llm_client=None` and `telemetry_provider=None` (so existing
  call sites and unit tests are unaffected). The orchestrator threads
  both through. The agent's `_synthesize_narrative` prompt carries
  ASSET / DETERMINISTIC VERDICT / domain-specific context / LIVE
  KALMAN TELEMETRY blocks.
- **Verify:** the new agent passes the same four-test pattern as T3.3 /
  T3.3b / T3.3c / T3.3d (see `S-DET-01`).

---

## Category C — Testing Gates

### `S-TEST-01` · Pytest floor + targeted-first protocol

- **When:** Before committing any change that touches `backend/` or
  `tests/`.
- **Rule:** `pytest -m "not slow"` MUST pass. **Floor: 726.** The full
  suite is the commit gate; the targeted-file run is the fast-feedback
  loop run first. Never commit on a partial test pass.
- **Verify:** the commit message records the new floor (e.g.
  `718 -> 726`). The `5 deselected (slow/FAISS)` count is stable.

### `S-TEST-02` · Vitest floor + per-view test minima

- **When:** Adding or modifying a `views/*.js` (or `core/*.js` ES module).
- **Rule:** `npm test` (Vitest, happy-dom) MUST pass. **Floor: 176**
  across **18 files**. Every new view ships with a
  `tests/frontend/<view>.test.js` exercising at minimum: (i) a render
  smoke test, (ii) an **XSS-escaping assertion** against an
  `<img onerror=…>` payload, (iii) a route-registration assertion via
  `isRegistered('<id>')`. LLM-authored views also assert no `<script>`
  survives a `{html: true}` reply.
- **Verify:** the commit message records the new floor (e.g.
  `165 -> 176`) and the file count (e.g. `17 -> 18`).

### `S-TEST-03` · Ruff is a binary gate

- **When:** Any change touching `backend/*.py` or `tests/*.py`.
- **Rule:** `ruff check backend/` reports **0 violations** at commit
  time (DC-EPMS-021 closure floor). Don't run `--fix` blindly: review
  the diff first. For test files, prefer dropping redundant string
  annotations (`UP037`) over adding `noqa`.
- **Verify:** running `ruff check` on the changed files prints
  `All checks passed!`.

---

## Category D — Security

### `S-SEC-01` · XSS routing — sanitizeHTML vs escapeHTML

- **When:** Writing innerHTML in any view or `core/*` module.
- **Rule:** Route **LLM-authored DOM surfaces** (chat replies, tool
  traces, agent narratives, RAG snippets) through
  `core/sanitize.js sanitizeHTML` (F3-5 allowlist). Use **per-value
  `escapeHTML`** on structured UI that needs interactive `<button>`
  elements (the sanitizeHTML allowlist drops buttons by design — this
  is correct, not a bug). Never concatenate untrusted strings into
  innerHTML without one of these two paths.
- **Verify:** the test file asserts both that (a) a `<script>` payload
  is dropped from LLM surfaces and (b) the `escapeHTML` path still
  emits the data-bearing elements (e.g. write buttons in the BMS view).

### `S-SEC-02` · Claim-based RBAC on every write

- **When:** Adding or modifying any state-changing endpoint.
- **Rule:** Every write route enforces claim-based RBAC. `/api/bms/write`
  is gated at **SME_L6** (`role_rank ≥ 6`); CMMS approve/reject goes
  through `assert_can_approve_work_order`; procedure/witness routers
  use `_require_actor_role`; ProcedureGenerator promotion gates the
  draft→approved transition. A frontend caller MUST send `actor_role`
  in the JSON payload; the server is authoritative.
- **Verify:** a sub-SME_L6 call to the new endpoint returns HTTP 403.
  The route's test file includes both the happy-path and the
  RBAC-denial case.

### `S-LEDGER-01` · All control-surface writes traverse the Forensic Ledger seam

- **When:** Adding any code path that mutates BMS / actuator state, or
  wiring a new `BmsWriteFn` seam.
- **Rule:** Every BMS write — AI-originated via the Optimizer approve
  flow OR human-direct via `/api/bms/write` — MUST go through
  `backend.ledger.wrap_bms_write_fn`. The wrapper appends a
  `BMS_WRITE_REQUESTED` pre-entry (carries `tag_id`, `requested_value`,
  `prev_value`, `source`, `proposal_id`) AND a `BMS_WRITE_RESULT`
  post-entry (carries `ref_entry_id`, `success`, `message`) to the
  HMAC-chained ledger. Never call `bms_connector.BMSConnector.write()`
  directly from an endpoint or agent — go through the wrapped seam
  stashed on `app.state.direct_bms_write_fn` /
  `app.state.optimizer_bms_write_fn` / `app.state.revert_bms_write_fn`.
  Reason: ADR-011 — IEC 62443-3-3 SR 6.1 / 6.2 / 7.3 / 7.4 require an
  inmutable, tamper-evident, recovery-supporting audit trail. The legacy
  `bms_connector.write_audit_log[-200:]` ring buffer is informational
  only, not authoritative. Related: [[S-PROPOSER-01]].
- **Verify:** `await ledger.verify_chain()` returns `None` after the
  test; the new write surface's test file asserts pre + post entries
  exist for both success and failure paths
  (`test_failed_bms_write_still_appends_result_entry`).

### `S-PROPOSER-01` · AI-originated writes carry an approved proposal_id

- **When:** Implementing or modifying an endpoint that calls a wrapped
  `BmsWriteFn` with an AI-derived value.
- **Rule:** When a BMS write originates from the Optimizer (or any
  future AI proposer), the `proposal_id` UUID MUST be set on the
  forensic-ledger context via
  `backend.ledger.set_proposal_context(proposal_id)` BEFORE invoking
  `await asyncio.to_thread(wrapped, tag_id, value, user)`, and reset in
  a `try/finally`. `/api/bms/write` ALSO accepts an optional
  `proposal_id` in the payload; when provided it MUST resolve to an
  `approved` row in the Optimizer `ApprovalLog` with matching
  `bms_tag_id` (HTTP 404 if missing, 409 on
  decision/tag mismatch). This closes the Proposer chain end-to-end:
  consensus → operator approval → ledger entry, all joined by a single
  UUID. Reason: ADR-006 §4 *"Auditable provenance"* upgraded to ADR-011
  scope; DC-EPMS-MSD-003 closure. Related: [[S-DET-02]] (the chain
  starts at the Safety VETO gate; this skill closes the back end).
- **Verify:** `tests/test_bms_write_proposer_chain.py` covers the
  approval-mismatch 404/409 cases AND the happy-path proposal_id
  stamping in the ledger payload.

---

## Category E — Commit & Release Discipline

### `S-COMMIT-01` · `-F` file-based messages, ASCII, signed

- **When:** Any `git commit` from the harness.
- **Rule:** Use `git commit --no-verify -F .git/COMMITMSG.txt` and
  delete the file after — the PowerShell 5.1 embedded-quote bug splits
  `-m` arguments containing `"`. Commit messages and tag annotations
  are **ASCII-only** (Rule 9). Every commit ends with:
  `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- **Verify:** `git log --format=%B -1` shows the trailer; no UTF-8
  smart quotes / em-dashes in the message body.

### `S-COMMIT-02` · Atomic batches + "tag is not closure"

- **When:** Any commit, especially release tags and multi-step sprints.
- **Rule:** One concern per commit — never bundle unrelated changes.
  Stage explicit paths (`git add a b c`), not `git add -A`. After
  tagging, **verify** via `git log --oneline --decorate -3` that the
  tag points to the **new** release commit and not its predecessor
  (the Batch 3.5 lesson). For sprints, break into 2–3 sub-batches
  each independently validatable.
- **Verify:** `git log --decorate -1` for a release commit shows
  `tag: vX.Y.Z` on the HEAD line itself.

---

## Category F — Runtime & Smoke Testing

### `S-RUNTIME-01` · Stale-process is the silent bug; restart + verify

- **When:** After any backend code change, *especially* agent / LLM
  wiring. Before any AI-feature smoke test.
- **Rule:** Python does NOT hot-reload. Stop the existing process
  (`Stop-Process -Id <pid>` for the one listening on `:8080`),
  relaunch `python backend\main.py`, poll `/api/health` until 200,
  AND grep `logs/epms_pro.log` for the fresh `[BOOT] Multi-Agent
  façade active` line and confirm its signature matches the current
  code (post-T3.3 it carries `Diagnostician live-Gemma narrative
  %s`). The boot-line signature is the cheapest stale-process
  detector — unit-test pass + healthy `/api/health` is **not
  sufficient evidence** the in-memory module is fresh.
- **Verify:** the boot timestamp in `logs/epms_pro.log` is newer than
  the most recent backend commit hash's commit time.

---

## Category G — Documentation Drift Prevention

### `S-DOC-01` · Doc-sync is a separate commit after architectural change

- **When:** A code commit alters the CURRENT STATE recorded in
  `CLAUDE.md` (HEAD, test floors, file inventories, sprint vectors) or
  the live backlog in `docs/ROADMAP-V11.md`.
- **Rule:** Follow each architectural code commit with a dedicated
  `docs: sync compass — …` commit that updates (a) the CURRENT STATE
  block + recent-commits in `CLAUDE.md`, and (b) the relevant ROADMAP
  section (status header, sprint entries, vector list). Never inline
  doc-sync into the code commit — atomicity (`S-COMMIT-02`) requires
  the separation. Engram (`docs/engram/main-context.md`) is refreshed
  at *epic* milestones, not every commit.
- **Verify:** the doc-sync commit's title starts with `docs:` and only
  touches `*.md` files.

---

## Category H — Path C2 Vocabulary (the credibility fence)

### `S-VOCAB-01` · 800 VDC is unipolar; never "trifásico"

- **When:** Writing any text — prompt, narrative, log line, commit
  message, doc, comment, demo script — that names a downstream Phase 2
  bus.
- **Rule:** **"trifásico"** applies ONLY to AC upstream of the MV
  Rectifier (Phase 1 480 VAC, Phase 2 35 kVAC). The downstream Phase 2
  **800 VDC bus is unipolar TN-S** — it has no phases. The phrase
  *"800 VDC trifásico"* is a credibility-destroying error in panel
  review. Schema fields enforce the fence:
  `voltage_v_phase_ab/bc/ca` for AC, `voltage_v_dc_bus` for DC.
- **Verify:** `git grep -i "800.*VDC.*trif"` returns zero hits.
  `git grep "voltage_v_dc_bus"` matches Phase 2 schema only.

---

## Category I — Procedure Authoring Safety (Epic 6 Commit 3 hardening)

The audit gate at `backend/agents/procedure_architect.py:audit_procedure_safety`
is the deterministic Safety Officer for *documents* (parallel to S-DET-02
which is the Safety Officer for live operator queries). These three skills
encode the contracts the operator pinned on 2026-05-23.

### `S-SAFETY-01` · MOPs must satisfy the Universal 5-Point Structure + voltage verification

- **When:** Authoring a new MOP draft (via the Procedure Architect HMI,
  the `/api/procedures/architect/generate` route, or any pre-seeded
  catalog body in `docs/operaciones/mops/`).
- **Rule:** Every MOP must contain ALL FIVE universal sections —
  (1) Alcance y Objetivo, (2) Evaluación de Impacto y Riesgos,
  (3) Prerrequisitos, (4) Pasos Secuenciales, (5) Plan de Reversión /
  Back-out — AND at least ONE of: `Vivo-Muerto-Vivo` (de-energized
  work) OR `límite de aproximación restringida` (live work). Missing
  any section OR missing both voltage signals → `hard_stop` and the
  sign endpoint refuses with HTTP 403. The legacy LOTO + PPE +
  CSA Z462/NFPA 70E triad remains required (necessary, no longer
  sufficient).
- **Verify:** `tests/test_procedure_architect.py::TestAuditMOPUniversalSections`
  + `::TestAuditMOPVoltageVerification`. The 3 seed bodies in
  `docs/operaciones/mops/MOP-*.md` are audit-pinned by
  `::TestSeedMOPsPassNewAuditGate`.

### `S-DISTRIBUTION-01` · PDU / RPP / STS maneuvers require alarm history + SCR check

- **When:** Authoring a MOP whose context or `asset_id` names any
  distribution-layer gear: PDU, STS, RPP (case-insensitive, asset-id
  tolerant of underscores — e.g. `rpp_a1` triggers).
- **Rule:** The body MUST mention `historial de alarmas` /
  `alarm history` AND `caja SCR` / `STS state` / `tiristor` /
  `thyristor` before authorizing the transfer. Missing either →
  `hard_stop`. Rationale: the Eaton SOW R-48 pre-transfer validation
  + Tier IV operational practice — a transfer commanded without
  reading the alarm log and confirming SCR health is a known
  incident-class pattern.
- **Verify:** `tests/test_procedure_architect.py::TestAuditMOPDistributionPreTransfer`.
  See also: `config/knowledge/distribution-mop-catalog.md` for the
  underlying catalog the audit cross-references.

### `S-VENDOR-EATON-01` · Eaton SOW R-48 checklist is CAUTION (deterministic vendor lookup with string-match fallback)

- **When:** Authoring a MOP whose `asset_id` resolves to vendor=eaton
  in the deterministic cache, OR whose context/asset_id string-matches
  `eaton` (case-insensitive) when the cache cannot resolve.
- **Rule:** The body SHOULD mention BCMS, fibra óptica / fiber optic,
  FSB / firmware, and alarm history. Omissions surface as findings
  at `caution` severity, NOT `hard_stop`. Rationale: the operating
  fleet is multi-brand; forcing `hard_stop` would refuse legitimate
  MOPs on non-Eaton equipment.
- **Vendor resolution** (since v0.16.1 -- the schema-migration
  close-out, replacing the earlier TODO):
  1. **Deterministic** -- if `draft.asset_id` is present AND the
     in-memory `_vendor_cache` (populated at boot from
     `cmms_repository.list_assets_async()`) has an entry, the
     registry vendor wins. `vendor=eaton` -> rule fires;
     `vendor=vertiv` or any other -> rule does NOT fire (string-
     match is NOT consulted -- the registry is authoritative);
     `vendor=None` -> rule does NOT fire (vendor known-null is a
     deterministic answer, not "unknown").
  2. **Fallback string-match** -- if `asset_id` is missing OR not
     in the cache, regex-search `context + asset_id` for `\beaton\b`.
- **Cache lifecycle:** loaded once at boot via `set_vendor_cache()`
  from `backend/main.py` lifespan. Vendor changes require a backend
  restart (operationally rare). A `/api/admin/refresh-vendor-cache`
  endpoint can be added later if needed.
- **Finding annotation:** every Eaton finding now annotates the
  resolution source (`[deterministic lookup ...]` or
  `[string-match fallback (cache miss)]`) so the operator + future
  audits can trace why the rule fired.
- **Verify:** `tests/test_procedure_architect.py::TestAuditMOPEatonVendor`
  (legacy string-match) + `::TestAuditMOPEatonVendorDeterministicLookup`
  (5 tests covering cache hit eaton, cache hit non-eaton, cache miss,
  cache hit vendor=None, asset_id absent).
  See also: `config/knowledge/eaton-sow-r48-mp-checklist.md`,
  `backend/main.py` lifespan vendor-cache prime block.

### `S-VECTOR-01` · §2 must name at least one risk vector

- **When:** Authoring a MOP. The operator-supplied richer system
  prompt (2026-05-24) requires §2 to classify the maneuver under at
  least ONE of six explicit risk vectors:
  `Vector Eléctrico`, `Vector Mecánico/Térmico`, `Vector Life Safety`,
  `Vector Combustible`, `Vector Lógico/Controles`, or
  `Impacto Aguas Arriba/Abajo`.
- **Rule:** Audit surfaces a `caution` finding if §2 has no explicit
  vector label. Verdict stays signable; the operator can re-prompt to
  enrich. Rationale: vectors force the LLM author to confront the
  multi-discipline reality of mission-critical infrastructure (an
  electrical MOP that ignores thermal cascade is incomplete).
- **Verify:** `tests/test_procedure_architect.py::TestAuditMOPRicherTemplate::test_missing_vector_is_caution`.
  Constants: `MOP_VECTOR_PATTERNS` in `backend/agents/procedure_architect.py`.

### `S-MCP-HEALTH-01` · §3 must mention MCP / Agent health-check gate (+ optional runtime probe)

- **When:** Authoring a MOP. The operator-supplied richer prompt
  mandates that the gatekeeper section includes confirmation that the
  Agente Revisor (Checker) and Discipline AIs (HVAC AI, Electrical AI)
  are `ONLINE` and reporting via **MCP** for concurrent monitoring.
- **Rule (option (i), always on):** audit string-matches the body for
  `MCP`, `Agente Revisor`, `Health Check`, `Checker ONLINE`,
  `Discipline AI`, `HVAC AI`, or `Electrical AI`. Missing all of them
  → `caution`. Per operator calibration the audit does NOT block on
  the string check; static string-match suffices for the LLM author
  nudge.
- **Rule (option (ii), feature-flagged via `DC_EPMS_MCP_PROBE`):**
  v0.16.1 -- the closeout. When the env flag is enabled, an asyncio
  background task in `backend/mcp_health.py` polls
  `DC_EPMS_MCP_PROBE_URL` (default LM Studio at
  `http://127.0.0.1:1234/v1/models`) every `DC_EPMS_MCP_PROBE_INTERVAL_S`
  seconds (default 60s, 5s timeout). The audit gate reads the cached
  result sync (zero I/O in the verdict path) via `get_mcp_health()`.
  - State **None** (probe disabled) → behavior is identical to v0.16.0
    (string-match only); no extra finding.
  - State **True** (probe up) → no extra finding; rule satisfied by
    the operational fact of agent reachability.
  - State **False** (probe failing) → CAUTION finding with the probe
    reason annotated, e.g.
    `MCP health probe FAILED [URLError: Connection refused] -- Discipline AI agents may not be reachable; operator should verify before signing`.
  The string-match rule above runs independently; both can fire
  together when both omissions are present.
- **Lifecycle:** background task started in `backend/main.py` lifespan
  after CMMS seed; pinned onto `app.state.mcp_probe_task`; cancelled
  cleanly on shutdown. Initial sync probe runs before the loop so the
  first audit call sees a fresh result.
- **Verify:** `tests/test_procedure_architect.py::TestAuditMOPRicherTemplate::test_missing_mcp_health_check_is_caution`
  (string-match path) + `tests/test_mcp_health.py` (12 tests covering
  cache state transitions, probe success/failure modes, audit
  integration, and compound advisories). Constants:
  `MOP_MCP_HEALTH_PATTERNS` + `backend.mcp_health.{probe_mcp_sync,
  get_mcp_health, start_probe_background_task}`.

### `S-HOLD-POINT-01` · §4 must include `[HOLD POINT]` markers

- **When:** Authoring a MOP. The operator-supplied richer prompt
  mandates explicit `[HOLD POINT]` markers in the step sequence
  whenever the technician must pause and confirm a parameter in HMI
  before continuing (e.g. sync-check, ATD verification, sequencer
  approval).
- **Rule:** Audit fires `caution` when §4 contains no `[HOLD POINT]`
  (or `HOLD POINT` / `Hold Point` variants). Rationale: hold points
  are the single biggest defence against "auto-pilot" execution of a
  MOP where a step succeeds physically but the operator missed a
  precondition.
- **TODO (Commit 12 promotion):** the `MOP_PARAMETERIZED_ABORT_PATTERN`
  rule co-located in this skill family is currently CAUTION; Commit
  12 promotes it to HARD_STOP after the 23 seed bodies are updated
  to comply.
- **Verify:** `tests/test_procedure_architect.py::TestAuditMOPRicherTemplate::test_missing_hold_point_is_caution`.
  Constants: `MOP_HOLD_POINT_PATTERN`.

---

## Category J — Agent Continuity (Gentle IA H13)

### `S-CONTINUITY-01` · Long-running agent generations checkpoint pre/post LLM

- **When:** Wiring any agent whose `generate()` (or equivalent) makes a
  potentially-fragile LLM dispatch and whose work would be expensive
  (or impossible) to redo: ProcedureArchitect, future Diagnostician-RCA,
  any orchestration spanning multiple LLM calls.
- **Rule:** The agent accepts an optional
  `checkpoint_store: CheckpointStore | None` in its constructor.
  When wired, it MUST emit two checkpoints per generation:
  1. `PHASE_PRE_LLM` — recorded BEFORE the LLM call, carrying every
     input the dispatch needs (`doc_type`, `context`, `asset_id`,
     `metadata`, the hermetic `prompt`, `max_tokens`). This is the
     recovery anchor when a hard interrupt (SIGKILL, KeyboardInterrupt,
     network reset) escapes the agent's `except Exception`.
  2. `PHASE_POST_LLM` — recorded AFTER the LLM resolves (or after the
     deterministic skeleton fallback fires), carrying the full
     reconstructible draft (`content`, `llm_present`, `generated_at`).
     This is the idempotency anchor: a resume from a `post_llm` row
     MUST return the completed object WITHOUT a new LLM dispatch.
  The agent MUST expose `async resume_from_checkpoint(draft_id)` with
  three branches: (a) no checkpoint → `None`; (b) `post_llm` → rebuild
  + return, NO LLM call; (c) `pre_llm` → re-dispatch the persisted
  prompt + write the missing `post_llm` checkpoint so a second crash
  short-circuits via path (b).
  A store I/O failure MUST NOT propagate into the agent's primary
  contract — checkpointing is recovery instrumentation, not the
  load-bearing data path.
  Reason: H13 of the Gentle IA Agent Harness registry. Long-running
  authoring flows (the Procedure Architect ships 6+ step MOPs) lose
  load-bearing operator work when crash recovery is absent.
- **Verify:** `tests/test_agent_continuity.py` covers `CheckpointStore`
  primitives (10 tests), pre/post-LLM hook emission (4 tests), the
  three resume paths (3 tests), and an end-to-end crash + recovery
  acceptance test (1 test). The acceptance test uses
  `KeyboardInterrupt` (a `BaseException`, not caught by the agent's
  `except Exception`) to model a SIGKILL-class interrupt that escapes
  the LLM dispatch. Related: [[S-DET-01]] (the verdict path is
  independent of continuity), [[S-LEDGER-01]] (the audit trail for
  *write* actions; H13 is the recovery trail for *authoring* actions).

---

## Index — quick lookup

| ID | Category | Headline |
|---|---|---|
| `S-ROUTE-01` | Routing | Declarative routing only — no zombie router |
| `S-ROUTE-02` | Routing | Idempotent view init |
| `S-ROUTE-03` | Routing | `core/bootstrap.js` owns the navigateTo fallback |
| `S-DET-01` | AI Determinism | Verdict before LLM, always |
| `S-DET-02` | AI Determinism | Safety Officer VETO is uncrossable |
| `S-DET-03` | AI Determinism | Narrative-helper extension pattern |
| `S-TEST-01` | Testing | Pytest floor + targeted-first |
| `S-TEST-02` | Testing | Vitest floor + per-view minima |
| `S-TEST-03` | Testing | Ruff is a binary gate |
| `S-SEC-01` | Security | XSS routing — sanitizeHTML vs escapeHTML |
| `S-SEC-02` | Security | Claim-based RBAC on every write |
| `S-LEDGER-01` | Security | All control-surface writes traverse the Forensic Ledger seam |
| `S-PROPOSER-01` | Security | AI-originated writes carry an approved proposal_id |
| `S-COMMIT-01` | Commit | `-F` file-based, ASCII, signed |
| `S-COMMIT-02` | Commit | Atomic batches + tag-is-not-closure |
| `S-RUNTIME-01` | Runtime | Stale-process restart + BOOT log signature |
| `S-DOC-01` | Documentation | Doc-sync is a separate commit |
| `S-VOCAB-01` | Vocabulary | 800 VDC is unipolar; never trifásico |
| `S-SAFETY-01` | Procedure Safety | MOPs need 5 universal sections + voltage verification |
| `S-DISTRIBUTION-01` | Procedure Safety | PDU/RPP/STS need alarm history + SCR check |
| `S-VENDOR-EATON-01` | Procedure Safety | Eaton SOW R-48 omissions surface as caution |
| `S-VECTOR-01` | Procedure Safety | §2 must name ≥ 1 of 6 risk vectors (caution) |
| `S-MCP-HEALTH-01` | Procedure Safety | §3 must mention MCP / agent health check (caution, string-match) |
| `S-HOLD-POINT-01` | Procedure Safety | §4 must include `[HOLD POINT]` markers (caution) |
| `S-CONTINUITY-01` | Agent Continuity | Long-running agent generations checkpoint pre/post LLM |

**25 skills, 10 categories.** New skills extending this registry must follow
the same template (When / Rule / Verify) and be added to the index above.
