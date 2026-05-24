# Changelog

All notable changes to **DC-EPMS PRO** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Project**: DC-EPMS PRO — AI-native edge operations platform for Tier IV AI factories
> **Facility simulated**: A3-Alpha Toronto Area (67 MW AI factory hyperscale, Path C2)
> **Maintainer**: Wilmer Y. Angel Beltran — a3semi (A-Cubed Semiconductor Systems Inc.)

---

## [Unreleased]

> **CHANGELOG reconstruction note (2026-05-16)**: the entries from
> `v0.7.2-camino1` through `v0.10.13-modal-fix` below were reconstructed from
> annotated git tags. The CHANGELOG was not maintained during the rapid
> 2026-05-08..10 iteration arc; the tag annotations are the authoritative
> record and are transcribed faithfully here. Forward planning lives in
> `docs/ROADMAP-V11.md` (locked 2026-05-10).

## [v0.16.0] "Procedure Architect Universal" — 2026-05-24

> **Theme:** Epic 6 catalog integration + operator-supplied richer
> system prompt fully adopted. 23 canonical MOP bodies, all
> verdict=APPROVE under the Universal 5-Point + multi-vector risk
> taxonomy + MCP agent health check + parameterized abort triggers
> (HARD_STOP) contract.

### Added

- **Procedure Architect agent** (`backend/agents/procedure_architect.py`):
  LLM-authored SOP/MOP/EOP/EMP with deterministic Safety Officer audit
  pipeline. Hermetic prompt envelope (H17) + deterministic-skeleton
  fallback when no LLM is wired. Authoring is LLM-driven; the audit
  verdict is pure-Python pattern matching (S-DET-01 / ADR-006).
- **Operator-supplied "Generador Universal de MOPs" system prompt**
  (Commit 11) -- MOP template body explicitly demands Identificador
  (Tag) + Estado Final Esperado in §1, six risk Vectors (Eléctrico /
  Mecánico-Térmico / Life Safety / Combustible / Lógico /
  Aguas Arriba-Abajo) in §2, MCP Agent Health Check in §3, formal
  step syntax + `[HOLD POINT]` markers in §4, and parameterized
  abort triggers (number + unit, NEVER vague) in §5.
- **Hardened audit gate** -- 10 deterministic rules total across two
  phases. Phase 1 (legacy): per-template required terms. Phase 2
  (Epic 6 hardening + Commit 11 richer-template): Universal 5
  sections, voltage-verification-or-approach-limit, PDU/RPP/STS
  pre-transfer alarm + SCR check, Eaton SOW R-48 (caution),
  Identificador (caution), Estado Final (caution), Vector
  classification (caution), MCP Health Check (caution), `[HOLD
  POINT]` markers (caution), parameterized abort triggers
  (HARD_STOP -- vague back-out criteria block signing).
- **23 canonical MOP bodies** in `docs/operaciones/mops/`:
  infrastructure (UPS bypass / Transformer dry inspection / ATS
  commutation) + distribution (STS load transfer / PDU PM /
  PDU breaker replacement / RPP load balancing / RPP whip
  installation / RPP EPO reset / Busway tap-off install /
  Busway joint maintenance / Busway thermographic scan) +
  mechanical (Chiller staging / Chiller trip response / Chiller
  ride-through recovery / CRAH hot-swappable filters / CRAH
  VFD-valve calibration / CRAH psychrometric control / Tower
  chemical dosing / Tower pan cleaning / Tower free-cooling
  transition) + global (IST full-load test / DBB main-ring
  isolation). Every body satisfies the full richer-template
  contract -- audit=APPROVE.
- **Library pre-seed at boot** -- `_seed_architect_library_from_catalog`
  parses every `MOP-*.md` and appends to the Architect library
  with `source="catalog"` + category tag. Boot log:
  `[BOOT] Architect library pre-seeded with 23 catalog MOP(s)`.
- **GraphRAG corpus expansion 6 → 10 documents**:
  `electrical-mop-catalog.md` + `distribution-mop-catalog.md` +
  `eaton-sow-r48-mp-checklist.md` + `cooling-thermodynamics-references.md`
  (ASHRAE TC 9.9 + Uptime Tier IV + OCP + CTI ATC-105 + physics
  equations).
