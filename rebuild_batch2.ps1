###############################################################################
# DC-EPMS PRO - rebuild_batch2.ps1
#
# Closes Batch 2 by applying the torch CPU-only fix (Decision GO-OPTION-C
# 2026-05-06). Targets ~2 GB image size, down from 8.85 GB v1.
#
# Operations:
#   1. Backup current pyproject.toml + Dockerfile
#   2. Apply pyproject.toml patch (torch CPU pin in [rag] extra)
#   3. Replace Dockerfile with v2 (CPU index + cleanup)
#   4. Remove old bloated image (frees ~9 GB)
#   5. Rebuild with new Dockerfile (target dc-epms-pro:latest tag, fixes Layer 7)
#   6. Show final image size
#   7. Re-run validate_batch2.ps1
#
# Pre-requisites in Downloads:
#   - patch_pyproject_torch_cpu.py
#   - Dockerfile (v2)
#
# Usage:
#   .\rebuild_batch2.ps1
#   .\rebuild_batch2.ps1 -SkipValidate    (just build, no validate)
###############################################################################

[CmdletBinding()]
param(
    [switch]$SkipValidate,
    [string]$DownloadsPath = "$env:USERPROFILE\Downloads"
)

$ErrorActionPreference = 'Stop'
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$logFile = ".\batch2_rebuild_$ts.log"

function Write-Step {
    param([string]$Message, [string]$Color = 'Cyan')
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $Message"
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $logFile -Value $line
}

function Write-Pass {
    param([string]$Message)
    Write-Step "  [PASS] $Message" 'Green'
}

function Write-Fail {
    param([string]$Message)
    Write-Step "  [FAIL] $Message" 'Red'
}

Write-Host ''
Write-Host '======================================================================' -ForegroundColor Cyan
Write-Host '   DC-EPMS PRO - Batch 2 Rebuild (Decision GO-OPTION-C)' -ForegroundColor Cyan
Write-Host '   Target: ~2 GB image (CPU-only torch, aggressive cleanup)' -ForegroundColor Cyan
Write-Host '======================================================================' -ForegroundColor Cyan
Write-Host ''
Write-Step "Log file: $logFile"

# ----------------------------------------------------------------------------
# Step 1: Pre-flight
# ----------------------------------------------------------------------------
Write-Step "Step 1/7 - Pre-flight checks..." 'Yellow'

if (-not $env:VIRTUAL_ENV) {
    Write-Fail "venv not active"
    exit 1
}
Write-Pass "venv active"

if (-not (Test-Path 'pyproject.toml')) {
    Write-Fail "pyproject.toml not found - run from project root"
    exit 1
}
Write-Pass "Project root confirmed"

# Locate fix artifacts in Downloads
$patchScript = Join-Path $DownloadsPath "patch_pyproject_torch_cpu.py"
$dockerfileV2 = Join-Path $DownloadsPath "Dockerfile"

if (-not (Test-Path $patchScript)) {
    Write-Fail "patch_pyproject_torch_cpu.py not found in $DownloadsPath"
    exit 2
}
Write-Pass "Found patch script in Downloads"

if (-not (Test-Path $dockerfileV2)) {
    Write-Fail "Dockerfile (v2) not found in $DownloadsPath"
    exit 2
}
$dfSize = (Get-Item $dockerfileV2).Length
Write-Pass "Found Dockerfile v2 in Downloads ($dfSize bytes)"

# ----------------------------------------------------------------------------
# Step 2: Backup current files
# ----------------------------------------------------------------------------
Write-Step "Step 2/7 - Backing up current files..." 'Yellow'

Copy-Item pyproject.toml "pyproject.toml.bak_pre_torch_cpu_$ts" -Force
Write-Pass "Backed up pyproject.toml"

Copy-Item Dockerfile "Dockerfile.bak_pre_v2_$ts" -Force
Write-Pass "Backed up Dockerfile (v1)"

# ----------------------------------------------------------------------------
# Step 3: Apply pyproject patch
# ----------------------------------------------------------------------------
Write-Step "Step 3/7 - Applying pyproject.toml patch..." 'Yellow'

Move-Item $patchScript .\patch_pyproject_torch_cpu.py -Force

$patchOut = & python patch_pyproject_torch_cpu.py 2>&1
$patchExit = $LASTEXITCODE
$patchOut | ForEach-Object { Add-Content -Path $logFile -Value $_ }

