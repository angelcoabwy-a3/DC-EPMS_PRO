# Changelog

All notable changes to **DC-EPMS PRO** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Project**: DC-EPMS PRO — AI-native edge operations platform for Tier IV AI factories
> **Facility simulated**: A3-Alpha Toronto Area (67 MW AI factory hyperscale, Path C2)
> **Maintainer**: Wilmer Y. Angel Beltran — a3semi (A-Cubed Semiconductor Systems Inc.)

---

## [Unreleased]

> Active development frontier post-audit 2026-05-03.
> Phase V9 in progress (12-week roadmap, Option A confirmed).

### Added — Documentation baseline (post-archaeological audit 2026-05-03)
- Replaced obsolete `02_STATUS_SUMMARY.md` with evidence-verified `02_STATUS_SUMMARY_REAL.md`
  (873 lines, every claim cross-referenced against codebase and filesystem).
- New `S5_5_BRIEFING_SPEC.md` — technical spec for Pre-Operational Briefing sprint
  (split S5.5a W6.5 orchestrator + S5.5b W7 PUE logic with architecture-aware thresholds).

### Decisions RESOLVED (2026-05-03 to 2026-05-06)
- **Decision 1** *(votes 1A + 2B + D-B, 2026-05-03)*: integrate `cyber_physical_tools.py`
  in S5; integrate `dpo_edge_healing.py` capture-only with manual trigger in S6;
  DPO compute on CPU bitsandbytes.
- **Decision 2** *(Path C2, 2026-05-05)*: facility scale set to **67 MW AI factory hyperscale**.
  118× GB200 NVL72 + 250× GB300 NVL144. Rubin Ultra excluded.
- **Decision 3** *(vote 3B, 2026-05-03)*: keep `agent_engine.py` as dual-AI fallback
  coexisting with `agent_copilot.py`.
- **Decision 4** *(Option 4-B, 2026-05-05)*: convert `T4-MOP-CHI-001` and `T4-MOP-UPS-001`
  markdown to executable YAML in S5.
- **Decision GO-OPTION-C** *(2026-05-06)*: accept ~2 GB Docker image size for Phase 1
  (CPU-only torch, RAG stack in-container, edge-first autonomy preserved).
  Migration to Distroless or Alpine deferred to Phase 3.
- ADR-004 *(scheduled S5.5b H6)*: `agent_engine.py` dual-AI coexistence rationale.
- ADR-005 *(scheduled S6 H6)*: DPO compute strategy.

---

### DevOps Quick Wins — Batch 1 *(✅ COMPLETED 2026-05-05)*

#### Added
- **Unified `pyproject.toml`** (PEP 621, ~13 KB): consolidates dependencies and
  tool configs. 10 optional-dependency extras: `db`, `rag`, `obs`, `ai`, `phys`,
  `dpo`, `mcp`, `dev`, `full`, `all`. Critical pins exact-matched to installed
  venv. ZERO runtime downgrades.
- **`.pre-commit-config.yaml`** (177 lines, 17 hooks). Installation deferred to
  Batch 3 (requires git repo).
- **`validate_environment.ps1`** (292 lines, 8 checks).
- Tooling installed: `ruff` 0.9.10, `mypy` 1.15.0, `black` 25.12.0, `pre-commit`
  4.6.0, `pytest-cov` 6.3.0, `pytest-mock` 3.15.1, `pytest-timeout` 2.4.0.

#### Changed
- `pytest.ini` permissive bug fixed via `testpaths = ["tests"]` in pyproject.toml.
- `pytest.ini` file deleted; configuration migrated entirely to pyproject.toml.

#### Test verification
- 91 tests pass in 5.56s (`test_procedure_engine.py` + `test_site_model.py` + `test_graphrag.py`)
- 5 tests deselected by default (FAISS slow tests, see DC-EPMS-001)
- EXIT CODE: 0

---

### DevOps Quick Wins — Batch 2 *(✅ COMPLETED 2026-05-06)*

> **Theme**: Containerization + observability. AI-Factory Speed mode under
> Protocol Override (V9 Rules 1-5).

#### Added
- **`.dockerignore`** (159 lines, ~3 GB excluded): aggressive exclusion list
  preventing dev artifacts (.venv, _legacy_backup, data/chroma_db, scripts root)
  from being copied into Docker build context.
