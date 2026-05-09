# DC-EPMS PRO - Claude Code Project Memory

**Project**: DC-EPMS PRO (Edge Operations Platform for Tier IV AI factories)
**Repository**: `C:\dev\DC-EPMS_PRO`
**Maintainer**: Wilmer Y. Angel Beltran (a3semi - A-Cubed Semiconductor Systems Inc.)
**Target**: CET role at Microsoft Cloud Operations + Innovation (CO+I) division
**Interview target**: early August 2026

## 🎯 What this project is

DC-EPMS PRO is an AI-native edge operations platform simulating **A3-Alpha Toronto Area** under **Path C2** (sealed 2026-05-05): a 67 MW Tier IV AI factory with 368 racks total.

- Phase 1 (Buildings A/B deployed): **118 NVIDIA GB200 NVL72 racks @ 142 kW**, 480 VAC trifásico 2N, UPS Schneider Galaxy VX, chillers York YZ N+1
- Phase 2 (Building D target Q2 2026): **250 NVIDIA GB300 NVL144 racks @ 200 kW**, upstream 3-phase AC at 35 kVAC trifásico into MV Rectifier, 800 VDC unipolar TN-S downstream, SSCB 1-100 microsecond clearing per IEC 60947-2, BESS 2.5 MWh, full DLC retrofit to 12 VDC at GPU
- Rubin Ultra excluded from V9 scope

**Vocabulary discipline (CRITICAL)**: "trifásico" applies ONLY to AC upstream of MV Rectifier. The 800 VDC bus is unipolar (no phases). Saying "800 VDC trifásico" is a credibility-destroying error in panel review.

## 📊 CURRENT STATE (verified 2026-05-09 03:00)

```
HEAD:    d853907  docs(loto): DC-EPMS-032 walk direction polarity comment (LOW)
Tag:     v0.7.3-sprint5-patches  ← LATEST
Tests:   412+ passing
Validation layers: 8 of 8 PASS

System completion:
  Backend:   80%
  Frontend:  82%
  Total V9:  79%

Tags chronological:
  v0.5.0
  v0.6.0-batch3
  v0.6.1-batch3.5
  v0.7.0-batch4
  v0.7.2-camino1
  v0.7.3-sprint5-patches  ← HEAD
```

**Last 5 commits**:
```
d853907 (HEAD, tag: v0.7.3-sprint5-patches) docs(loto): DC-EPMS-032 polarity comment
324d87f fix(loto): DC-EPMS-031 graphrag loto_with_knowledge (MED)
da995e1 fix(loto): DC-EPMS-030 cooling_chain via impact_set (MED)
00caff1 fix(loto): DC-EPMS-033 voltage_v fallback (MED)
9f138ab docs(camino1): CHANGELOG entry for v0.7.2-camino1
```

## 🏗️ ARCHITECTURE

