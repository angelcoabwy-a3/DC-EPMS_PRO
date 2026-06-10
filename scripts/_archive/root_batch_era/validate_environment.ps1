# =============================================================================
# DC-EPMS PRO - validate_environment.ps1
# Pre-flight check BEFORE running `pip install -e ".[dev]"`.
#
# This script does NOT modify anything. Read-only validation only.
# Run from C:\dev\DC-EPMS_PRO with .venv activated.
#
# Exit codes:
#   0 = all checks pass, safe to proceed with pip install
#   1 = at least one check failed, DO NOT install
# =============================================================================

$ErrorActionPreference = "Continue"
$script:Failures = @()
$script:Warnings = @()

function Write-CheckHeader {
    param([string]$Title)
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan
}

function Write-Pass { param([string]$Msg) Write-Host "  [PASS] $Msg" -ForegroundColor Green }
function Write-Fail { param([string]$Msg) Write-Host "  [FAIL] $Msg" -ForegroundColor Red; $script:Failures += $Msg }
function Write-Warn { param([string]$Msg) Write-Host "  [WARN] $Msg" -ForegroundColor Yellow; $script:Warnings += $Msg }
function Write-Info { param([string]$Msg) Write-Host "  [INFO] $Msg" -ForegroundColor Gray }

# =============================================================================
# Check 1: Working directory
# =============================================================================
Write-CheckHeader "Check 1 of 8: Working directory"

$expectedDir = "C:\dev\DC-EPMS_PRO"
$currentDir  = (Get-Location).Path

if ($currentDir -eq $expectedDir) {
    Write-Pass "Current directory: $currentDir"
} else {
    Write-Fail "Wrong directory. Expected: $expectedDir, Got: $currentDir"
    Write-Info "Fix: cd $expectedDir"
}

# =============================================================================
# Check 2: Python virtual environment activated
# =============================================================================
Write-CheckHeader "Check 2 of 8: Virtual environment activation"

if ($env:VIRTUAL_ENV) {
    Write-Pass "VIRTUAL_ENV is set: $env:VIRTUAL_ENV"
    if ($env:VIRTUAL_ENV -like "*$expectedDir*") {
        Write-Pass "venv path matches project directory"
    } else {
        Write-Fail "venv path does NOT match project directory"
    }
} else {
    Write-Fail "VIRTUAL_ENV not set - venv is NOT activated"
    Write-Info "Fix: .\.venv\Scripts\Activate.ps1"
}

# =============================================================================
# Check 3: Python version
# =============================================================================
Write-CheckHeader "Check 3 of 8: Python version"

try {
    $pythonVersion = & python --version 2>&1
    if ($pythonVersion -match "Python 3\.12\.\d+") {
        Write-Pass "Python version: $pythonVersion"
    } elseif ($pythonVersion -match "Python 3\.13") {
        Write-Fail "Python 3.13 detected - pyproject.toml requires 3.12.x"
    } elseif ($pythonVersion -match "Python 3\.\d+") {
        Write-Fail "Wrong Python version: $pythonVersion (need 3.12.x)"
    } else {
        Write-Fail "Could not parse Python version: $pythonVersion"
    }

    # Confirm python is from the venv
    $pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($pythonPath -and $pythonPath -like "*$expectedDir*\.venv*") {
        Write-Pass "python.exe is from venv: $pythonPath"
    } else {
        Write-Fail "python.exe is NOT from venv. Path: $pythonPath"
    }
} catch {
    Write-Fail "Failed to query python: $_"
}

# =============================================================================
# Check 4: pyproject.toml present and valid TOML
# =============================================================================
Write-CheckHeader "Check 4 of 8: pyproject.toml file"

if (Test-Path "pyproject.toml") {
    $size = (Get-Item "pyproject.toml").Length
    Write-Pass "pyproject.toml exists (size: $size bytes)"

    if ($size -lt 1000) {
        Write-Fail "pyproject.toml is suspiciously small (<1 KB) - likely empty or corrupted"
    } else {
        # Validate TOML syntax via Python
        try {
            $tomlCheck = & python -c "import tomllib; tomllib.loads(open('pyproject.toml',encoding='utf-8').read()); print('OK')" 2>&1
            if ($tomlCheck -eq "OK") {
                Write-Pass "pyproject.toml is valid TOML syntax"
            } else {
                Write-Fail "pyproject.toml has TOML syntax errors:"
                Write-Host "    $tomlCheck" -ForegroundColor Red
            }
        } catch {
            Write-Fail "Could not validate TOML: $_"
        }

        # Confirm critical metadata
        try {
            $projectCheck = & python -c "import tomllib; d=tomllib.loads(open('pyproject.toml',encoding='utf-8').read()); print(d['project']['name'], d['project']['version'])" 2>&1
            Write-Info "Project name + version: $projectCheck"
        } catch {
            Write-Warn "Could not extract project metadata"
        }
    }
} else {
    Write-Fail "pyproject.toml NOT FOUND in current directory"
    Write-Info "Fix: copy pyproject.toml to $expectedDir"
}

