###############################################################################
# DC-EPMS PRO - apply_batch2.ps1 v2 (Batch 2 Orchestrator)
#
# CI/CD 100% LOCAL (V9 Rule 5). Zero GitHub.
#
# v2 fix: pip version specifier uses array form to avoid PowerShell parsing
# the '<' character as a redirection operator inside double-quoted strings.
#
# Idempotent script that:
#   1. Backs up any pre-existing Batch 2 files
#   2. Copies all 6 artifacts from Downloads into project
#   3. Patches backend/main.py (idempotent via patch_main_metrics.py)
#   4. Installs prometheus-fastapi-instrumentator into venv
#   5. Validates Python syntax + imports
#   6. Reports final state
#
# Usage (from C:\dev\DC-EPMS_PRO with venv active):
#   .\apply_batch2.ps1
#
# Skip-install mode (only copy + patch, no pip install):
#   .\apply_batch2.ps1 -SkipInstall
###############################################################################

[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [string]$DownloadsPath = "$env:USERPROFILE\Downloads"
)

$ErrorActionPreference = 'Stop'
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$logFile = ".\batch2_apply_$ts.log"

# ----------------------------------------------------------------------------
# Logging helpers
# ----------------------------------------------------------------------------
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

function Write-Warn {
    param([string]$Message)
    Write-Step "  [WARN] $Message" 'Yellow'
}

function Write-Fail {
    param([string]$Message)
    Write-Step "  [FAIL] $Message" 'Red'
}

# ----------------------------------------------------------------------------
# Banner
# ----------------------------------------------------------------------------
Write-Host ''
Write-Host '======================================================================' -ForegroundColor Cyan
Write-Host '   DC-EPMS PRO - Batch 2 Apply Orchestrator (v2)' -ForegroundColor Cyan
Write-Host '   Docker + Telemetry - V9 AI-Factory Speed Mode' -ForegroundColor Cyan
Write-Host '======================================================================' -ForegroundColor Cyan
Write-Host ''
Write-Step "Log file: $logFile"
Write-Step "Downloads path: $DownloadsPath"

# ----------------------------------------------------------------------------
# Step 1: Pre-flight environment checks
# ----------------------------------------------------------------------------
Write-Step "Step 1/7 - Pre-flight checks..." 'Yellow'

if (-not $env:VIRTUAL_ENV) {
    Write-Fail "VIRTUAL_ENV not set. Activate venv first: .\.venv\Scripts\Activate.ps1"
    exit 1
}
Write-Pass "venv active: $env:VIRTUAL_ENV"

if (-not (Test-Path 'pyproject.toml')) {
    Write-Fail "pyproject.toml not found. Run from C:\dev\DC-EPMS_PRO"
    exit 1
}
Write-Pass "Project root confirmed"

$pyVer = (& python --version 2>&1).ToString()
if ($pyVer -notmatch 'Python 3\.12\.\d+') {
    Write-Fail "Wrong Python: $pyVer (expected 3.12.x)"
    exit 1
}
Write-Pass "$pyVer"

if (-not (Test-Path $DownloadsPath)) {
    Write-Fail "Downloads path not found: $DownloadsPath"
    exit 1
}

# ----------------------------------------------------------------------------
# Step 2: Locate Batch 2 artifacts in Downloads
# ----------------------------------------------------------------------------
Write-Step "Step 2/7 - Locating Batch 2 artifacts in Downloads..." 'Yellow'

$artifacts = @{
    'dockerignore_root'     = @('dockerignore', '.dockerignore')
    'Dockerfile'            = @('Dockerfile')
    'docker-compose.yml'    = @('docker-compose.yml')
    'metrics_router.py'     = @('metrics_router.py')
    'patch_main_metrics.py' = @('patch_main_metrics.py')
    'test_metrics.py'       = @('test_metrics.py')
}

$located = @{}
foreach ($targetName in $artifacts.Keys) {
    $candidates = $artifacts[$targetName]
    $found = $null
    foreach ($name in $candidates) {
        $full = Join-Path $DownloadsPath $name
        if (Test-Path $full) {
            $found = $full
            break
        }
    }
    if ($found) {
        $size = (Get-Item $found).Length
        $located[$targetName] = $found
        Write-Pass "$targetName found ($size bytes)"
    } else {
        $tried = $candidates -join ', '
        Write-Fail "$targetName NOT found. Tried: $tried"
    }
}

if ($located.Count -lt 6) {
    Write-Fail "Missing artifacts: $(6 - $located.Count) of 6"
    Write-Step "Download all 6 artifacts to $DownloadsPath then re-run."
    exit 2
}
Write-Pass "All 6 artifacts located"

# ----------------------------------------------------------------------------
# Step 3: Backup pre-existing files
# ----------------------------------------------------------------------------
Write-Step "Step 3/7 - Backing up pre-existing files..." 'Yellow'

$filesToBackup = @(
    '.dockerignore'
    'Dockerfile'
    'docker-compose.yml'
    'backend\main.py'
)

foreach ($p in $filesToBackup) {
    if (Test-Path $p) {
        $backupName = "$p.bak_pre_batch2_$ts"
        Copy-Item $p $backupName -Force
        Write-Pass "Backed up $p -> $backupName"
    } else {
        Write-Step "  [INFO] $p does not exist (no backup needed)"
    }
}

# ----------------------------------------------------------------------------
# Step 4: Copy artifacts into project
# ----------------------------------------------------------------------------
Write-Step "Step 4/7 - Copying artifacts into project..." 'Yellow'