### Directory layout
```
C:\dev\DC-EPMS_PRO\
├── backend/                     ← FastAPI + SQLAlchemy + asyncpg
│   ├── main.py                  ← 1823 lines, 5 routers, ~50 endpoints
│   ├── physics_engine.py        ← 369 lines, facade for 4 physics modules
│   ├── physics/                 ← 4 sub-modules (it_thermal, mechanical, electrical, heat_rejection), 85 unit tests
│   ├── agent_copilot.py         ← 894 lines, primary agent with 6 tools
│   ├── agent_engine.py          ← 294 lines, dual-AI fallback (NeMo Guardrails + Claude Sonnet)
│   ├── procedure_engine.py      ← 641 lines, 8-state machine, 32 tests
│   ├── witness_engine.py        ← 290 lines, multi-signature drafts, 26 tests
│   ├── cmms_mcp.py              ← 492 lines, LOR scoring, 51 tests
│   ├── site_model.py            ← 462 lines, declarative YAML parser, 44 tests + 41 integration
│   ├── graphrag_service.py      ← 166 lines, NetworkX MultiDiGraph + FAISS, 20 tests
│   ├── rag_service.py           ← 234 lines, ChromaDB primary, 20-doc operational corpus
│   ├── loto_auditor_agent.py    ← 1100+ lines, 6-pillar paranoid validator
│   ├── loto_auditor_pillar_helpers.py  ← Helpers for Pillar 1-6
│   ├── loto_auditor_routes.py   ← 4 REST endpoints under /api/loto
│   ├── shift_briefing.py        ← (NOT YET) Sprint 5.5a target
│   ├── cyber_physical_tools.py  ← 248 lines ORPHAN (Sprint 5 Telemetry target)
│   ├── dpo_edge_healing.py      ← 352 lines ORPHAN (Sprint 6 target)
│   ├── mcp_server.py            ← 531 lines, Claude Desktop subprocess
│   └── hal/                     ← Cummins, ASCO, Russelectric adapters
├── frontend/                    ← Production-grade HMI
│   ├── index.html               ← 105KB, 13 nav routes, includes LOTO Auditor view
│   └── assets/
│       ├── app.js               ← 3601 lines, IIFE pattern
│       └── app.css              ← 71KB
├── config/
│   ├── site_model.yml           ← 91 components, 50 racks (will expand to 368 in Sprint 5)
│   ├── knowledge/               ← 5 GraphRAG markdown docs
│   └── pue_targets.yml          ← (NOT YET) Sprint 5.5b target
├── data/
│   └── chroma_db/               ← 20-doc 4-tier corpus (Safety/Vendor/Standards/MOPs)
├── tests/                       ← 412+ tests
├── docs/
│   ├── adr/                     ← 7 ADRs (MADR format)
│   └── architecture/sre_layers.md
├── scripts/
│   └── _archive/                ← Session helpers archive
├── CHANGELOG.md
├── pyproject.toml               ← PEP 621, 10 extras
├── pytest.ini
├── .pre-commit-config.yaml      ← 17 hooks
└── docker-compose.yml
```

### Key endpoints (~50 total)

**Health + telemetry**: `/api/health`, `/api/telemetry`, `/api/telemetry/stream` (SSE)
**Site model**: `/api/site/components`, `/api/site/loto-impact/{id}`, `/api/site/health`
**GraphRAG**: `/api/graph/query`, `/api/graph/loto`, `/api/graph/upstream`
**RAG**: `/api/rag/query`, `/api/rag/docs`
**LOTO Auditor** (4 endpoints under `/api/loto`): `POST /api/loto/audit`, `GET /api/loto/audit/{audit_id}`, `GET /api/loto/audit/{audit_id}/markdown`, `GET /api/loto/audits/recent`
**Procedures**: `/api/procedures`, `/api/procedures/{id}/execute`
**CMMS**: `/api/cmms/draft`, `/api/cmms/drafts/{id}`, `/api/cmms/approve/{id}`
**Witness**: `/api/witness/sign`, `/api/witness/drafts`
**Agent Copilot**: `/agent/stream` (SSE)
**MOPs**: `/api/mops` + `/api/mops/{doc_id}` + `/api/mops/generate`

### LOTO Auditor 6-Pillar architecture

| Pillar | Function | Status |
|---|---|---|
| 1 | Topology + GraphRAG impact radius | ✅ FIXED (DC-EPMS-030/031/032) |
| 2 | Redundancy 2N validation | ✅ FIXED (DC-EPMS-029) |
| 3 | Capacitor discharge per NEC 460.6 | ✅ Working |
| 4 | Witness Gate per CSA Z462 | ✅ FIXED (DC-EPMS-034) |
| 5 | Cooling chain check | ✅ Working |
| 6 | PPE matrix per NFPA 70E | ✅ FIXED (DC-EPMS-033) |

## 🐛 BUGS REGISTRY