- **HMI MOP chip categorías 4 → 10** with 32 chip starter templates
  (UPS / Transformer / Utility / PDU-STS / RPP / Busway / Chiller /
  CRAH / Cooling Tower / Global). Each chip embeds the full safety
  contract (LOTO + PPE + CSA Z462 + voltage-or-approach + back-out +
  {asset} substitution).
- **Maker-Checker witness gate** (Sprint 3 Phase 4 alignment):
  MOPs require two distinct `operator_id`s to seal into the
  Forensic Ledger. Self-witnessing → HTTP 403. Content drift
  between signs → HTTP 409. Documented in
  `docs/architecture/maker-checker-cuatro-ojos.md`.
- **6 new skills** in Category I "Procedure Authoring Safety" --
  `S-SAFETY-01` (Universal 5-Point + voltage verification),
  `S-DISTRIBUTION-01` (PDU/RPP/STS pre-transfer alarm + SCR),
  `S-VENDOR-EATON-01` (Eaton SOW R-48 caution),
  `S-VECTOR-01` (vector classification),
  `S-MCP-HEALTH-01` (MCP / agent health check string-match),
  `S-HOLD-POINT-01` (`[HOLD POINT]` markers). Registry 18 → 24.
- **Save-to-library endpoint** + `source` filter -- operator can
  pin approved Architect drafts into the in-memory library;
  `GET /api/procedures/architect/library?source=catalog|signed`
  filters by origin.
- **Option A consolidation** -- legacy `POST /api/mops/generate`
  retired with HTTP 410 Gone + migration pointer. MOPs view cross-
  links to the Procedure Architect for new procedure authoring.

### Changed

- `PROCEDURE_ARCHITECT_SYSTEM_PROMPT` MOP template body replaced
  with the operator-supplied "Generador Universal" structure (the
  prior Universal 5-Point with extra sub-fields).
- `MOP_PARAMETERIZED_ABORT_PATTERN` promoted from CAUTION to
  HARD_STOP (Commit 12) -- vague abort criteria are safety-critical.
- HMI MOP chip categorías: previously a single flat list of 4
  generic templates; now 10 categorías with 32 specialized chips,
  each pre-seeding the safety vocabulary the audit gate enforces.
- Backend `__version__` 0.15.0 → 0.16.0; mirrored in `package.json`,
  `pyproject.toml`, `frontend/assets/js/core/version.js`, and the
  two `<span data-app-version-stamp>` literals in
  `frontend/index.html`.

### Fixed

- `DC-EPMS-MSD-006` (HIGH, resolved earlier in cycle): asyncpg
  UUID → str coercion in `forensic_ledger.PostgresPersistence`
  `_row_to_entry`. `/api/ledger/verify` no longer 500s against
  Postgres-backed deployments. +4 integration tests in
  `test_forensic_ledger_postgres.py`.

### Tests + tooling

- pytest **875 → 1126** (+251 cumulative across Epic 4 + DC-EPMS-MSD-005
  + Epic 3 Capacity Planner + Epic 6 catalog integration + Epic 6
  richer-template adoption).
- vitest **193 → 313** (+120 across optimizer view, Hermes stream,
  MOP categorías, chip filter, safety-contract assertions).
- ruff: 0 violations in `backend/`.
- GraphRAG: 10 knowledge documents indexed at boot.
- Architect library: 23 catalog MOP entries pre-seeded at boot, all
  verdict=APPROVE.

## [v0.10.13-modal-fix] - 2026-05-10

### Fixed

- DC-EPMS-MAINT-003: closure modal "zombie" — `app.css .m-modal-overlay`
  used `display: flex`, overriding the UA `[hidden]` rule on specificity.
  Fix plus inline validation UX (shake/hint replacing silent `alert()`)
  plus force-close on success. Plus 3 hardening directives.

## [v0.10.12-maint-fix] - 2026-05-10

### Fixed

- DC-EPMS-MAINT-001/002: Maintenance nav-routing flicker (`maintenance` key
  absent from the legacy `MODULES` dict) and dead asset-panel to Maintenance
  focus handoff (`sessionStorage.cmms_focus_asset_id` was never consumed).

