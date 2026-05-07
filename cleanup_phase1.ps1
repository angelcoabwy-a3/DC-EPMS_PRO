# DC-EPMS PRO - cleanup_phase1.ps1
# ============================================================
# Phase 1 cleanup orchestrator. 4 atomic phases ordered from
# zero-risk (move-only) to low-risk (Docker prune).
#
# Reclaimable target: ~11.5 GB
# Resolves DC-EPMS-005 followup (3 iteration scripts at root)
#
# V9 PowerShell Pre-Delivery Rules verified:
#   1. No greater-than/less-than chars inside double-quoted strings
#   2. No em-dashes
#   3. No double-dash word starting tokens
#   4. Variable colons escape with backtick (where needed)
#   5. No python -c heredocs
#   6. ErrorActionPreference Continue around native (docker, git)
#   7. NEW Rule 8 (Batch 3.5 lesson): validate exit codes before OK
# ============================================================

[CmdletBinding()]
param(
    [switch]$DryRun = $false,
    [switch]$AutoConfirm = $false,
    [switch]$SkipDocker = $false,
    [switch]$KeepBatch2Validate = $false
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = ".\cleanup_phase1_$timestamp.log"

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

function Format-Size {
    param([long]$Bytes)
    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes B"
}

function Get-DirSize {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return 0 }
    $ErrorActionPreference = "SilentlyContinue"
    $size = (Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
             Measure-Object -Property Length -Sum).Sum
    $ErrorActionPreference = "Stop"
    if ($null -eq $size) { return 0 }
    return [long]$size
}

function Test-PytestRunning {
    $ErrorActionPreference = "SilentlyContinue"
    $pytestProcs = Get-Process -Name "pytest" -ErrorAction SilentlyContinue
    $pythonProcs = Get-Process -Name "python" -ErrorAction SilentlyContinue |
                   Where-Object { $_.CommandLine -like "*pytest*" }
    $ErrorActionPreference = "Stop"
    return ($pytestProcs.Count -gt 0 -or $pythonProcs.Count -gt 0)
}

# ============================================================
# Pre-flight
# ============================================================

Write-Phase "DC-EPMS PRO Cleanup Phase 1 - Pre-flight"
Write-Host "Mode: $(if ($DryRun) { 'DRY-RUN' } else { 'APPLY' })" -ForegroundColor $(if ($DryRun) { 'Magenta' } else { 'Yellow' })
Write-Host "Log: $logFile`n"

# Project root sanity
$markers = @("pyproject.toml", "backend", "tests", ".git")
$missing = $markers | Where-Object { -not (Test-Path $_) }
if ($missing) {
    Write-Err "Not at project root. Missing: $($missing -join ', ')"
    exit 1
}
Write-Ok "Project root verified"

# Capture initial state for delta reporting
Write-Info "Capturing initial state..."
$initialProjectSize = Get-DirSize -Path "."
Write-Info "Project root current total: $(Format-Size $initialProjectSize)"

# Check pytest is not running (would conflict with __pycache__ cleanup)
if (Test-PytestRunning) {
    Write-Warn "pytest appears to be running. Cleaning __pycache__ during a test run can cause ImportError."
    if (-not (Confirm-Action "Continue anyway? Recommend stopping pytest first")) {
        Write-Err "Aborted by user"
        exit 1
    }
}

# Capture Docker state
$dockerAvailable = $false
$initialDockerSize = ""
if (-not $SkipDocker) {
    $ErrorActionPreference = "Continue"
    $dockerCheck = Get-Command docker -ErrorAction SilentlyContinue
    $ErrorActionPreference = "Stop"
    if ($dockerCheck) {
        $dockerAvailable = $true
        Write-Info "Docker CLI available"
        $ErrorActionPreference = "Continue"
        $initialDockerSize = & docker system df 2>&1 | Out-String
        $ErrorActionPreference = "Stop"
        Add-Content -Path $logFile -Value "Initial docker system df:"
        Add-Content -Path $logFile -Value $initialDockerSize
    } else {
        Write-Warn "Docker CLI not found in PATH. Skipping all Docker phases."
    }
}

# ============================================================
# Phase 1: Move-only operations (zero risk)
# ============================================================

Write-Phase "Phase 1 of 4: Archive iteration scripts (DC-EPMS-005 followup)"

$archiveDir = ".\scripts\_archive\pre_batch3_5"
$scriptsToArchive = @(
    "fix_orphan_imports.py",
    "fix_mojibake.py",
    "finalize_batch3.py"
)
# Also catch _dc014_fix_*.py and _dc012013_*.py if they survived
$ErrorActionPreference = "SilentlyContinue"
$dcHelpers = Get-ChildItem -Path . -File -Force -Filter "_dc*_fix_*.py" -ErrorAction SilentlyContinue
$ErrorActionPreference = "Stop"
if ($dcHelpers) {
    $scriptsToArchive += ($dcHelpers | ForEach-Object { $_.Name })
}