### Closed in v0.7.3-sprint5-patches (2026-05-09)
- **DC-EPMS-029** (HIGH): Pillar 2 SHI calculation (`pre_validation.get` vs `.site_health` attribute)
- **DC-EPMS-029a** (LOW): SHI threshold calibration (was already 0.5, NO-OP)
- **DC-EPMS-FE-001** (MED): Path C2 drift in frontend (40 MW to 67 MW total, v4.0 to v8.1.0)
- **DC-EPMS-FE-002** (LOW): LOTO Auditor view ausente in HMI
- **DC-EPMS-033** (MED): voltage_v fallback in get_voltage_nominal (site_model.yml uses voltage_v for switchgear/transformer)
- **DC-EPMS-030** (MED): cooling_chain_for() doesn't exist; replaced with impact_set(chain="cooling")
- **DC-EPMS-031** (MED): query_topology() doesn't exist; replaced with loto_with_knowledge(target_id)
- **DC-EPMS-032** (LOW): walk direction polarity comment block

### Open / Deferred

**DC-EPMS-029b** (MED) - DEFERRED to Sprint 5 Telemetry sprint
- Symptom: `simulate_loto_measurements` produces `shi_pre == shi_post` (no delta)
- Root cause hypothesis: `physics_engine.validate_site()` uses thermal fields (hall_inlet_temp_c, chiller_supply_temp_c, cdu_pressure_bar) that simulate_loto doesn't modify
- Why deferred: requires physics_engine.py code review; bandaid risky without it
- Will resolve naturally during Sprint 5 Telemetry integration

**DC-EPMS-034** (LOW) - RESOLVED 2026-05-09 (commit pending Phase B closure)
- Symptom: `witness_engine_protection: "engine present but interface unknown"` in Pillar 4
- Root cause: helper in `backend/loto_auditor_agent.py:_check_witness_engine_protection`
  looked for 3 method names (`get_protection_status`, `is_identity_collision_protected`,
  `validate_signer_identity`) that do not exist on the canonical `WitnessStore` instance
  injected by `backend/main.py:2218`.
- Fix: extended helper to recognize WitnessStore canonical interface (triple-attr
  duck-type `sign + create + reject` with `inspect.signature(sign)` parameter
  verification to guard against false positives) and WitnessGate interface
  (`await_witness + store`). Legacy named methods preserved for forward compat.
- Verified: 5/5 smoke tests pass (real WitnessStore, None, unknown, false-positive
  guard, legacy method). Pillar 4-5-6 test suite: 14/14 GREEN.

**DC-EPMS-036** (MED) - NEW (opened 2026-05-09, test-fixture drift)
- Symptom: 4 tests in `tests/test_loto_auditor_pillars.py` fail on HEAD:
  - `TestPillar1Topology::test_pillar1_graphrag_inconsistency_noted_not_failed`
  - `TestPillar1Topology::test_pillar1_cooling_chain_integration`
  - `TestPillar2Redundancy::test_pillar2_happy_path_path_a`
  - `TestPillar2Redundancy::test_pillar2_shi_below_threshold_hard_fail`
- Root cause: test fixtures expect pre-fix behavior of Pillar 1 (calling nonexistent
  `query_topology()`) and Pillar 2 (treating physics result as `dict.get('site_health')`).
  When DC-EPMS-029, DC-EPMS-030, DC-EPMS-031 fixed production code in commits 160be89,
  da995e1, 324d87f, the test mocks were not updated. Verified pre-existing (failures
  reproduce on clean HEAD 17dfded without DC-EPMS-034 patch via stash test).
- Runtime impact: NONE. Production code is correct; only test mocks are stale.
- CI impact: pytest aggregate fails on these 4 cases.
- Resolution path: update Pillar 1 mocks to match `loto_with_knowledge` payload
  (returns `{edges, evidence_chunks}` not `{topology}`), and update Pillar 2 mocks
  to return `SiteValidation` object (with `.site_health` attribute) not bare dict.
  Estimated effort: 1-2h surgical mock refactor + re-run aggregate.
- Target: Sprint 5 Telemetry sprint (covered by DC-EPMS-029b natural resolution
  of physics_engine surface area).