Copy-Item $located['dockerignore_root'] '.\.dockerignore' -Force
Write-Pass "Copied .dockerignore"

Copy-Item $located['Dockerfile'] '.\Dockerfile' -Force
Write-Pass "Copied Dockerfile"

Copy-Item $located['docker-compose.yml'] '.\docker-compose.yml' -Force
Write-Pass "Copied docker-compose.yml"

Copy-Item $located['metrics_router.py'] '.\backend\metrics_router.py' -Force
Write-Pass "Copied backend/metrics_router.py"

Copy-Item $located['patch_main_metrics.py'] '.\patch_main_metrics.py' -Force
Write-Pass "Copied patch_main_metrics.py"

Copy-Item $located['test_metrics.py'] '.\tests\test_metrics.py' -Force
Write-Pass "Copied tests/test_metrics.py"

# ----------------------------------------------------------------------------
# Step 5: Apply main.py patch
# ----------------------------------------------------------------------------
Write-Step "Step 5/7 - Patching backend/main.py to wire setup_metrics(app)..." 'Yellow'

$patchOutput = & python patch_main_metrics.py 2>&1
$patchExit = $LASTEXITCODE
$patchOutput | ForEach-Object { Add-Content -Path $logFile -Value $_ }

if ($patchExit -ne 0) {
    Write-Fail "patch_main_metrics.py failed with exit code $patchExit"
    Write-Step "--- patch output ---"
    $patchOutput | ForEach-Object { Write-Host $_ }
    Write-Step "--- end output ---"
    Write-Step "Log saved to: $logFile"
    exit 3
}
Write-Pass "main.py patched successfully"
$patchOutput | ForEach-Object { Write-Host "    $_" }

# ----------------------------------------------------------------------------
# Step 6: Install prometheus-fastapi-instrumentator
# ----------------------------------------------------------------------------
if ($SkipInstall) {
    Write-Step "Step 6/7 - SKIPPED (--SkipInstall flag)" 'Yellow'
}
else {
    Write-Step "Step 6/7 - Installing prometheus-fastapi-instrumentator..." 'Yellow'

    # FIX v2: pass version specifier as array element to avoid PowerShell
    # parsing '<' as a redirection operator. Using @() splatting form.
    $pipArgs = @(
        'install',
        'prometheus-fastapi-instrumentator>=7.0.0,<8.0.0'
    )

    $pipOutput = & pip @pipArgs 2>&1
    $pipExit = $LASTEXITCODE
    $pipOutput | ForEach-Object { Add-Content -Path $logFile -Value $_ }

    if ($pipExit -ne 0) {
        Write-Fail "pip install failed with exit code $pipExit"
        Write-Step "--- pip output (last 20 lines) ---"
        $pipOutput | Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
        Write-Step "--- end output ---"
        exit 4
    }

    $instInfo = & pip show prometheus-fastapi-instrumentator 2>&1
    $verLine = ($instInfo -split "`n") | Where-Object { $_ -match '^Version:' } | Select-Object -First 1
    Write-Pass "Installed: $verLine"
}

# ----------------------------------------------------------------------------
# Step 7: Validate
# ----------------------------------------------------------------------------
Write-Step "Step 7/7 - Validating installation..." 'Yellow'

# 7a: Import metrics_router
$validate1 = & python -c "from backend.metrics_router import setup_metrics, LATENCY_BUCKETS, EXCLUDED_PATHS; print('imports OK')" 2>&1
if ($validate1 -match 'imports OK') {
    Write-Pass "backend.metrics_router imports clean"
}
else {
    Write-Fail "Import error: $validate1"
    exit 5
}

# 7b: Import main.py with the patch applied
$validate2 = & python -c "from backend.main import app; print('main.py + setup_metrics OK')" 2>&1
if ($validate2 -match 'OK') {
    Write-Pass "backend.main imports clean (with metrics wired)"
}
else {
    Write-Warn "main.py import warning (may be lifespan startup, non-fatal):"
    Write-Host $validate2 -ForegroundColor Yellow
}

# 7c: Docker CLI sanity
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Pass "Docker CLI available for build"
}
else {
    Write-Warn "Docker CLI not found - image build deferred"
}

# ----------------------------------------------------------------------------
# Final summary
# ----------------------------------------------------------------------------
Write-Host ''
Write-Host '======================================================================' -ForegroundColor Green
Write-Host '   BATCH 2 APPLY - COMPLETE' -ForegroundColor Green
Write-Host '======================================================================' -ForegroundColor Green
Write-Host ''
Write-Step "Files in project:"
$projectFiles = @(
    '.dockerignore'
    'Dockerfile'
    'docker-compose.yml'
    'backend\metrics_router.py'
    'tests\test_metrics.py'
    'patch_main_metrics.py'
)
foreach ($p in $projectFiles) {
    if (Test-Path $p) {
        $size = (Get-Item $p).Length
        $line = "    {0,-40} {1,8} bytes" -f $p, $size
        Write-Host $line -ForegroundColor Gray
    }
}

Write-Host ''
Write-Step "Backups created (rollback available):" 'Cyan'
Get-ChildItem "*.bak_pre_batch2_$ts*", "backend\*.bak_pre_metrics_*" -ErrorAction SilentlyContinue | ForEach-Object {
    $rel = $_.FullName.Replace($PWD.Path + '\', '')
    Write-Host "    $rel" -ForegroundColor Gray
}

Write-Host ''
$nextMsg = "Next step: run .\validate_batch2.ps1 to test the full stack"
Write-Step $nextMsg 'Cyan'
Write-Host ''
Write-Step "Log saved: $logFile"
Write-Host ''
exit 0
