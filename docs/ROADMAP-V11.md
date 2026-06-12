# DC-EPMS PRO — Roadmap V11

- **Status**: v11.20 (2026-06-12) — **EPIC 5 CLOSED (E5.A-E5.G)** · MVP S3 + S4 Epic-5 scope satisfied · next = S4 bug closeout (T1.6, DC-EPMS-029c, DC-EPMS-TEST-01, E2E WARNING triage)
- **Decision-maker**: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
- **Locked**: 2026-05-10 · **Synced**: 2026-06-12 (v11.20)
- **v11.20 sync (2026-06-12) — EPIC 5 CLOSED.** Reality-check finding:
  Epic 5 Sprints 1+2 AND E5.E were already on master since 2026-05-23
  (`0aa9e6b3` Sprint 1 heartbeat + per-agent voting, `5b55111`
  Sprint 2 history sidebar + forensic trail + preview UI, `c1d334a`
  E5.E sandbox preview backend) — they predate the v11.18 MVP plan,
  whose S3/S4 windows assumed them pending. This session delivered
  the only missing pieces, Sprint 3's E5.F + E5.G, found in-flight
  in the working tree and completed with their test artifacts:
  `3269ae9` — E5.F read-only OptimizerConfig inspector
  (`config_snapshot()` + `GET /api/optimizer/config`, 503 on
  default-OFF; collapsed "Config & Bounds" panel, human-readable
  units) + E5.G client-side rejection analytics (word/tag clustering
  over the E5.B feed, 10-rejection gate, S-SEC-01 escaping of
  operator-authored reasons). Floors: pytest 1414 -> 1416, vitest
  513 -> 523 (31 files), ruff clean. Live smoke per S-RUNTIME-01:
  fresh boot verified (components=113), `/api/optimizer/config`
  returns 503 with the Optimizer default-OFF; the 200-enabled
  posture is covered by TestClient with the service wired. The MVP
  sequence is now ~3 weeks ahead of plan: S4's remaining scope is
  the bug closeout only.
- **v11.19 sync (2026-06-11) — MVP S2 BACKEND GROUNDING DELIVERED**,
  same session as S1 and ahead of the jun 18-24 window (operator
  visual acceptance of S1 received first: "ok lo veo bien").
  `3c0a2a3` S2-A: gen_farm_d / mv_bus_d / stepup_xfmr_d join the
  site_model graph (Path D standby generation, 110 -> 113 components,
  registry graph ids real). `92f3fd9` S2-B: Phase 2 DESIGN-sim
  telemetry — 6 generator types incl. the schema-fenced
  `voltage_v_dc_bus`, metadata-keyed utility intakes (27.5/35 kV),
  dead-bus standby farm aggregates, `dc_bus_sag` anomaly, Kalman
  calibration for 9 metrics; live wire 238 -> 281 channels.
  `66288d4` S2-C: What-If DAG + N-1 Shadow over Building D (farm
  auto-run on utility-D loss; sscb_d/dc_bus_d critical, util_d
  warning-degraded; hall_d is N-1 load). `63bb9f0` live SSE smoke
  tool, PASS against a fresh boot (S-RUNTIME-01). Floors: pytest
  1409 -> 1414, vitest 500 -> 513 (31 files). Deferred honestly:
  proto-adapter v1 classification of the new metrics (Epic 8
  follow-up); per-unit farm telemetry (post-MVP).
- **Supersedes**: ad-hoc "what's next" decisions across the v0.10.x arc; and the
  2026-05-10 lock of this file's own status fields
- **v11.18 sync (2026-06-11) — THE MVP CUT.** Operator approved the full
  re-engineering evaluation + MVP-final plan in one blanket GO
  ("aprobamos todo"). Two parts:

  **(1) SLD Reengineering delivered same session (Batches A-C):**
  the third "green tests != operator sees it" failure was diagnosed
  as structural — `#view-power` booted into the 2.5D iso stage
  (Phase-1-only, zero Phase 2 / 50 MW content) while every Diagram
  Rebuild feature lived on the hidden flat SLD. `345e098` retired the
  iso stage + camera (-851 LOC; flat SLD = the ONE Power surface;
  live Kalman severity retargeted onto it; SLD-R1 default-surface
  regression fence). `cf0c331` farm level-of-detail (LOD 0 honest
  lineup block; LOD 1 viewBox-focused per-unit switchgear cubicles
  with NFPA 110 state strips; `farmUnits()` single source).
  `a6eecd1` codified `S-VISUAL-01` (visual closure on the DEFAULT
  rendered surface) + default-first preview tool. vitest 490 -> 500
  (31 files).

  **(2) MVP FINAL — approved sequence (panel: early August 2026):**

  ```
  S1  jun 11-17   SLD Reengineering A-C  [DELIVERED 2026-06-11]
  S2  jun 18-24   Bloque 3 backend grounding: farm + mv_bus_d +
                  stepup_d into site_model graph; Phase 2 design-sim
                  telemetry channels (labeled DESIGN); power_grid DAG
                  + n1Power extended to Building D
  S3  jun 25-jul 1  Epic 5 Sprints 1+2 (E5.A heartbeat, E5.C 6-agent
                  breakdown, E5.B approval sidebar, E5.D forensic
                  trail link) ~21 h  [ALREADY ON MASTER 2026-05-23]
  S4  jul 2-8     Epic 5 Sprint 3 (E5.F config, E5.G analytics,
                  E5.E What-If preview) + bug closeout: T1.6,
                  DC-EPMS-029c, DC-EPMS-TEST-01, E2E WARNING triage
                  [EPIC 5 PORTION DELIVERED 2026-06-12; bug closeout
                  remains]
  S5  jul 9-15    FEATURE FREEZE -> T1.1 Mission Control eyeball
                  validation, DEMO_SCRIPT v5, replay_demo refresh,
                  full regression, tag v1.0.0-rc
  S6  jul 16-22   T1.3 OBS rehearsals x3 + final take + edit;
                  hardening; tag v1.0.0 MVP (tag-is-not-closure
                  verified)
  S7+ jul 23-aug  EXPLICIT BUFFER: interview prep, zero new code,
                  P0 fixes only
  ```

  **Executive decisions under the blanket GO:** iso stage RETIRED
  (not demoted — Mission Control covers the spatial wow); Epic 5
  COMPLETE (all 3 sprints, E5.E included); **CUT from MVP**: 3.B
  OT Security/Morpheus, T2.3 Vite+TS (DC-EPMS-036 lesson — toolchain
  churn weeks before panel), T3.7 Module Federation, T3.8 DPO, T3.2
  voice-whisper, T3.9 orbit camera, T3.10 PDF, Hermes V1.0
  confederation. `edge/` polyglot stays OUT unless the operator's A3
  manifest lands before S3. MVP definition-of-done: one canonical
  SLD surface with the farm legible + grounded Phase 2 data,
  6-agent breakdown + forensic trail visible in the Optimizer HMI,
  suites green with bugs closed-or-adjudicated, DEMO_SCRIPT v5 +
  recorded OBS take + runbook, tag v1.0.0 on a NEW verified commit.
