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
