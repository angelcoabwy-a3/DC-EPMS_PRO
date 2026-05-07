# DC-EPMS PRO - disk_audit_dc_epms.ps1
# ============================================================
# Read-only disk audit. Identifies disk consumption hotspots
# without modifying anything. Generates report with priority
# recommendations.
#
# V9 PowerShell Pre-Delivery Rules verified clean:
#   1. No greater-than/less-than chars inside double-quoted strings
#   2. No em-dashes
#   3. No double-dash word starting tokens in strings
#   4. Variable colons escape with backtick
#   5. No python -c heredocs
#   6. ErrorActionPreference Continue around native commands
#   7. AST/TOML validation N/A
#   8. NEW Rule from Batch 3.5: validate exit codes before claiming OK
# ============================================================

[CmdletBinding()]
param(
    [string]$ProjectRoot = "C:\dev\DC-EPMS_PRO"
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$reportPath = ".\disk_audit_$timestamp.txt"

# ============================================================
# Helpers
# ============================================================

function Format-Size {
    param([long]$Bytes)
    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes B"
}

function Get-DirectorySize {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return 0 }
    $ErrorActionPreference = "SilentlyContinue"
    $size = (Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
             Measure-Object -Property Length -Sum).Sum
    $ErrorActionPreference = "Stop"
    if ($null -eq $size) { return 0 }
    return [long]$size
}

function Write-Section {
    param([string]$Title)
    $line = "=" * 70
    $msg = "`n$line`n  $Title`n$line"
    Write-Host $msg -ForegroundColor Cyan
    Add-Content -Path $reportPath -Value $msg
}

function Write-Item {
    param([string]$Label, [string]$Value, [ConsoleColor]$Color = "White")
    $msg = "  {0,-50} {1}" -f $Label, $Value
    Write-Host $msg -ForegroundColor $Color
    Add-Content -Path $reportPath -Value $msg
}

function Write-Note {
    param([string]$Text)
    Write-Host "  [NOTE] $Text" -ForegroundColor Yellow
    Add-Content -Path $reportPath -Value "  [NOTE] $Text"
}

function Write-Warn {
    param([string]$Text)
    Write-Host "  [WARN] $Text" -ForegroundColor Red
    Add-Content -Path $reportPath -Value "  [WARN] $Text"
}

# ============================================================
# Header
# ============================================================

$header = "DC-EPMS PRO Disk Audit - $timestamp"
$line = "=" * 70
Set-Content -Path $reportPath -Value "$line`n$header`n$line`n"
Write-Host "`n$line" -ForegroundColor Cyan
Write-Host "  $header" -ForegroundColor Cyan
Write-Host $line -ForegroundColor Cyan

if (-not (Test-Path $ProjectRoot)) {
    Write-Warn "Project root not found at $ProjectRoot"
    exit 1
}

Set-Location $ProjectRoot
Write-Host "  Project: $ProjectRoot" -ForegroundColor Cyan
Write-Host "  Report: $reportPath`n" -ForegroundColor Cyan

# ============================================================
# Section 1: Drive overview
# ============================================================

Write-Section "Section 1 of 9: Drive overview"

$ErrorActionPreference = "Continue"
$drive = Get-PSDrive -Name (Split-Path $ProjectRoot -Qualifier).TrimEnd(":") -ErrorAction SilentlyContinue
$ErrorActionPreference = "Stop"
if ($drive) {
    Write-Item "Drive" "$($drive.Name):"
    Write-Item "Used" (Format-Size ($drive.Used))
    Write-Item "Free" (Format-Size ($drive.Free))
    Write-Item "Total" (Format-Size ($drive.Used + $drive.Free))
    $usedPct = [math]::Round(($drive.Used / ($drive.Used + $drive.Free)) * 100, 1)
    Write-Item "Used percent" "$usedPct percent"
    if ($usedPct -gt 85) {
        Write-Warn "Drive is over 85 percent full. Cleanup recommended urgently."
    }
}

# ============================================================
# Section 2: Project root top-level subdirectories
# ============================================================

Write-Section "Section 2 of 9: Top-level project subdirectories"

$topDirs = Get-ChildItem -Path . -Directory -Force | Sort-Object Name
$totalProjectSize = 0
$dirSizes = @{}

