# Batch 3.5 - Surgical Tech Debt Resolution Plan

**Generated**: 2026-05-06 (Batch 3 closure)
**Maintainer**: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
**Status**: PLANNED - pending dedicated session
**Estimated effort**: 3 to 4 hours (5 atomic steps)
**Predecessor**: Batch 3 closed with tag `v0.6.0-batch3` and 6 new bugs DC-EPMS-012 to 017
**Successor**: Batch 4 LOTO Auditor Agent (12 to 16 hours, Pillar 4 implementation)

---

## 1. Why a dedicated batch and not "fold into Batch 4"

The V9 Atomic Batches principle requires each batch to be independently validatable. Batch 4 is the LOTO Auditor Agent - Pillar 4 functionality with paranoid 2N redundancy validation, integration tests, and ADR. Mixing tech debt cleanup into that scope would:

1. Inflate Batch 4 estimate from 12 to 16 hours into 16 to 20 hours, breaking the "honest scope" V9 working style rule.
2. Make rollback ambiguous if Batch 4 needs revision (which fix do we revert?).
3. Hide encoding/import bugs behind agent functionality, making post-mortem investigation harder.

Batch 3.5 is **surgical**, **bounded**, and **defensive**. Each step is independently revertable. The end state is a green pre-commit run plus 8 of 8 validation layers PASS.

---

## 2. Entry criteria

Before starting Batch 3.5, verify:

| Check | Expected | Command |
|-------|----------|---------|
| Tag `v0.6.0-batch3` exists | yes | `git tag -l` |
| Working tree clean | yes | `git status` |
| pytest aggregate | 352 passed, 5 deselected | `pytest --tb=no -q` |
| Container healthy | yes | `docker ps --filter name=dc-epms-pro` |
| Pre-commit installed | yes | `Test-Path .git/hooks/pre-commit` |

If ANY check fails, do NOT start Batch 3.5. Diagnose first.

---

## 3. Step-by-step plan (5 atomic steps)

### Step 1: Fix DC-EPMS-012 - cyber_physical_tools.py orphan imports

**Estimated time**: 30 minutes
**Severity**: HIGH (blocks S5 sprint integration of Decision D1 vote 1A)

Open `backend/cyber_physical_tools.py` in editor. After existing module docstring, before first line of code, insert:

```python
import numpy as np
from numba import njit
```

Confirm Numba is in pyproject.toml `[ml]` extra. If not present, add `numba>=0.60.0` and run `pip install -e .[ml]` in venv.

AST-validate, run import smoke test, run ruff on file.

**Acceptance**: file imports clean, Numba decorator resolves, no F821 errors.

---

### Step 2: Fix DC-EPMS-013 - dpo_edge_healing.py orphan imports

**Estimated time**: 30 minutes
**Severity**: HIGH (blocks S6 sprint integration of Decision D1 vote 2B)

Open `backend/dpo_edge_healing.py` in editor. After existing module docstring, insert:

```python
import json
import time
from pathlib import Path

try:
    import torch
    from peft import LoraConfig, TaskType
    from transformers import TrainingArguments
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
```

Wrap any direct uses of `LoraConfig(...)`, `TrainingArguments(...)`, `torch.cuda.mem_get_info()` in `if _TORCH_AVAILABLE:` guards. The orphan file should import clean even on a machine without torch installed.

**Acceptance**: file imports without crashing on machines lacking torch; with torch present, all symbols resolve. No F821 errors.

**Important**: do NOT verify the actual training step works in Batch 3.5. That verification is gated to S6 Hour 1 per ADR-007 entry criteria.

---

### Step 3: Fix DC-EPMS-014 - cummins_adapter.py mypy parse error

**Estimated time**: 15 minutes
**Severity**: MEDIUM (blocks mypy strict pre-commit hook)

Inspect line 41 of `backend/hal/cummins_adapter.py` for non-ASCII bytes. Look for BOM, mojibake patterns, or invisible chars.

Re-save file as pure UTF-8 without BOM:

```python
with open('backend/hal/cummins_adapter.py', 'rb') as f:
    raw = f.read()
if raw.startswith(b'\xef\xbb\xbf'):
    raw = raw[3:]
text = raw.decode('utf-8-sig')
with open('backend/hal/cummins_adapter.py', 'w', encoding='utf-8', newline='\n') as f:
    f.write(text)
```

Run `mypy backend/hal/cummins_adapter.py` and `pytest tests/test_hal_adapters.py -q`.

**Acceptance**: mypy parses file, all 39 hal tests still pass.

---

### Step 4: Fix DC-EPMS-015 - Mass mojibake replacement

**Estimated time**: 60 to 90 minutes
**Severity**: MEDIUM (blocks ruff pre-commit hook)