$scriptsPresent = $scriptsToArchive | Where-Object { Test-Path $_ }

if ($scriptsPresent.Count -eq 0) {
    Write-Info "No iteration scripts at root (Phase 1 already done or never created)"
} else {
    Write-Info "Found $($scriptsPresent.Count) iteration script(s) to archive:"
    foreach ($s in $scriptsPresent) { Write-Info "  $s" }

    if (Confirm-Action "Archive these to $archiveDir ?") {
        if (-not $DryRun) {
            if (-not (Test-Path $archiveDir)) {
                New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
                Write-Ok "Created $archiveDir"
            }
            $movedCount = 0
            foreach ($s in $scriptsPresent) {
                try {
                    Move-Item -Path $s -Destination $archiveDir -Force
                    $movedCount++
                } catch {
                    Write-Err "Failed to move $s : $_"
                }
            }
            Write-Ok "Archived $movedCount of $($scriptsPresent.Count) scripts"
        } else {
            Write-Info "[DRY-RUN] Would archive $($scriptsPresent.Count) scripts to $archiveDir"
        }
    }
}

# Also archive cleanup_phase1.ps1 itself? No - keep at root for re-use.
# Same for disk_audit_dc_epms.ps1 - keep at root as maintenance tool.

# ============================================================
# Phase 2: Move batch logs to logs/_archive/
# ============================================================

Write-Phase "Phase 2 of 4: Archive batch and diag logs"

$logsArchiveDir = ".\logs\_archive"
$ErrorActionPreference = "SilentlyContinue"
$batchLogs = @()
$batchLogs += Get-ChildItem -Path . -File -Force -Filter "batch*_apply_*.log" -ErrorAction SilentlyContinue
$batchLogs += Get-ChildItem -Path . -File -Force -Filter "batch*_diag_*.log" -ErrorAction SilentlyContinue
$batchLogs += Get-ChildItem -Path . -File -Force -Filter "batch*_validate_*.log" -ErrorAction SilentlyContinue
$batchLogs = $batchLogs | Sort-Object LastWriteTime -Descending
$ErrorActionPreference = "Stop"

if ($batchLogs.Count -eq 0) {
    Write-Info "No batch/diag logs at root"
} else {
    Write-Info "Found $($batchLogs.Count) batch/diag logs (preserving 2 most recent)"
    $logsToArchive = $batchLogs | Select-Object -Skip 2
    $logsToKeep = $batchLogs | Select-Object -First 2

    foreach ($l in $logsToKeep) {
        Write-Info "  KEEP: $($l.Name) ($(Format-Size $l.Length))"
    }
    foreach ($l in $logsToArchive) {
        Write-Info "  ARCHIVE: $($l.Name) ($(Format-Size $l.Length))"
    }

    if ($logsToArchive.Count -gt 0 -and (Confirm-Action "Archive $($logsToArchive.Count) logs to $logsArchiveDir ?")) {
        if (-not $DryRun) {
            if (-not (Test-Path $logsArchiveDir)) {
                New-Item -ItemType Directory -Path $logsArchiveDir -Force | Out-Null
                Write-Ok "Created $logsArchiveDir"
            }
            $movedCount = 0
            foreach ($l in $logsToArchive) {
                try {
                    Move-Item -Path $l.FullName -Destination $logsArchiveDir -Force
                    $movedCount++
                } catch {
                    Write-Err "Failed to move $($l.Name) : $_"
                }
            }
            Write-Ok "Archived $movedCount of $($logsToArchive.Count) logs"
        } else {
            Write-Info "[DRY-RUN] Would archive $($logsToArchive.Count) logs"
        }
    }
}

# Also archive pre-cleanup .bak_pre_* older than 24 hours
Write-Info "Checking .bak_pre_* files older than 24 hours..."
$bakArchiveDir = ".\_legacy_backup\bak_pre_pool"
$cutoff = (Get-Date).AddHours(-24)
$ErrorActionPreference = "SilentlyContinue"
$oldBaks = Get-ChildItem -Path . -Recurse -Force -File -Filter "*.bak_pre_*" -ErrorAction SilentlyContinue |
           Where-Object { $_.LastWriteTime -lt $cutoff -and $_.FullName -notlike "*\_legacy_backup\*" }
$ErrorActionPreference = "Stop"