- **`Dockerfile`** v2 (137 lines): multi-stage builder + runtime. Targets:
  - amd64 only
  - non-root user `epms` (uid 10001, gid 10001) per IEC 62443 segregation
  - tini as PID 1 (zombie process protection, signal handling)
  - `--mount=type=cache,target=/root/.cache/pip` for build cache reuse
  - Build-time arg `EXTRAS=db,rag,obs` parametrizable
  - HEALTHCHECK aligned with Tier IV monitoring: 30s interval, 5s timeout, 3
    retries, 60s start_period (FastAPI lifespan grace)
  - Aggressive cleanup post-install: remove `__pycache__/`, `.pyc`, `tests/`,
    strip `.so` debug symbols, prune pip cache (~150-300 MB savings)
  - **Critical**: torch installed FIRST from PyTorch CPU index
    (`https://download.pytorch.org/whl/cpu`) preventing CUDA toolkit
    auto-pull (~3.5 GB savings). See DC-EPMS-009.
- **`docker-compose.yml`** (143 lines): healthcheck-first design fixing the
  long-standing `epms-backend` auto-restart bug:
  - `restart: unless-stopped` (was: `always`, causing port-8080 restart storms)
  - `stop_grace_period: 30s` (DB) and `20s` (backend) for fsync/lifespan cleanup
  - Network isolation: `epms-internal` + `epms-egress` bridges
  - `depends_on: { epms-db: condition: service_healthy }` ensures ordered startup
  - Volumes: `epms-db-data` (Postgres), `epms-chroma-data` (preserves 2.4 MB
    operational corpus across container recreates)
  - `host.docker.internal:host-gateway` so container can reach LM Studio on
    Windows host
- **`backend/metrics_router.py`** (236 lines): Prometheus instrumentation with
  curated SLO buckets and normative grounding in docstrings:
  - SLO 1: Pre-Op Briefing latency p95 < 8s (S5_5_BRIEFING_SPEC §6.2 + ISO 11064-7)
  - SLO 2: EOP abort decision p99 < 100ms (NFPA 70E §130 + IEC 62443-3-3 SR 3.4/7.6)
  - SLO 3: SSCB software decision p99 < 5ms (OCP-LVDC §4 + IEC 60947-2 + IEC TR 63282 §5.2)
  - SLO 4: Telemetry ingestion sustained > 1000 req/s (ASHRAE TC 9.9 Class A2 sample rate)
  - SLO 5: DB pool saturation < 80% (Uptime Institute 2024 incident review)
  - Histogram buckets explicit: 5ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s, 8s, 15s, 30s, 60s
  - Excluded paths: `/metrics`, `/favicon.ico`, `/static`, `/lm/`
  - Graceful degradation if `prometheus-fastapi-instrumentator` not installed
    (returns False with warning, app continues to start)
  - `ENABLE_METRICS=true|false` env var for runtime toggle
- **`tests/test_metrics.py`** (212 lines): 12 unit tests across 4 categories
  (configuration, endpoint exposure, instrumentation behavior, env var control).
  Includes `clear_prometheus_registry` autouse fixture preventing global REGISTRY
  pollution between tests.
- **`patch_main_metrics_v3.py`**: BOM-aware, paren-balanced parser for inserting
  `setup_metrics(app)` after `FastAPI(...)` instantiation. Validates AST before
  writing. Handles strings with parentheses correctly (v1 and v2 had regex bugs).
- **`apply_batch2.ps1`** v2 (295 lines): orchestrator script. Backup, copy,
  patch, install, validate. Idempotent. Logs to `batch2_apply_<ts>.log`.
- **`validate_batch2.ps1`** v2 (410 lines): 8-layer CI/CD validator producing
  paste-to-Claude diagnostic log on failures. Layers: files, imports, pytest
  test_metrics, pytest aggregate, docker build, compose config, container
  healthcheck (max 90s), `/metrics` HTTP+Prometheus format.
- **`rebuild_batch2.ps1`** (254 lines): full rebuild orchestrator for size fix
  (Decision GO-OPTION-C). Backup → patch → image cleanup → rebuild → re-validate.
- **`patch_pyproject_torch_cpu.py`**: pyproject patcher (idempotent, BOM-aware,
  TOML-validating).
- **`patch_pyproject_obs.py`**: adds `prometheus-fastapi-instrumentator>=7.0.0,<8.0.0`
  to `[obs]` extra. Resolves DC-EPMS-011.