Build a mojibake-to-replacement mapping table. Common cases:

| Mojibake | Original | ASCII replacement |
|----------|----------|-------------------|
| `times` | multiplication | `x` |
| `endash` | en dash | `-` |
| `rsquote` | right single quote | `'` |
| `degC` | degree sign | `degC` |
| `Delta` | delta symbol | `delta` |
| `tau` | tau Greek | `tau` |
| `epsilon` | epsilon Greek | `epsilon` |
| `leq` | less-equal | `<=` |
| `geq` | greater-equal | `>=` |
| `approx` | approximately | `~` |
| `arrow` | right arrow | `->` |

Affected files (12 total):
- `backend/agent_copilot.py`
- `backend/cyber_physical_tools.py`
- `backend/dpo_edge_healing.py`
- `backend/main.py`
- `backend/metrics_router.py`
- `backend/physics/electrical.py`
- `backend/physics/heat_rejection.py`
- `backend/physics/it_thermal.py`
- `backend/physics/mechanical.py`
- `backend/shift_report.py`
- `scripts/simulator.py`

Write `fix_mojibake.py` script that loads each file, applies mappings (longest-first), AST-validates, writes back. Run `ruff check --fix` after.

**Acceptance**: zero ruff RUF001/RUF002/RUF003 errors, 352 tests pass, formulas readable.

---

### Step 5: Fix DC-EPMS-016 + DC-EPMS-017 - pre-commit config tweaks

**Estimated time**: 30 minutes
**Severity**: LOW (cosmetic CI gates)

**DC-EPMS-016 yamllint encoding**: create `.yamllint` config forcing UTF-8 read. Set `PYTHONUTF8=1` env in dev environment.

**DC-EPMS-017 markdownlint style**: create `.markdownlint.json`:

```json
{
  "default": true,
  "MD004": { "style": "dash" },
  "MD013": false,
  "MD034": false,
  "MD041": false
}
```

**Acceptance**: both yamllint and markdownlint hooks PASS.

---

## 4. Closure of Batch 3.5

After all 5 steps complete:

```powershell
git status
pre-commit run --all-files
pytest --tb=no -q
.\validate_batch3.ps1
```

All should be GREEN. Then:

```powershell
git add -A
git commit -m "fix(batch3.5): resolve DC-EPMS-012 to 017 tech debt"
git tag -a v0.6.1-batch3.5 -m "Batch 3.5: tech debt resolved, all hooks GREEN"
```

Update CHANGELOG.md: move all 6 bug entries from "Pending Tech Debt" to "Fixed".

---

## 5. Out of scope (do NOT do in Batch 3.5)

- Do not run actual DPO training (gated to S6 Hour 1 per ADR-007)
- Do not refactor any orphan file logic (only add imports)
- Do not migrate from FAISS to hnswlib (V10 candidate)
- Do not start the LOTO Auditor Agent (that is Batch 4)
- Do not bump major versions of dependencies (separate batch)

---

## 6. Risk register

| Risk | Probability | Mitigation |
|------|-------------|------------|
| Mojibake replacement breaks math notation | Medium | Manual review of physics modules; AST-validate per file |
| Adding numba inflates Docker image | Low | Already pulled transitively; net delta < 50 MB |
| Cummins fix breaks 39 hal tests | Low | Re-save should be byte-equivalent; pytest catches divergence |
| Pre-commit config edits disable real hooks | Low | Each change reviewed against reference config |
| Git history pollution if step 1 needs rollback | Low | Each step commits separately; revert SHA |

---

## 7. Definition of Done

Batch 3.5 is DONE when:

- All 5 steps completed in order
- `pre-commit run --all-files` returns exit 0
- `pytest --tb=no -q` returns 352 passed, 5 deselected
- `.\validate_batch3.ps1` returns 8 of 8 layers PASS
- Tag `v0.6.1-batch3.5` exists
- CHANGELOG.md "Pending Tech Debt" section empty (all 6 bugs in "Fixed")
- Container `dc-epms-pro:latest` healthy in 10 seconds

---

## 8. Why this matters for the Microsoft CO+I narrative

A panel reviewer will ask: "you have 11 bugs registered, what does that mean for production readiness?"

Defensible answer:

1. Bugs are registered with severity, file path, line number, resolution path. Mature engineering hygiene.
2. Five bugs were exposed by adopting CI tooling. That is the value of pre-commit, not its failure.
3. Bugs are isolated: tests still pass, container still builds, runtime unaffected.
4. Resolution is bounded and surgical: 3 to 4 hours dedicated batch with explicit acceptance criteria.

This is engineering culture for hyperscale critical environments. CO+I would much rather see 11 documented bugs with a 3-hour resolution plan than zero bugs that nobody bothered to look for.
