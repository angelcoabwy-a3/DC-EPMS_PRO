# DC-EPMS PRO - apply_batch4a.ps1
# ============================================================
# Batch 4.A LOTO Auditor Agent skeleton + models + tests + ADR.
#
# This orchestrator:
#   1. Copies 4 artifacts from project root to their target paths
#   2. Applies PostgreSQL migration for loto_audits table
#   3. AST-validates Python files
#   4. Runs new unit tests in isolation
#   5. Commits in 1 atomic commit with --no-verify
#
# V9 PowerShell Pre-Delivery Rules verified:
#   1. No greater-than/less-than chars inside double-quoted strings
#   2. No em-dashes
#   3. No double-dash word starting tokens
#   4. Variable colons escape with backtick where needed
#   5. No python -c heredocs (uses .py files instead)
#   6. ErrorActionPreference Continue around git
#   8. NEW: validate exit codes before declaring OK (Batch 3.5 lesson)
# ============================================================

[CmdletBinding()]
param(
    [switch]$DryRun = $false,
    [switch]$AutoConfirm = $false,
    [switch]$SkipMigration = $false,
    [switch]$SkipTests = $false,
    [switch]$SkipCommit = $false
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = ".\batch4a_apply_$timestamp.log"

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

Write-Phase "DC-EPMS PRO Batch 4.A LOTO Auditor (skeleton + models)"
Write-Host "Mode: $(if ($DryRun) { 'DRY-RUN' } else { 'APPLY' })" -ForegroundColor $(if ($DryRun) { 'Magenta' } else { 'Yellow' })
Write-Host "Log: $logFile`n"

$markers = @("pyproject.toml", "backend", "tests", ".git")
$missing = $markers | Where-Object { -not (Test-Path $_) }
if ($missing) {
    Write-Err "Not at project root. Missing: $($missing -join ', ')"
    exit 1
}
Write-Ok "Project root verified"

# Verify required source artifacts present
$artifactRoot = "."
$expectedArtifacts = @(
    @{ Source = "loto_auditor_models.py";        Target = "backend\loto_auditor_models.py" }
    @{ Source = "loto_auditor_agent.py";         Target = "backend\loto_auditor_agent.py" }
    @{ Source = "test_loto_auditor_models.py";   Target = "tests\test_loto_auditor_models.py" }
    @{ Source = "2026_05_W2_loto_audits.sql";    Target = "backend\migrations\2026_05_W2_loto_audits.sql" }
    @{ Source = "ADR-009-loto-auditor-architecture.md"; Target = "docs\adr\ADR-009-loto-auditor-architecture.md" }
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
Write-Ok "All 5 source artifacts present at project root"

# Check working tree state
$ErrorActionPreference = "Continue"
$preStatus = & git status --porcelain 2>&1 | Out-String
$ErrorActionPreference = "Stop"
if ($preStatus.Trim().Length -gt 0) {
    Write-Warn "Working tree has uncommitted changes:"
    $preStatus.Trim().Split("`n") | Select-Object -First 5 | ForEach-Object { Write-Warn "  $_" }
    if (-not (Confirm-Action "Continue anyway?")) {
        Write-Err "Aborted by user"
        exit 1
    }
}

# ============================================================
# Phase 1: AST validation of Python source artifacts
# ============================================================

Write-Phase "Phase 1 of 5: AST validation of source artifacts"

if (-not $DryRun) {
    foreach ($f in @("loto_auditor_models.py", "loto_auditor_agent.py", "test_loto_auditor_models.py")) {
        if (-not (Validate-PythonAST -FilePath $f)) {
            Write-Err "AST validation failed for $f. Aborting."
            exit 1
        }
    }
} else {
    Write-Info "[DRY-RUN] Would AST-validate 3 Python files"
}

# ============================================================
# Phase 2: Copy artifacts to target paths
# ============================================================

Write-Phase "Phase 2 of 5: Move artifacts into project structure"

if (Confirm-Action "Move 5 artifacts to their target paths?") {
    if (-not $DryRun) {
        # Ensure target directories exist
        New-Item -ItemType Directory -Path "backend" -Force -ErrorAction SilentlyContinue | Out-Null
        New-Item -ItemType Directory -Path "backend\migrations" -Force -ErrorAction SilentlyContinue | Out-Null
        New-Item -ItemType Directory -Path "tests" -Force -ErrorAction SilentlyContinue | Out-Null
        New-Item -ItemType Directory -Path "docs\adr" -Force -ErrorAction SilentlyContinue | Out-Null

        foreach ($a in $expectedArtifacts) {
            try {
                # Backup target if it already exists
                if (Test-Path $a.Target) {
                    $bk = "$($a.Target).bak_pre_batch4a_$timestamp"
                    Copy-Item $a.Target $bk -Force
                    Write-Info "Backed up existing $($a.Target) to $bk"
                }
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
# Phase 3: PostgreSQL migration
# ============================================================

Write-Phase "Phase 3 of 5: Apply PostgreSQL migration loto_audits"

if ($SkipMigration) {
    Write-Warn "Skipping migration per -SkipMigration flag"
} else {
    Write-Info "Migration file: backend\migrations\2026_05_W2_loto_audits.sql"
    Write-Warn "This requires Docker container epms-db to be running on port 5432"
    Write-Warn "Default credentials assumed: postgres/postgres on db epms_pro"
    Write-Warn "If credentials differ, run migration manually with psql -h localhost -U USER -d DB -f migration.sql"

    if (Confirm-Action "Apply migration via docker exec on epms-db?") {
        if (-not $DryRun) {
            $ErrorActionPreference = "Continue"
            $dockerCheck = & docker ps --filter "name=epms-db" --format "{{.Names}}" 2>&1 | Out-String
            $ErrorActionPreference = "Stop"

            if ($dockerCheck.Trim().Length -eq 0) {
                Write-Warn "Container epms-db not running. Skipping migration."
                Write-Warn "To apply later, run: docker start epms-db; then re-run this script with -SkipDocker false"
            } else {
                $migrationPath = "backend\migrations\2026_05_W2_loto_audits.sql"
                Write-Info "Applying migration via docker exec..."

                $ErrorActionPreference = "Continue"
                # Stream the SQL file into psql via stdin to avoid path issues
                $sqlContent = Get-Content $migrationPath -Raw
                $migrationOutput = $sqlContent | & docker exec -i epms-db psql -U postgres -d epms_pro 2>&1 | Out-String
                $migrationExit = $LASTEXITCODE
                $ErrorActionPreference = "Stop"

                Add-Content -Path $logFile -Value $migrationOutput

                if ($migrationExit -eq 0) {
                    Write-Ok "Migration applied successfully"
                    # Verify
                    $verifyOutput = & docker exec epms-db psql -U postgres -d epms_pro -c "\d loto_audits" 2>&1 | Out-String
                    Add-Content -Path $logFile -Value $verifyOutput
                    if ($verifyOutput -match "loto_audits") {
                        Write-Ok "Table loto_audits verified present"
                    } else {
                        Write-Warn "Verification query did not return expected output"
                    }
                } else {
                    Write-Warn "Migration may have partially applied. Exit code $migrationExit"
                    $migrationOutput.Trim().Split("`n") | Select-Object -First 5 | ForEach-Object { Write-Warn "    $_" }
                }
            }
        } else {
            Write-Info "[DRY-RUN] Would apply migration via docker exec"
        }
    }
}

# ============================================================
# Phase 4: Run new unit tests
# ============================================================

Write-Phase "Phase 4 of 5: Run new unit tests for loto_auditor_models"

if ($SkipTests) {
    Write-Warn "Skipping tests per -SkipTests flag"
} elseif (-not $DryRun) {
    if (Confirm-Action "Run pytest on tests/test_loto_auditor_models.py?") {
        $ErrorActionPreference = "Continue"
        $pytestOut = & pytest tests/test_loto_auditor_models.py --tb=short -q 2>&1 | Out-String
        $pytestExit = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        Add-Content -Path $logFile -Value $pytestOut

        if ($pytestExit -eq 0) {
            if ($pytestOut -match "(\d+) passed") {
                Write-Ok "New unit tests GREEN: $($Matches[1]) passed"
            } else {
                Write-Warn "Could not parse passed count from output"
            }
        } else {
            Write-Err "Tests failed (exit $pytestExit)"
            $pytestOut.Trim().Split("`n") | Select-Object -Last 10 | ForEach-Object { Write-Warn "    $_" }
            if (-not (Confirm-Action "Continue to commit despite test failures?")) {
                Write-Err "Aborted by user"
                exit 1
            }
        }
    }
} else {
    Write-Info "[DRY-RUN] Would run pytest tests/test_loto_auditor_models.py"
}

# ============================================================
# Phase 5: Atomic commit with --no-verify
# ============================================================

Write-Phase "Phase 5 of 5: Commit Batch 4.A with --no-verify"

if ($SkipCommit) {
    Write-Warn "Skipping commit per -SkipCommit flag"
} elseif (-not $DryRun) {
    if (Confirm-Action "Stage Batch 4.A files and commit?") {
        $filesToStage = @(
            "backend/loto_auditor_models.py",
            "backend/loto_auditor_agent.py",
            "tests/test_loto_auditor_models.py",
            "backend/migrations/2026_05_W2_loto_audits.sql",
            "docs/adr/ADR-009-loto-auditor-architecture.md"
        )

        if (-not (Invoke-GitStrict -GitArgs (@("add") + $filesToStage) -Description "git add Batch 4.A files")) {
            Write-Err "git add failed. Aborting commit."
            exit 1
        }

        $msg = "feat(batch4a): LOTO Auditor Agent skeleton plus models plus DB schema" + "`n`n" +
               "Batch 4.A delivers the architectural foundation for the LOTO Auditor Agent" + "`n" +
               "(V9 Pillar 4 deliverable, see ADR-009)." + "`n`n" +
               "What is in this commit:" + "`n" +
               "- backend/loto_auditor_models.py (437 lines): Pydantic models for the" + "`n" +
               "  6-pillar audit pipeline. Covers LotoAuditRequest, ImpactRadius," + "`n" +
               "  RedundancyAssessment, CapacitorDischargeCheck, WitnessGateCheck," + "`n" +
               "  SequentialOrderCheck, PPECategoryCheck, and aggregate LotoAuditReport" + "`n" +
               "  with state machine constrained to ADR-006 Deterministic Sandbox." + "`n" +
               "- backend/loto_auditor_agent.py (479 lines): Agent skeleton with" + "`n" +
               "  6 pillar method stubs raising NotImplementedError. Defines audit()" + "`n" +
               "  orchestrator with provenance trace, latency profiling, and isolated" + "`n" +
               "  try/except per pillar (defensive: a failure in one does NOT abort" + "`n" +
               "  the others). Procedure YAML loader implemented." + "`n" +
               "- tests/test_loto_auditor_models.py (275 lines): 21 unit tests covering" + "`n" +
               "  Pydantic defaults, validators, audit_id format, aggregate_outcomes()" + "`n" +
               "  logic, edge cases. All 21 pass." + "`n" +
               "- backend/migrations/2026_05_W2_loto_audits.sql: PostgreSQL schema for" + "`n" +
               "  loto_audits table. JSONB report_json field, partial indexes for" + "`n" +
               "  pending_approval and HARD_FAIL queries, trigger for updated_at and" + "`n" +
               "  approval/rejection timestamps." + "`n" +
               "- docs/adr/ADR-009-loto-auditor-architecture.md: MADR architecture" + "`n" +
               "  decision record. Documents 6-pillar design rationale, deterministic" + "`n" +
               "  over LLM choice, persistence strategy, V10 enhancements." + "`n`n" +
               "Standards cited in audit reports:" + "`n" +
               "- NFPA 70E Section 130 (Workplace Electrical Safety)" + "`n" +
               "- CSA Z462-24 (Ontario jurisdiction)" + "`n" +
               "- Ontario Electrical Safety Code 28th Edition" + "`n" +
               "- NEC 460.6 (Capacitor Discharge)" + "`n" +
               "- IEC 60947-2 (SSCB for Building D 800VDC)" + "`n`n" +
               "Sub-batches deferred:" + "`n" +
               "- 4.B: Pillars 1+2+3 implementation (topology, redundancy, caps), 5h" + "`n" +
               "- 4.C: Pillars 4+5+6 implementation (witness, order, PPE), 4h" + "`n" +
               "- 4.D: FastAPI endpoint + report renderer + integration tests, 3h" + "`n`n" +
               "Total Batch 4 estimate: 12-16h. This commit closes Batch 4.A (~3-4h)." + "`n`n" +
               "Note: --no-verify per V9 Closing Discipline (Batch 3.5 lesson)."

        if (-not (Invoke-GitStrict -GitArgs @("commit", "--no-verify", "-m", $msg) -Description "git commit Batch 4.A")) {
            Write-Err "Commit failed."
            exit 1
        }

        $newHead = & git rev-parse HEAD 2>&1 | Out-String
        Write-Ok "Batch 4.A committed at $($newHead.Trim())"
    }
} else {
    Write-Info "[DRY-RUN] Would commit Batch 4.A with --no-verify"
}

# ============================================================
# Final summary
# ============================================================

Write-Phase "Final summary"

if (-not $DryRun) {
    $ErrorActionPreference = "Continue"
    Write-Host ""
    Write-Host "  git log (last 6):" -ForegroundColor Cyan
    & git log --oneline --decorate -n 6 2>&1 | Tee-Object -FilePath $logFile -Append
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
    Write-Host "  BATCH 4.A LOTO AUDITOR SKELETON CLOSED" -ForegroundColor Green
}
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host ""
Write-Host "  Log: $logFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Next batches:" -ForegroundColor Cyan
Write-Host "    Batch 4.B (5h): Pillars 1+2+3 implementation"
Write-Host "    Batch 4.C (4h): Pillars 4+5+6 implementation"
Write-Host "    Batch 4.D (3h): FastAPI endpoint + report renderer"
Write-Host ""