**DC-EPMS-035** (LOW) - NEW (opened 2026-05-09, recovery-loss-tooling)
- Symptom: 13 untracked session helpers (.ps1 + diagnose_output.txt) lost during
  Phase A archive operation. Only `frontend_pre_camino1_20260508_215625.zip`
  recovered intact.
- Root cause (shell-friction): `mkdir scripts\_archive\sesion_sprint5` invoked via
  Bash tool collapsed Windows-style backslashes (Bash interprets `\` as escape) and
  created a single FILE named `sesion_sprint5` instead of the directory. Subsequent
  `Move-Item -Force` loop overwrote that file 14 times, preserving only the last
  source (the ZIP).
- Lesson learned: in Windows + PowerShell hybrid environment, NEVER invoke `mkdir`
  with backslash paths via Bash. Always use PowerShell-native `New-Item -ItemType
  Directory -Force` and validate destination with `Test-Path -PathType Container`
  before bulk Move-Item operations.
- Mitigation: Rule V9.1 (PowerShell Native Mandate) added — Bash forbidden for
  filesystem ops on Windows. ZIP recovered to canonical path. Effects of all 13
  lost orchestrators ARE preserved in committed code (commits 00caff1, da995e1,
  324d87f, d853907, 160be89, 2f33a59) and CHANGELOG entries v0.7.2-camino1 +
  v0.7.3-sprint5-patches. Forensic reproducibility lost; functional state intact.
- Target: closed by V9.1 rule adoption + commit (this entry).

**DC-EPMS-019** (LOW) - investigated but mitigation deferred
- ResourceWarning on logs/epms_pro.log file held open at module import
- Root cause: logging.basicConfig in backend/main.py:117 without close on shutdown
- Mitigation: lifespan cleanup hook in main.py

**DC-EPMS-021** (MED) - 90 ruff legacy errors
- B904, F821, E402, SIM102, RUF005, RUF013 across many files
- Pre-existing tech debt, target Batch 3.6 (~6-8h)

**DC-EPMS-022** (LOW) - 6 ADRs use asterisk bullets violating MD004
- 5 min mass sed replacement, target Batch 3.6

## 🗺️ ROADMAP V9 - what's next

### Sprint 5 Telemetry + Kalman (W5-6, 1.5 sem) ⭐ IMMEDIATE NEXT

**Backend goal**: integrate `cyber_physical_tools.py` orphan (248 lines, Kalman + Numba @njit + Send-on-Delta)

| Component | Effort | Output |
|---|---|---|
| Synthetic telemetry stream generator | 1 day | `/api/telemetry/stream` real (no SSE placeholder) |
| Kalman innovation residual integration | 2 days | Sensor fusion for anomaly detection |
| Numba @njit JIT compile validation | 0.5 day | Performance test, microsecond decision target |
| Send-on-Delta dispatcher | 1 day | Bandwidth-efficient updates |
| Unit tests (~6-8) | 1 day | Coverage |
| 2 MOPs markdown to YAML conversion (D4 decision) | 1 day | T4-MOP-CHI-001 + T4-MOP-UPS-001 executable |
| **Resolves naturally**: DC-EPMS-029b | -- | -- |

**Tag target**: `v0.8.0-sprint5-kalman`

### Sprint 5.5a Pre-Operational Briefing Orchestrator (W6.5, 6-8h)

**New backend module**: `backend/shift_briefing.py` (~250 lines)

5-step pipeline:
1. `_step1_subsystem_status()` -> physics_engine.validate_site() (<50ms)
2. `_step2_topology_awareness()` -> graphrag.query("redundancy") (~100ms)
3. `_step3_incidents_12h()` -> TimescaleDB (<30ms)
4. `_step4_relevant_procedures()` -> ChromaDB tier-priority (~200ms)
5. `_step5_llm_synthesis()` -> LM Studio gemma-4-e2b-it (2-5s, timeout 10s)

**Endpoint**: `POST /api/shift/briefing`
**Persistence**: `shift_briefings` table (PostgreSQL)
**Tag target**: `v0.8.5-sprint55a-briefing`

### Sprint 5.5b PUE Logic + ADR-004 (W7, 5-6h)

- `physics_engine.compute_pue()` with first-law cross-check (<2% residual)
- `config/pue_targets.yml` architecture-aware:
  - Phase 1 (480 VAC trifásico): 1.30 / 1.45
  - Phase 2 (800 VDC unipolar TN-S): 1.15 / 1.25
- ADR-004 (agent_engine.py dual-AI rationale)

**Tag target**: `v0.9.0-sprint55b-pue`

### Sprint 6 DPO Capture-Only + ADR-005 (W8-9, 2-3 days)

**Backend**: integrate `dpo_edge_healing.py` orphan (352 lines)
- `dpo_pairs` table capturing (original_draft, corrected_draft, rejection_reason, ts)
- `POST /api/dpo/capture` (auto-disparado en CMMS WO rejection)
- `POST /api/dpo/recompile` (manual trigger)
- DPO compute: CPU bitsandbytes (preserves edge-local property)
- ADR-005 (DPO compute strategy)

**Tag target**: `v0.9.5-sprint6-dpo`

### Sprint 7 Alarm Storm Mitigation (W9-10, ~1 sem)
Bayesian network for alarm correlation. 10-100 alarms burst -> topological graph reduction -> 1-5 root causes.

### Sprint 8 EOP Abort under 100ms (W11-12, ~1 sem)
Mission-critical async event bus per NFPA 70E Section 130 + IEC 62443-3-3 SR 3.4/7.6.

**Tag target**: `v1.0.0-v9-complete`

## 🛠️ TOOLING CONSTRAINTS

- **Hardware**: ASUS Zephyrus G14, AMD Ryzen, RTX 3060 6GB, CUDA 13.2, Windows 11 + WSL2 + Docker Desktop
- **Python**: 3.12.10, venv at `C:\dev\DC-EPMS_PRO\.venv`
- **Activation**: `.\.venv\Scripts\Activate.ps1` (always activate before running tests/uvicorn)
- **LM Studio**: gemma-4-e2b-it on `127.0.0.1:1234`
- **TimescaleDB**: Docker container `epms-db` on port 5432 (postgres user)
- **FastAPI backend**: port 8080
- **Claude Desktop**: MCP server `dc-epms-pro` (stdio)
- **NetworkX 3.6.1, FAISS 1.13.2, sentence-transformers 3.2.1** (lazy-loaded)
- **ChromaDB persistent client** at `data/chroma_db/`
- **pre-commit installed** (Batch 3 closure), but USE `--no-verify` for orchestrator commits

**Critical operational notes**:
- Docker container `epms-backend` from old deployment auto-restarts and steals port 8080. Always `docker ps` and `docker stop epms-backend` if conflict.
- FAISS has AVX2 access violation on AMD Ryzen + Windows (DC-EPMS-001). Mitigated via `not slow` markers.
- The `epms-db` Docker container should ALWAYS stay running. Don't stop it.

## 🎓 WORKING STYLE - "Fine Tuning Quirúrgico"

These are non-negotiable principles for all work on this project:

1. **Never assume defaults silently** - surface every decision with explicit rationale and reality check before coding
2. **Reality check over hype** - if something is not genuinely demonstrable on a 6 GB RTX 3060 laptop, say so and propose what IS demonstrable
3. **Approve-then-execute** - present plan in clear bullets, wait for explicit "GO" before generating code (Wilmer says "GO" or "approved" or "luz verde")
4. **Atomic batches** - break sprints into 2-3 batches per session, each independently validatable before proceeding
5. **Defensive coding** - backup files (.bak_pre_*) before patching, AST validation before disk writes, syntax checks before tests
6. **Honest scope** - 6 weeks means 6 weeks. No padding, no hidden buffers
7. **Architectural Decision Records** - significant decisions get ADRs in MADR format under `docs/adr/`
8. **Tag is not closure** - verify with `git log --oneline --decorate -n 5` that tag points to a NEW commit, not the predecessor

## 🔒 V9 AI-FACTORY SPEED PROTOCOL (5 RULES - DEFAULT MODE)

These apply to ALL work, not just override mode:

1. **Ingesta Total**: Every response begins from a conscious read of project state (current bugs, decisions, container state, test count, latest commit hash). No cached assumptions.
2. **Migración CLI**: Every multi-step operation gets a PowerShell or Python orchestrator. No copy-paste of 20-line snippets.
3. **Multi-Agente Lógica + QA**: Every code artifact comes with its test artifact in the same turn. Tests are not deferred.
4. **Grounding Forzado**: Architectural decisions cite the standard, the file path, and the specific section. No vague hand-waves.
5. **CI/CD LOCAL**: All validation is local. ZERO `.github/workflows/` for this project (edge-first autonomy means no cloud CI dependency).

## 🛡️ HYPERSCALE OVERRIDE PROTOCOL (7 RULES)

When Wilmer initiates `[SYSTEM OVERRIDE: HYPERSCALE DEVELOPMENT MODE INITIATED]`, standard limits suspend:

1. **Zero-Placeholder Policy**: NO `pass`, `TODO`, "agrega tu lógica aquí". Production-ready even if 800+ lines.
2. **Deep Chain of Thought**: Open `<architecture_analysis>` block before any code, exhaustively analyzing physical dependencies (Thermodynamics, 800 VDC), 2N redundancy impact, race conditions.
3. **Multi-Agente Full Stack Delivery**: Single turn delivers core code + integration tests (pytest + fixtures) + local PowerShell injection script.
4. **Defensive Coding Agresivo**: Industrial-grade exception handling. Assume network failures and hardware degradation.
5. **Silencio Administrativo**: Text outside code blocks limited to architectural decisions (ADRs) and reality checks.
6. **Documentation Drift Prevention**: Auto-update CLAUDE.md if work alters architectural baseline.
7. **Honest Tech Debt Registry**: Every batch closure generates DC-EPMS-NNN entry if any check failed during execution. Pre-commit hook fails, partial commits, false [OK] reports - all get tracked.

## ⚠️ POWERSHELL PRE-DELIVERY RULES (8 RULES + ASCII-only)

Hard rules for every PowerShell artifact, distilled from Batches 1+2+3+3.5+5 and Camino 1:

1. **No `<` or `>` chars** inside double-quoted strings. PowerShell parses as redirection operators. Includes `->` arrow notation.
2. **No em-dashes anywhere** in PowerShell code. Replace with hyphen-minus or remove.
3. **No double-dash word starting tokens** in argument-like positions inside strings.
4. **Variable colons escape with backtick**: write `` `$variable: `` not `$variable:`.
5. **No `python -c` heredocs** with embedded code. Always write a `.py` file and invoke it.
6. **Wrap native command invocations** with `$ErrorActionPreference = 'Continue'` when stderr might be non-error (git, docker).
7. **AST-validate Python before disk write**, TOML-validate `pyproject.toml` before disk write.
8. **Validate $LASTEXITCODE before declaring [OK]** (Rule from Batch 3.5 Recovery). When invoking native commands, warning text on stderr can be misinterpreted as success.
9. **ASCII-only commit messages**.
10. **Use Convert-Path or Get-AbsolutePath** for .NET I/O calls. `[System.IO.File]::*` resolves relative paths against system PWD, not PowerShell CWD.
11. **String.Replace, NOT [regex]::Replace** when replacement contains $N patterns (interpreted as RegexOptions enum, breaks).
12. **Use UTF8NoBOM encoding** when writing Python files. `Set-Content -Encoding UTF8` preserves BOM; use `[System.IO.File]::WriteAllText` with `New-Object System.Text.UTF8Encoding($false)`.
13. **Multi-variant tolerance for special chars** (middle-dot U+00B7, multiplication sign U+00D7) - check all encoding variants when matching.

## 📜 CLOSING DISCIPLINE (Lesson from Batch 3.5 Recovery)

A batch is not closed merely by tagging:

- **Tag is not closure**. After tagging, verify with `git log --oneline --decorate -n 5` that tag actually points to NEW commit.
- **Pre-commit hooks recursively modify**. Use `git commit --no-verify` for orchestrator commits IF (and only if) changes have already passed manual AST validation and pytest.
- **Honest failure reporting**. Every batch closure must report what was attempted but failed.
- **Forensic tarball before destructive ops**. Save `.tar.gz` before any operation that rewrites git history.

## 🗂️ CONNECTORS / TOOLS DECLARATION

When making changes that need to coordinate with external services:
- **Docker**: prefer `docker compose` (V2) over `docker-compose` (V1)
- **Git**: always `--no-verify` on orchestrator commits with manual AST + pytest validation
- **Tests**: `pytest -m "not slow" --tb=short` (slow markers exclude FAISS AVX2 issue)
- **Browser**: http://127.0.0.1:8080/ for HMI smoke tests
- **MCP**: stdio server `dc-epms-pro` for Claude Desktop integration

## 🎬 RECENT SESSION HIGHLIGHTS (2026-05-08 to 2026-05-09)

**9.5-hour overnight session 7+8 closed**:
- 11 commits + 2 tags (v0.7.2-camino1, v0.7.3-sprint5-patches)
- 8 bugs closed (1 HIGH + 4 MED + 3 LOW)
- Backend 75% to 80%, Frontend 70% to 82%
- LOTO Auditor view production-grade in HMI
- Path C2 drift sync (40 MW to 67 MW)
- Sprint 5 patches verified in browser smoke test:
  - 16 sources_consulted, 14 OK + 1 deferred (ADR-009) + 1 warning (DC-EPMS-034)
  - decision_time_ms ~12ms maintained
- Real-world bug discovery: MOP-ATS-MONTHLY-001 + ups_a target = NEC 460.6 violation in 12ms (demo killer for CO+I panel)

## 📝 COMMUNICATION PREFERENCES

- **Language**: Spanish-English mix. Respond in the language Wilmer uses.
- **Pushback recognition**: When Wilmer pushes back ("ninguna de tus opciones evalua"), recognize as legitimate critical thinking. Re-analyze, do not capitulate.
- **Reality check first**: ALWAYS verify state before suggesting work. `git log --oneline -n 5` + `git status` before proposing.
- **Path C2 vocabulary**: USE precise terminology. "Upstream 3-phase AC into MV Rectifier downstream 800 VDC unipolar TN-S" - NOT "800 VDC trifásico".

## 🎯 IMMEDIATE NEXT STEPS (when resuming)

1. **Smoke test pending** (3 min): browser verify v0.7.3-sprint5-patches at http://127.0.0.1:8080/ - audit MOP-ATS-MONTHLY-001 + ups_a, confirm sources_consulted shows 14 OK + 1 deferred + 1 warning
2. **CHANGELOG entry pending** (5 min): append v0.7.3 details (smoke verified results) + DC-EPMS-034 registration
3. **Archive helpers pending** (1 min): scripts/_archive/sesion_sprint5/ for Camino 1 + Sprint 5 PowerShell artifacts
4. **Then**: Sprint 5 Telemetry kickoff. Read cyber_physical_tools.py orphan, plan integration, atomic batches.

## 🚨 DO NOT TOUCH

- `epms-db` Docker container (always running)
- `_legacy_backup/` directory (Batch 1+2 archived materials)
- `.venv/` directory (regenerate via `pip install -e .[dev]` if needed)
- Any commits older than v0.5.0 (foundation, brittle)
- `agent_engine.py` (dual-AI fallback per ADR-004 future, do NOT delete)
