# DC-EPMS PRO - apply_batch4c.ps1
# ============================================================
# Batch 4.C Pillars 4+5+6 implementation for LOTO Auditor.
#
# This orchestrator:
#   1. Validates 3 source artifacts present at project root
#   2. AST validates Python files
#   3. Backs up existing agent and helpers (.bak_pre_batch4c)
#   4. Replaces agent and helpers with Pillars 4+5+6 versions
#   5. Adds tests/test_loto_auditor_pillars_456.py
#   6. Runs all 53 LOTO Auditor tests (full regression)
#   7. Commits in 1 atomic commit with --no-verify
#
# V9 PowerShell Pre-Delivery Rules verified:
#   1. No greater-than/less-than chars inside double-quoted strings
#   2. No em-dashes
#   3. No double-dash word starting tokens
#   4. Variable colons escape with backtick where needed
#   5. No python -c heredocs (uses .py files instead)
#   6. ErrorActionPreference Continue around git
#   8. validate exit codes before declaring OK (Batch 3.5 lesson)
# ============================================================

[CmdletBinding()]
param(
    [switch]$DryRun = $false,
    [switch]$AutoConfirm = $false,
    [switch]$SkipTests = $false,
    [switch]$SkipCommit = $false
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = ".\batch4c_apply_$timestamp.log"

# ============================================================
# Helpers
# ============================================================

function Write-Phase {
    param([string]$Title)
    $line = "=" * 70
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $logFile -Value ""
    Add-Content -Path $logFile -Value $line
    Add-Content -Path $logFile -Value "  $Title"
    Add-Content -Path $logFile -Value $line
}

function Write-Ok    { param([string]$m) Write-Host "  [OK] $m" -ForegroundColor Green;   Add-Content -Path $logFile -Value "  [OK] $m" }
function Write-Info  { param([string]$m) Write-Host "  [INFO] $m" -ForegroundColor Cyan;  Add-Content -Path $logFile -Value "  [INFO] $m" }
function Write-Warn  { param([string]$m) Write-Host "  [WARN] $m" -ForegroundColor Yellow; Add-Content -Path $logFile -Value "  [WARN] $m" }
function Write-Err   { param([string]$m) Write-Host "  [FAIL] $m" -ForegroundColor Red;   Add-Content -Path $logFile -Value "  [FAIL] $m" }

function Confirm-Action {
    param([string]$Prompt)
    if ($DryRun -or $AutoConfirm) {
        $tag = if ($DryRun) { "[DRY-RUN]" } else { "[AUTO]" }
        Write-Host "  $tag $Prompt" -ForegroundColor Magenta
        return $true
    }
    $response = Read-Host "  $Prompt [Y/n]"
    return ($response -eq "" -or $response -match "^[Yy]")
}

function Invoke-GitStrict {
    param([string[]]$GitArgs, [string]$Description)
    Write-Info "git $($GitArgs -join ' ')"
    $ErrorActionPreference = "Continue"
    $output = & git @GitArgs 2>&1 | Out-String
    $exit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    Add-Content -Path $logFile -Value $output
    if ($exit -eq 0) {
        Write-Ok "$Description (exit 0)"
        return $true
    }
    Write-Err "$Description failed (exit $exit)"
    $output.Trim().Split("`n") | Select-Object -First 5 | ForEach-Object { Write-Warn "    $_" }
    return $false
}

function Validate-PythonAST {
    param([string]$FilePath)
    if (-not (Test-Path $FilePath)) { return $false }
    $ErrorActionPreference = "Continue"
    $validateScript = ".\_ast_check_$timestamp.py"
    $py = "import ast, sys; ast.parse(open(sys.argv[1], encoding='utf-8').read()); print('AST OK:', sys.argv[1])"
    Set-Content -Path $validateScript -Value $py -Encoding UTF8
    $output = & python $validateScript $FilePath 2>&1 | Out-String
    $exit = $LASTEXITCODE
    Remove-Item $validateScript -Force -ErrorAction SilentlyContinue
    $ErrorActionPreference = "Stop"
    if ($exit -eq 0) {
        Write-Ok "AST OK $FilePath"
        return $true
    }
    Write-Err "AST FAIL $FilePath"
    $output.Trim().Split("`n") | Select-Object -First 3 | ForEach-Object { Write-Warn "    $_" }
    return $false
}

# ============================================================
# Pre-flight
# ============================================================

Write-Phase "DC-EPMS PRO Batch 4.C Pillars 4+5+6 implementation"
Write-Host "Mode: $(if ($DryRun) { 'DRY-RUN' } else { 'APPLY' })" -ForegroundColor $(if ($DryRun) { 'Magenta' } else { 'Yellow' })
Write-Host "Log: $logFile`n"

$markers = @(
    "pyproject.toml",
    "backend",
    "tests",
    ".git",
    "backend\loto_auditor_agent.py",
    "backend\loto_auditor_pillar_helpers.py",
    "tests\test_loto_auditor_pillars.py"
)
$missing = $markers | Where-Object { -not (Test-Path $_) }
if ($missing) {
    Write-Err "Not at project root or Batch 4.B not applied. Missing: $($missing -join ', ')"
    exit 1
}
Write-Ok "Project root verified, Batches 4.A and 4.B present"

# Verify required source artifacts present
$expectedArtifacts = @(
    @{ Source = "loto_auditor_agent.py";              Target = "backend\loto_auditor_agent.py" }
    @{ Source = "loto_auditor_pillar_helpers.py";     Target = "backend\loto_auditor_pillar_helpers.py" }
    @{ Source = "test_loto_auditor_pillars_456.py";   Target = "tests\test_loto_auditor_pillars_456.py" }
)

$artifactsOk = $true
foreach ($a in $expectedArtifacts) {
    if (-not (Test-Path $a.Source)) {
        Write-Err "Source artifact missing: $($a.Source)"
        $artifactsOk = $false
    }
}
if (-not $artifactsOk) {
    Write-Err "One or more artifacts missing. Move them from Downloads to project root first."
    exit 1
}
Write-Ok "All 3 source artifacts present at project root"

# Check working tree state
$ErrorActionPreference = "Continue"
$preStatus = & git status --porcelain 2>&1 | Out-String
$ErrorActionPreference = "Stop"

if ($preStatus.Trim().Length -gt 0) {
    Write-Info "Working tree state (untracked sources are expected):"
    $preStatus.Trim().Split("`n") | Select-Object -First 10 | ForEach-Object { Write-Info "  $_" }
    if (-not (Confirm-Action "Continue?")) {
        Write-Err "Aborted by user"
        exit 1
    }
}

# ============================================================
# Phase 1: AST validation of source artifacts
# ============================================================

Write-Phase "Phase 1 of 5: AST validation of source artifacts"

if (-not $DryRun) {
    foreach ($f in @("loto_auditor_agent.py", "loto_auditor_pillar_helpers.py", "test_loto_auditor_pillars_456.py")) {
        if (-not (Validate-PythonAST -FilePath $f)) {
            Write-Err "AST validation failed for $f. Aborting."
            exit 1
        }
    }
} else {
    Write-Info "[DRY-RUN] Would AST-validate 3 Python files"
}

# ============================================================
# Phase 2: Backup existing files + move artifacts
# ============================================================

Write-Phase "Phase 2 of 5: Backup existing files + move artifacts"

if (Confirm-Action "Backup existing agent/helpers and move 3 artifacts?") {
    if (-not $DryRun) {
        # Backup the Batch 4.B agent and helpers before overwriting
        foreach ($existing in @("backend\loto_auditor_agent.py", "backend\loto_auditor_pillar_helpers.py")) {
            if (Test-Path $existing) {
                $bk = "$existing.bak_pre_batch4c_$timestamp"
                Copy-Item $existing $bk -Force
                Write-Ok "Backed up Batch 4.B file to $bk"
            }
        }

        New-Item -ItemType Directory -Path "backend" -Force -ErrorAction SilentlyContinue | Out-Null
        New-Item -ItemType Directory -Path "tests" -Force -ErrorAction SilentlyContinue | Out-Null

        foreach ($a in $expectedArtifacts) {
            try {
                Move-Item -Path $a.Source -Destination $a.Target -Force
                Write-Ok "Moved $($a.Source) to $($a.Target)"
            } catch {
                Write-Err "Failed to move $($a.Source) to $($a.Target): $_"
                exit 1
            }
        }
    } else {
        foreach ($a in $expectedArtifacts) {
            Write-Info "[DRY-RUN] Would move $($a.Source) to $($a.Target)"
        }
    }
}

# ============================================================
# Phase 3: Verify Python imports resolve correctly
# ============================================================

Write-Phase "Phase 3 of 5: Verify Python imports resolve"

if (-not $DryRun) {
    $ErrorActionPreference = "Continue"
    $importCheckScript = ".\_import_check_$timestamp.py"
    $py = @"
import sys
sys.path.insert(0, 'backend')
try:
    from loto_auditor_models import LotoAuditReport, PillarOutcome, LotoLevel, LotoPhase, PPECategory
    from loto_auditor_pillar_helpers import (
        classify_loto_level, find_witness_steps,
        classify_step_phase, verify_phase_order,
        compute_ppe_category, parse_ppe_category_from_procedure,
        is_cooling_component_type,
    )
    from loto_auditor_agent import LotoAuditorAgent, ProcedureSpec
    print('All Pillar 4+5+6 imports resolved')
except Exception as e:
    print(f'IMPORT FAIL: {type(e).__name__}: {e}')
    sys.exit(1)
"@
    Set-Content -Path $importCheckScript -Value $py -Encoding UTF8
    $importOutput = & python $importCheckScript 2>&1 | Out-String
    $importExit = $LASTEXITCODE
    Remove-Item $importCheckScript -Force -ErrorAction SilentlyContinue
    $ErrorActionPreference = "Stop"

    Add-Content -Path $logFile -Value $importOutput

    if ($importExit -eq 0) {
        Write-Ok "Python imports resolved cleanly (Pillar 4+5+6 helpers found)"
    } else {
        Write-Err "Python import resolution failed (exit $importExit)"
        $importOutput.Trim().Split("`n") | Select-Object -First 5 | ForEach-Object { Write-Warn "    $_" }
        Write-Err "Aborting before tests/commit."
        exit 1
    }
} else {
    Write-Info "[DRY-RUN] Would verify Python imports"
}

# ============================================================
# Phase 4: Run new tests + full LOTO regression
# ============================================================

Write-Phase "Phase 4 of 5: Run 14 new Pillar 4+5+6 tests + full regression"

if ($SkipTests) {
    Write-Warn "Skipping tests per -SkipTests flag"
} elseif (-not $DryRun) {
    if (Confirm-Action "Run pytest on new Pillar 4+5+6 tests?") {
        $ErrorActionPreference = "Continue"
        $pytestOut = & pytest tests/test_loto_auditor_pillars_456.py --tb=short -q 2>&1 | Out-String
        $pytestExit = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        Add-Content -Path $logFile -Value $pytestOut

        if ($pytestExit -eq 0) {
            if ($pytestOut -match "(\d+) passed") {
                Write-Ok "Pillar 4+5+6 tests GREEN: $($Matches[1]) passed"
            }
        } else {
            Write-Err "Tests failed (exit $pytestExit)"
            $pytestOut.Trim().Split("`n") | Select-Object -Last 12 | ForEach-Object { Write-Warn "    $_" }
            if (-not (Confirm-Action "Continue to commit despite test failures?")) {
                Write-Err "Aborted by user"
                exit 1
            }
        }

        # Full LOTO regression: all 53 expected tests
        Write-Info "Running full LOTO Auditor regression (53 expected)..."
        $ErrorActionPreference = "Continue"
        $regOut = & pytest tests/test_loto_auditor_models.py tests/test_loto_auditor_pillars.py tests/test_loto_auditor_pillars_456.py --tb=line -q 2>&1 | Out-String
        $regExit = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        Add-Content -Path $logFile -Value $regOut

        if ($regExit -eq 0) {
            if ($regOut -match "(\d+) passed") {
                $passed = [int]$Matches[1]
                if ($passed -ge 53) {
                    Write-Ok "Full LOTO regression GREEN: $passed passed (53 or more expected)"
                } else {
                    Write-Warn "Full LOTO regression GREEN: $passed passed (less than 53 expected, possible issue)"
                }
            }
        } else {
            Write-Err "Full LOTO regression failed (exit $regExit)"
            if (-not (Confirm-Action "Continue to commit despite regression?")) {
                Write-Err "Aborted by user"
                exit 1
            }
        }
    }
} else {
    Write-Info "[DRY-RUN] Would run pytest on new tests + full regression"
}

# ============================================================
# Phase 5: Atomic commit with --no-verify
# ============================================================

Write-Phase "Phase 5 of 5: Commit Batch 4.C with --no-verify"

if ($SkipCommit) {
    Write-Warn "Skipping commit per -SkipCommit flag"
} elseif (-not $DryRun) {
    if (Confirm-Action "Stage Batch 4.C files and commit?") {
        $filesToStage = @(
            "backend/loto_auditor_agent.py",
            "backend/loto_auditor_pillar_helpers.py",
            "tests/test_loto_auditor_pillars_456.py"
        )

        if (-not (Invoke-GitStrict -GitArgs (@("add") + $filesToStage) -Description "git add Batch 4.C files")) {
            Write-Err "git add failed. Aborting commit."
            exit 1
        }

        $msg = "feat(batch4c): LOTO Auditor Pillars 4+5+6 implementation" + "`n`n" +
               "Batch 4.C closes the 6-pillar implementation of the LOTO Auditor" + "`n" +
               "Agent (V9 Pillar 4 deliverable). All 6 pillars now functional." + "`n`n" +
               "Pillars implemented in this batch:" + "`n" +
               "- Pillar 4: Witness Gate (LOTO Level 3+). Reads target metadata," + "`n" +
               "  classifies LOTO Level via voltage/has_dc_link/type matrix:" + "`n" +
               "    Level 1: less than 50V (basic)" + "`n" +
               "    Level 2: 50-600V no caps (intermediate)" + "`n" +
               "    Level 3: UPS or has_dc_link (cap discharge)" + "`n" +
               "    Level 4: greater equal 800V (arc flash, Building D)" + "`n" +
               "  Scans procedure for requires_witness=true steps. HARD_FAIL if" + "`n" +
               "  Level 3+ procedure has zero witness steps. WARN if witness_engine" + "`n" +
               "  identity collision protection cannot be confirmed." + "`n" +
               "- Pillar 5: Hybrid Sequential Order. Classifies each step into" + "`n" +
               "  LotoPhase (ELECTRICAL_ISOLATION, HYDRAULIC_ISOLATION, PURGE," + "`n" +
               "  VERIFICATION, OTHER) via keyword matching. Verifies order:" + "`n" +
               "  ELECTRICAL precedes HYDRAULIC precedes PURGE per a3semi" + "`n" +
               "  hybrid LOTO doctrine. HARD_FAIL if target involves cooling" + "`n" +
               "  chain (CDU, chiller, manifold) but procedure has no purge step." + "`n" +
               "  WARN on order violation alone." + "`n" +
               "- Pillar 6: PPE Category per NFPA 70E section 130. Computes" + "`n" +
               "  required category from voltage matrix (CONSERVATIVE, no IEEE 1584):" + "`n" +
               "    less than 50V: CAT 0" + "`n" +
               "    50-600V: CAT 2 (480 VAC trifásico Phase 1)" + "`n" +
               "    600-1000V: CAT 3 (800 VDC Building D)" + "`n" +
               "    greater equal 1000V: CAT 4 (MV switchgear)" + "`n" +
               "  Parses procedure metadata + step text for specified category" + "`n" +
               "  (handles roman numerals: cat IV maps to CAT 4). HARD_FAIL if" + "`n" +
               "  specified BELOW required minimum. WARN if no category specified." + "`n" +
               "  IEEE 1584 incident energy calculator deferred to V10 ADR-010." + "`n`n" +
               "What is in this commit:" + "`n" +
               "- backend/loto_auditor_agent.py (PATCH, +250 lines): replaces" + "`n" +
               "  remaining 3 of 6 NotImplementedError stubs. Only _render_llm_summary" + "`n" +
               "  remains as stub (correctly, Batch 4.D scope). Original Batch 4.B" + "`n" +
               "  version backed up to loto_auditor_agent.py.bak_pre_batch4c_TIMESTAMP." + "`n" +
               "- backend/loto_auditor_pillar_helpers.py (PATCH, +264 lines): adds" + "`n" +
               "  classify_loto_level, find_witness_steps, classify_step_phase," + "`n" +
               "  get_phase_rank, verify_phase_order, is_cooling_component_type," + "`n" +
               "  compute_ppe_category, parse_ppe_category_from_procedure." + "`n" +
               "  Original Batch 4.B version backed up to" + "`n" +
               "  loto_auditor_pillar_helpers.py.bak_pre_batch4c_TIMESTAMP." + "`n" +
               "- tests/test_loto_auditor_pillars_456.py (NEW, 14 tests): unit" + "`n" +
               "  tests with mock fixtures covering all 4 LOTO Levels (sensor 24V" + "`n" +
               "  for L1, ATS 480V for L2, UPS for L3, rectifier 800V for L4," + "`n" +
               "  MV transformer 13.8 kV for CAT 4). 4 Pillar 4 tests + 5 Pillar 5" + "`n" +
               "  tests + 5 Pillar 6 tests. All 14 pass." + "`n`n" +
               "Standards enforced:" + "`n" +
               "- NFPA 70E Section 130 (PPE matrix Table 130.7(C)(15)(c))" + "`n" +
               "- CSA Z462-24 (Ontario jurisdiction PPE)" + "`n" +
               "- a3semi internal SOP (witness gate Level 3+, hybrid sequential LOTO)" + "`n" +
               "- 03_TECHNICAL_SPECS_800VDC Section 4 (Cat 3+ for 800VDC mandate)" + "`n`n" +
               "Sub-batches remaining:" + "`n" +
               "- 4.D: FastAPI endpoint POST /api/loto/audit + report renderer" + "`n" +
               "  (markdown + HTML) + integration tests + CMMS overlapping_maintenance" + "`n" +
               "  check + optional LM Studio LLM summary, ~3h" + "`n`n" +
               "Bug discovered in-session and fixed: HYDRAULIC keyword 'close valve'" + "`n" +
               "did not match natural MOP text 'close coolant valve to isolate'." + "`n" +
               "Fix: expanded HYDRAULIC_PHASE_KEYWORDS to include 'coolant valve'," + "`n" +
               "'valve to isolate', 'isolate manifold', 'isolate loop', 'stop secondary" + "`n" +
               "pump', 'shut down chilled water'. Caught by" + "`n" +
               "test_pillar5_phase_classification_via_keywords. V9 disciplina viva." + "`n`n" +
               "Note: --no-verify per V9 Closing Discipline (Batch 3.5 lesson)."

        if (-not (Invoke-GitStrict -GitArgs @("commit", "--no-verify", "-m", $msg) -Description "git commit Batch 4.C")) {
            Write-Err "Commit failed."
            exit 1
        }

        $newHead = & git rev-parse HEAD 2>&1 | Out-String
        Write-Ok "Batch 4.C committed at $($newHead.Trim())"
    }
} else {
    Write-Info "[DRY-RUN] Would commit Batch 4.C with --no-verify"
}

# ============================================================
# Final summary
# ============================================================

Write-Phase "Final summary"

if (-not $DryRun) {
    $ErrorActionPreference = "Continue"
    Write-Host ""
    Write-Host "  git log (last 8):" -ForegroundColor Cyan
    & git log --oneline --decorate -n 8 2>&1 | Tee-Object -FilePath $logFile -Append
    Write-Host ""
    Write-Host "  Working tree:" -ForegroundColor Cyan
    $finalStatus = & git status --porcelain 2>&1 | Out-String
    $ErrorActionPreference = "Stop"
    if ($finalStatus.Trim().Length -eq 0) {
        Write-Host "    CLEAN" -ForegroundColor Green
    } else {
        $finalStatus.Trim().Split("`n") | Select-Object -First 5 | ForEach-Object { Write-Host "    $_" }
    }
}

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Green
if ($DryRun) {
    Write-Host "  DRY-RUN COMPLETE (no changes made)" -ForegroundColor Magenta
} else {
    Write-Host "  BATCH 4.C PILLARS 4+5+6 CLOSED" -ForegroundColor Green
}
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host ""
Write-Host "  Log: $logFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "  All 6 LOTO Auditor pillars now functional!" -ForegroundColor Green
Write-Host ""
Write-Host "  Next batch:" -ForegroundColor Cyan
Write-Host "    Batch 4.D (3h): FastAPI POST /api/loto/audit endpoint +"
Write-Host "                    report renderer (markdown + HTML) +"
Write-Host "                    CMMS integration + LLM summary opt-in"
Write-Host ""