- **v11.17 sync (2026-05-23)**: **Epic 5 QUEUED** (Optimizer HMI v2 -- 7 tasks,
  ~35h, observability + multi-agent transparency + Epic 4 wire-up). Also
  retroactively records two events delivered out-of-roadmap since v11.16:
  (1) **Epic 4 -- Forensic Ledger** delivered 2026-05-23 in 4 atomic commits
  (`07cc39a` ADR-011, `89b6930` ledger module + 18 unit tests,
  `5b0cb68` BMS Proposer chain + Rollback Harness on `/api/bms`,
  `de41703` doc-sync). HMAC-SHA256 chained append-only audit, TimescaleDB-
  backed, IEC 62443-3-3 SR 6.1/6.2/7.3/7.4. Reactive to the 2026-05-22
  MSD v2.0 forensic audit's 4 CRITICAL findings -- not queued in this
  roadmap beforehand. (2) **DC-EPMS-MSD-005** (HIGH) discovered during the
  post-Epic-4 runtime smoke and resolved same session (`491e9f6` fix +
  `3db2bd1` doc-sync): asyncpg deserialises the UUID column as
  `asyncpg.pgproto.pgproto.UUID`, breaking `_compute_hmac().encode()` on
  every `verify_chain()` against Postgres. The 18 unit tests only
  exercised `InMemoryPersistence` -- false-positive gate. Closed with a
  1-line boundary coercion in `_row_to_entry` + 4 new integration tests
  against real Postgres in a per-PID isolated schema. Backend pytest:
  830 -> 871 (+41 Epic 4) -> 875 (+4 MSD-005); ruff 0 violations; HMAC
  key now persisted in `config/.env` (`key_version=1`,
  cross-restart-verifiable). Epic 5 backlog below codifies the next
  Optimizer HMI improvements suggested by Epic 4 visibility into the
  ledger.
- **v11.16 sync (2026-05-20)**: **Epic 3 Batch 3.C DELIVERED** (`9267667` mock
  + `79ed614` agent). The multi-agent fleet now has **6 specialised
  perspectives** — Carbon/Grid joins as the new sixth member. Owns the
  carbon-aware question none of the previous five could answer: "is this a
  good moment, on the local Ontario grid, to run this action?" Verdict bands
  (deterministic, ADR-006): HARD_STOP when carbon ≥ 200 gCO2/kWh AND on-peak
  TOU; CAUTION when either trips alone; APPROVE on clean off-peak +
  low-carbon. **No VETO authority** (S-DET-02) — Safety Officer remains the
  sole vetoer; the Carbon/Grid HARD_STOP propagates via the rank-2 "any
  agent hard_stop" rule (binding test:
  `test_carbon_grid_has_no_veto_authority`). Reuses
  `_collect_kalman_lines` + `_gemma_complete` verbatim (T3.3 pattern).
  Dep-prep: `backend/grid_provider.py` (320 LOC + 14 tests) — deterministic
  Ontario IESO mock keyed to time-of-day + weekend status, modelling the
  Ontario nuclear+hydro baseload swing to natural-gas peaker dispatch
  (~30-40 g/kWh overnight → ~215 g/kWh weekday afternoon). TOU tiers per
  OEB summer RPP. Self-contained UTC-4 fallback for Windows without IANA
  tzdata. Real-IESO API integration is a function-as-DI-seam swap. Backend
  pytest: 805 → 830 (+14 grid mock + +8 Carbon/Grid agent + +3 orchestrator
  behaviour). **3.B (OT Security / Morpheus) still deferred** pending
  explicit GO — needs Morpheus stub or live engine before the agent class.
- **v11.15 sync (2026-05-19)**: **Epic 3 Batch 3.A DELIVERED** (`c132eff`). The
  multi-agent fleet grew from 4 to 5 with the addition of the **Capacity
  Planner** — a forward-looking IT-load utilisation perspective complementing
  the Analyst's retrospective cost framing. Verdict basis: HARD_STOP ≥ 95 % of
  Path C2 Phase 1 design capacity (16 756 kW), CAUTION ≥ 85 %, APPROVE
  otherwise. Asset-specific impact modelled when the consult is about adding
  a rack-class asset. Follows the T3.3 narrative-helper pattern verbatim
  (reuses `_collect_kalman_lines` + `_gemma_complete`); no change to the
  consensus rule — Safety Officer VETO still inquebrantable. Backend pytest:
  797 → 805 (+8: 4 verdict-class + 4 narrative T3.3-pattern tests). Honest
  scope: prior recommendation was 1 agent (Capacity Planner) post-demo. User
  authorised all three (Capacity / OT Security / Carbon-Grid); 3.A shipped
  this commit, 3.B + 3.C **deferred** pending explicit go — both need
  substantial dep-prep (Morpheus stub for OT, IESO mock for Grid) BEFORE the
  agent class.
