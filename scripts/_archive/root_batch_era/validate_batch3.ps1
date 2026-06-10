# DC-EPMS PRO - validate_batch3.ps1 (v2 - cosmetic fix)
# Batch 3 Validator: 8-layer paste-to-Claude diagnostic script
# v2 fix: Layer 2 ReadAllText now guarded by Test-Path explicit check

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = ".\batch3_diag_$timestamp.log"

$summary = @{}

function Write-Layer {
    param([int]$Num, [string]$Name)
    $line = "=" * 60
    Write-Host ""
    Write-Host $line
    Write-Host "Layer $Num of 8: $Name"
    Write-Host $line
    Add-Content -Path $logFile -Value ""
    Add-Content -Path $logFile -Value $line
    Add-Content -Path $logFile -Value "Layer $Num of 8: $Name"
    Add-Content -Path $logFile -Value $line
}

function Layer-Pass {
    param([int]$Num, [string]$Detail)
    Write-Host "  [PASS] $Detail" -ForegroundColor Green
    Add-Content -Path $logFile -Value "  [PASS] $Detail"
    $summary[$Num] = "PASS"
}

function Layer-Fail {
    param([int]$Num, [string]$Detail)
    Write-Host "  [FAIL] $Detail" -ForegroundColor Red
    Add-Content -Path $logFile -Value "  [FAIL] $Detail"
    $summary[$Num] = "FAIL"
}

function Layer-Info {
    param([string]$Detail)
    Write-Host "  [INFO] $Detail" -ForegroundColor Cyan
    Add-Content -Path $logFile -Value "  [INFO] $Detail"
}

# ============================================================
# Header
# ============================================================

$header = "=" * 70
Write-Host $header -ForegroundColor Cyan
Write-Host "  DC-EPMS PRO - Batch 3 Validator v2 (8 layers)"
Write-Host "  Diagnostic log: $logFile"
Write-Host $header -ForegroundColor Cyan
Add-Content -Path $logFile -Value $header
Add-Content -Path $logFile -Value "  DC-EPMS PRO - Batch 3 Validator v2 (8 layers)"
Add-Content -Path $logFile -Value "  Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

# ============================================================
# Layer 1: Files in place
# ============================================================

Write-Layer 1 "Required files in place"

$requiredFiles = @(
    ".gitignore",
    "pyproject.toml",
    ".pre-commit-config.yaml",
    "Dockerfile",
    "docker-compose.yml",
    "CHANGELOG.md",
    "01_INSTRUCTIONS.md",
    "backend\main.py",
    "backend\metrics_router.py",
    "backend\graphrag_service.py",
    "tests\test_metrics.py",
    "docs\adr\ADR-001-dual-rag-architecture.md",
    "docs\adr\ADR-002-networkx-in-memory.md",
    "docs\adr\ADR-003-faiss-flatip.md",
    "docs\adr\ADR-006-deterministic-sandbox.md",
    "docs\adr\ADR-007-sprint6-simulator-killed.md",
    "docs\adr\ADR-008-image-size-go-option-c.md",
    "docs\architecture\sre_layers.md"
)

$allPresent = $true
foreach ($f in $requiredFiles) {
    if (Test-Path $f) {
        $size = (Get-Item $f).Length
        Layer-Info "$f ($size bytes)"
    } else {
        Layer-Fail 1 "$f MISSING"
        $allPresent = $false
    }
}

if ($allPresent) {
    Layer-Pass 1 "All $($requiredFiles.Count) required files in place"
}

# ============================================================
# Layer 2: Cleanup verified
# ============================================================

Write-Layer 2 "Cleanup verified (DC-EPMS-002, 004, 005, 006)"

$dc002 = $false
if (Test-Path "backend\graphrag_service.py") {
    try {
        $content = Get-Content "backend\graphrag_service.py" -Raw -ErrorAction Stop
        if ($content -match "from backend\.knowledge_graph") {
            Layer-Info "DC-EPMS-002 fixed: import uses backend.knowledge_graph"
            $dc002 = $true
        } else {
            Layer-Info "DC-EPMS-002 NOT fixed: import path still uses old form"
        }
    } catch {
        Layer-Info "DC-EPMS-002 cannot read graphrag_service.py: $_"
    }
} else {
    Layer-Info "DC-EPMS-002 file backend/graphrag_service.py not found at this location"
}

$duplicates = @(
    "backend\physics\physics_it_thermal.py",
    "backend\physics\physics_heat_rejection.py",
    "backend\physics\physics_electrical.py",
    "backend\physics\physics__init__.py",
    "backend\physics__init__.py"
)
$dc004 = $true
foreach ($d in $duplicates) {
    if (Test-Path $d) {
        Layer-Info "DC-EPMS-004 still present: $d"
        $dc004 = $false
    }
}
if ($dc004) { Layer-Info "DC-EPMS-004 fixed: 5 duplicates absent from backend/physics/" }

