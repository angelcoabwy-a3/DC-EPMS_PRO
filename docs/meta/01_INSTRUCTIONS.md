# DC-EPMS PRO — Project Instructions

## Role and Context
You are working with **Wilmer Angel**, Critical Environment Technician (CET) and Lead Architect of **a3semi** (A-Cubed Semiconductor Systems Inc.), targeting a CET role at Microsoft Cloud Operations + Innovation (CO+I) division for hyperscale AI data centers. Wilmer is building **DC-EPMS PRO**, an AI-native edge operations platform for Tier IV AI factories, simulating **A3-Alpha Toronto Area**: a 40MW design-intent facility (118-rack target capacity) with 50-rack Phase 1 currently modeled in `site_model.yml` (5 rows × 10 racks @ 142 kW each = 7.1 MW IT load simulated). Building D Phase 2 expansion with 800VDC architecture and 60+ additional GB300 NVL144 racks is planned for S3 V9 deployment per `03_TECHNICAL_SPECS_800VDC.md`.

## Phase V9 Objectives
Phase V9 evolves the platform from rule-based (Software 2.0) to AI-native (Software 3.0) architecture, while maintaining strict IEC 62443 zone-and-conduit segregation. The four CET pillars driving the work:

1. **Liquid Cooling and High-Density Thermodynamics** — CDU ΔP control, manifold pressure monitoring for D2C micro-leak detection, dew point safety margins
2. **800VDC Critical Electrical Infrastructure** — SSCB protection logic in microseconds, BESS load-swing absorption, dual-path failover validation per CSA Z462-24 and OCP-LVDC standards. Architecture: upstream 3-phase AC (35 kVAC trifásico) → MV Rectifier (rectificación balanceada, reducción de ripple, mitigación de armónicos) → 800 VDC unipolar TN-S downstream (bus DC, sin fases).
3. **AI-Native BMS/EPMS Orchestration** — alarm storm mitigation via topological graph, sensor fusion for predictive failure detection (Kalman innovation residual via `cyber_physical_tools.py`), deterministic LOR-scored CMMS work-order generation, edge-local DPO self-improvement loop
4. **Operational Rigor and Cyberphysical Isolation** — EOP emergency abort signaling under 100ms decision time, MOP pre-condition gates with telemetry validation, hybrid sequential LOTO (electrical zero-energy then hydraulic isolation then purge)

The system architecture preserves the **Deterministic Sandbox**: AI has read-only topological authority and document-drafting capability, but **zero write-action authority**. Every CMMS WO, MOP, or THA stays in "Approval Request" state in Paperclip until a qualified CET validates and executes — this is non-negotiable Human-in-the-Loop discipline.

## Current Project State (Post-Audit 2026-05-03)

The 2026-05-03 archaeological audit (Batches A+B+C) revealed the codebase is significantly more sophisticated than the previous status doc reflected. **`02_STATUS_SUMMARY_REAL.md` is the operational baseline** with full evidence-based inventory. Key facts for incoming sessions:

**Verified Completed**:
- **Sprint S1 (Site Model)**: 44 unit tests + 41 integration tests on declarative YAML parsing, LOTO impact analysis, deterministic CMMS LOR scoring
- **Sprint S2 (GraphRAG)**: 20 tests. NetworkX MultiDiGraph + FAISS + sentence-transformers `all-MiniLM-L6-v2` indexing 5 docs in `config/knowledge/`, 6 endpoints `/api/graph/*`, agent tool `query_graph_rag`
- **Physics Engine** (not previously documented): 4 sub-modules (`it_thermal`, `mechanical`, `electrical`, `heat_rejection`) with 85 unit tests applying Darcy-Weisbach pressure drop, Magnus-Tetens psychrometrics, Joule's law per ANSI C57.12, ODE integration via `scipy.solve_ivp`
- **Dual-RAG architecture** (not previously documented): `rag_service.py` (ChromaDB primary, 20 refs in main.py) over 20-doc operational corpus across 4 tiers (Safety/Vendor/Standards/a3semi MOPs) + `graphrag_service.py` (secondary topological layer)
- **MCP Server stdio** (`mcp_server.py`, 531 lines, 0 refs in main.py — correct by design as Claude Desktop subprocess): 3 tools (`simulate_failure`, `read_bms_tag`, `list_bms_tags`) + 4 resources (telemetry, SHI, scenarios, incidents)
- **Agent Copilot**: 6 tools registered via `_build_default_registry()` (`query_unified_graph`, `analyze_rul_and_supply`, `draft_precooling_plan`, `query_site_model`, `query_graph_rag`, `draft_cmms_work_order`)
- **REST endpoints**: 29 direct + 5 routers ≈ ~50 total
- **HMI/Frontend**: Lucide UI Polish + 9 endpoints `/api/site/*`
- **Total tests verified**: 346 (not "350+" as previously claimed)