- **v11.14 sync (2026-05-19)**: **EPIC 2 CLOSED.** Batch 2.E (`79e8ddd` +
  `8ce48fb`) wired `SURFACE_TO_BMS_TAG` to the real existing
  `HVAC.CHILLER1.CW_SETPOINT` (Honest-scope reality-check: 2.C had used a
  placeholder that didn't exist in the catalogue) + added the missing
  `HVAC.CTOWER1.FAN_VFD` writable AO; OptimizerConfig gained Toronto-baseline
  (ASHRAE Zone 6A) calibration rationale per threshold; live smoke verified
  BOTH default-OFF (HTTP 503 expected, confirmed) AND ENABLED (HTTP 200 +
  HTTP 403 on `actor_role=TECH_L4` with literal F3-4 RBAC message — proves
  `S-SEC-02` enforcement at runtime). Manifests bumped 0.12.0 → 0.13.0;
  annotated tag `v0.13.0` "Proactive Edge" cut at `8ce48fb` and pushed.
  Tags chronological: 41 total.
- **v11.13 sync (2026-05-19)**: **Epic 2 Batch 2.D DELIVERED** (`4d1a611`). The
  Optimizer now has an operator HMI: `views/optimizer.js` lists the queued
  proposals with the two LLM-authored narratives routed through F3-5
  `sanitizeHTML` per `S-SEC-01`; the Approve form posts the operator's
  `actor_role` (default `SME_L6`) + an explicit ASHRAE confirmation per
  `S-SEC-02`; backend `event_emitter` swapped from `log.info` stub to
  `hermes.emit_event("optimizer_proposal", …)`; `core/hermes_events.js`
  subscribes to the new stream and re-emits `hermes:optimizer-proposal` for
  the view to consume. Vitest: 176 → 193 (+17 across optimizer + hermes_events
  files); pytest: 797 (unchanged — 2.D added no backend tests). 2.E is the
  only remaining batch.
- **v11.12 sync (2026-05-19)**: **Epic 2 Batch 2.C DELIVERED** (`18b66b1`). The
  operator-approval surface is live: 4 endpoints under `/api/optimizer/*`
  (`GET /proposals`, `GET /approvals[/{id}]`, `POST /approve/{id}`,
  `POST /reject/{id}`). The approve handler enforces a **strict** SME_L6 gate
  (`actor_role` required AND rank ≥ 6 — stricter than the platform's default
  enforce-when-present), demands `confirm_ashrae=true`, defence-in-depth-
  refuses any proposal carrying an active Safety Officer veto (HTTP 409), and
  is the ONLY Epic 2 code that may invoke the BMS write seam — the operator's
  claim is what authorises the actuation, never the Optimizer's. A new
  directional AST invariant (`test_no_optimizer_routes_import`) keeps
  `backend/optimizer.py` write-path-free: 5 Proposer-Pattern guards now hold
  the line. Backend pytest: 774 → 797 (+23). 2.D + 2.E pending.
- **v11.11 sync (2026-05-19)**: **Epic 2 Batch 2.B DELIVERED** (`c19e853`). The
  Optimizer now routes every proposal through the Epic 1 multi-agent consensus
  chain (Safety Officer VETO uncrossable — audit-logged + queue-blocked +
  emit-blocked on `hard_stop`), synthesizes its own advisory Gemma narrative
  (T3.3 prompt shape), enqueues `QueuedProposal`s in a bounded in-memory
  `ProposalQueue` (PG-backed in 2.C), and emits a Hermes-shaped
  `optimizer-proposal` event per queued proposal. `main.py` gains a lifespan
  startup hook (opt-in via `DC_EPMS_OPTIMIZER_ENABLED`, default OFF) and a
  clean teardown. The 4 Proposer-Pattern AST guards still hold. Backend
  pytest: 759 → 774 (+15). 2.C–2.E pending.
- **v11.10 sync (2026-05-19)**: **Epic 2 Batch 2.A DELIVERED** (`6a6c786`). The
  Optimizer deterministic control law (chiller-LWT + CT-fan-VFD heuristics),
  drift/pacing guards, in-memory audit log, and the asyncio loop scaffold
  ship behind `DC_EPMS_OPTIMIZER_ENABLED` (default OFF). The
  Proposer-Pattern invariant is now machine-enforced — 4 AST-scan tests in
  `tests/test_optimizer.py` fail-loudly on any HTTP client / FastAPI / 
  `bms_connector` / live `/api/bms/write` reference added to
  `backend/optimizer.py`. Backend pytest: 726 → 759 (+33). First task
  executed under the Skill Digestion Harness (citing S-DET-01, S-DET-03,
  S-TEST-01/03, S-SEC-02, S-COMMIT-01/02). 2.B–2.E pending.
- **v11.9 sync (2026-05-19)**: **Epic 2 — The Optimizer — DESIGN DEFINED.** Full
  design brief at `docs/architecture/epic-2-optimizer.md`. The Optimizer is a
  proactive edge-agent for PUE/WUE that **proposes** chiller-LWT and CT-fan
  setpoint adjustments — never actuates. Anchored in ADR-006 (deterministic
  control law + advisory Gemma narrative) and routed through the Epic 1
  multi-agent consensus chain (Safety Officer VETO uncrossable). Operator
  approval at SME_L6 is what issues `/api/bms/write`. V11 cut: chiller LWT +
  CT fan VFD only; single-step proposals; ~9 days in 5 sub-batches. Tag
  target: `v0.13.0` "Proactive Edge".
- **v11.8 sync (2026-05-19)**: **Epic 1 COMPLETE.** T3.3c (Analyst, `d6208ae`)
  and T3.3d (Architect, `691fd11`) wired the last two agents to the live Gemma
  advisory layer. The full multi-agent fleet — Architect / Safety Officer /
  Diagnostician / Analyst — now carries an LLM narrative on top of an unchanged
  deterministic verdict path. ADR-006 invariants preserved across all four
  agents. Backend pytest: 726 passed (+8 T3.3c/d tests).
- **v11.7 sync (2026-05-19)**: **Epic T2.1 CLOSED.** Vector 4 dismantled the
  last of the IIFE — `views/topology.js` (4a), `views/overview.js` (4b), and
  the residual router glue promoted to `core/bootstrap.js` (4c). `app.js` is
  DELETED: 4003 → 0 LOC. The HMI is now fully modular (12 views + core
  engines, declarative routing). Frontend Vitest: 176 passed (18 files).
- **v11.6 sync (2026-05-18)**: multi-epic extraction sprint — Power SLD L3
  control plane (RBAC breaker actuation + What-If DAG sandbox + sparklines),
  the BMS-tag registry mapped to real seeded ISA-95 tags, T2.1 `cooling` view
  extracted then rebuilt as an orthogonal thermodynamic SCADA SLD + L3 control
  plane, and T2.1 `copilot` view extracted — LLM-authored DOM surfaces routed
  through the F3-5 `sanitizeHTML` XSS filter, wired to `hermes:agent-consensus`.
  Frontend Vitest: 146 passed.
- **v11.5 sync (2026-05-18)**: consolidation sprint — structural compaction
  (4 duplicated CMMS helpers consolidated to `backend/cmms_classification.py`,
  5 frontend `_escape` copies to `core/sanitize.js`, 3 orphan functions purged),
  T3.3b live-Gemma Safety Officer (advisory narrative; VETO stays deterministic),
  T2.1 `mops` view extracted to an ES module.
- **v11.4 sync (2026-05-17)**: master-pipeline sprint — DC-EPMS-021 ruff hygiene
  (124 → 0 violations), T3.3 live-Gemma Diagnostician delivered, T2.1 `incidents`
  view extracted to an ES module. DC-EPMS-022 closed (verified stale).
- **v11.2 sync (2026-05-17)**: T3.1 Project Hermes DELIVERED — multiplexed WS
  EDA plane (telemetry + cmms_alerts + agent_consensus), SSE→WS telemetry
  cutover, CET-gated edge-healing engine, and the maintenance.js poll→event
  cutover. T2.1 advanced (scenarios + maintenance views off the IIFE).
- **v11.1 sync (2026-05-17)**: T1.4 / T1.5 / T2.2 delivered; T2.4 / T2.5 partial;
  OBS demo-recording (T1.1 / T1.3) descoped; T3.8 DPO file eradicated; Hermes
  ADR corrected to ADR-011.

This document is the queued backlog after `v0.10.5-power-sld-v2`. Each
tier is independently fundable — pick by available time, panel
proximity, or career trajectory. Items are intentionally specific so
review (mine, the panel's, or future Claude's) can verify the cut.

---

## Tier 1 — Demo Readiness (~8h, target: any 1-day burst)

The platform is panel-ready as code. **Delivery is the unfinished
business.**

### T1.1 — Browser-validation of B1 Mission Control (~1 h)

The Tesla-Megapack mission control was shipped (`v0.10.4-b1-production`)
but never validated by human eyes on a real WebGL canvas. Verify:

- 4 cards project correctly onto each building anchor as the camera/
  viewport changes
- Glassmorphism `backdrop-filter` renders (Chrome / Edge / Safari OK;
  Firefox needs flag)
- 28 InstancedMesh particles flow visibly Yard → A and Yard → B
- Building A card flips to amber CAUTION when 3 anomalies are queued
  (current demo state)
- Click drill-down to `#rack-heatmap` / `#site_topology` /
  `#tech-assist` works smoothly
- FPS sustained ≥ 60 (spike measured 144)

Iterate on whatever fails.

### T1.2 — DEMO_SCRIPT v5 (~2 h)

Current `DEMO_SCRIPT.md` (v4) does not mention:
- Mission Control (`v0.10.4`)
- Rack Anomaly Heatmap (`v0.10.2`)
- Force-directed Site Topology graph (`v0.10.1`)
- Path-coded Power flow (`v0.10.1`)
- Sound + boot splash + keyboard shortcuts (`v0.10.0`)
- Voice closure modal (`v0.9.15`)
- Asset enrichment loop (`v0.9.16`)

V5 must reorganise the 13-15 min walkthrough around **Mission Control
as the new opening visual** (replaces the bare KPI grid as the
panel-impression frame), then drill into Maintenance → Multi-Agent →
LOTO Auditor → Tech Assist with the new affordances cited.

### T1.3 — Recording rehearsal × 3 + final OBS take (~3 h)

OBS Studio split-screen (terminal left, browser right). Three
rehearsal takes minimum before the actual recording. Final cut to
DaVinci Resolve / kdenlive for trimming, captions, lower-thirds.

### T1.4 — ✅ DELIVERED `7be472b` — `PRIMER_PROMPT.md` polishing + commit

Untracked file currently. Update it to reflect everything through
`v0.10.5-power-sld-v2`. Commit so future Claude sessions can absorb
the project context in 30 seconds without re-reading 50 sprints.

### T1.5 — ✅ DELIVERED `6b38a16` — `replay_demo.ps1` / twin-script injector

Add:
- Reset Mission Control simulation state to nominal
- Set sessionStorage flags to a known-clean state
- Print a "browser hard-reload Ctrl+Shift+R" reminder at the end

### T1.6 — Backend bug closeout (~1 h, opportunistic)

While in cleanup mode, knock out the cosmetic bugs that have lingered:
- DC-EPMS-019 logging file handle on shutdown (30 min)
- DC-EPMS-022 6 ADRs MD004 asterisks (5 min sed)
- DC-EPMS-039 chromadb posthog + pydantic warnings (30 min)

DC-EPMS-021 (90 ruff legacy errors) and DC-EPMS-029c (physics LOTO
sensitivity) deferred — they don't affect demo quality.

---

## Tier 2 — Architectural Polish (~7-10 days, target: 2-3 weeks)

For Senior+/Staff Engineer interview ammunition. The platform is
demonstrable; the architecture has visible debt that a deep-dive
reviewer can find in 30 seconds with DevTools.

### T2.1 — Dismantle `app.js` IIFE — legacy views (~3-4 days)

The single largest visible piece of architectural debt. Migrate one
view per session, in order of demo relevance.

**Registry reality-check (2026-05-18, post-v0.11.0 SitRep).** The
original "8 vistas legacy" list undercounted: a code-level audit of
`app.js` (2,600 LOC post-v0.11.0, from 4,003) found **5 legacy
surfaces still un-extracted** — not 2. The HLD/LLD Topology view, the
LOTO Auditor view and the Overview/landing dashboard were never on the
checklist. The list below is corrected to the real surface inventory.

**Phase A — DELIVERED (6 views off the monolith):**

1. ✅ `views/scenarios.js` — failure scenario simulator (DELIVERED `480f03b`)
2. ✅ `views/incidents.js` — postgres audit log (DELIVERED `3aa944b`)
3. ✅ `views/mops.js` — MOPs/SOPs/EOPs library (DELIVERED `de7404f`)
4. ✅ `views/cooling.js` — extracted, then rebuilt as an orthogonal
   thermodynamic SCADA SLD + an L3 control plane (RBAC pump actuation,
   What-If sandbox, telemetry sparklines) (DELIVERED `7b85ab9` /
   `33e7459` / `bb10e4e`)
5. ✅ `views/power.js` — SLD data plane extracted; the 2.5D iso engine
   preserved + enriched to an explicit 5-layer Tier IV topology
   (paralleling bus N+1), aggressive dark-SCADA restyle, Hermes-bound
   (DELIVERED `b5a82ed`)
6. ✅ `views/copilot.js` — Facility Co-Pilot agent chat + HITL drafts;
   LLM-authored DOM surfaces routed through the F3-5 `sanitizeHTML` XSS
   filter, wired to the Hermes `hermes:agent-consensus` EDA event
   (DELIVERED `38605d3`)

**Phase B — eradication vectors (the 5 discovered legacy surfaces):**

- ✅ **V1.** `views/bms.js` — BMS Connector: tag registry, table, RBAC
  write-modal, NIST SP 800-82 audit modal. `showBmsAudit` re-exposed on
  `window` for the `copilot.js` deep-link. (DELIVERED `807185e`)
- ✅ **V2.** `views/loto.js` — LOTO Auditor view (was missing from the
  original registry). The legacy click-delegation + `setTimeout(0)`
  zombie-router hack retired for `core/router.js` `registerRoute`.
  (DELIVERED `fc3ead6`)
- ✅ **V3.** Legacy Site Topology tree+detail — ADJUDICATED as dead
  code (the force-directed `views/site_topology.js` owns the
  `site_topology` route via `core/router.js`, so the legacy
  `renderSiteTopologyView` was unreachable) and ERADICATED (−277 LOC),
  not migrated. Follow-up: the per-rack LOTO-Impact breakdown is not in
  the force-graph detail panel — a clean future feature ticket, the
  `/api/site/loto-impact` endpoint already exists. (DELIVERED `3b98449`)
- ✅ **V4.** The final two surfaces, in three staged commits:
  - **4a** — the HLD/LLD Topology view → `views/topology.js`
    (`registerRoute('topology')`). (DELIVERED `f0a9620`)
  - **4b** — the Overview/landing dashboard → `views/overview.js`
    (health, KPIs, PUE chart, agent chat, incidents, voice,
    shift-report, SHI). The dormant legacy `EventSource` SSE-fallback
    path was deleted as part of this (`core/telemetry_engine.js` owns
    the SSE). (DELIVERED `5ae535d`)
  - **4c** — the IIFE residual (`MODULES` + `navigateTo` + `setupRouter`
    + `renderPlaceholder`) promoted to `core/bootstrap.js`; `app.js`
    **DELETED**; `index.html` reduced to a single ES-module entry
    point. (DELIVERED `5ae535d`)

**Result — EPIC T2.1 CLOSED.** `app.js`: **4003 → 0 LOC**. The HMI is
fully modular — 12 `views/*.js` + the `core/*.js` engines, every route
on the declarative `core/router.js`. No IIFE monolith remains.

### T2.2 — ✅ DELIVERED `42ecdf7` — Declarative router

Replace `navigateTo()` switch statement + 5 `setTimeout(0)` LOTO-pattern
hacks with:

```typescript
// core/router.ts
const routes = new Map<string, RouteHandler>();
export function registerRoute(path: string, handler: RouteHandler) { … }
export function navigateTo(path: string) {
    history.pushState({}, '', `#${path}`);
    routes.get(path)?.activate();
}
```

Each ES module view auto-registers in its `init()`. Eliminates the 5
`setTimeout(0)` overrides and the zombie-router (where overview shows
for one frame before being hidden).

### T2.3 — Vite + TypeScript strict (~2 days)

Pre-condition for Module Federation if we ever want it. Fast HMR
unlocks 10× dev velocity. Type safety catches the kind of dead-code
+ phantom-button drift that would otherwise accumulate.

```
+ pnpm/npm + vite + typescript
+ frontend/package.json (at last)
+ frontend/vite.config.ts (with Module Federation plugin already
                           installed even if not yet activated)
