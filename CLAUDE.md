# DC-EPMS PRO - Claude Code Project Memory

**Project**: DC-EPMS PRO (Edge Operations Platform for Tier IV AI factories)
**Repository**: `C:\dev\DC-EPMS_PRO`
**Maintainer**: Wilmer Y. Angel Beltran (a3semi - A-Cubed Semiconductor Systems Inc.)
**Target**: CET role at Microsoft Cloud Operations + Innovation (CO+I), interview early August 2026.

## 🎯 What this project is

DC-EPMS PRO simulates **A3-Alpha Toronto Area** under **Path C2** (sealed 2026-05-05): a 67 MW Tier IV AI factory with 368 racks total.

- Phase 1 (Buildings A/B deployed): **118 NVIDIA GB200 NVL72 racks @ 142 kW**, 480 VAC trifásico 2N, UPS Schneider Galaxy VX, chillers York YZ N+1.
- Phase 2 (Building D target Q2 2026): **250 NVIDIA GB300 NVL144 racks @ 200 kW**, upstream 3-phase AC at 35 kVAC trifásico into MV Rectifier, 800 VDC unipolar TN-S downstream, SSCB 1-100 µs clearing per IEC 60947-2, BESS 2.5 MWh, full DLC retrofit to 12 VDC at GPU.
- Rubin Ultra excluded from V9 scope.

**🚨 Vocabulary discipline (CRITICAL — panel-grade fence)**: "trifásico" applies ONLY to AC upstream of MV Rectifier. The 800 VDC bus is **unipolar TN-S** (no phases). Saying "800 VDC trifásico" is a credibility-destroying error in CO+I panel review. Schema names MUST encode polarity: `voltage_v_phase_ab/bc/ca` for AC, `voltage_v_dc_bus` for DC. The v1 proto schema (`backend/telemetry_proto/v1/telemetry.proto`) enforces this structurally via `oneof topology { ac_three_phase | dc_unipolar }` — see `tests/test_telemetry_proto_schema.py::TestVocabularyFence`.

## 📊 CURRENT STATE (synced 2026-06-12 — EPIC 5 CLOSED E5.A-E5.G; next = S4 bug closeout)