## [v0.10.11-ddu-busway] - 2026-05-10

### Added

- DDU / busway expansion in the Power SLD — 12 GB200 NVL72 rack drops.

## [v0.10.10-aesthetic-polish] - 2026-05-10

### Changed

- PBR brushed-metal isometric blocks; JetBrains Mono global typography.

## [v0.10.9-asset-panel] - 2026-05-10

### Added

- Phase 4 contextual SCADA asset panel with Chart.js sparkline.

## [v0.10.8-power-cam] - 2026-05-10

### Added

- Bounded isometric camera controls (zoom/pan/pitch/yaw/flat) for the Power & UPS SLD.

## [v0.10.7-dag-engine] - 2026-05-10

### Added

- DAG-driven electrical propagation engine with universal fault injection.

## [v0.10.6-iso-sld] - 2026-05-10

### Added

- 2.5D isometric "living-organism" Power & UPS single-line diagram.

## [v0.10.5-power-sld-v2] - 2026-05-10

### Added

- Power & UPS SLD "Lead Engineer Mode".
- `docs/ROADMAP-V11.md` committed — the V11 backlog (Tier 1/2/3 + Hermes).

## [v0.10.4-b1-production] - 2026-05-10

### Added

- B1 Mission Control — Tesla Megapack glass-panel: glassmorphism overlay cards
  (live PUE / MW / Racks / Anomalies), animated InstancedMesh particle flow
  Yard to A/B, Raycaster drill-down with 600 ms eased zoom into rack-heatmap /
  site-topology / tech-assist.

## [v0.10.3-b1-spike] - 2026-05-10

### Added

- B1 gray-box three.js spike — 4 BoxGeometry buildings, isometric ortho camera,
  Raycaster, FPS HUD. Validates 4 B1 acceptance criteria. Not production.

## [v0.10.2-tier-b-anomaly-heatmap] - 2026-05-10

### Added

- Tier B: 50-rack anomaly heatmap (Tesla Megapack aesthetic); Tier A+ polish
  (search box, Path A/B coloring, per-rack heat dots). 1019 LOC.

## [v0.10.1-tier-a-topology] - 2026-05-10

### Added

- Tier A: force-directed topology graph (`/api/site/graph` + SVG sim),
  path-coded SLD power flow, thermal heat overlay on the cooling P&ID. 1133 LOC.

## [v0.10.0-tier-c-polish] - 2026-05-10

### Added

- Tier C: WebAudio sound design, boot splash, keyboard shortcuts. Marks the
  v0.10.x feature-set milestone.

## [v0.9.16-asset-enrichment] - 2026-05-10

### Added

- `PATCH /api/cmms/assets/{id}` and a Tech Assist enrich modal — closes the
  nameplate matcher loop end-to-end (seed_new_asset to link_to_existing 0.95+).

## [v0.9.15-voice-closure-modal] - 2026-05-10

### Added

- Voice closure modal in the Maintenance view (closes the API-only gap from v0.9.7).

## [v0.9.14-pue-physics] - 2026-05-10

### Added

- PUE physics widget with first-law cross-check; ADR-004 (Phase 1 480 VAC live,
  Phase 2 800 VDC design).

## [v0.9.13-demo-veto-sample] - 2026-05-09

### Added

- Pre-seeded VETO sample work order so the Multi-Agent demo Act 3 is 100% UI.

## [v0.9.12-multi-agent-facade] - 2026-05-09

### Added

- Sprint 10.1: Multi-Agent facade — 4 agents plus Safety Officer veto,
  deterministic consensus.

## [v0.9.11-consolidation-2026-05-09] - 2026-05-09

### Added

- Pre-demo consolidation: replay script, work-order drill-down, DEMO_SCRIPT.md v2.

### Fixed

- DC-EPMS-040: audit-trail fix.

## [v0.9.10-demo-snapshot-2026-05-09] - 2026-05-09

### Added

- Demo snapshot: 3 predictive_kalman P1 LOTO work orders (cooling / UPS / power
  distribution), all CET-signed — the CO+I panel walkthrough state.

## [v0.9.9-tech-assist-view] - 2026-05-09