+ tsconfig.json strict (noImplicitAny, strictNullChecks, etc.)
+ FastAPI serves dist/ build, NOT raw source
+ Cache busting via vite content hashing (no more ?v=8.1.0-s66)
```

### T2.4 — 🟡 PARTIAL `6c77f41`/`ec8effb` (Vitest harness + mission_control suite) — Frontend tests (Vitest + happy-dom, ~2 days)

Backend has 549 tests. Frontend has 0. Smoke per view minimum:
- mission_control: renders 4 buildings + cards bind data correctly
- rack_heatmap: 50-cell grid renders, click flips selection
- site_topology: graph layout converges in ≤ 500ms with 91 nodes
- maintenance: WO row click opens approve/reject correctly
- multi_agent: VETO scenario flips banner red

### T2.5 — 🟡 PARTIAL `f384937` (A11y-1: focus-trap, keyboard drill-down, skip-link) — A11y audit (~1 day)

Keyboard-only navigation completeness, ARIA labels on every action
control, focus management on modal open/close, prefers-reduced-motion
already honored — extend to prefers-color-scheme + high-contrast mode.

### T2.6 — Cache busting + asset hashing (~2 h)

Currently every asset has a hardcoded `?v=8.1.0-s66` query that we
never bump. Move to vite content-hashed filenames so each deploy
self-busts.

---

## Tier 3 — Capability Expansion (~3-4 weeks, target: open-ended)

The capabilities that push **past** demo-ready into a competitive
differentiator. Pick selectively; do NOT attempt all in one push.

### T3.1 — WebSocket Hermes pipeline — ✅ DELIVERED 2026-05-17

**The architectural inflection point — shipped.** Delivered across
`caf5cc1` (WS vertical slice) → `bf20042` (live Kalman tap + SSE→WS
telemetry cutover) → `66abc30` (unified EDA plane: cmms_alerts +
agent_consensus + CET-gated edge-healing) → maintenance.js poll→event
cutover. Still open: retiring the remaining per-view polls
(`mission_control.js`), and PUE / power_sld over the socket. The
original plan below is kept as the design record.

Replace REST+polling for PUE + CMMS + Multi-Agent + Power SLD with a
single multiplexed WebSocket stream:

```
GET   /api/physics/pue                  ← 15 s polling → REPLACE
GET   /api/cmms/work-orders?only_open   ← 15 s polling → REPLACE
GET   /api/multi-agent/consult          ← on-demand → KEEP (req/res)