#### Changed
- `backend/main.py` patched: `from backend.metrics_router import setup_metrics`
  added near other backend imports; `setup_metrics(app)` called after FastAPI
  instantiation. BOM preserved. AST-validated.
- `pyproject.toml` `[obs]` extra updated: now includes
  `prometheus-fastapi-instrumentator>=7.0.0,<8.0.0` (was missing, see DC-EPMS-011).
- Old bloated image `dc-epms-pro:batch2-validate` removed during cleanup.
  Final tag: `dc-epms-pro:latest` (matches `docker-compose.yml` reference).

#### Test verification (2026-05-06 cierre)
- 12 tests pass for `test_metrics.py` in 0.92s
- 103 tests pass in aggregate (`test_procedure_engine.py` + `test_site_model.py`
  + `test_graphrag.py` + `test_metrics.py`) in 6.67s
- 5 tests deselected by default (FAISS slow tests, see DC-EPMS-001)
- 8/8 validation layers PASS
- Container healthy in 10 seconds (6× faster than 60s start_period budget)
- `/metrics` endpoint returns HTTP 200 with valid Prometheus exposition format
  including `dc_epms_*` namespace, `# HELP` and `# TYPE` comments

#### Final image metrics
- Disk usage: **1.54 GB** (was 8.85 GB — **83% reduction**)
- Content size (compressed): 338 MB
- Build time cold (--no-cache): ~5-7 min
- Build time warm: ~30s
- CPU-only torch from PyTorch official index: `torch==2.5.1+cpu`,
  `torchvision==0.20.1+cpu`

#### Backups defensively created (Batch 2)
- `pyproject.toml.bak_pre_batch2_20260506_*`
- `pyproject.toml.bak_pre_torch_cpu_20260506_*`
- `pyproject.toml.bak_pre_obs_fix_20260506_*`
- `Dockerfile.bak_pre_batch2_20260506_*`
- `Dockerfile.bak_pre_v2_20260506_*`
- `docker-compose.yml.bak_pre_batch2_20260506_*`
- `backend/main.py.bak_pre_batch2_20260506_*`
- `backend/main.py.bak_pre_metrics_*` (3 attempts: v1, v2, v3 — only v3 succeeded)

---

### Bugs discovered during Batches 1+2 (technical debt — registered for future cleanup)

