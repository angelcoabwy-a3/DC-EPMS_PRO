# DC-EPMS PRO - move_diagnostics_to_scripts.ps1
# ============================================================
# Layer 2 permanent fix: move diagnostic helpers out of root.
#
# Context: validate_batch3.ps1 Layer 2 flags any .py file at project root
# as a candidate iteration script (DC-EPMS-005 cleanup policy). This is
# a recurring false positive when we add legitimate helper scripts.
#
# Solution: move helpers to scripts/, where they belong by project
# convention. Also archive transient diagnostic .txt outputs.
#
# What gets moved:
#   - diagnose_main_py_engines.py     -> scripts/
#   - diagnose_service.ps1            -> scripts/
#   - fix_layer2_demo_seed.ps1        -> scripts/_archive/closure_session/
#   - apply_main_py_activation.ps1    -> scripts/_archive/closure_session/
#   - apply_changelog_patch.ps1       -> scripts/_archive/closure_session/
#   - apply_batch3_6_orchestrator.ps1 -> scripts/_archive/closure_session/
#   - apply_batch4*.ps1               -> scripts/_archive/closure_session/
#   - verify_loto_endpoint.ps1        -> scripts/  (operational)
#   - apply_activation_v2.ps1         -> scripts/_archive/closure_session/ (after running)
#
# What gets deleted (transient outputs):
#   - main_py_diagnostic.txt
#   - service_diagnostic.txt
#   - batch4d_apply_*.log
#   - batch3_6_apply_*.log
#   - changelog_patch_*.log
#   - activation_*.log
#
# V9 PowerShell rules verified clean.
# ============================================================

[CmdletBinding()]
param(
    [switch]$DryRun = $false,
    [switch]$AutoConfirm = $false,
    [switch]$KeepLogs = $false
)

$ErrorActionPreference = "Stop"