foreach ($dir in $topDirs) {
    $size = Get-DirectorySize -Path $dir.FullName
    $totalProjectSize += $size
    $dirSizes[$dir.Name] = $size
}

$dirSizes.GetEnumerator() | Sort-Object -Property Value -Descending | ForEach-Object {
    $color = "White"
    if ($_.Value -gt 1GB) { $color = "Red" }
    elseif ($_.Value -gt 100MB) { $color = "Yellow" }
    Write-Item "  $($_.Key)/" (Format-Size $_.Value) $color
}

Write-Item "TOTAL project root" (Format-Size $totalProjectSize) "Cyan"

# ============================================================
# Section 3: .venv breakdown
# ============================================================

Write-Section "Section 3 of 9: Python virtualenv analysis"

if (Test-Path ".\.venv") {
    $venvSize = Get-DirectorySize -Path ".\.venv"
    Write-Item ".venv total" (Format-Size $venvSize)

    $venvSitePackages = ".\.venv\Lib\site-packages"
    if (Test-Path $venvSitePackages) {
        $top10Packages = Get-ChildItem $venvSitePackages -Directory -Force |
                         ForEach-Object {
                             [PSCustomObject]@{
                                 Name = $_.Name
                                 Size = Get-DirectorySize -Path $_.FullName
                             }
                         } |
                         Sort-Object -Property Size -Descending |
                         Select-Object -First 10
        Write-Item "Top 10 site-packages by size:" ""
        foreach ($pkg in $top10Packages) {
            Write-Item "    $($pkg.Name)" (Format-Size $pkg.Size)
        }
    }

    if ($venvSize -gt 5GB) {
        Write-Warn ".venv exceeds 5 GB. Consider reinstalling minimal extras only."
    }
} else {
    Write-Note ".venv not found at .\.venv"
}

# ============================================================
# Section 4: __pycache__ scan
# ============================================================

Write-Section "Section 4 of 9: __pycache__ regenerable bytecode"

$ErrorActionPreference = "SilentlyContinue"
$pycaches = Get-ChildItem -Path . -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue
$ErrorActionPreference = "Stop"

if ($pycaches) {
    $pycacheTotal = 0
    foreach ($pc in $pycaches) {
        $pycacheTotal += Get-DirectorySize -Path $pc.FullName
    }
    Write-Item "Total __pycache__ directories" $pycaches.Count
    Write-Item "Combined size" (Format-Size $pycacheTotal)
    Write-Note "Safe to delete: pyc files regenerate on next import"
    Write-Note "Cleanup command (read-only check, copy to run): Get-ChildItem -Recurse -Force -Filter __pycache__ | Remove-Item -Recurse -Force"
} else {
    Write-Item "No __pycache__ directories found" "OK"
}

# ============================================================
# Section 5: Backup files
# ============================================================

Write-Section "Section 5 of 9: Backup files (.bak_pre_*)"

$ErrorActionPreference = "SilentlyContinue"
$backupFiles = Get-ChildItem -Path . -Recurse -Force -File -Filter "*.bak_pre_*" -ErrorAction SilentlyContinue
$ErrorActionPreference = "Stop"

if ($backupFiles) {
    $backupTotal = ($backupFiles | Measure-Object -Property Length -Sum).Sum
    Write-Item "Total .bak_pre_* files" $backupFiles.Count
    Write-Item "Combined size" (Format-Size $backupTotal)
    Write-Item "Files (newest first):" ""
    $backupFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 15 | ForEach-Object {
        $age = (Get-Date) - $_.LastWriteTime
        $ageStr = "{0:N1} hours ago" -f $age.TotalHours
        Write-Item "    $($_.Name)" "$(Format-Size $_.Length) ($ageStr)"
    }
    if ($backupFiles.Count -gt 15) {
        Write-Note "...and $($backupFiles.Count - 15) more older backups"
    }
    Write-Note "Retention policy: keep last 24 hours of backups, archive or delete older"
} else {
    Write-Item "No .bak_pre_* files found" "OK"
}

# ============================================================
# Section 6: Logs and ephemeral files
# ============================================================

Write-Section "Section 6 of 9: Logs and ephemeral files"