### Added

- Sprint 7.1 frontend: 3-panel Tech Assist view (nameplate / troubleshoot / library).

## [v0.9.8-tech-assist-71d] - 2026-05-09

### Added

- Sprint 7.1d: nameplate OCR and asset fuzzy matcher (29 tests).

## [v0.9.7-tech-assist-71c] - 2026-05-09

### Added

- Sprint 7.1c: voice/dictation closure pipeline (text mode) — informal notes to
  LLM-normalized professional report plus auto-detected follow-up WOs in
  `pending_approval`.

## [v0.9.6-tech-assist-71b] - 2026-05-09

### Added

- Sprint 7.1b: PDF ingestion pipeline — a field tech uploads a vendor manual and
  the chunks integrate into troubleshoot QA on the next query.

## [v0.9.5-tech-assist-71a] - 2026-05-09

### Added

- Sprint 7.1a: real-time troubleshoot QA combining RAG + CMMS + LLM, 3-section
  cited answers, safety-keyword detection.

## [v0.9.0-cmms-predictive] - 2026-05-09

### Added

- Sprint 9.1: predictive WO trigger end-to-end — simulator to Kalman to auto-WO
  P1 with telemetry forensic snapshot.

## [v0.8.5-cmms-core-v1] - 2026-05-09

### Added