WS    /api/hermes/stream                ← NEW, multiplexed:
        type: 'pue.snapshot'            phase_1 + phase_2 every 1 s
        type: 'cmms.delta'              WO state transitions
        type: 'cmms.snapshot'           full backlog every 30 s
        type: 'multi_agent.broadcast'   consensus events as they fire
        type: 'telemetry.kalman'        z-score + sustain per channel
        type: 'power_sld.event'         simulated faults / real faults
```

**Frontend backpressure**: RxJS `bufferTime(50ms) → distinctUntilChanged
→ throttleTime(33ms)` per channel. Web Worker for JSON parsing if a
single tick > 200 messages.

**Backend**: a single `hermes_orchestrator.py` that fans out to all
existing services and serializes to JSON Lines.

### T3.2 — Voice closure transcription (~3-4 days)

Sprint 7.1c V2: integrate `faster-whisper` (already a Python dep)
behind `POST /api/tech-assist/closure/{wo_id}/transcribe-and-dictate`.
Frontend audio capture via MediaRecorder + WebRTC.

### T3.3 — Multi-Agent ML upgrade — ✅ DELIVERED 2026-05-17 (`c811865`)

The Diagnostician now makes a real call to the local Gemma model. The
agent's VERDICT stays pure-Python deterministic (ADR-006 — no LLM in the
critical decision path); Gemma is wired as an *advisory narrative* layer
that runs AFTER the verdict and never alters it.

Delivered:
  - `AgentEngine.complete_gemma()` — non-streaming Gemma completion.
  - `hermes.latest_kalman_channels()` — public live Kalman Z-score tap.
  - `DiagnosticianAgent` takes an `llm_client` + `telemetry_provider`;
    after the deterministic verdict it grounds a prompt in the asset's
    live Kalman Z-scores and stores the synthesized narrative in
    `AgentVerdict.llm_narrative`. Any LLM/telemetry failure degrades to
    an empty narrative.
  - 4 tests mock the external LLM call (narrative grounding, verdict
    immutability under a contradicting LLM, graceful degradation,
    no-client baseline).

NOTE: the original brief proposed RAG-corpus-chunk grounding; the
delivered cut grounds on live Kalman telemetry instead — closer to the
real physical state and consistent with the Hermes EDA plane.

**T3.3b — ✅ DELIVERED 2026-05-18 (`10fd664`)**: the same advisory-narrative
pattern extended to the **Safety Officer**. Two shared helpers
(`_collect_kalman_lines` / `_gemma_complete`) were extracted; the
Diagnostician was slimmed onto them. The Safety Officer's verdict —
including its HARD_STOP **VETO**, which outranks every other agent —
stays 100% deterministic; Gemma only writes the advisory narrative in a
verdict-independent `_finalize()`. 4 LLM-mocked tests.

**T3.3c — ✅ DELIVERED 2026-05-19 (`d6208ae`)**: the **Analyst** wired to
Gemma. Prompt frames the CapEx-vs-OpEx capital-planning narrative around
the heuristic cost model (`OPEX REPAIR` / `CAPEX REPLACE` / prior repair
count) and the live Kalman Z-scores. The 40 % breakeven verdict + the
cost heuristics remain authoritative — the prompt explicitly forbids
the model from overriding either. 4 LLM-mocked tests.

**T3.3d — ✅ DELIVERED 2026-05-19 (`691fd11`)**: the **Architect** wired to
Gemma. Prompt frames the topology narrative around the asset's
redundancy pillar / path / criticality with a Tier IV / Uptime
Institute concurrent-maintainability lens. The HARD_STOP / CAUTION
thresholds and pillar rules remain deterministic. 4 LLM-mocked tests.

**Epic 1 complete (2026-05-19).** The full 4-agent multi-agent fleet
(Architect / Safety Officer / Diagnostician / Analyst) is now LLM-
augmented. Backend pytest: 718 → 726 (+8 narrative tests across T3.3c
+ T3.3d). ADR-006 invariants preserved: every verdict and the
Safety Officer veto chain stay 100 % deterministic; the LLM layer is
strictly advisory across all four agents.

### T3.4 — Power flow live tied to current_a (~1 day)

Currently 28 InstancedMesh particles in Mission Control and SLD
flow at fixed velocity. Hook to `current_a_phase_*` from the
telemetry stream (after T3.1 lands). Speed and density per Path
modulated by real load.

### T3.5 — Mission Control glass-panel polish (~2 days)

Selective bloom on healthy edges (cyan glow), `CSS3DRenderer` for
the floating cards instead of HTML overlay (eliminates the
projection math each frame). **Risk**: bloom is the kitsch knife
edge; if it crosses, kill it.

### T3.6 — Anomaly heatmap real-time integration — ✅ DELIVERED 2026-05-17

`views/rack_heatmap.js` now subscribes to the `channels` state key (the
Hermes `telemetry` channel_innovations payload) and maps each rack's
real Kalman `max_z` + `last_emission` onto the cell color band + anomaly
blink. The deterministic sinusoid is retained only as a stale-fallback
(resumes after a 15 s live-data gap). The last client-side `setInterval`
HTTP poll was also eliminated — `mission_control.js` → Hermes events.

### T3.7 — Module Federation (~5-7 days)

Pre-condition: T2.3 (Vite + TS). After:

```typescript
// vite.config.ts with @originjs/vite-plugin-federation
federation({
    name: 'shell',
    remotes: {
        maintenance: 'http://...:8081/maintenance/remoteEntry.js',
        tech_assist: 'http://...:8082/tech-assist/remoteEntry.js',
    }
})
```

**Only valid if separate teams need to deploy independently.** For
single-developer single-laptop, this is over-engineering. Documented
here as a future option.

### T3.8 — DPO edge healing (~4-5 days)

Sprint 6 deferred capability. `backend/dpo_edge_healing.py` (352 LOC) was
**eradicated 2026-05-17 in `d495c7b`** as a confirmed orphan — never wired,
and the "Sprint 6 = DPO" plan was superseded by CMMS Core. Reviving this epic
now requires first restoring the file from git history
(`git show d495c7b^:backend/dpo_edge_healing.py`) or re-authoring it, then
surfacing it as `POST /api/dpo/capture` (auto-fires on CMMS WO rejection) +
`POST /api/dpo/recompile` (manual trigger). Edge-local LLM fine-tuning loop.
ADR-007 documents the original reuse decision (amended 2026-05-17).

### T3.9 — 3D Mission Control orbit camera + Building D walkthrough (~3 days)

Optional: relax the "fixed iso" constraint when the user explicitly
clicks an "orbit mode" toggle. Still bounded; nothing free-roam.
Building D click could trigger a fly-through to Q2 2026 design view.

### T3.10 — Print/PDF export (~1-2 days)

Operations panels often need this for audit trails. Server-rendered
HTML → headless Chrome via Playwright → PDF for any backlog snapshot,
LOTO audit, or PUE report.

---

## Epic 2 — The Optimizer (proactive edge-agent for PUE / WUE)

**Status:** ✅ **COMPLETE** — all five batches (2.A–2.E) delivered
2026-05-19 (`6a6c786`, `c19e853`, `18b66b1`, `4d1a611`, `79e8ddd`,
`8ce48fb`); released as **`v0.13.0` "Proactive Edge"**. Smoke-test
verified live against the running backend. Full design brief:
**`docs/architecture/epic-2-optimizer.md`**.

**Sub-batch progress:**

- ✅ **2.A** — `backend/optimizer.py` deterministic control law +
  drift/pacing guards + audit log + asyncio scaffold + 33 unit tests
  (incl. 4 Proposer-Pattern AST-invariant guards). (`6a6c786`)
- ✅ **2.B** — multi-agent consensus integration (Safety VETO uncrossable)
  + `ProposalQueue` + Optimizer Gemma narrative (T3.3 shape) + Hermes
  `optimizer-proposal` event emission + `main.py` lifespan startup +
  teardown hook (opt-in, default OFF). 15 new tests. (`c19e853`)
- ✅ **2.C** — `backend/optimizer_routes.py` with 4 endpoints (`GET
  /proposals`, `GET /approvals[/{id}]`, `POST /approve/{id}`,
  `POST /reject/{id}`); strict SME_L6 RBAC gate (`actor_role` required
  AND rank ≥ 6); `confirm_ashrae=true` demand on approve; HTTP 409
  defence-in-depth Safety-veto refusal; `bms_write_fn` injection seam
  is the ONLY Epic 2 path to the BMS write — wired in `main.py` over
  `BMS_AVAILABLE` + `get_bms().write`. In-memory `ApprovalLog`
  (PG-backed table is the 2.C+ follow-up). +22 tests + 1 new
  directional AST invariant. (`18b66b1`)
- ✅ **2.D** — `views/optimizer.js` (~370 LOC) lists the proposal queue
  with the two LLM-authored narratives (Optimizer's own + consensus
  rationale) routed through F3-5 `sanitizeHTML`; Approve form carries
  the operator's `actor_role` + ASHRAE confirmation (S-SEC-02);
  backend `event_emitter` swapped from `log.info` stub to
  `hermes.emit_event` (the real WS producer); `core/hermes_events.js`
  re-emits `hermes:optimizer-proposal`. 16 Vitest tests (+1 in
  hermes_events.test.js). (`4d1a611`)
- ✅ **2.E** — `config/bms_tags.yml` extended (`HVAC.CTOWER1.FAN_VFD`
  writable AO) + `SURFACE_TO_BMS_TAG` rewired to the existing
  `HVAC.CHILLER1.CW_SETPOINT` (a 2.C placeholder was discovered + fixed
  during 2.E recon — the original `HVAC.CHILLER_1.LWT_SETPOINT` name
  didn't exist in the catalogue);
  `OptimizerConfig` gained Toronto-baseline calibration rationale
  (ASHRAE Climate Zone 6A) per threshold; live smoke verified both
  default-OFF and ENABLED postures end-to-end against the running stack
  — `actor_role=TECH_L4` returned HTTP 403 with the literal F3-4 RBAC
  message, proving S-SEC-02 at runtime; manifests bumped 0.12.0 →
  0.13.0; **annotated tag `v0.13.0` "Proactive Edge" cut** at
  `8ce48fb` and pushed. (`79e8ddd` + `8ce48fb`)

Epic 1 delivered the *reactive* fleet — the four consultative agents that
respond to operator queries with verdicts + live Gemma narratives. Epic 2
delivers the *proactive* complement: a continuous edge-agent (the Optimizer)
that watches Hermes telemetry and **proposes** chiller-LWT and cooling-tower-
fan setpoint adjustments to drive PUE toward the architecture-aware target.

The load-bearing architectural decision is the **Proposer Pattern**: the
Optimizer is a proposer, NOT an actuator. ADR-006 invariants are preserved
end-to-end:

- The proposal value is computed by a deterministic control law — the LLM
  only writes an advisory narrative (`S-DET-01`).
- Every proposal routes through the existing `multi_agent.consult()` chain.
  The Safety Officer's `HARD_STOP` veto is uncrossable (`S-DET-02`).
- The Optimizer has no `actor_role`. It NEVER calls `/api/bms/write`. Only
  the operator-approval endpoint (SME_L6 gate) issues the write
  (`S-SEC-02`).
- Each proposal carries a What-If sandbox outcome (projected delta-PUE,
  ASHRAE distance, redundancy post-state) as a pre-flight validation gate.

**Sub-batches** (~9 days total when ungated):

- **2.A** — `backend/optimizer.py` deterministic control law + asyncio loop.
- **2.B** — Multi-agent consensus integration + proposal queue.
- **2.C** — `POST /api/optimizer/approve` + `/reject` endpoints (RBAC-gated).
- **2.D** — `views/optimizer.js` HMI + Vitest.
- **2.E** — Live smoke test (boot-signature verified per `S-RUNTIME-01`) +
  release tag **`v0.13.0` "Proactive Edge"**.

**V11 scope cut:** chiller LWT + CT fan VFD only; single-step proposals;
reactive (PUE-drift) trigger; 15-minute pacing per surface. Deferred to
Epic 2.1+: pump VFD, CDU temperature, free-cooling switching, predictive
multi-step horizon, WUE optimisation, BESS dispatch.

See `docs/architecture/epic-2-optimizer.md` for the full design (control
law, multi-agent validation table, RBAC actuation path, HMI surface,
testing strategy, ADR-006 acceptance checklist).

---

## Epic 3 — Reactive Fleet Expansion (5 → 7 agents, post-CO+I demo)

**Status:** IN PROGRESS — Batches 3.A + 3.C delivered (6-agent fleet
live); only 3.B (OT Security / Morpheus) deferred pending explicit
go-ahead.

The multi-agent fleet now has **6 specialised perspectives** (after 3.C).
Epic 3 plans the expansion to 7 to close the remaining hyperscale gap
the existing agents don't cover. Each new agent must satisfy the 4
entry criteria (orthogonal perspective, deterministic verdict, clear
veto behaviour, T3.3 4-test pattern viable).

**Sub-batch progress:**

- ✅ **3.A — Capacity Planner** (`c132eff`). Forward-looking IT-load
  utilisation perspective (HARD_STOP ≥ 95 %, CAUTION ≥ 85 %).
  Complements the Analyst's retrospective cost framing. Uses existing
  data sources (`site_model`, `cmms_repo`); follows the T3.3 narrative
  pattern verbatim. +8 tests; +0 dep-prep needed.
- ⏳ **3.B — OT Security / Threat agent** (Morpheus-style). Cyber-
  physical anomaly detection on BACnet/Modbus traffic + IEC 62443 zone
  violations. **Dep-prep required FIRST:** NVIDIA Morpheus is currently
  `MODULES.morpheus` *placeholder* — needs either a Morpheus stub
  (~5 days simulating SR 5.2 anomaly detection without the real
  framework) OR the full Morpheus integration. Then the agent itself
  (~5 days). Authorisation deferred.
- ✅ **3.C — Carbon / Grid agent** (`9267667` mock + `79ed614` agent).
  Ontario IESO carbon-intensity + Time-of-Use perspective for the CO+I
  2030 carbon-negative commitment. Verdict bands: HARD_STOP when
  carbon ≥ 200 g/kWh AND on-peak TOU; CAUTION when either trips alone;
  APPROVE on clean off-peak + low-carbon. **No VETO authority**
  (S-DET-02 binding) — Safety Officer remains the sole vetoer; the
  Carbon/Grid HARD_STOP propagates via the rank-2 "any agent
  hard_stop" rule. T3.3 narrative-helper pattern reused verbatim.
  Dep-prep delivered as `backend/grid_provider.py` — deterministic
  Ontario IESO mock (nuclear+hydro baseload + gas-peaker afternoon
  swing) keyed to time-of-day + weekend; real-IESO API integration is
  a function-as-DI-seam swap. +22 tests (14 mock + 8 agent) +3 modified
  orchestrator tests. Backend pytest: 805 → 830.

**Target fleet ceiling: 7 agents.** Beyond 7, the operator cognitive
load on a consult chip-grid degrades faster than the marginal value of
another perspective. Stop at 7 — after 3.B lands the fleet is full.

---

## Epic 5 — Optimizer HMI v2 (operator observability + multi-agent transparency)

**Status:** 🟦 **QUEUED** — 7 tasks, ~35 h total, 3 sprints of ~1-2 days each.
No commits yet. Backlog landed in roadmap 2026-05-23 (v11.17 sync).

**Motivation.** The Optimizer view shipped with Epic 2 Batch 2.D
(`4d1a611`, `frontend/assets/js/views/optimizer.js`) is functional for
its narrow 2.D scope -- list queued proposals, allow SME_L6 approve/
reject -- but the view's own docstring (lines 26-30) enumerates three
deferred surfaces: per-agent narrative breakdown, What-If sandbox,
persistent approval history. Two new pressures have surfaced since 2.D:

  1. **Multi-agent fleet grew 4 -> 6** (Capacity Planner 3.A,
     Carbon/Grid 3.C). The HMI still shows only the rolled-up consensus
     verdict + a single combined `consensus_rationale` -- the 6
     individual perspectives are invisible. This erases the
     differentiator the fleet was built for.
  2. **Epic 4 Forensic Ledger** (2026-05-23, out-of-roadmap) now
     guarantees that every approved proposal generates a `proposal_id`-
     stamped chain of ledger entries (S-PROPOSER-01). The HMI has no
     visualisation of that trail, so the audit feature is invisible to
     the operator who triggered it.
  3. **Default-OFF + silent ticks** of the Optimizer leave the HMI
     ambiguous between "loop dead" and "loop alive + ADR-006 decided
     no-action". The proactive agent reads as failed at a glance.

Epic 5 is the HMI layer that closes those three gaps.

**Out of scope:** mutating control-law thresholds at runtime (ADR-006
says config is design-time, not operator-tunable), and any change to
the Proposer Pattern itself (the AST guards in
`tests/test_optimizer.py` still bind).

### E5.A — Optimizer loop heartbeat strip (~5 h) · Sprint 1

**Problem:** HMI no distingue "loop muerto" de "loop sano + ADR-006
no-action". Queue vacío es ambiguo.

- Backend: `GET /api/optimizer/health` returns `{last_tick_at,
  ticks_total, recent_outcomes_60s: {no_drift, proposed, paced_out,
  safety_veto}, live_pue, pue_target, drift, pacing_until_per_surface}`.
  Data already in `_audit_log: list[AuditEntry]` + `TelemetryPoint`.
  Hermes event `hermes:optimizer-tick` emitted from the orchestrator.
- Frontend: horizontal strip in `views/optimizer.js` above the card
  list. 5-min PUE sparkline (reuses `core/shi_sparkline.js` style).
  Live update via Hermes WS event, no polling fallback needed.

**Acceptance:** 200 enabled / 503 default-OFF; strip refreshes within
5 s of real tick; sparkline draws from telemetry_pipeline curve.

**Tests (+4 backend, +3 frontend):** health shape validation,
default-OFF 503, hermes event emit, sparkline render, hermes refresh
listener, sanitize numeric values.

**Files:** `backend/optimizer.py` (~50 LOC reducer),
`backend/optimizer_routes.py` (~30 LOC endpoint), `backend/hermes.py`
(~10 LOC event), `views/optimizer.js` (~80 LOC strip),
`core/hermes_events.js` (+1 subscription).

**Skills:** S-ROUTE-02, S-SEC-01, S-DET-01, S-TEST-01, S-TEST-02.

### E5.B — Approval history sidebar (~5 h) · Sprint 2

**Problem:** `GET /api/optimizer/approvals` exists
(`optimizer_routes.py:281`) but no frontend consumer. Operator does
not see decision history or the write -> ledger trace.

- Backend: **zero changes** -- endpoint already exposes
  `OptimizerApproval.to_dict()` with proposal_id, decision,
  operator_id, actor_role, decision_at, bms_write_success,
  bms_write_message, bms_tag_id, approval_id.
- Frontend: collapsible right-aside `<aside data-opt-history>` with
  last 10 decisions. Per row: relative timestamp, pid (8 chars),
  decision badge (green/red), operator_id, BMS write status. Expand
  shows approval_id + full reason.

**Acceptance:** empty when total=0; renders last N otherwise;
auto-refresh on `hermes:optimizer-proposal` (assumes dequeue ->
approval); XSS sanitization on reason field.

**Tests (+3 frontend):** render empty / render N / hermes refresh.

**Files:** `views/optimizer.js` (~70 LOC sidebar).

**Skills:** S-SEC-01, S-TEST-02.

### E5.C — Per-agent voting breakdown in each card (~7 h) · Sprint 1

**Problem:** Card shows only rolled-up `consensus_verdict` +
combined `consensus_rationale`. The 6 individual agent voices are
invisible. This IS the project's differentiator and it is hidden.

- Backend: `QueuedProposal` gains
  `agent_breakdown: list[AgentVote]` where
  `AgentVote = {agent_id, verdict, rationale_oneline}`. The
  orchestrator already has this data; just stop discarding it in the
  roll-up.
- Frontend: collapsible "6 agents voted" section inside
  `_renderProposalCard`. Compact table with icons by verdict
  (✓ APPROVE / ⚠ CAUTION / ✗ HARD_STOP / 🛑 VETO -- VETO only for
  Safety Officer per S-DET-02).

**Acceptance:** `to_dict()` includes agent_breakdown with exactly 6
entries (or less when partial consult); frontend degrades cleanly to
0/n/6; only Safety Officer gets the 🛑 icon (S-DET-02 binding); the
existing card-header "SAFETY VETO" badge remains the canonical
operator signal.

**Tests (+4 backend, +3 frontend):** breakdown propagation
(full / partial / empty / safety_veto), card render, XSS sanitize on
rationale_oneline, icon mapping per verdict.

**Files:** `backend/optimizer.py` (~30 LOC QueuedProposal),
`backend/multi_agent.py` (~20 LOC propagate breakdown from
`_compute_consensus`), `views/optimizer.js` (~60 LOC section).

**Skills:** S-DET-02 (binding test), S-DET-03, S-SEC-01, S-TEST-01,
S-TEST-02.

**Risk:** touches `multi_agent.py` -- the 8 existing consensus tests
must remain green. Run `tests/test_multi_agent.py` targeted first per
S-TEST-01.

### E5.D — Per-card forensic trail link (Epic 4 wire-up, ~4 h) · Sprint 2

**Problem:** Epic 4's forensic ledger is invisible from HMI. The
operator who approved a proposal cannot see the 2 entries
(`BMS_WRITE_REQUESTED` + `BMS_WRITE_RESULT`) their action generated.

- Backend: `GET /api/ledger/entries?proposal_id=<uuid>` filter by
  payload field. SQL:
  `WHERE payload->>'proposal_id' = $1` in
  `PostgresPersistence.fetch_all_by_proposal_id` (~30 LOC + protocol
  method). New JSONB index in a follow-up migration if chains grow
  past ~10k entries.
- Frontend: after the approval result block in the card, link
  "View forensic trail (N entries)" opens a modal showing both
  entries with HMAC chain visualisation (`entry_hmac` of entry #1 ==
  `prev_hash` of entry #2).

**Acceptance:** endpoint returns `[]` for unknown proposal_id; full
chain for approved write. Modal renders chain link explicitly. XSS
sanitization on message field.

**Tests (+3 backend, +3 frontend):** filter no-match / 2-entry match /
multiple writes same proposal_id; modal render / chain visualization /
sanitize.

**Files:** `backend/ledger/forensic_ledger.py` (~30 LOC),
`backend/main.py` (~15 LOC endpoint variant), `views/optimizer.js`
(~80 LOC modal).

**Skills:** S-LEDGER-01, S-SEC-01, S-TEST-01, S-TEST-02.

**Dependency:** ship after E5.B (sidebar provides the entry-point UI).

### E5.E — What-If sandbox preview before approve (~9 h) · Sprint 3

**Problem:** `confirm_ashrae` checkbox is an act of faith -- operator
sees no sandbox projection. Epic 2 brief §6 required it; 2.D shipped
without it.

- Backend: `POST /api/optimizer/preview/{proposal_id}` runs the
  deterministic impact computation WITHOUT actuation. Returns
  `{projected_pue, projected_wue, projected_ashrae_distance,
  projected_chiller_load_pct, ...}`. Requires extracting projection
  logic from the tick into a pure function
  `simulate_setpoint_impact(point, surface, proposed_value)`
  reusable by both paths.
- Frontend: "Preview impact" button before Approve renders a preview
  card with projected vs current values. ASHRAE distance in
  green/amber/red per tolerance band.

**Acceptance:** preview is purely deterministic (S-DET-01 -- zero LLM
call); endpoint idempotent (same input -> same output); frontend
preview persists until new input or cancel.

**Tests (+4 backend, +3 frontend):** verdict-class tests (green /
amber / red / saturated-out-of-bounds); preview render, color
mapping, re-fetch on input change.

**Files:** `backend/optimizer.py` (~80 LOC pure function +
extraction), `backend/optimizer_routes.py` (~30 LOC endpoint),
`views/optimizer.js` (~100 LOC preview UI).

**Skills:** S-DET-01, S-TEST-01, S-TEST-02.

**Dependency:** no technical blockers, but recommend after A+B+C+D --
this is polish, not fundamentals.

### E5.F — OptimizerConfig inspector panel (~2 h) · Sprint 3 (cheap)

**Problem:** Operator approving a proposal has no context on why
the Optimizer chose THIS value vs another. Thresholds
(`PUE_DRIFT_THRESHOLD`, `MIN_TIME_BETWEEN_PROPOSALS`, surface bounds)
are invisible.

- Backend: `GET /api/optimizer/config` serialises `OptimizerConfig`
  dataclass to dict. Read-only -- config is design-time per ADR-006.
- Frontend: collapsed-by-default "Config & Bounds" panel at view
  footer. Key/value table with tooltips per threshold.

**Acceptance:** endpoint returns all public OptimizerConfig fields;
frontend renders human-readable values (e.g. `600s = 10 min`).

**Tests (+1 backend, +1 frontend):** shape validation, render.

**Files:** `backend/optimizer_routes.py` (~20 LOC),
`views/optimizer.js` (~40 LOC).

**Skills:** S-SEC-01, S-TEST-01, S-TEST-02.

### E5.G — Rejection-reason analytics (~3 h) · Sprint 3

**Problem:** 2.D left a comment "feeds the optional 2.2 learning
loop" but never surfaced analysis. Reject reasons stay buried in
`ApprovalLog`.

- Backend: **zero changes** -- `GET /api/optimizer/approvals` already
  returns all `reason` fields.
- Frontend: at the end of the approval sidebar (E5.B), block "Common
  rejection patterns last 30 days" with simple word frequency or
  surface clustering. If <10 rejections total, show "Not enough data
  -- need more rejections".

**Acceptance:** purely client-side derivation (no new backend);
empty / sparse / dense cases render cleanly.

**Tests (+3 frontend):** empty / 5 rejections sparse / 30 rejections
with clustering.

**Files:** `views/optimizer.js` (~50 LOC analytics block).

**Skills:** S-SEC-01 (reasons are operator-authored -- sanitizeHTML
before any frequency display), S-TEST-02.

**Dependency:** lives inside the E5.B sidebar.

### Epic 5 sequencing & gate impact

```
Sprint 1 (~12 h, 1.5 days) -- observability layer
  E5.A heartbeat -> E5.C per-agent breakdown
  Core differentiator. Sprint 1 alone delivers the bulk of demo value.