```
HEAD:  EPIC 5 SPRINT 3 — E5.F + E5.G (2026-06-12, commit 3269ae9):
       reality check revealed Epic 5 Sprints 1+2 AND E5.E were already
       on master since 2026-05-23 (0aa9e6b3 / 5b55111 / c1d334a) —
       the v11.18 plan's S3/S4 windows assumed them pending. This
       session completed the in-flight Sprint 3 working-tree diff
       with its missing test artifacts and committed:
       * E5.F OptimizerConfig inspector — config_snapshot() serialises
         every UPPER_CASE control-law threshold + PUE target +
         surfaces; GET /api/optimizer/config (read-only per ADR-006,
         503 when DC_EPMS_OPTIMIZER_ENABLED default-OFF); collapsed
         "Config & Bounds" panel, human-readable units (900 s = 15 min),
         lazy fetch on open.
       * E5.G rejection-reason analytics — pure client-side word/tag
         clustering over the E5.B approval feed; gated <10 rejections;
         ES/EN stopwords; operator-authored reasons escaped (S-SEC-01).
       Live smoke per S-RUNTIME-01: fresh boot (components=113),
       /api/optimizer/config -> 503 default-OFF on the wire; the
       200-enabled posture covered by TestClient with service wired.
       EPIC 5 IS NOW CLOSED COMPLETE (E5.A-E5.G). MVP runs ~3 weeks
       ahead of plan; S4 remaining scope = bug closeout only (T1.6,
       DC-EPMS-029c, DC-EPMS-TEST-01, E2E WARNING triage).
       Previous HEAD — MVP S2 BACKEND GROUNDING (2026-06-11, same session as S1,
       executed ahead of schedule under the blanket GO):
       * 3c0a2a3 S2-A: gen_farm_d + mv_bus_d + stepup_xfmr_d join the
         site_model.yml graph (Path D standby generation; 110 -> 113
         components; registry rows gain real graph ids).
       * 92f3fd9 S2-B: Phase 2 DESIGN-sim telemetry — 6 new generator
         types (utility_intake metadata-keyed 27.5/35 kV, mv_rectifier,
         sscb, dc_bus voltage_v_dc_bus, bess, genset_farm dead-bus
         standby) + dc_bus_sag anomaly + Kalman calibration for 9 new
         metrics. Live channels 238 -> 281.
       * 66288d4 S2-C: What-If DAG + N-1 Shadow extended to Building D
         (farm auto-run on utility-D loss, mvrect 2-input merge, hall_d
         as N-1 load; sscb_d/dc_bus_d = critical, util_d = warning).
       * 63bb9f0 smoke tool: scripts/smoke_phase2_channels.py — live
         SSE PASS (281 channels, vocab fence clean), boot verified
         per S-RUNTIME-01 (knowledge_graph components=113).
       Earlier same day — SLD REENGINEERING A-C. Root cause of "no veo las
       miniaturas" was structural: #view-power booted into the 2.5D
       iso stage, which carried ZERO Phase 2 / 50 MW content.
       * 345e098 Batch A: iso stage RETIRED (power_ups_iso.js +
         power_cam.js deleted, -851 LOC). Flat registry-driven SLD =
         the ONE Power surface; live Kalman severity finally paints
         it (it previously painted only the iso blocks). SLD-R1
         regression fence: farm + Phase 2 asserted on the DEFAULT
         surface after initPowerView().
       * cf0c331 Batch B: genset farm LEVEL-OF-DETAIL. LOD 0 =
         honest switchgear-lineup block at fit-width (count/rating/
         N+2/farm MW from power_budget.js, state summary, expand
         hint). LOD 1 = click -> viewBox focus + one REAL cubicle
         per unit (ANSI 52, gen glyph, G01..G22, rating, NFPA 110
         state strip). farmUnits() roster = single source.
       * a6eecd1 Batch C: S-VISUAL-01 visual-closure gate (registry
         32 skills / 15 categories) + preview tool renders the
         DEFAULT surface first + farm LOD 1 section.
       MVP PLAN S1-S6 APPROVED (operator: "aprobamos todo") -- see
       ROADMAP-V11.md v11.18. Decisions: iso retired (not demoted),
       Epic 5 complete (3 sprints), edge/ OUT of MVP unless the A3
       manifest lands before S3. NEXT: S2 = Bloque 3 backend
       grounding (farm into site_model graph + Phase 2 design-sim
       telemetry channels + DAG/N-1 over Building D).
       Previous sync 2026-06-10: (a) repo hygiene -- ruff gate fix acf00b9, root
       batch-era artifacts archived ca31e09, BMO runbooks 9abd84a,
       doc-syncs 585763f/1859aee/bf16ca1; (b) DIAGRAM REBUILD
       Batches 0-5: shared diagram kit + canonical node registry
       0b3726f, Power SLD + Phase 2 800 VDC branch 9b99b18, Cooling
       P&ID + availability DAG b9787db, registry-driven HLD (static
       SVG retired, 480VDC vocab fix) de00cc2, site-graph live
       severity + SLD cross-link 84c1336, Power & UPS engineering
       detail (NFPA 110 genset sequence, IEC 62040-3 UPS modes)
       66d9eb2; (c) Batch 6 closure: ADR-012 + S-DIAGRAM-01 +
       preview tool. Stable baseline =
       v0.13.0 "Proactive Edge" (2026-05-19). Post-v0.17.0 work delivered:
       * Epic 1: full 4-agent fleet LLM-augmented + multi-agent façade.
       * Epic 2 (v0.13.0): "The Optimizer" proactive edge-agent (2.A-2.E).
       * Epic 3 (3.A + 3.C): Capacity Planner + Carbon/Grid agents → 6-agent fleet.
         3.B (OT Security via Morpheus) deferred pending GO.
       * Epic 4: Forensic Ledger (HMAC-chained, append-only) + Proposer-chain
         closure + Rollback Harness. ADR-011. S-LEDGER-01 + S-PROPOSER-01.
       * Epic 6 (13 atomic commits): 23 canonical MOP bodies + richer-template
         adoption + 6-vector risk taxonomy + parameterized-abort HARD_STOP +
         Library Pre-seed + Cuatro Ojos alignment.
       * v0.17.0: Life Safety + Combustible asset categories (6 new MOPs).
       * Gentle IA Bloque 4 cerrado: H13 Apply Continuity (5e35dfc),
         H16 Skill Resolution Feedback (8682fdf), H06 Phase DAG (1b26786).
       * Epic 8 (7 commits): canonical v1 telemetry.proto + schema invariant
         tests (37) + generated Python stubs + pipeline-to-proto adapter
         (34 tests) + SSE endpoint /api/telemetry/stream/proto (12 tests).
         Live smoke: 243 envelopes/tick decoded clean, vocab fence preserved
         through wire, ~93 Kbps wire util at dev scale.
       * Epic 9 (2 commits): BB84 educational QKD simulator + Forensic Ledger
         provenance + HMI. 28ca649 chore boot-stability (starlette<0.39 pin
         to match FastAPI 0.115, agent_copilot lifespan migration, protobuf
         excluded from ruff). 948f33c feat: backend/crypto/bb84_core.py +
         backend/services/qkd_service.py + ForensicLedger qkd_provider
         protocol + /api/qkd/status endpoint + frontend views/quantum.js
         (QBER badge, pool stats, audit table). Honest framing preserved
         throughout (educational simulator, not a real quantum channel).
       * Epic 10 (4 commits): backend IAM core (4 roles L1_OPERATOR /
         L2_TECHNICIAN / SAFETY_OFFICER / FACILITY_MANAGER, stateless JWT
         HS256, PBKDF2-SHA256 pwd hashing, login endpoint) 5a8252e;
         Maker-Checker dual-JWT enforcement on procedure sign (distinct
         SAFETY_OFFICER subs + content-sha gate, 409/403) a68381e; frontend
         login + auth gate + API middleware 58f648a; QKD-gated signing UI
         (blocks firmas when QBER >= 11%) b186bb3. Backward-compatible with
         the pre-Epic-10 body-only sign path. Pushed to origin/master.

Tests:   backend 1416 passed (E5.F +2 config inspector; S2 +5 design-sim;
         Epic 10 +60; incl. 7 PG integration) — full pytest ~70s, 0 fail,
         5 deselected (slow/FAISS).
         frontend 523 vitest passed across 31 files (SLD Reengineering
         -> 500: SLD-R1 default-surface fence + SLD-R2 farm LOD;
         MVP S2-C -> 513: Building D DAG + N-1 coverage;
         Epic 5 Sprint 3 -> 523: E5.F render/units/postures/XSS +
         E5.G empty/sparse/dense/pure-fn/XSS).
         GraphRAG: 14 knowledge documents at boot (+2 Q-state track:
         galaxy-vx-internal-oneline, genset-farm-mv-paralleling).
         BMS catalog: 62 tags (+10 PWR.UPS_x.Qn_POS breaker positions).
         Architect library: 29 catalog MOPs pre-seeded, all audit=APPROVE.
         Skills registry: 32 explicit skills across 15 categories
         (S-VISUAL-01 added: visual closure on the DEFAULT rendered
         surface, never on markup strings alone).
         ruff: 0 violations in backend/ (generated protobuf excluded).

Perf baseline (AMD Ryzen + Win11):
  Numba JIT cold compile     : 4.8 ms
  Hot compute() / 238 channels: 5.11 ms / window
  Per-step Kalman             : 4.3 µs

Runtime:
  backend  = `python backend\main.py` on :8080 (native, NOT docker)
  epms-db  = TimescaleDB pg16, DB `dcepms`, user `epms` (Docker container)

V9 scope = feature-complete. Live backlog = docs/ROADMAP-V11.md (locked 2026-05-10).
```

## 🏗️ ARCHITECTURE (high-level)