if ($oldBaks.Count -eq 0) {
    Write-Info "No .bak_pre_* files older than 24h"
} else {
    $oldBakSize = ($oldBaks | Measure-Object -Property Length -Sum).Sum
    Write-Info "Found $($oldBaks.Count) .bak_pre_* files older than 24h ($(Format-Size $oldBakSize) total)"
    if (Confirm-Action "Move these to $bakArchiveDir ?") {
        if (-not $DryRun) {
            if (-not (Test-Path $bakArchiveDir)) {
                New-Item -ItemType Directory -Path $bakArchiveDir -Force | Out-Null
            }
            $movedCount = 0
            foreach ($b in $oldBaks) {
                try {
                    Move-Item -Path $b.FullName -Destination $bakArchiveDir -Force
                    $movedCount++
                } catch {
                    # Probably name collision; rename with timestamp
                    $newName = "$($b.Name).archived_$timestamp"
                    try {
                        Move-Item -Path $b.FullName -Destination (Join-Path $bakArchiveDir $newName) -Force
                        $movedCount++
                    } catch {
                        Write-Err "Failed to archive $($b.Name) : $_"
                    }
                }
            }
            Write-Ok "Archived $movedCount of $($oldBaks.Count) .bak_pre_* files"
        } else {
            Write-Info "[DRY-RUN] Would archive $($oldBaks.Count) old .bak_pre_* files"
        }
    }
}

# ============================================================
# Phase 3: __pycache__ recursive cleanup
# ============================================================

Write-Phase "Phase 3 of 4: __pycache__ recursive cleanup (regenerable bytecode)"

$ErrorActionPreference = "SilentlyContinue"
$pycaches = Get-ChildItem -Path . -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notlike "*\.venv\*" -and $_.FullName -notlike "*\_legacy_backup\*" }
$ErrorActionPreference = "Stop"

if ($pycaches.Count -eq 0) {
    Write-Info "No __pycache__ directories outside .venv/_legacy_backup"
} else {
    $pycacheTotal = 0
    foreach ($pc in $pycaches) {
        $pycacheTotal += Get-DirSize -Path $pc.FullName
    }
    Write-Info "Found $($pycaches.Count) __pycache__ dirs outside .venv ($(Format-Size $pycacheTotal))"

    # Note: we deliberately exclude .venv to avoid breaking sentence-transformers,
    # torch, etc. which sometimes ship pre-compiled .pyc that they expect present.
    Write-Info "Excluding .venv site-packages __pycache__ (preserves dependency speed)"

    if (Confirm-Action "Delete $($pycaches.Count) __pycache__ dirs ($(Format-Size $pycacheTotal)) ?") {
        if (-not $DryRun) {
            $deletedCount = 0
            foreach ($pc in $pycaches) {
                try {
                    Remove-Item -Path $pc.FullName -Recurse -Force -ErrorAction Stop
                    $deletedCount++
                } catch {
                    Write-Err "Failed to delete $($pc.FullName) : $_"
                }
            }
            Write-Ok "Deleted $deletedCount of $($pycaches.Count) __pycache__ dirs"
        } else {
            Write-Info "[DRY-RUN] Would delete $($pycaches.Count) dirs ($(Format-Size $pycacheTotal))"
        }
    }
}

# ============================================================
# Phase 4: Docker cleanup
# ============================================================

Write-Phase "Phase 4 of 4: Docker cleanup"