Sprint 2 (~9 h, 1 day) -- auditability layer
  E5.B approval sidebar -> E5.D forensic trail link
  Closes the Epic 4 <-> Epic 2 loop (Proposer chain visible).

Sprint 3 (~14 h, 1.5-2 days) -- polish layer
  E5.F config inspector (2 h, quick win)
  E5.G rejection analytics (3 h)
  E5.E What-If preview (9 h, biggest investment, high demo value)
```

**Total test coverage delta:** +17 backend tests (pytest floor 875 ->
892), +19 frontend tests (vitest 193 -> 212). Both ruff and AST-
invariant Proposer Pattern guards continue to hold.

**Risk surface per task** logged in the proposal text; the highest-
impact one is E5.C's touch of `multi_agent.py` (8 consensus tests
must remain green) -- mitigate with targeted-first protocol.

---

## Hermes Vision (Confederation, queued)

The original elite-architect prompt described "Hermes" as a central
Multi-Agent Consensus orchestrator — a confederation pattern where
the frontend is a high-throughput telemetry receiver and not a REST
poller. After T3.1 (WebSocket pipeline) lands, the building blocks
exist:

```
                    ┌──────────────────────────────────────────────┐
                    │                  HERMES ORCHESTRATOR          │
                    │  (backend/hermes_orchestrator.py — NEW)       │
                    │                                                │
                    │  1. Fan-in:                                    │
                    │     - Kalman pipeline (telemetry events)       │
                    │     - CMMS state machine (WO transitions)      │
                    │     - Predictive trigger (z-score breaches)    │
                    │     - Multi-agent consensus (deterministic)    │
                    │     - Physics validators (PUE, SHI, BBC)       │
                    │                                                │
                    │  2. Filtering + dedup:                         │
                    │     - bufferTime(50ms) per channel             │
                    │     - distinctUntilChanged on payload          │
                    │     - rate-limited rebroadcast                 │
                    │                                                │
                    │  3. Multiplex to clients via WS                │
                    └──────────────────────────────────────────────┘
                                          │
                          ┌───────────────┴───────────────┐
                          ▼                               ▼
                    Frontend client                 ML training pipeline
                    (Mission Control,               (DPO edge healing,
                     Maintenance, etc.)              Sprint 6)