```
backend/                     FastAPI + asyncpg — ~50 endpoints
  main.py                    central hub, ~50+ endpoints, lifespan boot
  physics_engine.py + physics/   facade + 4 modules (it_thermal, mechanical, electrical, heat_rejection)
  agent_*.py                 Sprint 10.1 multi-agent façade (6 agents + Safety Officer veto)
  agents/procedure_architect.py  H13 Apply Continuity wired
  agent_continuity.py        H13 CheckpointStore (JSONL append-only)
  skill_audit.py             H16 commit citation auditor + CLI
  phase_dag.py               H06 PhaseTracker + enforce_phase_dependency decorator
  procedure_engine.py / witness_engine.py / procedure_generator.py
  cmms_*.py                  Sprint 6 CMMS Core (91 assets)
  loto_auditor_*.py          6-pillar validator
  telemetry_simulator.py / telemetry_pipeline.py / cyber_physical_tools.py  Sprint 5 Kalman
  telemetry_proto/v1/        Epic 8 canonical wire format (.proto + _pb2)
  telemetry_proto_adapter.py Epic 8 pipeline → strict-SI envelopes
  telemetry_proto_stream.py  Epic 8 SSE encoder
  ledger/                    Epic 4 Forensic Ledger (Epic 9: qkd_provider seam)
  crypto/                    Epic 9 BB84 educational QKD simulator
  services/                  Epic 9 QKDService pool + status payload helper
  optimizer*.py              Epic 2 Optimizer + approve/reject routes
  graphrag_*.py / rag_service.py / knowledge_graph.py
  database.py / bms_connector.py / metrics_router.py
  migrations/                SQL migrations (apply with psql + restart)
  hal/                       Cummins, ASCO, Russelectric adapters
  mcp_server.py              Claude Desktop stdio subprocess
frontend/                    Fully modular ES (T2.1 closed; Diagram Rebuild 2026-06-10)
  index.html + assets/js/main.js  single ES-module entry
  assets/js/core/            router, bootstrap, telemetry_engine, hermes_events, ...
    diagram_kit.js           ADR-012 shared symbols/wires/legend/severity (orthoPath throws on diagonals)
    node_registry.js         ADR-012 canonical asset identity (SLD<->topo<->graph<->Kalman prefixes)
    power_grid.js            electrical DAG (NFPA 110 genset sequence, IEC 62040-3 UPS modes)
    cooling_grid.js          hydraulic availability DAG (N+1/2N peer degradation)
    asset_engineering.js     per-asset engineering sections (UPS mimic, genset phase strip, ...)
  assets/js/views/           12 views (overview, mission_control, copilot, bms, loto, ...)
config/
  site_model.yml             110 components, 91 locations
  telemetry_channels.yml     per-channel R/Q/F (Sprint 5 C3)
  procedures/                executable MOP YAMLs
  knowledge/                 GraphRAG markdown corpus
  .env                       PG creds (gitignored — see DC-EPMS-DB-001)
data/chroma_db/              20-doc 4-tier ChromaDB corpus
tests/                       1288 backend tests + 313 frontend vitest
docs/
  adr/                       ADRs (MADR format; ADR-011 ledger, ADR-012 diagram kit + node registry)
  ROADMAP-V11.md             live backlog (v11.7, 2026-05-19)
  rfc/                       telemetry v0.9 historical + v1 sizing+OCP RFC (Epic 8)
  skills/skill-registry.md   30 skills across 13 categories
  skills/agent-harness-registry.md  Gentle IA 30-harness master registry
  engram/main-context.md     architectural state snapshot
```

### Key endpoints (~50 total)

- **Health + telemetry**: `/api/health`, `/api/telemetry`, `/api/telemetry/stream` (JSON SSE), `/api/telemetry/stream/proto` (Epic 8 v1 proto SSE).
- **Site model**: `/api/site/components`, `/api/site/loto-impact/{id}`, `/api/site/health`.
- **GraphRAG**: `/api/graph/query`, `/api/graph/loto`, `/api/graph/upstream`.
- **RAG**: `/api/rag/query`, `/api/rag/docs`.
- **LOTO Auditor**: 4 endpoints under `/api/loto` (audit / get / markdown / recent).
- **Procedures**: `/api/procedures*` + Procedure Generator routes (SOP/MOP/EOP/EMP).
- **CMMS**: `/api/cmms/draft`, `/api/cmms/drafts/{id}`, `/api/cmms/approve/{id}` (SME_L6 RBAC).
- **Witness**: `/api/witness/sign`, `/api/witness/drafts`.
- **Ledger**: `/api/ledger/entries`, `/api/ledger/verify`, `/api/bms/write` (chained), `/api/bms/revert/{id}`.
- **QKD (Epic 9, educational)**: `/api/qkd/status` (pool depth + QBER + recent audit; HMI surface in `views/quantum.js`).
- **Optimizer**: queue + `/api/optimizer/approve|reject` (SME_L6 RBAC).
- **Agent Copilot**: `/agent/stream` (SSE).
- **Hermes EDA**: `/api/hermes` (WebSocket, multiplexed: telemetry + alerts + consensus).
- **MOPs**: `/api/mops` + `/api/mops/{doc_id}` + `/api/mops/generate`.

### LOTO Auditor 6-Pillar (all green)

| Pillar | Function | Status |
|---|---|---|
| 1 | Topology + GraphRAG impact radius | ✅ |
| 2 | Redundancy 2N validation | ✅ |
| 3 | Capacitor discharge per NEC 460.6 | ✅ |
| 4 | Witness Gate per CSA Z462 | ✅ |
| 5 | Cooling chain check | ✅ |
| 6 | PPE matrix per NFPA 70E | ✅ |

## 🐛 BUGS REGISTRY — open / deferred only

(Closed bugs are in git history. The full closed list lived in the pre-2026-05-27 CLAUDE.md if needed.)