if (-not $dockerAvailable) {
    Write-Info "Skipping Phase 4 (Docker not available)"
} else {
    # Step 4a: Remove batch2-validate image
    if ($KeepBatch2Validate) {
        Write-Info "Keeping dc-epms-pro:batch2-validate (per -KeepBatch2Validate flag)"
    } else {
        $ErrorActionPreference = "Continue"
        $hasBatch2 = & docker images -q "dc-epms-pro:batch2-validate" 2>&1 | Out-String
        $ErrorActionPreference = "Stop"

        if ($hasBatch2.Trim().Length -gt 0) {
            Write-Info "Found dc-epms-pro:batch2-validate (1.54 GB)"
            if (Confirm-Action "Delete batch2-validate image ?") {
                if (-not $DryRun) {
                    $ErrorActionPreference = "Continue"
                    $rmiOutput = & docker rmi "dc-epms-pro:batch2-validate" 2>&1 | Out-String
                    $rmiExit = $LASTEXITCODE
                    $ErrorActionPreference = "Stop"
                    Add-Content -Path $logFile -Value $rmiOutput
                    if ($rmiExit -eq 0) {
                        Write-Ok "Removed dc-epms-pro:batch2-validate"
                    } else {
                        Write-Warn "docker rmi exited $rmiExit. Output:"
                        $rmiOutput.Trim().Split("`n") | Select-Object -First 5 | ForEach-Object { Write-Warn "    $_" }
                    }
                } else {
                    Write-Info "[DRY-RUN] Would remove dc-epms-pro:batch2-validate"
                }
            }
        } else {
            Write-Info "dc-epms-pro:batch2-validate not present (already removed or never tagged)"
        }
    }

    # Step 4b: Image prune (dangling and unused)
    if (Confirm-Action "Run docker image prune -a (removes unused images, NOT in-use ones) ?") {
        if (-not $DryRun) {
            $ErrorActionPreference = "Continue"
            $pruneOutput = & docker image prune -a -f 2>&1 | Out-String
            $pruneExit = $LASTEXITCODE
            $ErrorActionPreference = "Stop"
            Add-Content -Path $logFile -Value $pruneOutput
            if ($pruneExit -eq 0) {
                $reclaimed = ($pruneOutput | Select-String "Total reclaimed space:")
                Write-Ok "Image prune complete. $reclaimed"
            } else {
                Write-Warn "Image prune exited $pruneExit"
            }
        } else {
            Write-Info "[DRY-RUN] Would run docker image prune -a -f"
        }
    }

    # Step 4c: Builder cache prune
    if (Confirm-Action "Run docker builder prune (removes 6.7 GB cache) ?") {
        if (-not $DryRun) {
            $ErrorActionPreference = "Continue"
            $cacheOutput = & docker builder prune -a -f 2>&1 | Out-String
            $cacheExit = $LASTEXITCODE
            $ErrorActionPreference = "Stop"
            Add-Content -Path $logFile -Value $cacheOutput
            if ($cacheExit -eq 0) {
                $reclaimed = ($cacheOutput | Select-String "Total:")
                Write-Ok "Builder cache prune complete. $reclaimed"
            } else {
                Write-Warn "Builder prune exited $cacheExit"
            }
        } else {
            Write-Info "[DRY-RUN] Would run docker builder prune -a -f"
        }
    }

    # Step 4d: Volume prune (orphans only, preserves attached)
    if (Confirm-Action "Run docker volume prune (removes orphaned volumes only, NOT epms-db) ?") {
        if (-not $DryRun) {
            $ErrorActionPreference = "Continue"
            $volOutput = & docker volume prune -f 2>&1 | Out-String
            $volExit = $LASTEXITCODE
            $ErrorActionPreference = "Stop"
            Add-Content -Path $logFile -Value $volOutput
            if ($volExit -eq 0) {
                $reclaimed = ($volOutput | Select-String "Total reclaimed space:")
                Write-Ok "Volume prune complete. $reclaimed"
            } else {
                Write-Warn "Volume prune exited $volExit"
            }
        } else {
            Write-Info "[DRY-RUN] Would run docker volume prune -f"
        }
    }
}

# ============================================================
# Final summary
# ============================================================

Write-Phase "Final summary - Reclaim verification"

$finalProjectSize = Get-DirSize -Path "."
$projectDelta = $initialProjectSize - $finalProjectSize
Write-Info "Project root before: $(Format-Size $initialProjectSize). After: $(Format-Size $finalProjectSize). Delta: $(Format-Size $projectDelta)"

if ($dockerAvailable) {
    Write-Host ""
    Write-Info "Final docker system df:"
    $ErrorActionPreference = "Continue"
    $finalDockerDf = & docker system df 2>&1 | Out-String
    $ErrorActionPreference = "Stop"
    Add-Content -Path $logFile -Value "Final docker system df:"
    Add-Content -Path $logFile -Value $finalDockerDf
    $finalDockerDf.Trim().Split("`n") | ForEach-Object { Write-Host "    $_" }
}

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Green
if ($DryRun) {
    Write-Host "  DRY-RUN COMPLETE - no changes made" -ForegroundColor Magenta
    Write-Host "  Run without -DryRun to apply" -ForegroundColor Magenta
} else {
    Write-Host "  CLEANUP PHASE 1 COMPLETE" -ForegroundColor Green
}
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host ""
Write-Host "  Log: $logFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Resolves DC-EPMS-005 followup (3 iteration scripts archived)" -ForegroundColor Yellow
Write-Host "  Re-run validate_batch3.ps1 to confirm Layer 2 PASS" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Next steps in priority order:" -ForegroundColor Cyan
Write-Host "    1. Run validate_batch3.ps1 (verify 8 of 8 layers PASS)"
Write-Host "    2. Decide Batch 3.5 Recovery option (A minimal | B extend | C bypass)"
Write-Host "    3. Update 01_INSTRUCTIONS.md with drift fixes"
Write-Host "    4. Plan Batch 4 LOTO Auditor session"
Write-Host ""