```

The vision is intentionally **deferred until T3.1 + T3.3 land** —
without those building blocks, Hermes is premature abstraction.

When ready, the Hermes orchestrator gets:
- Its own ADR — **ADR-011** (the original "ADR-010" reservation is void:
  ADR-010 was assigned to the dual-graph asset taxonomy on 2026-05-17) —
  documenting the consensus protocol
- An async test harness simulating 1000 events/sec
- A backpressure metrics dashboard (built on the existing telemetry
  Activity Strip pattern)
- A "kill switch" feature flag so the legacy REST endpoints stay
  available for emergency rollback

**Acceptance criteria for Hermes V1.0**:
- 100 Hz sustained throughput from backend → multiplexed WS
- Frontend stays at 60 FPS with all modules subscribing
- One subscriber crash does not kill the orchestrator
- Hermes itself observable: `GET /api/hermes/health` shows queue
  depths per channel + WS connection count + backpressure metrics

---

## Recommended sequencing

For a CET interview at Microsoft CO+I in early August 2026:

```
NOW (this session)         T1.1-T1.6        ~8h     PANEL READINESS
+1 week                    T2.1 (IIFE)      3-4d    Cleaner DevTools view
+2 weeks                   T2.2-T2.4        4-5d    Tests + router + Vite
+3 weeks                   T3.1 (Hermes WS) 5-7d    Real-time differentiator
+4 weeks                   T3.3 (Diag ML)   3d      Multi-agent depth
+5 weeks                   Hermes V1.0      ~5d     Confederation arrives

INTERVIEW WINDOW           early August 2026
```

For continued V11 development without panel pressure: pick by
appetite. Tier 3 in any order. Hermes after T3.1 + T3.3.

---

**Locked: 2026-05-10. Updates require explicit version-bump of this
file with a new "supersedes" line at the top.**