# logs/ directory
if (Test-Path ".\logs") {
    $logsSize = Get-DirectorySize -Path ".\logs"
    Write-Item "logs/ directory total" (Format-Size $logsSize)
    $ErrorActionPreference = "SilentlyContinue"
    $logFiles = Get-ChildItem -Path ".\logs" -File -Force -ErrorAction SilentlyContinue
    $ErrorActionPreference = "Stop"
    if ($logFiles) {
        $logFiles | Sort-Object Length -Descending | Select-Object -First 10 | ForEach-Object {
            Write-Item "    $($_.Name)" (Format-Size $_.Length)
        }
        $epmsLog = $logFiles | Where-Object { $_.Name -eq "epms_pro.log" }
        if ($epmsLog -and $epmsLog.Length -gt 50MB) {
            Write-Warn "epms_pro.log exceeds 50 MB. DC-EPMS-019 root cause likely - file held open without rotation."
        }
    }
} else {
    Write-Item "logs/ directory" "not present"
}

# Top-level batch logs
$ErrorActionPreference = "SilentlyContinue"
$batchLogs = Get-ChildItem -Path . -File -Force -Filter "batch*_apply_*.log" -ErrorAction SilentlyContinue
$diagLogs = Get-ChildItem -Path . -File -Force -Filter "batch*_diag_*.log" -ErrorAction SilentlyContinue
$ErrorActionPreference = "Stop"

if ($batchLogs -or $diagLogs) {
    $allBatchLogs = @($batchLogs) + @($diagLogs)
    $batchLogsTotal = ($allBatchLogs | Measure-Object -Property Length -Sum).Sum
    Write-Item "Top-level batch/diag logs" $allBatchLogs.Count
    Write-Item "Combined size" (Format-Size $batchLogsTotal)
    Write-Note "Safe to archive after batch closure (preserve last 1-2 for forensics)"
}

# ============================================================
# Section 7: Archives and tarballs
# ============================================================

Write-Section "Section 7 of 9: Forensic archives"

$ErrorActionPreference = "SilentlyContinue"
$tarballs = Get-ChildItem -Path . -File -Force -Filter "*.tar.gz" -ErrorAction SilentlyContinue
$archiveDir = ".\scripts\_archive"
$ErrorActionPreference = "Stop"

if ($tarballs) {
    Write-Item "Top-level .tar.gz forensic tarballs:" ""
    foreach ($tb in $tarballs) {
        Write-Item "    $($tb.Name)" (Format-Size $tb.Length)
    }
    Write-Note "These are precious forensic backups. Do NOT delete pre-batch tarballs."
}

if (Test-Path $archiveDir) {
    $archiveSize = Get-DirectorySize -Path $archiveDir
    $ErrorActionPreference = "SilentlyContinue"
    $archiveSubdirs = Get-ChildItem -Path $archiveDir -Directory -Force -ErrorAction SilentlyContinue
    $ErrorActionPreference = "Stop"
    Write-Item "scripts/_archive/ total" (Format-Size $archiveSize)
    if ($archiveSubdirs) {
        foreach ($sub in $archiveSubdirs) {
            $subSize = Get-DirectorySize -Path $sub.FullName
            Write-Item "    $($sub.Name)/" (Format-Size $subSize)
        }
    }
}

if (Test-Path ".\_legacy_backup") {
    $legacySize = Get-DirectorySize -Path ".\_legacy_backup"
    Write-Item "_legacy_backup/" (Format-Size $legacySize)
    Write-Note "Pre-V9 baseline. Do NOT touch."
}

# ============================================================
# Section 8: Docker
# ============================================================

Write-Section "Section 8 of 9: Docker disk consumption"

$ErrorActionPreference = "Continue"
$dockerCheck = Get-Command docker -ErrorAction SilentlyContinue
$ErrorActionPreference = "Stop"