if ($patchExit -ne 0) {
    Write-Fail "patch_pyproject_torch_cpu.py failed (exit $patchExit)"
    $patchOut | ForEach-Object { Write-Host $_ }
    exit 3
}
Write-Pass "pyproject.toml patched"
$patchOut | ForEach-Object { Write-Host "    $_" }

# ----------------------------------------------------------------------------
# Step 4: Replace Dockerfile
# ----------------------------------------------------------------------------
Write-Step "Step 4/7 - Replacing Dockerfile with v2..." 'Yellow'

Move-Item $dockerfileV2 .\Dockerfile -Force
$newSize = (Get-Item Dockerfile).Length
Write-Pass "Dockerfile v2 in place ($newSize bytes)"

# ----------------------------------------------------------------------------
# Step 5: Remove old bloated images (frees disk)
# ----------------------------------------------------------------------------
Write-Step "Step 5/7 - Removing old bloated images..." 'Yellow'

$oldImages = & docker images dc-epms-pro --format "{{.Repository}}:{{.Tag}}" 2>&1
if ($oldImages) {
    $oldImages | ForEach-Object {
        & docker rmi -f $_ 2>&1 | Out-Null
        Write-Pass "Removed image: $_"
    }
} else {
    Write-Step "  [INFO] No old dc-epms-pro images found"
}

# Optional: prune build cache (frees more space)
& docker builder prune -af 2>&1 | Out-Null
Write-Pass "Build cache pruned"

# ----------------------------------------------------------------------------
# Step 6: Rebuild with target tag dc-epms-pro:latest
# ----------------------------------------------------------------------------
Write-Step "Step 6/7 - Rebuilding image (target: dc-epms-pro:latest)..." 'Yellow'
Write-Step "  [INFO] First build with CPU torch will take 3-7 min." 'Gray'

$buildStart = Get-Date

$buildArgs = @(
    'build',
    '--target', 'runtime',
    '-t', 'dc-epms-pro:latest',
    '.'
)

$buildOut = & docker @buildArgs 2>&1 | Out-String
$buildExit = $LASTEXITCODE
$buildOut | Add-Content -Path $logFile

$buildEnd = Get-Date
$buildDuration = [math]::Round(($buildEnd - $buildStart).TotalSeconds, 0)

if ($buildExit -ne 0) {
    Write-Fail "docker build failed (exit $buildExit)"
    Write-Step "Last 30 lines of build output:"
    ($buildOut -split "`n") | Select-Object -Last 30 | ForEach-Object { Write-Host $_ }
    Write-Step "Full log: $logFile"
    exit 4
}

Write-Pass "Image built in ${buildDuration}s"

# Show new size
$sizeRaw = & docker images dc-epms-pro:latest --format "{{.Size}}" 2>&1
Write-Pass "New image size: $sizeRaw"

# Compare to v1 (8.85 GB)
Write-Host ''
Write-Host '   ===== SIZE COMPARISON =====' -ForegroundColor Cyan
Write-Host '   v1 (with CUDA):   8.85 GB' -ForegroundColor Yellow
Write-Host "   v2 (CPU-only):    $sizeRaw" -ForegroundColor Green
Write-Host ''

# ----------------------------------------------------------------------------
# Step 7: Re-validate
# ----------------------------------------------------------------------------
if ($SkipValidate) {
    Write-Step "Step 7/7 - SKIPPED (-SkipValidate flag)" 'Yellow'
}
else {
    Write-Step "Step 7/7 - Running validate_batch2.ps1..." 'Yellow'

    if (-not (Test-Path '.\validate_batch2.ps1')) {
        Write-Fail "validate_batch2.ps1 not in project. Re-validate manually after this completes."
        exit 0
    }

    Write-Host ''
    & .\validate_batch2.ps1
    $validateExit = $LASTEXITCODE
    exit $validateExit
}

# ----------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------
Write-Host ''
Write-Host '======================================================================' -ForegroundColor Green
Write-Host '   REBUILD COMPLETE' -ForegroundColor Green
Write-Host '======================================================================' -ForegroundColor Green
Write-Host ''
Write-Step "Build duration: ${buildDuration}s"
Write-Step "New image: dc-epms-pro:latest ($sizeRaw)"
Write-Step "Log: $logFile"
Write-Host ''
Write-Step "Next: .\validate_batch2.ps1 (or it ran above if -SkipValidate not set)"
Write-Host ''

exit 0