function Write-Phase {
    param([string]$Title)
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Write-Ok    { param([string]$m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Info  { param([string]$m) Write-Host "  [INFO] $m" -ForegroundColor Cyan }
function Write-Warn  { param([string]$m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }

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

# ============================================================

Write-Phase "Diagnostic helpers cleanup (Layer 2 permanent fix)"

# Ensure target dirs exist
if (-not (Test-Path "scripts")) { New-Item -ItemType Directory -Path "scripts" | Out-Null }
$archiveDir = "scripts\_archive\closure_session"
if (-not (Test-Path $archiveDir)) { New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null }

# Operational helpers (stay accessible in scripts/)
$operationalMoves = @(
    @{ Source = "diagnose_main_py_engines.py"; Target = "scripts\diagnose_main_py_engines.py" }
    @{ Source = "diagnose_service.ps1";        Target = "scripts\diagnose_service.ps1" }
    @{ Source = "verify_loto_endpoint.ps1";    Target = "scripts\verify_loto_endpoint.ps1" }
)

# Closure session helpers (archived after one-shot use)
$archiveMoves = @(
    "fix_layer2_demo_seed.ps1",
    "apply_main_py_activation.ps1",
    "apply_changelog_patch.ps1",
    "apply_batch3_6_orchestrator.ps1",
    "apply_activation_v2.ps1",
    "apply_batch4a.ps1",
    "apply_batch4b.ps1",
    "apply_batch4c.ps1",
    "apply_batch4d.ps1",
    "CHANGELOG_BATCH4D_PATCH.md",
    "CHANGELOG_SECTIONS_2_3_MANUAL.md",
    "DEMO_SCRIPT.md"
)

# Transient outputs (deleted)
$transientDelete = @(
    "main_py_diagnostic.txt",
    "service_diagnostic.txt"
)

# Logs (deleted unless -KeepLogs)
$logPatterns = @(
    "batch4d_apply_*.log",
    "batch3_6_apply_*.log",
    "changelog_patch_*.log",
    "activation_apply_*.log",
    "activation_v2_*.log",
    "batch3_diag_*.log"
)

# ============================================================
# Phase 1: Move operational helpers
# ============================================================

Write-Phase "Phase 1: Move operational helpers to scripts/"

foreach ($m in $operationalMoves) {
    if (Test-Path $m.Source) {
        if (-not $DryRun) {
            Move-Item $m.Source $m.Target -Force
            Write-Ok "Moved $($m.Source) to $($m.Target)"
        } else {
            Write-Info "[DRY-RUN] Would move $($m.Source) to $($m.Target)"
        }
    } else {
        Write-Info "  Skip: $($m.Source) not at root"
    }
}

# ============================================================
# Phase 2: Archive closure session helpers
# ============================================================

Write-Phase "Phase 2: Archive closure session helpers"

$archivedCount = 0
foreach ($f in $archiveMoves) {
    if (Test-Path $f) {
        $target = Join-Path $archiveDir $f
        if (-not $DryRun) {
            Move-Item $f $target -Force
            Write-Ok "Archived $f"
        } else {
            Write-Info "[DRY-RUN] Would archive $f"
        }
        $archivedCount++
    }
}
Write-Info "Archived: $archivedCount files"

# ============================================================
# Phase 3: Delete transient outputs
# ============================================================

Write-Phase "Phase 3: Delete transient diagnostic outputs"

foreach ($f in $transientDelete) {
    if (Test-Path $f) {
        if (-not $DryRun) {
            Remove-Item $f -Force
            Write-Ok "Deleted $f"
        } else {
            Write-Info "[DRY-RUN] Would delete $f"
        }
    }
}

# ============================================================
# Phase 4: Delete log files (unless -KeepLogs)
# ============================================================

Write-Phase "Phase 4: Delete batch log files"

if ($KeepLogs) {
    Write-Warn "Skipping log deletion per -KeepLogs flag"
} else {
    foreach ($pattern in $logPatterns) {
        $logs = Get-ChildItem -Path "." -Filter $pattern -ErrorAction SilentlyContinue
        foreach ($log in $logs) {
            if (-not $DryRun) {
                Remove-Item $log.FullName -Force
                Write-Ok "Deleted $($log.Name)"
            } else {
                Write-Info "[DRY-RUN] Would delete $($log.Name)"
            }
        }
    }
}

# ============================================================
# Phase 5: Commit
# ============================================================

Write-Phase "Phase 5: Commit cleanup"

if (-not $DryRun) {
    if (Confirm-Action "Stage moves and commit Layer 2 fix?") {
        $ErrorActionPreference = "Continue"
        & git add -A 2>&1 | Out-Null

        $staged = & git diff --cached --name-only 2>&1 | Out-String
        if ($staged.Trim().Length -eq 0) {
            Write-Warn "No changes staged"
            exit 0
        }

        $msg = "chore(layer2): archive closure session helpers and clean root" + "`n`n" +
               "Permanent Layer 2 fix: moves all diagnostic helpers and one-shot" + "`n" +
               "orchestrator scripts out of project root, where they were tripping" + "`n" +
               "validate_batch3.ps1 Layer 2 (DC-EPMS-005 iteration script check)." + "`n`n" +
               "Operational helpers moved to scripts/:" + "`n" +
               "  diagnose_main_py_engines.py" + "`n" +
               "  diagnose_service.ps1" + "`n" +
               "  verify_loto_endpoint.ps1" + "`n`n" +
               "Closure session orchestrators archived to scripts/_archive/closure_session/:" + "`n" +
               "  apply_batch4a.ps1, apply_batch4b.ps1, apply_batch4c.ps1, apply_batch4d.ps1" + "`n" +
               "  apply_main_py_activation.ps1, apply_activation_v2.ps1" + "`n" +
               "  apply_changelog_patch.ps1, apply_batch3_6_orchestrator.ps1" + "`n" +
               "  fix_layer2_demo_seed.ps1" + "`n" +
               "  CHANGELOG_BATCH4D_PATCH.md, CHANGELOG_SECTIONS_2_3_MANUAL.md" + "`n" +
               "  DEMO_SCRIPT.md (in case you want to keep editing)" + "`n`n" +
               "Transient .txt diagnostic outputs deleted." + "`n" +
               "Batch log files deleted (use -KeepLogs flag to preserve)." + "`n`n" +
               "After this commit, validate_batch3.ps1 Layer 2 should report PASS." + "`n`n" +
               "Note: --no-verify per V9 Closing Discipline." + "`n" +
               "Note: ASCII-only commit message per DC-EPMS-024 policy."

        & git commit --no-verify -m $msg 2>&1 | Out-Null
        $commitExit = $LASTEXITCODE
        $ErrorActionPreference = "Stop"

        if ($commitExit -eq 0) {
            $newHead = & git rev-parse HEAD 2>&1 | Out-String
            Write-Ok "Cleanup committed at $($newHead.Trim())"
        } else {
            Write-Warn "Commit failed (exit $commitExit)"
        }
    }
}

Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Green
Write-Host "  Layer 2 cleanup complete" -ForegroundColor Green
Write-Host ("=" * 60) -ForegroundColor Green
Write-Host ""
Write-Host "  Next: run .\validate_batch3.ps1 - Layer 2 should PASS now" -ForegroundColor Cyan
Write-Host ""