#### DC-EPMS-001 — FAISS AVX2 access violation on AMD Ryzen + Windows
**Severity**: Hardware-specific (Wilmer's ASUS Zephyrus G14 + AMD Ryzen + Windows 11)
**Status**: 🟡 Mitigated via `-m "not slow"` in addopts. 5 tests skip on this hardware.
**Root cause**: FAISS C++ runtime caches CPU detection at first load, ignoring
`FAISS_NO_AVX2=1` env var on subsequent allocations. Bug exists across faiss-cpu
1.7.x to 1.13.x on AMD+Windows specifically; Linux and Intel hardware unaffected.
**Future fix**: Linux CI runner (Batch 3) or migrate to hnswlib/annoy (S5+).

#### DC-EPMS-002 — Broken import path in `graphrag_service.py`
**Severity**: 🟡 Latent (works in pytest context, fragile elsewhere)
**Status**: Pending fix in Batch 3
**Description**: `backend/graphrag_service.py` line 26 should use
`from backend.knowledge_graph` instead of `from knowledge_graph`.

#### DC-EPMS-003 — Encoding mojibake in legacy text files
**Severity**: 🟢 Cosmetic
**Status**: Pending automatic fix in Batch 3 (first pre-commit run after `git init`)

#### DC-EPMS-004 — Duplicate physics modules (MD5-identical)
**Severity**: 🟢 Low (excluded from linting via pyproject.toml)
**Status**: Pending deletion in Batch 3

#### DC-EPMS-005 — Iteration scripts cluttering project root (23 files)
**Severity**: 🟢 Low (excluded from linting)
**Status**: Pending archive in Batch 3

#### DC-EPMS-006 — Two ChromaDB directories (root + data/)
**Severity**: 🟡 Medium (storage waste)
**Status**: Pending investigation in Batch 3

#### DC-EPMS-007 — UTF-8 BOM in `backend/main.py`
**Severity**: 🟢 Cosmetic
**Status**: Mitigated. Patch script `patch_main_metrics_v3.py` is BOM-aware
(decodes with `utf-8-sig`, validates AST after stripping BOM, writes back
preserving BOM).
**Description**: `backend/main.py` ships with UTF-8 BOM (3 bytes `EF BB BF`
at file start). Python 3.12 imports it transparently, but `ast.parse()` on
raw bytes rejects it as "invalid non-printable character U+FEFF" in line 1.
Same root cause as DC-EPMS-003 — encoding inconsistencies in Windows authoring.
**Future fix**: pre-commit hook `fix-byte-order-marker` from pre-commit-hooks
(activated in Batch 3 after `git init`).

#### DC-EPMS-008 — Prometheus REGISTRY pollution between pytest tests
**Severity**: 🟡 Medium (resolved in v2)
**Status**: ✅ Resolved by `clear_prometheus_registry` autouse fixture in
`tests/test_metrics.py`.
**Description**: `prometheus_client.REGISTRY` is a process-global singleton.
Tests creating multiple `FastAPI` apps in the same session collide with
`ValueError: Duplicated timeseries in CollectorRegistry: {'dc_epms_inprogress_requests'}`.
**Lesson**: future Prometheus tests must use the same cleanup fixture. Will
apply to S5.5 PUE tests and S5 telemetry tests.

#### DC-EPMS-009 — Container image size 1.54 GB exceeds original target <1.2 GB
**Severity**: 🟡 Medium (operational, not blocking)
**Status**: Documented as Phase 1 acceptable per Decision GO-OPTION-C (2026-05-06).
Plan: address in Phase 3.
**Description**: Container image after Batch 2 v2 rebuild: 1.54 GB disk / 338 MB
compressed. Original target was <1.2 GB but breakdown reveals ML stack
(torch CPU + sentence-transformers + chromadb + faiss + transformers) consumes
~1.3 GB of the venv inherently. Compressing further would require sacrificing
edge-first autonomy (RAG out of container) or migrating to Alpine base
(musl libc compatibility risk for cuda-bindings even in CPU mode) or distroless
final stage (debugging difficulty).
**Decision**: accept ~1.54 GB as Phase 1 pragmatic. Edge-first autonomy preserved.
Plan Distroless or Alpine migration for Phase 3 if image distribution bandwidth
becomes a constraint.
**Future fix candidates**: Phase 3 Batch X — Alpine base + statically linked
deps; Distroless final stage; multi-arch (amd64 + arm64) for Graviton edge deploy.

#### DC-EPMS-010 — `rebuild_batch2.ps1` falsely fails on Docker stderr noise
**Severity**: 🟢 Low (cosmetic, build actually succeeds)
**Status**: Recognized 2026-05-06, fix deferred to Batch 3.
**Description**: PowerShell `& docker build ... 2>&1 | Out-String` aborts with
`$ErrorActionPreference='Stop'` even when Docker writes informational output
to stderr (`#0 building with desktop-linux instance using docker driver`).
Builds complete correctly but the wrapper script reports false failure.
The user can verify success via `docker images dc-epms-pro` (image is built).
**Future fix (Batch 3)**: use cmd.exe wrapper for native commands or explicitly
set `$ErrorActionPreference='Continue'` around docker invocations.

#### DC-EPMS-011 — `prometheus-fastapi-instrumentator` missing from `[obs]` extra
**Severity**: 🟡 Medium (silent feature degradation)
**Status**: ✅ Resolved 2026-05-06. Now pinned at
`prometheus-fastapi-instrumentator>=7.0.0,<8.0.0` in `[obs]` extra.
**Description**: During Batch 2 development, prometheus-fastapi-instrumentator
was installed manually via `pip install` into local venv but not added to
pyproject.toml's `[obs]` extra. Container builds via `pip install -e ".[obs]"`
therefore did NOT include it, leaving `/metrics` endpoint absent from runtime.
The graceful degradation in `metrics_router.py` masked this — app continued
to start cleanly, only logging a WARNING. Healthcheck passed (Layer 7),
but `/metrics` was 404 (Layer 8).
**Lesson**: graceful degradation with logging is correct V9 design, but
discovery of the gap requires production-grade validation (which is exactly
what `validate_batch2.ps1` Layer 8 caught). Future protocol: when running
`pip install` manually, always verify the package is also pinned in
pyproject.toml. Better: only install via extras mechanism.

---

### Pending — DevOps Quick Wins remainder

#### Batch 3 *(next session, ~3 hours)*
- `git init` + `.gitignore` (covers `.venv/`, `__pycache__/`, `data/chroma_db/`,
  `chroma_db/`, `_legacy_backup/`, `*.bak_pre_*`, `htmlcov/`, `.pytest_cache/`,
  `pytest_*.log`, `*.bak`, all the iteration scripts and orchestrator scripts)
- First commit phases (formatting baseline, then config addition)
- `pre-commit install` + `pre-commit install --hook-type commit-msg`
- First `pre-commit run --all-files` (auto-fixes DC-EPMS-003 mojibake +
  DC-EPMS-007 BOM)
- `.github/workflows/test.yml` — disabled (per V9 Rule 5: ZERO GitHub).
  Replaced by local `watch_tests.ps1` + `pre-commit hook`.
- `docs/adr/` initial set: ADR-001 through ADR-009 (last 5 created during
  Batch 2 decisions)
- Cleanup of DC-EPMS-002 through DC-EPMS-006 (cumulative ~1.5h)
- Fix DC-EPMS-010 (PowerShell wrapper for native commands)

#### Backlog for Phase 3 / V10
- DC-EPMS-009 follow-up: Alpine or Distroless base image migration
- Multi-arch builds (amd64 + arm64) for Graviton edge deploy
- Replace faiss-cpu with hnswlib/annoy to retire DC-EPMS-001

---

## [0.4.0] — TBD (Sprint S2 GraphRAG completion, ~2026-04 mid)

### Added
- **GraphRAG service** (`backend/graphrag_service.py`, 166 lines) with NetworkX
  `MultiDiGraph` + FAISS `IndexFlatIP` + sentence-transformers `all-MiniLM-L6-v2`.
- **GraphRAG router** (`backend/graphrag_routes.py`, 62 lines): 6 endpoints `/api/graph/*`.
- **Knowledge corpus** under `config/knowledge/`: 5 markdown documents.
- **Agent tool** `query_graph_rag` registered, total Copilot tools = 6.
- 20 unit tests (`tests/test_graphrag.py`).

### Architecture
- Established **Dual-RAG topology**: ChromaDB primary + GraphRAG secondary.

---

## [0.3.0] — TBD (Sprint S1b Site Model + Lucide UI Polish, ~2026-04 early)

### Added
- **Declarative site model** (`backend/site_model.py`, 462 lines).
- **Site routes** (`backend/site_routes.py`, 186 lines): 9 endpoints `/api/site/*`.
- **LOTO impact analysis**: walks power_chains and cooling_chains DAGs.
- 44 unit tests + 41 integration tests = 85 tests total.

### Architecture
- YAML as single source of truth for facility topology.

---

## [0.3.0-physics] — TBD (Physics Engine, ~2026-04 early)

### Added
- 4 physics modules: `it_thermal.py`, `heat_rejection.py`, `electrical.py`,
  `mechanical.py` (~3500 lines, 85 tests total).
- `physics_engine.py` facade aggregating Site Health Index.

---

## [0.2.0] — TBD (Sprint S1a Procedure Engine, ~2026-04 early)

### Added
- **Procedure orchestration engine** with 8-state machine.
- **Witness engine** for multi-signature draft approval.
- **First MOP YAML executable**: `MOP-ATS-MONTHLY-001.yml`.
- **HAL** (Cummins, ASCO, Russelectric adapters): 39 tests.
- **CMMS work-order drafting**: deterministic LOR scoring, 51 tests.

### Decided (foundational)
- **Deterministic Sandbox**: zero write-action authority for AI per IEC 62443.

---

## [0.1.0] — TBD (Initial baseline, ~2026-03)

### Added
- FastAPI backend skeleton.
- TimescaleDB persistence layer.
- BMS connector stub (BACnet/Modbus).
- Initial agent engine (Gemma + Claude Sonnet + NeMo Guardrails).
- Initial frontend HMI.
- Shift report PDF generator.
- MCP server (3 tools + 4 resources).

---

## Format conventions

- `[Unreleased]` always at the top.
- Versioned releases below in reverse chronological order.
- Categories: **Added**, **Changed**, **Deprecated**, **Removed**, **Fixed**,
  **Security**, **Architecture**, **Decisions RESOLVED**, **Bugs discovered**.
- Date format: `YYYY-MM-DD`. `TBD` indicates date to be reconstructed from journal.
- Sprint references: `S{N}` for sprints, `W{N}` for weeks of 12-week roadmap.
- Bug IDs: `DC-EPMS-NNN`, sequential, registered in `[Unreleased]` until resolution.