**Phase V9 Sprint Decisions (2026-05-03)**:
- ✅ **Decision 1 RESOLVED** (votes 1A+2B+D-B): integrate `cyber_physical_tools.py` (Kalman innovation residual + Numba @njit + Send-on-Delta) in S5 + `dpo_edge_healing.py` (capture-only + manual trigger via `POST /api/dpo/recompile`) in S6 + DPO compute on CPU bitsandbytes nightly. ADR-005 to be written in S6 H6.
- ✅ **Decision 3 RESOLVED** (vote 3B): keep `agent_engine.py` (294 lines, 2 refs) as dual-AI fallback (Gemma local + Claude Sonnet cloud + NeMo Guardrails) coexisting with `agent_copilot.py` (primary tool-calling agent). ADR-004 to be written in S5.5b H6.
- ✅ **Sprint S5.5 approved** (decisions A1+B1+C1+D1+E2+F2+G1+H1+I1) — split into S5.5a (W6.5, orchestrator) + S5.5b (W7, PUE logic with architecture-aware thresholds). PUE targets: Phase 1 (480 VAC trifásico 2N) optimal <1.30 deviation <1.45; Phase 2 (Building D 800VDC) optimal <1.15 deviation <1.25 — engineered targets, NOT marketing 1.10 claim. See `S5_5_BRIEFING_SPEC.md` for hour-by-hour implementation plan.
- 🟡 **Decision 2 PENDING**: 50 racks vs 118 (Building D expansion in YAML)
- 🟡 **Decision 4 PENDING**: convert 1-2 MOPs markdown → YAML executable

**Known Tech Debt**:
- No git repository initialized (`fatal: not a git repository`) — to be resolved in S3 V9 W1-2 DevOps
- `pytest.ini` permissive (no `testpaths`) — aggregate `pytest` hangs; workaround: run individual test files
- 4 duplicate files in `backend/physics/` (MD5 identical, ~1280 lines pending cleanup)
- 6 MOPs in `data/corpus/tier4_a3semi_mops/` exist as markdown indexed in ChromaDB but only 1 (`MOP-ATS-MONTHLY-001.yml`) exists as YAML executable in `config/procedures/`

**Roadmap V9 Status**: 12-week Option A confirmed. Interview target: 3 months (late July 2026). S9 EKF killed (Sensor Fusion covered by `cyber_physical_tools.py` integration in S5, no need for separate sprint). Tiempo liberado por reuse de huérfanos (~50-60h) reasignado a S5.5a/b briefing + Building D expansion + MOPs YAML conversion + polish.

**Critical references**:
- `02_STATUS_SUMMARY_REAL.md` — operational baseline, evidence-verified inventory, decisions log
- `S5_5_BRIEFING_SPEC.md` — next implementation gate (W6.5 + W7), hour-by-hour plan
- `03_TECHNICAL_SPECS_800VDC.md` — Building D specs for S3 V9 deployment

## Working Style — "Fine Tuning Quirúrgico"
Wilmer demands surgical precision in every iteration:
- **Never assume defaults silently** — surface every decision with explicit rationale and reality check before coding
- **Reality check over hype** — if something is not genuinely demonstrable on a 6GB RTX 3060 laptop, say so and propose what IS demonstrable
- **Approve-then-execute** — present plan in clear bullets, wait for explicit "GO" before generating code (Wilmer says "GO" or "approved" or "luz verde" to authorize)
- **Atomic batches** — break sprints into 2-3 batches per session, each batch independently validatable before proceeding
- **Defensive coding** — backup files (.bak_pre_*) before patching, AST validation before disk writes, syntax checks before tests
- **Honest scope** — when proposing roadmap weeks, count them honestly. 6 weeks means 6 weeks, no padding, no hidden buffers

## Communication Patterns
- Wilmer often pastes terminal output where `.py`, `.com`, `.html` patterns get auto-converted to markdown links by his client. Generate scripts as downloadable files via the artifact system, not paste-able commands
- PowerShell `[System.IO.File]` operations also corrupt on paste — use Python scripts via files for binary file ops
- Wilmer responds in Spanish-English mix; respond in the language he uses in each turn
- When Wilmer pushes back ("ninguna de tus opciones evalúa..."), recognize the pushback as legitimate critical thinking and re-analyze, do not capitulate

## Tooling Constraints
- Hardware: ASUS Zephyrus G14, RTX 3060 6GB, CUDA 13.2, Windows 11 + WSL2 + Docker Desktop
- Python 3.12.10, venv at `C:\dev\DC-EPMS_PRO\.venv`
- LM Studio running gemma-4-e2b-it on `127.0.0.1:1234`
- TimescaleDB (Docker container `epms-db`) on port 5432
- FastAPI backend on port 8080
- Claude Desktop with MCP server `dc-epms-pro` (stdio communication, not HTTP)
- Semantic Stack: NetworkX 3.6.1, FAISS (faiss-cpu 1.13.2), and sentence-transformers 3.2.1 running `all-MiniLM-L6-v2` locally (lazy-loaded)
- Persistent RAG: ChromaDB persistent client at `data/chroma_db/` (2 collections, ~1.6 MB each, 20 docs across 4 tiers)
- Persistent Audit Trail: PostgreSQL via asyncpg + TimescaleDB hypertables for telemetry + incidents
- Code Quality & DevOps: pytest, black, ruff, mypy, Docker multi-stage builds (DevOps Quick Wins pending S3 V9 W1-2)
- IMPORTANT: Docker container `epms-backend` from earlier deployment frequently auto-restarts and steals port 8080. Always verify `docker ps` and `docker stop epms-backend` if conflict appears.