$rootScripts = @(Get-ChildItem -Path "." -Filter "*.py" | Where-Object {
    $_.Name -notin @(
        "patch_pyproject_obs.py", "patch_pyproject_torch_cpu.py", "patch_main_metrics_v3.py",
        "prepare_repo_structure.py", "create_gitignore.py", "conftest.py"
    )
})
$dc005 = $true
if ($rootScripts.Count -gt 0) {
    Layer-Info "DC-EPMS-005 still has $($rootScripts.Count) iteration scripts at root"
    foreach ($s in $rootScripts | Select-Object -First 5) {
        Layer-Info "  $($s.Name)"
    }
    if ($rootScripts.Count -gt 5) {
        Layer-Info "  ...and $($rootScripts.Count - 5) more"
    }
    $dc005 = $false
}
if (Test-Path "scripts\_archive\pre_batch3") {
    $archived = (Get-ChildItem "scripts\_archive\pre_batch3" -File -ErrorAction SilentlyContinue).Count
    Layer-Info "DC-EPMS-005 archive: scripts/_archive/pre_batch3/ contains $archived files"
} else {
    Layer-Info "DC-EPMS-005 archive directory not yet created"
}

$dc006 = -not (Test-Path "chroma_db")
if (Test-Path "chroma_db") {
    Layer-Info "DC-EPMS-006 NOT fixed: chroma_db/ at root still present"
} else {
    Layer-Info "DC-EPMS-006 fixed: stray chroma_db/ at root absent"
}
if (Test-Path "data\chroma_db") {
    $opSize = ((Get-ChildItem -Path "data\chroma_db" -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1024)
    Layer-Info "DC-EPMS-006: operational data/chroma_db preserved ($([math]::Round($opSize, 1)) KB)"
}

if ($dc002 -and $dc004 -and $dc005 -and $dc006) {
    Layer-Pass 2 "All cleanup operations verified"
} else {
    Layer-Fail 2 "Cleanup incomplete (002=$dc002 004=$dc004 005=$dc005 006=$dc006)"
}

# ============================================================
# Layer 3: Git repo healthy
# ============================================================

Write-Layer 3 "Git repository healthy"

if (Test-Path ".\.git") {
    Layer-Info "Git repo initialized at .git/"
    $branchOutput = & git rev-parse --abbrev-ref HEAD 2>&1
    if ($LASTEXITCODE -eq 0) {
        Layer-Info "Branch: $branchOutput"
    }

    $logOutput = & git log --oneline -n 5 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0 -and $logOutput.Length -gt 0) {
        Layer-Info "Recent commits:"
        $logOutput.Trim().Split("`n") | ForEach-Object { Layer-Info "  $_" }

        $tags = & git tag -l 2>&1 | Out-String
        if ($tags.Trim().Length -gt 0) {
            Layer-Info "Tags: $($tags.Trim() -replace "`n", ', ')"
        } else {
            Layer-Info "No tags yet"
        }

        Layer-Pass 3 "Git repo healthy with commits"
    } else {
        Layer-Fail 3 "No commits in repo"
    }
} else {
    Layer-Fail 3 "Git repo not initialized"
}

# ============================================================
# Layer 4: Pytest aggregate green (no regression)
# ============================================================

Write-Layer 4 "Pytest aggregate (no regression Batch 1+2)"

$pytestOutput = & pytest --tb=no -q 2>&1 | Out-String
$lastLines = ($pytestOutput.Trim() -split "`n" | Select-Object -Last 5) -join " | "
Layer-Info "pytest summary: $lastLines"

if ($pytestOutput -match "(\d+) passed") {
    $passed = [int]$Matches[1]
    if ($passed -ge 100) {
        Layer-Pass 4 "Aggregate green: $passed tests passed"
    } else {
        Layer-Fail 4 "Only $passed passed (expected at least 100)"
    }
} else {
    Layer-Fail 4 "Could not parse pytest summary"
}

# ============================================================
# Layer 5: pyproject.toml still valid TOML + obs has instrumentator
# ============================================================

Write-Layer 5 "pyproject.toml integrity"

$tomlValidator = @"
import tomllib, sys
try:
    with open('pyproject.toml', 'rb') as f:
        data = tomllib.loads(f.read().decode('utf-8-sig'))
    obs = data['project']['optional-dependencies'].get('obs', [])
    has_instrumentator = any('prometheus-fastapi-instrumentator' in x for x in obs)
    if has_instrumentator:
        print('OBS_OK')
    else:
        print('OBS_MISSING')
except Exception as e:
    print('TOML_INVALID:', e)
"@

$tomlPath = ".\_validate_toml_$timestamp.py"
Set-Content -Path $tomlPath -Value $tomlValidator -Encoding UTF8

$tomlResult = & python $tomlPath 2>&1 | Out-String
Remove-Item $tomlPath -Force -ErrorAction SilentlyContinue

if ($tomlResult -match "OBS_OK") {
    Layer-Pass 5 "pyproject.toml valid + [obs] has prometheus-fastapi-instrumentator"
} elseif ($tomlResult -match "OBS_MISSING") {
    Layer-Fail 5 "[obs] extra missing prometheus-fastapi-instrumentator"
} else {
    Layer-Fail 5 "TOML invalid: $($tomlResult.Trim())"
}

# ============================================================
# Layer 6: ADRs syntactically valid markdown with required sections
# ============================================================

Write-Layer 6 "ADR markdown structural validity"

if (-not (Test-Path "docs\adr")) {
    Layer-Fail 6 "docs/adr/ directory does not exist"
} else {
    $adrFiles = Get-ChildItem -Path "docs\adr" -Filter "ADR-*.md" -ErrorAction SilentlyContinue
    if ($adrFiles.Count -eq 0) {
        Layer-Fail 6 "No ADR files found in docs/adr/"
    } else {
        $allValid = $true
        foreach ($adr in $adrFiles) {
            $content = Get-Content $adr.FullName -Raw -ErrorAction SilentlyContinue
            if (-not $content) {
                Layer-Fail 6 "$($adr.Name) cannot be read"
                $allValid = $false
                continue
            }
            $hasContext = $content -match "## Context"
            $hasDecision = $content -match "## Decision"
            $hasConsequences = $content -match "## Consequences"
            if ($hasContext -and $hasDecision -and $hasConsequences) {
                Layer-Info "$($adr.Name) ($($content.Length) bytes) sections OK"
            } else {
                Layer-Fail 6 "$($adr.Name) missing required sections"
                $allValid = $false
            }
        }
        if ($allValid) {
            Layer-Pass 6 "$($adrFiles.Count) ADRs structurally valid"
        }
    }
}

# ============================================================
# Layer 7: 01_INSTRUCTIONS.md has required markers
# ============================================================

Write-Layer 7 "01_INSTRUCTIONS.md content markers"

if (Test-Path ".\01_INSTRUCTIONS.md") {
    $instContent = Get-Content ".\01_INSTRUCTIONS.md" -Raw -ErrorAction SilentlyContinue

    if ($instContent) {
        $markers = @{
            "67 MW" = $instContent -match "67\s*MW"
            "Path C2" = $instContent -match "Path\s*C2"
            "118 GB200" = $instContent -match "118.{0,30}GB200"
            "250 GB300" = $instContent -match "250.{0,30}GB300"
            "Batch 1 CLOSED" = $instContent -match "Batch\s*1.*CLOSED"
            "Batch 2 CLOSED" = $instContent -match "Batch\s*2.*CLOSED"
            "Hyperscale Override" = $instContent -match "Hyperscale\s*(Development\s*)?Override"
            "DC-EPMS-NNN" = $instContent -match "DC-EPMS-0\d\d"
            "LOTO Auditor" = $instContent -match "LOTO\s*Auditor"
            "Deterministic Sandbox" = $instContent -match "Deterministic\s*Sandbox"
        }

        $foundCount = 0
        foreach ($key in $markers.Keys) {
            if ($markers[$key]) {
                Layer-Info "Found marker: $key"
                $foundCount++
            } else {
                Layer-Info "Missing marker: $key"
            }
        }

        if ($foundCount -ge 8) {
            Layer-Pass 7 "01_INSTRUCTIONS.md has $foundCount of $($markers.Count) expected markers"
        } else {
            Layer-Fail 7 "Only $foundCount of $($markers.Count) markers found (expected at least 8)"
        }
    } else {
        Layer-Fail 7 "01_INSTRUCTIONS.md exists but cannot be read"
    }
} else {
    Layer-Fail 7 "01_INSTRUCTIONS.md missing"
}

# ============================================================
# Layer 8: pre-commit hook installed
# ============================================================

Write-Layer 8 "pre-commit hook installed"

if (Test-Path ".\.git\hooks\pre-commit") {
    $hookContent = Get-Content ".\.git\hooks\pre-commit" -Raw -ErrorAction SilentlyContinue
    if ($hookContent -and $hookContent -match "pre-commit") {
        Layer-Pass 8 "pre-commit hook active in .git/hooks/pre-commit"
    } else {
        Layer-Fail 8 "Hook file exists but does not invoke pre-commit"
    }
} else {
    Layer-Info "pre-commit hook not installed yet (run: pre-commit install)"
    Layer-Fail 8 "pre-commit hook not active"
}

# ============================================================
# Summary
# ============================================================

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host "  VALIDATION SUMMARY"
Write-Host ("=" * 70) -ForegroundColor Cyan

$passes = 0
foreach ($i in 1..8) {
    $status = $summary[$i]
    if (-not $status) { $status = "UNKNOWN" }
    $color = switch ($status) {
        "PASS" { "Green" }
        "FAIL" { "Red" }
        default { "Yellow" }
    }
    Write-Host "  Layer $i`: [$status]" -ForegroundColor $color
    if ($status -eq "PASS") { $passes++ }
}

Write-Host ""
Write-Host "  $passes of 8 layers passed" -ForegroundColor $(if ($passes -eq 8) { "Green" } else { "Yellow" })
Write-Host "  Diagnostic log: $logFile"

if ($passes -eq 8) {
    Write-Host ""
    Write-Host "   BATCH 3 VALIDATED - All systems green." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "   BATCH 3 INCOMPLETE - $($summary.Count - $passes) layer(s) need attention." -ForegroundColor Yellow
    Write-Host "   Paste log $logFile to Claude for diagnosis." -ForegroundColor Yellow
}