- Sprint 6: CMMS Core v1.0 — persistent asset registry, work-order lifecycle,
  REST router. Vision deck (Wilmer #1..#7) persisted as a CLAUDE.md appendix.

## [v0.8.0-sprint5-kalman] - 2026-05-09

### Added

- Sprint 5 closure: telemetry simulator + Kalman pipeline + per-channel YAML
  calibration (`config/telemetry_channels.yml`).

## [v0.7.6-kalman-pipeline] - 2026-05-09

### Added

- Sprint 5 C2: Kalman + Send-on-Delta pipeline wired.

## [v0.7.5-telemetry-stream] - 2026-05-09

### Added

- Sprint 5 C1: synthetic telemetry simulator wired into the SSE endpoint.

## [v0.7.4-frontend-pivot] - 2026-05-09

### Added

- Sprint 5.5 hybrid frontend pivot milestone (local Chart.js, telemetry
  activity strip, SHI trend sparkline).

## [v0.7.3-sprint5-patches] - 2026-05-08

### Fixed

- Sprint 5 patches: 4 of 5 bugs closed plus UTF-8 BOM strip.

## [v0.7.2-camino1] - 2026-05-08

### Added

- Camino 1 closure: Path C2 drift sync (40 to 67 MW) and the LOTO Auditor HMI view.

## [v0.7.0-batch4] - 2026-05-08

### Added

- **Batch 4.D**: LOTO Auditor closure (REST endpoint + persistence + rendering).
  - `backend/loto_auditor_repository.py` (267 lines): asyncpg-backed
    PostgreSQL persistence with idempotent INSERT ON CONFLICT save,
    AuditNotFoundError exception for explicit FastAPI 404 mapping,
    MockLotoAuditRepository for tests.
  - `backend/loto_auditor_report_renderer.py` (347 lines): pure-function
    markdown renderer producing per-pillar sections, citations table,
    provenance trace, ADR-006 PENDING APPROVAL banner.
  - `backend/loto_auditor_routes.py` (332 lines): FastAPI router with
    4 endpoints. Exports `register_loto_auditor()` for 1-line wiring.
  - `backend/loto_auditor_agent.py` (PATCH +149 lines): final
    NotImplementedError stub replaced with full LM Studio LLM summary
    implementation. Optional `cmms_service` constructor parameter.
  - `tests/test_loto_auditor_e2e.py` (NEW, 7 integration tests).

- **Batch 4.C** (commit `bb4a26b`): Pillars 4+5+6 implementation.
  Witness Gate, Hybrid Sequential Order, PPE Category. +14 unit tests.

- **Batch 4.B** (commit `f0d373e`): Pillars 1+2+3 implementation.
  Topology Impact Radius, 2N Redundancy Survival, Capacitor Discharge.
  +18 unit tests.

- **Batch 4.A** (commit `d4a5ac8`): LOTO Auditor skeleton + models +
  PostgreSQL schema. +21 unit tests. Added ADR-009.

### Changed

- `backend/loto_auditor_agent.py` constructor accepts optional
  `cmms_service` parameter for Pillar 2 overlapping_maintenance check.
  All Batch 4.B/4.C tests remain GREEN with default None.
- `git config --local i18n.commitencoding utf-8` and
  `i18n.logoutputencoding utf-8` set on repo (DC-EPMS-024 mitigation).

### Fixed

- **DC-EPMS-024**: mojibake in commit messages when apply_batch*.ps1
  orchestrators contained Unicode characters. Mitigations:
  1. Phase 0 of `apply_batch4d.ps1` sets git's UTF-8 commitencoding.
  2. All future apply_batch*.ps1 commit messages are ASCII-only.
  3. Historical commit `bb4a26b` not amended (cosmetic only).



<!-- Batch 3 closure addendum 2026-05-06 -->
### Batch 3 closure addendum (2026-05-06)

#### Added
- 6 ADRs in MADR format under `docs/adr/`: ADR-001 dual-RAG architecture,
  ADR-002 NetworkX in-memory rationale, ADR-003 FAISS IndexFlatIP rationale,
  ADR-006 Deterministic Sandbox foundational principle,
  ADR-007 Sprint 6 simulator killed (DPO orphan reuse),
  ADR-008 GO-OPTION-C image size 1.54 GB Phase 1.
- `docs/architecture/sre_layers.md`: 5-layer SRE mapping (Predictive,
  Management, Safety, Post-Incident, Commissioning) for Microsoft CO+I
  interview narrative; explicit gap declaration for V10 candidates
  (RCA agent, IST runner, Arc Flash boundary calculator).
- `01_INSTRUCTIONS.md` regenerated as master instructions: Path C2
  baseline (67 MW, 368 racks), Hyperscale Override Protocol preserved,
  Batches 1+2 closure status, 11 bugs registered, LOTO Auditor
  scheduled for Batch 4.
- Pre-commit hooks installed (`.git/hooks/pre-commit` + `commit-msg`)
  and ran on all files for the first time.
- `pre_batch3_cleanup_20260506_211234.tar.gz` (88.4 KB) preserved
  outside git as forensic record of pre-cleanup state (5 duplicates
  + 33 iteration scripts + stray chroma_db).
- `scripts/_archive/pre_batch3/` directory containing 33 archived
  iteration scripts from S1-S2 sprints (B3-2c sub-decision: archive
  AND version, do not delete forensic history).
- `logs/.gitkeep` skeleton directory for runtime diagnostic logs
  (gitignored content but tracked directory).

#### Fixed
- **DC-EPMS-002 RESOLVED**: `backend/graphrag_service.py` import path
  corrected from `from knowledge_graph` to `from backend.knowledge_graph`.
  AST-validated and backed up as `graphrag_service.py.bak_pre_dc002_20260506_211234`.
- **DC-EPMS-004 RESOLVED**: 5 MD5-identical duplicates deleted from
  `backend/physics/`: `physics_it_thermal.py`, `physics_heat_rejection.py`,
  `physics_electrical.py`, `physics__init__.py`, plus the orphan
  `backend/physics__init__.py` outside the package. Combined ~1280 LOC
  removed without functional impact (canonicals preserved at expected
  paths, MD5 verified before deletion).
- **DC-EPMS-005 RESOLVED**: 33 iteration scripts moved from project
  root to `scripts/_archive/pre_batch3/`: 23 `.py` files (apply_lucide,
  patch_main_metrics, setup_graphrag_*, sprint*_e2e_test, etc.) and
  10 `.ps1` files (add_bom, edit3_apply, sprint3_demo, etc.).
- **DC-EPMS-006 RESOLVED**: Stray `chroma_db/` (164 KB) at project root
  removed. Operational `data/chroma_db/` (5,677 KB, 2 collections, 20-doc
  corpus) preserved untouched.

#### Pending Tech Debt (opened for Batch 3.5)

##### DC-EPMS-012 (HIGH severity, opened 2026-05-06)
**File**: `backend/cyber_physical_tools.py`
**Issue**: Orphan file (Decision D1 vote 1A target for S5 integration)
contains 248 lines of Kalman + Send-on-Delta + Numba `@njit` code but is
**missing all required imports**. Ruff reports F821 errors for `np`,
`njit` across 17 sites (lines 37, 39, 40, 42, 64, 102, 104-106, 134,
205-211, 233).
**Runtime impact**: NONE — file has zero references in `main.py`, never
imported, never executed (orphan confirmed during 2026-05-03 audit).
**CI impact**: pre-commit ruff hook fails. Cannot integrate file into
S5 sprint until fixed.
**Resolution path** (Batch 3.5): add header imports
`import numpy as np`, `from numba import njit`. AST-validate.
Estimated effort: 30 minutes including unit smoke test.

##### DC-EPMS-013 (HIGH severity, opened 2026-05-06)
**File**: `backend/dpo_edge_healing.py`
**Issue**: Orphan file (Decision D1 vote 2B target for S6 integration)
contains 352 lines of DPO + LoRA + bitsandbytes code but is
**missing all required imports**. Ruff reports F821 errors for `json`,
`time`, `torch`, `LoraConfig`, `TaskType`, `TrainingArguments` across
6+ sites (lines 147, 221, 239, 246, 259, 286, 359, 409).
**Runtime impact**: NONE — orphan never imported.
**CI impact**: pre-commit ruff hook fails. Cannot integrate file into
S6 sprint until fixed.
**Resolution path** (Batch 3.5): add header imports
`import json`, `import time`, `import torch`,
`from peft import LoraConfig, TaskType`,
`from transformers import TrainingArguments`. AST-validate.
Note: deferred runtime verification of `peft` and `bitsandbytes`
import chain happens in S6 Hour 1 per ADR-007 entry criteria, NOT
in Batch 3.5.
Estimated effort: 30 minutes for import fix + AST validation.

##### DC-EPMS-014 (MEDIUM severity, opened 2026-05-06)
**File**: `backend/hal/cummins_adapter.py` line 41
**Issue**: mypy strict reports `error: invalid syntax` at line 41.
Hypothesis: BOM corruption or mojibake unicode confusing mypy parser
(but NOT Python interpreter — `sys.path.insert` plus runtime import
chain works, evidenced by 39 HAL adapter tests passing within the
352-test aggregate).
**Runtime impact**: NONE — module imports fine via Python interpreter,
HAL adapters tested clean.
**CI impact**: mypy strict pre-commit hook hard-fails on this file.
**Resolution path** (Batch 3.5): inspect line 41 for non-ASCII bytes,
re-encode file as pure UTF-8 without BOM, replace any mojibake with
ASCII equivalents. Verify mypy passes.
Estimated effort: 15 minutes.

##### DC-EPMS-015 (MEDIUM severity, opened 2026-05-06)
**Files**: `backend/agent_copilot.py`, `backend/cyber_physical_tools.py`,
`backend/dpo_edge_healing.py`, `backend/main.py`,
`backend/metrics_router.py`, `backend/physics/electrical.py`,
`backend/physics/heat_rejection.py`, `backend/physics/it_thermal.py`,
`backend/physics/mechanical.py`, `backend/shift_report.py`,
`scripts/simulator.py` (12 files total).
**Issue**: Mojibake unicode characters in strings, comments, and
docstrings. Examples: `├ù` (should be `×` or `x`),
`ΓÇô` (should be `-`), `ΓÇÖ` (should be `'`), `╬öP` (should be `dP`),
`╧ä` (should be `tau`), `╬µ` (should be `epsilon`).
Source: copy-paste from earlier Claude conversations where Spanish
prose used Spanish quotation marks and mathematical symbols that got
encoded as cp1252-flavored UTF-8 then re-saved as UTF-8.
**Runtime impact**: NONE — Python reads UTF-8 fine.
**CI impact**: ruff hard-fails on RUF001/RUF002/RUF003 ambiguous
characters (~50 occurrences across files). Without `--unsafe-fixes`
flag, these cannot be auto-resolved.
**Resolution path** (Batch 3.5): mass find-replace via Python script
mapping mojibake to ASCII or proper unicode. Run `ruff check
--unsafe-fixes --fix` after to catch any residual.
Estimated effort: 60-90 minutes including manual review of
substitutions in physics formulas (do not break math notation).

##### DC-EPMS-016 (LOW severity, opened 2026-05-06)
**File**: `config/site_model.yml` (and possibly other config YAMLs)
**Issue**: yamllint pre-commit hook crashes with
`UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d in position
13221: character maps to undefined`. Root cause: yamllint reads files
using Python's default codec which on Windows is cp1252; the YAML file
contains UTF-8 bytes (probably from mojibake or accented characters
in component descriptions) that cp1252 cannot decode.
**Runtime impact**: NONE — `site_model.py` reads with explicit
`encoding="utf-8"`, parses fine.
**CI impact**: yamllint hook crashes (not just fails); blocks
pre-commit pipeline.
**Resolution path** (Batch 3.5): patch `.pre-commit-config.yaml`
yamllint hook to set `PYTHONUTF8=1` env var, OR rewrite affected
YAML files as pure ASCII (replace any accented characters in
descriptions).
Estimated effort: 15 minutes.

##### DC-EPMS-017 (LOW severity, opened 2026-05-06)
**Files**: All 6 ADRs under `docs/adr/`
**Issue**: markdownlint pre-commit hook fires:
- MD034 "no-bare-urls" on `https://adr.github.io/madr/` reference line
  in each ADR header (cosmetic, but cited URL is intentional reference
  to MADR template authority).
- MD004 "ul-style: expected asterisk, actual dash" on every list bullet.
Project style preference (dash bullets) conflicts with markdownlint
default (asterisk).
**Runtime impact**: NONE — markdown renders fine on GitHub, in IDE
preview, in mkdocs.
**CI impact**: markdownlint hook fails; blocks pre-commit.
**Resolution path** (Batch 3.5): either (a) patch
`.markdownlint.json` to set `"MD004": { "style": "dash" }` plus
disable MD034 for ADR header lines, or (b) bulk find-replace `- ` to
`* ` at line start in ADRs. Option (a) is better — preserves project
style choice and documents it.
Estimated effort: 15 minutes.

#### Decisions

- **GO-OPCION-C** (Batch 3 closure strategy, 2026-05-06): accepted
  Atomic Batches discipline; auto-fixes from pre-commit captured in
  one clean commit; 6 new bugs (DC-EPMS-012 through DC-EPMS-017)
  registered as documented tech debt; surgical resolution deferred
  to Batch 3.5 (estimated 3-4h dedicated session). Rationale: mixing
  these fixes into Batch 3 violates V9 Atomic Batches principle and
  introduces risk of capturing partial mojibake fixes that re-break
  the encoding state.

#### Notes

- pytest aggregate after Batch 3 closure: **352 passed, 5 deselected**
  (the 5 deselected are FAISS-touching tests marked `slow` per
  DC-EPMS-001 hardware bug). NO regression vs Batch 2 baseline.
- Container image `dc-epms-pro:latest` 1.54 GB still healthy in 10 s.
- Two-commit strategy was approved (B3-1 vote C) but collapsed in
  practice because commit 1 captured ALL files including ADRs and
  SRE layers placed in Phase 3 of `apply_batch3.ps1`. The "commit 2
  failed because nothing to commit" message was the correct git
  behaviour (working tree clean), not a real failure. The auto-fixes
  commit captured by `close_batch3.ps1` becomes the de facto commit 2.
- Tags after closure: `v0.5.0` (Batches 1+2 milestone) +
  `v0.6.0-batch3` (Batch 3 closure including auto-fixes).

<!-- end Batch 3 closure addendum -->


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

## [v0.7.2-camino1] - 2026-05-09 (Frontend Path C2 sync + LOTO Auditor view)

### Added
- Frontend view-loto-auditor with form + 6 pillar cards renderer (commits 2a04d03, a90869c)
- Path C2 drift sync: 10 strings updated in frontend/index.html (commit 7ec55b2)
- nav-item LOTO Auditor with Lucide shield-alert icon
- Real-world demo: MOP-ATS-MONTHLY-001 + ups_a target catches NEC 460.6 violation in 12ms

### Fixed
- DC-EPMS-FE-001 MED: Path C2 drift in frontend (40 MW to 67 MW total, v4.0 to v8.1.0 footer)
- DC-EPMS-FE-002 LOW: LOTO Auditor view ausente in HMI

### Tech debt
- Phase B v1 bug discovered + remediated: [regex]::Replace breaks on $N patterns in replacement strings
- Multi-variant tolerance for middle-dot encoding (U+00B7 / and-middot / numeric entities)

### Demo capability
- Production-grade HMI now demonstrates 6-pillar LOTO Auditor end-to-end
- ADR-006 Deterministic Sandbox visible: status=pending_approval enforced
- Decision time 4-12ms in browser
- WARN vs HARD_FAIL color coding visible

## [v0.7.3-sprint5-patches] - 2026-05-09 (LOTO Auditor 6-pillar fixes + smoke verification)

### Fixed
- **DC-EPMS-033** (MED, commit 00caff1): voltage_v fallback in get_voltage_nominal.
  config/site_model.yml uses voltage_v field for switchgear/transformer canonical
  components; helper now reads voltage_v with graceful fallback to legacy keys.
- **DC-EPMS-030** (MED, commit da995e1): cooling_chain_for() called by Pillar 5 did
  not exist in site_model.py. Replaced call with impact_set(component_id,
  chain="cooling") which returns the equivalent downstream cooling DAG.
- **DC-EPMS-031** (MED, commit 324d87f): query_topology() called by Pillar 1 did
  not exist in graphrag_service.py. Replaced with loto_with_knowledge(target_id)
  returning {edges, evidence_chunks} payload Pillar 1 already expected.
- **DC-EPMS-032** (LOW, commit d853907): inline comment block clarifying walk
  direction polarity (downstream from disconnect to load) in Pillar 1 helper.
  No code change.

### Verified (browser smoke 2026-05-09 03:00)
- LOTO Auditor end-to-end on `MOP-ATS-MONTHLY-001` + `ups_a` target.
- 16 sources_consulted: 14 OK + 1 ADR-009 deferral + 1 DC-EPMS-034 warning.
- decision_time_ms ~12 ms maintained.
- Pillars 1, 2, 3, 5, 6 report OK; Pillar 4 reports the DC-EPMS-034 warning.
- Real-world demo capability: NEC 460.6 capacitor discharge violation surfaced
  in 12 ms on `MOP-ATS-MONTHLY-001` against `ups_a` target.

### Tech debt opened
- **DC-EPMS-034** (LOW, opened 2026-05-09): Pillar 4 reports
  `witness_engine_protection: "engine present but interface unknown"`. Witness
  engine is injected via dependency, but the helper cannot determine the call
  interface. Estimated effort: 30 min reading `backend/witness_engine.py` and
  fixing call site. Target: Sprint 5.5a or V10.

### Tech debt deferred
- **DC-EPMS-029b** (MED, deferred to Sprint 5 Telemetry):
  `simulate_loto_measurements` produces `shi_pre == shi_post` (no SHI delta).
  Hypothesis: `physics_engine.validate_site()` reads thermal fields
  (`hall_inlet_temp_c`, `chiller_supply_temp_c`, `cdu_pressure_bar`) that
  `simulate_loto` does not modify. Will resolve naturally during Kalman /
  telemetry stream integration in Sprint 5 (`v0.8.0-sprint5-kalman` target).

### Documentation
- CLAUDE.md endpoint listing for LOTO Auditor corrected to match runtime
  OpenAPI: `POST /api/loto/audit`, `GET /api/loto/audit/{id}`,
  `GET /api/loto/audit/{id}/markdown`, `GET /api/loto/audits/recent`.
  Previous listing erroneously included `/api/loto/procedures` and
  `/api/loto/health` (never registered).

### Session helpers archived
- 15 PowerShell orchestrators (`apply_*.ps1`, `diagnose_encoding.ps1`),
  `diagnose_output.txt`, and `frontend_pre_camino1_20260508_215625.zip` moved
  to `scripts/_archive/sesion_sprint5/` per Atomic Batches discipline
  (B3-2c precedent).