- **DC-EPMS-TEST-01** (LOW, test hygiene) — `tests/frontend/overview.test.js` leaks an unstubbed relative `fetch` when run in isolation (unhandled `ECONNREFUSED ::1:3000` against happy-dom's default origin). Pre-existing (reproduced on clean HEAD 2026-06-10); all assertions pass. Fix: stub fetch in the overview fixture. Found during the Q-state track.
- **DC-EPMS-029c** (LOW) — `physics_engine.validate_site()` SHI rollup insensitive to some LOTO types (chiller / cooling_tower / chw_pump / RPP). simulate_loto output is structurally correct; only the SHI delta is unreactive. UPS + CDU scenarios DO produce SHI delta, sufficient for demo. Resolution: tune `physics_engine` module thresholds (2-3h surgical). Target: V10 / dedicated bite.
- **E2E audit WARNING-tier findings** in `docs/audit/E2E_Security_Orphan_Audit.md` — the 3 CRITICAL RBAC findings closed in `b34efb1`; WARNINGs remain open.
- **TODO(asset-manufacturer-migration)**: S-VENDOR-EATON-01 string-matches context for "eaton" today. Next sprint should add `Asset.manufacturer` to `backend/cmms_models.py` for deterministic lookup. Tracked in `backend/agents/procedure_architect.py`.
- **DC-EPMS-036** (RESOLVED 2026-05-28) — venv contamination. An uncommitted langchain-1.x / crewai / instructor experiment (parallel to the still-uncommitted `package.json` JS deps `@anthropic-ai/sdk` + `@langchain/anthropic` + `langchain`) pip-installed `langchain-core 1.4.0` **violating the pyproject pin `<0.3.0`**, which dragged in `chromadb 1.1.1` + `transformers 4.57.6` and downgraded `protobuf` to 5.29.6. Two failures resulted: (a) Epic 8 proto stubs (gencode 6.31.1) refused to import under protobuf 5.29.6; (b) `from transformers import GPT2TokenizerFast` (via nemoguardrails + incompatible langchain-core) hung past the 30 s `pytest-timeout`. **Fix**: forensic backup (`pip freeze` + `chroma_db/` copy → `logs/env-rollback-20260528-210919/`), `pip install -e .[all]` to restore pyproject baseline (chromadb 0.5.18, langchain-core 0.2.43, pydantic 2.9.2), uninstall orphans (crewai*, instructor, langchain-anthropic, langchain-protocol), bump `protobuf` to 6.33.6 (resolver floated otel up to 1.42.1). `pyproject` now pins `protobuf>=6.31.1,<7` to prevent recurrence. `pip check` clean; suite restored to 1409/368. The JS counterpart (`package.json` deps `@anthropic-ai/sdk` + `@langchain/anthropic` + `langchain`) was reverted 2026-05-28 — zero frontend usage, Node libs incompatible with the static-ESM frontend, no bundler — so nothing to rescue. Fully closed.

## 🗺️ ROADMAP

**V9 scope is feature-complete** (tags `v0.5.0` → `v0.10.13` + Epics 1-6 + 8 + v0.17.0). Live backlog: `docs/ROADMAP-V11.md` (v11.7).

Delivered headline tracks: Sprint 5 telemetry+Kalman, Sprint 5.5b PUE physics, Sprint 6 CMMS Core, Sprint 7.1 Tech Assist, Sprint 9.1 predictive WO, Sprint 10.1 multi-agent + Safety Officer veto, HMI Tier A/B/C polish, B1 Mission Control (three.js), 2.5D isometric SLD + DAG engine, SCADA asset panel, ProcedureGenerator (dual-graph taxonomy, micro-LOTO, hyperscale RBAC), Hermes WS EDA plane, CET-gated edge healing, Optimizer (Epic 2), Capacity Planner + Carbon/Grid (Epic 3), Forensic Ledger + Proposer-chain (Epic 4), Procedure Architect catalog + richer-template (Epic 6), Gentle IA Bloque 4 (H06/H13/H16), Epic 8 telemetry v1 wire format, Epic 9 BB84 educational QKD + Ledger provenance seam.

**Deferred → V11**: DPO edge-healing revival, Alarm Storm Mitigation (Bayesian correlation), EOP Abort <100 ms (async event bus), demo recording + DEMO_SCRIPT v5.

## 🛠️ TOOLING CONSTRAINTS

- **Hardware**: ASUS Zephyrus G14, AMD Ryzen, RTX 3060 6GB, CUDA 13.2, Windows 11 + WSL2 + Docker Desktop.
- **Python**: 3.12.10, venv at `C:\dev\DC-EPMS_PRO\.venv`. Activate: `.\.venv\Scripts\Activate.ps1`.
- **LM Studio**: gemma-4-e2b-it on `127.0.0.1:1234`.
- **TimescaleDB**: Docker container `epms-db` on port 5432, DB `dcepms`, user `epms`, pwd `epms_dev_only_change_me`. Backend reads PG creds from `config/.env` — MUST be set or it falls back to non-existent defaults (DC-EPMS-DB-001 lesson).
- **FastAPI backend**: port 8080, launched native via `python backend\main.py`. `scripts/start.ps1` bootstraps venv + DB + backend.
- **Claude Desktop**: MCP server `dc-epms-pro` (stdio).
- **Libraries**: NetworkX 3.6.1, FAISS 1.13.2, sentence-transformers 3.2.1 (lazy-loaded), ChromaDB persistent client at `data/chroma_db/`, grpcio-tools 1.80.0 (Epic 8 stub regeneration).
- **pre-commit installed** but USE `--no-verify` for orchestrator commits with manual AST + pytest validation.

**Critical operational notes**:
- Docker `epms-backend` container from old deployment auto-restarts and steals port 8080. Always `docker ps` and `docker stop epms-backend` if conflict.
- FAISS has AVX2 access violation on AMD Ryzen + Windows (DC-EPMS-001). Mitigated via `not slow` markers.
- The `epms-db` container should stay running. If `Exited`, bring it back with `docker start epms-db` and wait for `docker inspect --format "{{.State.Health.Status}}" epms-db` = `healthy` before launching the backend.
- Epic 8 stub regeneration: `.\scripts\gen_telemetry_proto_stubs.ps1` (worktree-aware, installs grpcio-tools on demand).

## 🎓 WORKING STYLE — "Fine Tuning Quirúrgico" (non-negotiable)

1. **Never assume defaults silently** — surface every decision with explicit rationale and reality check before coding.
2. **Reality check over hype** — if it's not demonstrable on a 6 GB RTX 3060 laptop, say so and propose what IS demonstrable.
3. **Approve-then-execute** — present plan in clear bullets, wait for explicit "GO" (Wilmer says "GO" / "approved" / "luz verde") before generating code.
4. **Atomic batches** — break sprints into 2-3 batches per session, each independently validatable.
5. **Defensive coding** — backup files (`.bak_pre_*`) before patching, AST validation before disk writes, syntax checks before tests.
6. **Honest scope** — 6 weeks means 6 weeks. No padding, no hidden buffers.
7. **ADRs** — significant decisions get ADRs in MADR format under `docs/adr/`.
8. **Tag is not closure** — verify with `git log --oneline --decorate -n 5` that the tag points to a NEW commit, not the predecessor.

## 🔒 V9 AI-FACTORY SPEED PROTOCOL (5 rules — default mode)

1. **Ingesta Total**: every response begins from a conscious read of project state (current bugs, decisions, container state, test count, latest commit hash). No cached assumptions.
2. **Migración CLI**: every multi-step operation gets a PowerShell or Python orchestrator. No copy-paste of 20-line snippets.
3. **Multi-Agente Lógica + QA**: every code artifact comes with its test artifact in the same turn. Tests are not deferred.
4. **Grounding Forzado**: architectural decisions cite the standard, the file path, and the specific section. No vague hand-waves.
5. **CI/CD LOCAL**: all validation is local. ZERO `.github/workflows/`. Edge-first autonomy means no cloud CI dependency.

## 🛡️ HYPERSCALE OVERRIDE PROTOCOL (7 rules)

When Wilmer initiates `[SYSTEM OVERRIDE: HYPERSCALE DEVELOPMENT MODE INITIATED]`, standard limits suspend:

1. **Zero-Placeholder Policy**: NO `pass`, `TODO`, "agrega tu lógica aquí". Production-ready even if 800+ lines.
2. **Deep Chain of Thought**: open `<architecture_analysis>` block before any code, exhaustively analysing physical dependencies (Thermodynamics, 800 VDC), 2N redundancy impact, race conditions.
3. **Multi-Agente Full Stack Delivery**: single turn delivers core code + integration tests (pytest + fixtures) + local PowerShell injection script.
4. **Defensive Coding Agresivo**: industrial-grade exception handling. Assume network failures and hardware degradation.
5. **Silencio Administrativo**: text outside code blocks limited to architectural decisions (ADRs) and reality checks.
6. **Documentation Drift Prevention**: auto-update CLAUDE.md if work alters architectural baseline.
7. **Honest Tech Debt Registry**: every batch closure generates DC-EPMS-NNN entry if any check failed during execution. Pre-commit failures, partial commits, false [OK] reports — all get tracked.

## ⚠️ POWERSHELL PRE-DELIVERY RULES (13 + ASCII-only)

Hard rules for every PowerShell artifact, distilled across Batches 1+2+3+3.5+5 and Camino 1:

1. **No `<` or `>` chars** inside double-quoted strings. PowerShell parses as redirection operators. Includes `->` arrow notation.
2. **No em-dashes anywhere** in PowerShell code. Replace with hyphen-minus or remove.
3. **No double-dash word starting tokens** in argument-like positions inside strings.
4. **Variable colons escape with backtick**: write `` `$variable: `` not `$variable:`.
5. **No `python -c` heredocs** with embedded code. Always write a `.py` file and invoke it.
6. **Wrap native command invocations** with `$ErrorActionPreference = 'Continue'` when stderr might be non-error (git, docker).
7. **AST-validate Python before disk write**, TOML-validate `pyproject.toml` before disk write.
8. **Validate $LASTEXITCODE before declaring [OK]**. Warning text on stderr can be misinterpreted as success.
9. **ASCII-only commit messages**.
10. **Use `Convert-Path` or `Get-AbsolutePath`** for .NET I/O calls. `[System.IO.File]::*` resolves relative paths against system PWD, not PowerShell CWD.
11. **`String.Replace`, NOT `[regex]::Replace`** when replacement contains `$N` patterns (interpreted as RegexOptions enum, breaks).
12. **Use UTF8NoBOM encoding** when writing Python files. `Set-Content -Encoding UTF8` preserves BOM; use `[System.IO.File]::WriteAllText` with `New-Object System.Text.UTF8Encoding($false)`.
13. **Multi-variant tolerance for special chars** (middle-dot U+00B7, multiplication sign U+00D7) — check all encoding variants when matching.

## 📜 CLOSING DISCIPLINE (Batch 3.5 Recovery lesson)

- **Tag is not closure**. After tagging, verify with `git log --oneline --decorate -n 5` that the tag points to a NEW commit.
- **Pre-commit hooks recursively modify**. Use `git commit --no-verify` for orchestrator commits IF (and only if) changes have already passed manual AST validation and pytest.
- **Honest failure reporting**. Every batch closure must report what was attempted but failed.
- **Forensic tarball before destructive ops**. Save `.tar.gz` before any operation that rewrites git history.

## 🔌 V9.1 PowerShell Native Mandate (in force after DC-EPMS-035)

- **Filesystem ops on Windows**: PowerShell-native ONLY. NEVER `mkdir scripts\path` via Bash (backslash collapse).
- **Use**: `New-Item -ItemType Directory -Path 'a/b/c' -Force` (forward slashes), `Get-ChildItem`, `Move-Item`, `Remove-Item`, `Test-Path`.
- **Defensive**: `Test-Path -PathType Container` MUST verify destination is a directory BEFORE bulk `Move-Item`. `Move-Item -Force` to a non-existent directory creates a FILE; subsequent moves overwrite it.
- **Filtering**: `Select-String` (not `findstr` / `grep`).
- **Heredocs**: NO `python -c '...'` heredocs — write a `.py` file and invoke it.

## 🗂️ CONNECTORS / TOOLS

- **Docker**: prefer `docker compose` (V2) over `docker-compose` (V1).
- **Git**: always `--no-verify` on orchestrator commits with manual AST + pytest validation.
- **Tests**: `pytest -m "not slow" --tb=short` (slow markers exclude FAISS AVX2 issue).
- **Browser**: http://127.0.0.1:8080/ for HMI smoke tests.
- **MCP**: stdio server `dc-epms-pro` for Claude Desktop.

## 📝 COMMUNICATION PREFERENCES

- **Language**: Spanish-English mix. Respond in the language Wilmer uses.
- **Pushback recognition**: when Wilmer pushes back ("ninguna de tus opciones evalua"), recognise as legitimate critical thinking. Re-analyse, do not capitulate.
- **Reality check first**: ALWAYS verify state before suggesting work. `git log --oneline -n 5` + `git status` before proposing.
- **Path C2 vocabulary**: precise terminology. "Upstream 3-phase AC into MV Rectifier downstream 800 VDC unipolar TN-S" — NOT "800 VDC trifásico".

## 🎯 IMMEDIATE NEXT STEPS (when resuming)

1. **Verify state**: `git log --oneline -n 6` (HEAD must be `66d9eb2` or descendant — Diagram Rebuild B5). `git status` (expect a clean tree — `.ai/`, `logs/`, `.claude/settings.local.json` are gitignored since the 2026-06-10 hygiene session).
2. **Bring up the stack**:
   - `docker start epms-db` → wait for `docker inspect --format "{{.State.Health.Status}}" epms-db` = `healthy`.
   - `python backend\main.py` (native, :8080) — confirm `curl http://127.0.0.1:8080/api/health` reports `postgres: up` / `database: dcepms`. If `down`, see DC-EPMS-DB-001.
   - One-shot: `.\scripts\start.ps1`.
3. **Activate venv** for any test / CLI work: `.\.venv\Scripts\Activate.ps1`.
4. **Read `docs/ROADMAP-V11.md`** — the live backlog. Tier 1 = demo readiness.
5. **Wait for explicit GO** from Wilmer before starting any V11 work.

## 🧠 OPERATIONAL HARNESS (post-v0.12.0 — binding for ALL sessions)

- **OPERATIONAL RULE — Skill Digestion Harness.** Before modifying any file, you MUST consult `docs/skills/skill-registry.md`, extract the 3-4 relevant rules for that task (cited by ID, e.g. `S-DET-01`, `S-SEC-01`, `S-TELEMETRY-01`, `S-VOCAB-01`), and strictly adhere to them. If a directive conflicts with a skill, surface the conflict BEFORE executing — do not silently override. The architectural snapshot lives at `docs/engram/main-context.md` — read it whenever working context has drifted (new session, long compaction, ambiguous baseline).
- **RUNTIME CONSTRAINT — `S-RUNTIME-01`.** The Python backend does NOT hot-reload. After any backend / agent-wiring change, the active process MUST be restarted and the `[BOOT]` log signature in `logs/epms_pro.log` verified alongside `/api/health` before conducting smoke tests — to prevent stale-code false positives (the post-Epic-1 smoke surfaced exactly this failure mode: PID 46172 ran a pre-T3.3 module for 2+ days while unit tests + frontend smoke all passed, silently returning empty narratives).
- **Companion files (binding)**:
  - `docs/engram/main-context.md` — architectural state snapshot.
  - `docs/skills/skill-registry.md` — 32 skills across 15 categories. Latest addition (SLD Reengineering): `S-VISUAL-01` (visual work closes on the DEFAULT rendered surface — vitest on the activated view + regenerated preview eyeballed, never markup strings alone); prior: `S-DIAGRAM-01` (ADR-012), `S-TELEMETRY-01`, `S-OCP-CDU-01`, `S-PTP-01`.
  - `docs/skills/agent-harness-registry.md` — 30-harness Gentle IA master registry. **Bloque 4 cerrado completo** (H06/H13/H16 all OPERATIVO). Implementations: `backend/phase_dag.py` + `backend/agent_continuity.py` + `backend/skill_audit.py`.
- **Audit CLI**: `python -m backend.skill_audit --since HEAD~N` prints per-commit CLEAN / GAPS / UNKNOWNS reports against the registry.

## ⏸ PAUSE_STATE (last updated 2026-06-12 — EPIC 5 CLOSED E5.A-E5.G; next = S4 bug closeout)

> **✅ EPIC 5 CLOSED COMPLETE (2026-06-12, commit `3269ae9`).** The
> session's reality check found Sprints 1+2 + E5.E already on master
> since 2026-05-23 (`0aa9e6b3` / `5b55111` / `c1d334a`) — the v11.18
> plan windows S3/S4 assumed them pending. Sprint 3 (E5.F config
> inspector + E5.G rejection analytics) was found in-flight in the
> working tree, completed with its test artifacts (+2 pytest, +10
> vitest) and committed. Floors: **1416 pytest / 523 vitest (31
> files)**, ruff clean. Live smoke per S-RUNTIME-01: fresh boot
> 2026-06-12 05:46 (components=113, graphrag 14), GET
> /api/optimizer/config -> 503 with the Optimizer default-OFF
> (200-enabled posture covered by TestClient). Backend left RUNNING
> on :8080. NOT yet pushed to origin (local commits: `3269ae9` +
> doc-sync).
>
> **🔴 NEXT SESSION ENTRY POINT — MVP S4: bug closeout** (the Epic 5
> portion of S4 is done; MVP runs ~3 weeks ahead of the jul 2-8
> window): T1.6, DC-EPMS-029c (SHI rollup insensitivity), 
> DC-EPMS-TEST-01 (overview.test.js fetch leak), E2E WARNING triage
> (docs/audit/E2E_Security_Orphan_Audit.md). Then S5 = FEATURE
> FREEZE -> T1.1 Mission Control eyeball validation, DEMO_SCRIPT v5,
> full regression, tag v1.0.0-rc. Per S-VISUAL-01 the new optimizer
> HMI surfaces (Config & Bounds panel + rejection analytics block)
> still await operator eyeball on the live view (Optimizer view ->
> open history sidebar / expand Config & Bounds; nota: el Optimizer
> es default-OFF, el panel muestra "Optimizer not running" salvo
> DC_EPMS_OPTIMIZER_ENABLED=true).

> **✅ SLD REENGINEERING A-C CLOSED (2026-06-11, operator GO "aprobamos
> todo").** Root cause of "no veo las miniaturas" was NOT the mini
> size: `power_cam.js` defaulted #view-power to the 2.5D ISO stage,
> which carried ZERO Phase 2 / 50 MW content — everything new lived on
> the flat SLD behind `.sld-legacy-hidden`. Delivered:
> * `345e098` Batch A — iso stage + camera RETIRED (-851 LOC). Flat
>   SLD = the ONE Power surface. Live Kalman severity retargeted to
>   `.pf-node` (was painting only the iso blocks). SLD-R1 regression
>   fence: farm + Phase 2 asserted on the DEFAULT surface.
> * `cf0c331` Batch B — farm LEVEL-OF-DETAIL: LOD 0 honest lineup
>   block at fit-width; click -> LOD 1 viewBox focus with one real
>   switchgear cubicle per unit (52, G01..G22, rating, NFPA 110 state
>   strip). `farmUnits()` in power_budget.js = single source.
> * `a6eecd1` Batch C — `S-VISUAL-01` (visual closure on the DEFAULT
>   rendered surface; registry 32/15) + preview tool default-first +
>   farm LOD 1 section. `node scripts/preview_diagrams.mjs` -> open
>   `logs/diagram_preview.html` (secciones 1 y 1b) for acceptance.
> **PENDING OPERATOR VISUAL ACCEPTANCE** of the preview / live HMI —
> per S-VISUAL-01 the loop closes when Wilmer SEES it.
>
> **✅ MVP S2 — BACKEND GROUNDING CLOSED (2026-06-11, same day, ahead
> of the jun 18-24 plan window).** Operator visual acceptance of the
> S1 preview received ("ok lo veo bien"). Delivered: `3c0a2a3` farm
> into the site graph (113 components), `92f3fd9` Phase 2 design-sim
> channels (281 live on the wire, voltage_v_dc_bus fence clean),
> `66288d4` What-If + N-1 over Building D, `63bb9f0` live smoke tool
> (`python scripts/smoke_phase2_channels.py` — PASS against fresh
> boot). Backend left RUNNING on :8080 (booted 2026-06-11 16:40,
> knowledge_graph components=113 in the boot log).
>
> **✅ SUPERSEDED 2026-06-12 (Epic 5 closed — Sprints 1+2 were already
> on master since 2026-05-23; see the block above). Original entry:**
> ~~MVP S3: Epic 5 Sprints 1+2.~~
> Per ROADMAP-V11.md (plan v11.18, Epic 5 spec v11.17): E5.A
> Optimizer heartbeat strip + E5.C per-agent voting breakdown
> (Sprint 1, ~12 h), then E5.B approval sidebar + E5.D forensic
> trail link (Sprint 2, ~9 h). Epic 5 risk note: E5.C touches
> `multi_agent.py` — run `tests/test_multi_agent.py` targeted FIRST.
> The Optimizer is default-OFF (`DC_EPMS_OPTIMIZER_ENABLED`) — E5.A
> must verify BOTH postures (200 enabled / 503 default-OFF).
> Executive decisions standing: iso retired, Epic 5 complete (3
> sprints), edge/ OUT of MVP unless the A3 manifest lands before S3.
> Demo maneuver unlocked by S2: Power SLD What-If -> trip UTILITY D
> -> the farm lineup flips RUNNING and the whole D chain rides it
> degraded; N-1 badges live on Building D (sscb_d/dc_bus_d critical).

> **Diagram Rebuild (2026-06-10)** — the 5 diagram views now share ONE
> visual language + ONE asset identity (ADR-012, skill S-DIAGRAM-01):
> `core/diagram_kit.js` (orthogonal-by-construction symbols/wires/legend,
> unified --dk-sev-* severity tokens, RBAC modal factory) +
> `core/node_registry.js` (canonical id <-> topo key <-> graph id <->
> Kalman channel prefixes, grounded on the live backend). Power SLD
> gained the Phase 2 Building D branch with the AC/DC fence DRAWN
> (35 kV 3-phase AC -> MV Rectifier -> 800 VDC UNIPOLAR TN-S -> SSCB ->
> BESS/RPP, dashed DESIGN, non-operable). Cooling What-If became a real
> availability DAG (`cooling_grid.js`, N+1 peer degradation). The 18 KB
> static HLD SVG was retired (registry-generated; "480VDC" vocab error
> eradicated; 8 s poll -> Hermes). Site graph gained live severity +
> "Open in Power SLD / Cooling P&ID" cross-links. Power & UPS gained
> engineering detail: genset NFPA 110 sequence (STANDBY->CRANKING->
> RUNNING->ON LOAD->COOLDOWN) in power_grid.js, UPS IEC 62040-3 modes
> (VFI-SS-111) with internal power-path mimic, ATS/XFMR/batt sections,
> Phase 2 spec sheets (`asset_engineering.js` + asset panel wiring).
> Preview tool: `node scripts/preview_diagrams.mjs` -> logs/diagram_preview.html.
> Mission Control breadcrumb DELIVERED (0cc7d5e): drill-down trail
> surviving navigation + Building D retargeted to the Power SLD with
> mv_rect_d pre-selected (scene -> SLD -> Phase 2 spec sheet in one
> click). The Diagram Rebuild plan is 100% closed.
>
> **INNOVATION TRACK (2026-06-10, same session)** — two market-first
> features on top of the rebuild:
> * **N-1 Shadow** (c18b7c8): pure steady-state contingency
>   (`core/contingency.js` — genset = degraded survival, battery
>   holdup excluded, tone = load impact) painted live on the Power
>   SLD + Cooling P&ID via one shared overlay (`core/n1_overlay.js`):
>   tone-coded N-1 badges per node, hover lights victims. Disabled
>   inside What-If.
> * **Forensic Replay** (065d45f): session flight recorder
>   (`core/flight_recorder.js`, 600-tick in-browser ring buffer) +
>   REPLAY scrubber on the Power SLD — re-renders the full mimic at
>   any past instant; Forensic Ledger actions ride the timeline as
>   clickable markers with their HMAC chain prefix. Honest scope:
>   session-only, not persisted history.
> Vitest floor **481 / 30 files**. Demo gallery:
> `frontend/assets/demo/` (breadcrumb_demo + innovation_demo).
>
> **Q-STATE TRACK (2026-06-10, closing batch)** — the Galaxy VX
> one-line upgraded twice: (a) full Q-breaker discipline a002a55
> (Q1/Q2/Q3/Q5 glyphs, position != energization, MBP sequence);
> (b) operator-spec topology + Q-STATE AS BMS TAGS 45c2203: SSM as
> the common inverter/bypass output junction -> NEW Q4 -> load;
> 10 writable PWR.UPS_x.Qn_POS tags (62 total); parseQTags +
> qMismatches turn a wrong lineup into an ALARM ("Q3 reads CLOSED
> in double conversion -- MBP still bridged?"). Demo maneuver: BMS
> view -> write PWR.UPS_A.Q3_POS = Closed (SME_L6) -> Power SLD ->
> click UPS A -> pulsing alarm ring + mismatch banner. Knowledge
> corpus +2 (5838581): Galaxy internals + farm-scale MV paralleling
> (ANSI 25, dead-bus, load shedding) -- graphrag boot count now 14.

> Epic 10 closed on `master` via 4 atomic commits, **pushed to origin/master**:
> `5a8252e` backend IAM core (roles + JWT + login),
> `a68381e` Maker-Checker dual-JWT on procedure sign,
> `58f648a` frontend login + auth gate + API middleware,
> `b186bb3` QKD-gated signing UI (block firmas when QBER >= 11%).
>
> Verified green after a full venv-contamination remediation (DC-EPMS-036):
> backend **1409 passed / 0 skipped / 5 deselected** (62 s, epms-db healthy),
> frontend **368 vitest passed**, `pip check` clean.

### State at sync time

- SLD Reengineering A-C committed locally (`345e098` / `cf0c331` / `a6eecd1` + doc-sync); push at session end.
- Test floors: **1409 backend pytest / 500 vitest across 31 files** (SLD Reengineering +10 vitest net of fixture migration; backend untouched this session).
- Env: venv restored to pyproject baseline (chromadb 0.5.18, langchain-core 0.2.43, pydantic 2.9.2); `protobuf` bumped to 6.33.6 + pinned `>=6.31.1,<7` in pyproject; otel floated to 1.42.1; orphan experiment pkgs (crewai*, instructor, langchain-anthropic, langchain-protocol) uninstalled. Forensic backup at `logs/env-rollback-20260528-210919/`.
- Rust toolchain INSTALLED (rustup 1.29 / rustc+cargo 1.96, host x86_64-pc-windows-msvc, linker via VS Build Tools 2026). `edge/gateway-rs/` scaffolded + builds + 2 tests green (tokio + nalgebra wired; rmodbus + tonic declared, phase 2).
- Ruff: generated protobuf (`*_pb2.py`, `*_pb2_grpc.py`) excluded.
- Skills: 31 / 14 categories (S-DIAGRAM-01 new, ADR-012). Harnesses: H06+H13+H16 all OPERATIVO.
- Honest framing: Epic 9 BB84 remains an EDUCATIONAL simulator (random.Random entropy). Epic 10 JWT uses an ephemeral dev secret unless `DC_EPMS_JWT_SECRET` is set; in-memory user store is a demo MVP (production = Argon2id/OIDC + backing DB) — flagged in-code.

### Open architectural decisions / loose ends

- ~~`package.json` JS deps uncommitted~~ — CLOSED: reverted to the vitest-only harness and committed in `f3a3d06` (DC-EPMS-036 fully closed).
- **2026-06-10 hygiene session note**: the formerly-tracked forensic tarball `pre_recovery_batch3_5_20260506_223123.tar.gz` is now UNtracked (moved to `scripts/_archive/root_batch_era/` on disk, covered by the new `pre_recovery_*.tar.gz` ignore — consistent with the original "forensic tarballs are not versioned" design). 54 untracked root logs/.bak files relocated to `logs/root-archive-202605/`. Empty `scripts_archivesesion_sprint5/` (DC-EPMS-035 backslash-collapse residue) removed.
- **`edge/` polyglot monorepo IN FLIGHT** — gateway-rs scaffold done; PENDING the A3 manifest (`edge/CLAUDE.md`: 6-feature holographic vector + early-transcendentals control rules — operator to provide spec), the Swift stub (`edge/node-swift/`), and the proto-fence wiring (tonic -> existing v1 .proto, no backend changes).
- Deferred from Epic 8: gRPC service shim, MCP resource exposure of the proto stream, frontend proto-aware HMI surface.

### Resumption protocol (next session entry)

1. Run `IMMEDIATE NEXT STEPS` checklist.
2. Read `docs/ROADMAP-V11.md` for live backlog.
3. Verify boot log shows `[graphrag] loaded 14 knowledge documents` + `[BOOT] Architect library pre-seeded with 29 catalog MOP(s)` + `[BOOT] QKDService primed`.
4. Wait for Wilmer's explicit GO before any new work.

## 🚨 DO NOT TOUCH

- `epms-db` Docker container (always running).
- `_legacy_backup/` directory (archived Batch 1+2 materials).
- `.venv/` directory (regenerate via `pip install -e .[dev]` if needed).
- Any commits older than `v0.5.0` (foundation, brittle).
- `agent_engine.py` (dual-AI fallback per ADR-004, do NOT delete).
- `backend/telemetry_proto/v1/telemetry.proto` (Epic 8 schema is operator-approved; changes require RFC + ADR).