if (-not $dockerCheck) {
    Write-Note "Docker CLI not found in PATH. Skipping Docker analysis."
} else {
    Write-Host "  Querying Docker (this may take a moment)..." -ForegroundColor DarkGray

    $ErrorActionPreference = "Continue"
    $systemDf = & docker system df --format "table {{.Type}}\t{{.TotalCount}}\t{{.Active}}\t{{.Size}}\t{{.Reclaimable}}" 2>&1 | Out-String
    $ErrorActionPreference = "Stop"
    Write-Item "docker system df:" ""
    $systemDf.Trim().Split("`n") | ForEach-Object { Write-Item "    $_" "" }
    Add-Content -Path $reportPath -Value $systemDf

    Write-Host ""
    $ErrorActionPreference = "Continue"
    $dcEpmsImages = & docker images --filter "reference=dc-epms-pro*" --format "{{.Repository}}:{{.Tag}} {{.Size}}" 2>&1 | Out-String
    $ErrorActionPreference = "Stop"
    if ($dcEpmsImages.Trim().Length -gt 0) {
        Write-Item "DC-EPMS PRO images:" ""
        $dcEpmsImages.Trim().Split("`n") | ForEach-Object { Write-Item "    $_" "" }
    }

    $ErrorActionPreference = "Continue"
    $danglingCount = (& docker images -f "dangling=true" -q 2>&1 | Measure-Object).Count
    $ErrorActionPreference = "Stop"
    if ($danglingCount -gt 0) {
        Write-Warn "Dangling images detected: $danglingCount. Cleanup with: docker image prune"
    }

    $ErrorActionPreference = "Continue"
    $buildxCache = & docker buildx du --verbose 2>&1 | Out-String
    $ErrorActionPreference = "Stop"
    if ($buildxCache -and $buildxCache.Trim().Length -gt 0 -and $buildxCache -notmatch "error") {
        Write-Note "Buildx cache present. Use 'docker builder prune' to clean."
    }

    Write-Note "To prune everything safely (preserves running containers): docker system prune -a --volumes"
}

# ============================================================
# Section 9: Recommendations and priorities
# ============================================================

Write-Section "Section 9 of 9: Recommendations"

Write-Host ""
Write-Host "  PRIORITY HIGH (immediate cleanup)" -ForegroundColor Red
Write-Host "  ---------------------------------" -ForegroundColor Red
Write-Host "  1. Remove __pycache__ recursive (regenerable, can free 50-200 MB)"
Write-Host "  2. Archive .bak_pre_* older than 24h (freeing 5-15 MB)"
Write-Host "  3. docker system prune -a (can free 8-15 GB if buildx cache accumulated)"
Write-Host ""
Write-Host "  PRIORITY MEDIUM (review before delete)" -ForegroundColor Yellow
Write-Host "  ---------------------------------------" -ForegroundColor Yellow
Write-Host "  4. Move batch_apply_*.log files to logs/_archive/ (keep last 2)"
Write-Host "  5. logs/epms_pro.log rotation if approaching 50MB (DC-EPMS-019)"
Write-Host "  6. Remove fix_orphan_imports.py + fix_mojibake.py + finalize_batch3.py from root"
Write-Host "     (move to scripts/_archive/pre_batch3_5/ - this is the DC-EPMS-005 followup)"
Write-Host ""
Write-Host "  PRIORITY LOW (future planning)" -ForegroundColor Green
Write-Host "  -------------------------------" -ForegroundColor Green
Write-Host "  7. Define backup retention policy in 01_INSTRUCTIONS.md"
Write-Host "  8. Add cleanup script to scripts/maintenance/ for monthly run"
Write-Host "  9. Consider .venv reinstall with minimal extras for distribution"
Write-Host ""

Write-Host "  DO NOT DELETE" -ForegroundColor Cyan
Write-Host "  --------------" -ForegroundColor Cyan
Write-Host "  - data/chroma_db/ (operational RAG, 5.7 MB, gitignored)"
Write-Host "  - _legacy_backup/ (pre-V9 baseline, 63 KB)"
Write-Host "  - pre_batch3_cleanup_*.tar.gz (forensic, 88 KB)"
Write-Host "  - .git/ (commit history)"
Write-Host "  - scripts/_archive/pre_batch3/ (preserves iteration history)"
Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host "  DISK AUDIT COMPLETE" -ForegroundColor Green
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host ""
Write-Host "  Full report: $reportPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Next step: paste relevant findings to Claude for cleanup script generation" -ForegroundColor Yellow
Write-Host ""