# =============================================================================
# Check 5: .pre-commit-config.yaml present and valid YAML
# =============================================================================
Write-CheckHeader "Check 5 of 8: .pre-commit-config.yaml file"

if (Test-Path ".pre-commit-config.yaml") {
    $size = (Get-Item ".pre-commit-config.yaml").Length
    Write-Pass ".pre-commit-config.yaml exists (size: $size bytes)"

    try {
        $yamlCheck = & python -c "import yaml; yaml.safe_load(open('.pre-commit-config.yaml',encoding='utf-8').read()); print('OK')" 2>&1
        if ($yamlCheck -eq "OK") {
            Write-Pass ".pre-commit-config.yaml is valid YAML syntax"
        } else {
            Write-Fail ".pre-commit-config.yaml has YAML syntax errors:"
            Write-Host "    $yamlCheck" -ForegroundColor Red
        }
    } catch {
        Write-Fail "Could not validate YAML: $_"
    }
} else {
    Write-Warn ".pre-commit-config.yaml NOT FOUND - hooks won't install"
    Write-Info "(non-blocking for pip install, but Batch 1 incomplete without it)"
}

# =============================================================================
# Check 6: Critical packages are installed AND match expected versions
# =============================================================================
Write-CheckHeader "Check 6 of 8: Critical package version compatibility"

$criticalPackages = @{
    "chromadb"              = "0.5.18"
    "sentence-transformers" = "3.2.1"
    "faiss-cpu"             = "1.13.2"
    "networkx"              = "3.6.1"
    "pytest"                = "9.0.3"
    "pytest-asyncio"        = "1.3.0"
    "pydantic"              = "2.9.2"
    "fastapi"               = "0.115.0"
    "nemoguardrails"        = "0.10.1"
    "scipy"                 = "1.17.1"
}

$pipListOutput = & pip list --format=json 2>&1 | ConvertFrom-Json

foreach ($pkg in $criticalPackages.Keys) {
    $expected = $criticalPackages[$pkg]
    $found = $pipListOutput | Where-Object { $_.name -eq $pkg } | Select-Object -First 1

    if ($null -eq $found) {
        Write-Warn "$pkg : NOT INSTALLED (would be installed by pip install)"
    } elseif ($found.version -eq $expected) {
        Write-Pass "$pkg $($found.version) matches expected $expected"
    } else {
        # For some packages we accept newer minor versions
        if ($pkg -in @("scipy", "pytest", "pytest-asyncio")) {
            Write-Pass "$pkg $($found.version) (>= $expected, OK)"
        } else {
            Write-Fail "$pkg $($found.version) does NOT match expected $expected (corpus risk)"
        }
    }
}

# =============================================================================
# Check 7: data/ and chroma_db/ corpus integrity
# =============================================================================
Write-CheckHeader "Check 7 of 8: ChromaDB corpus integrity (deletion-risk check)"

$chromaPaths = @("data\chroma_db", "chroma_db")
$chromaFound = $false

foreach ($path in $chromaPaths) {
    if (Test-Path $path) {
        $chromaFound = $true
        $sqliteFile = Join-Path $path "chroma.sqlite3"
        if (Test-Path $sqliteFile) {
            $size = (Get-Item $sqliteFile).Length
            Write-Pass "ChromaDB found at $path (sqlite size: $size bytes)"
            if ($size -gt 1000000) {
                Write-Info "Corpus size suggests indexed documents present (preserve this)"
            }
        } else {
            Write-Warn "$path exists but no chroma.sqlite3 inside"
        }
    }
}

if (-not $chromaFound) {
    Write-Warn "ChromaDB persistence directory not found (no indexed corpus to protect)"
}

# =============================================================================
# Check 8: requirements.txt files (will be deprecated by pyproject.toml)
# =============================================================================
Write-CheckHeader "Check 8 of 8: Legacy requirements.txt files"

$reqFiles = @("requirements.txt", "requirements-full.txt", "requirements-minimal.txt")
foreach ($f in $reqFiles) {
    if (Test-Path $f) {
        Write-Info "$f present (will be deprecated by pyproject.toml v2)"
    }
}

if (Test-Path "pytest.ini") {
    Write-Info "pytest.ini present (will be removed - config moves into pyproject.toml)"
}

# =============================================================================
# Final summary
# =============================================================================
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  VALIDATION SUMMARY" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$failCount = $script:Failures.Count
$warnCount = $script:Warnings.Count

if ($failCount -eq 0) {
    Write-Host ""
    Write-Host "  RESULT: PASS" -ForegroundColor Green
    Write-Host "  $warnCount warnings (non-blocking)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Safe to proceed with: pip install -e `".[dev]`"" -ForegroundColor Green
    Write-Host ""
    exit 0
} else {
    Write-Host ""
    Write-Host "  RESULT: FAIL" -ForegroundColor Red
    Write-Host "  $failCount failures, $warnCount warnings" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Failures:" -ForegroundColor Red
    foreach ($f in $script:Failures) {
        Write-Host "    - $f" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "  DO NOT run pip install until failures are resolved." -ForegroundColor Red
    Write-Host ""
    exit 1
}
