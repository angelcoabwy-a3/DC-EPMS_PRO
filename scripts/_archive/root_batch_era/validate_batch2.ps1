###############################################################################
# DC-EPMS PRO - validate_batch2.ps1 v2 (Batch 2 Local CI/CD Validator)
#
# v2 FIX: Removed all "--" inside string literals. PowerShell parser
# interprets "--SkipDocker" as a unary operator token even inside double
# quotes, breaking the script. v2 uses single-dash "-SkipDocker" (the
# canonical PowerShell flag form) and removes em-dashes from comments.
#
# V9 RULE 5: Pure local validation. ZERO GitHub. If anything fails,
# it produces a structured batch2_diag_<ts>.log file ready to paste into
# Claude chat for instant debug.
#
# Validates 8 layers, fail-fast with exit code = first failed layer.
#
# Usage:
#   .\validate_batch2.ps1
#   .\validate_batch2.ps1 -SkipDocker    (if Docker not running)
#   .\validate_batch2.ps1 -OnlyLayer 3   (run only layer 3)
###############################################################################

[CmdletBinding()]
param(
    [switch]$SkipDocker,
    [int]$OnlyLayer = 0
)

$ErrorActionPreference = 'Continue'
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$diagFile = ".\batch2_diag_$ts.log"

# Initialize log
@"
================================================================================
DC-EPMS PRO - Batch 2 Validation Diagnostic Log (v2)
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Hostname: $env:COMPUTERNAME
User: $env:USERNAME
Working dir: $PWD
Python venv: $env:VIRTUAL_ENV
================================================================================
"@ | Set-Content -Path $diagFile -Encoding UTF8

$layerResults = @{}

function Write-Layer {
    param([int]$N, [string]$Title)
    $banner = "`n========== Layer $N/8: $Title =========="
    Write-Host $banner -ForegroundColor Cyan
    Add-Content -Path $diagFile -Value $banner
}

function Write-Result {
    param([int]$Layer, [bool]$Passed, [string]$Message, [string]$Details = "")
    $script:layerResults[$Layer] = $Passed
    if ($Passed) {
        Write-Host "  [PASS] $Message" -ForegroundColor Green
        Add-Content -Path $diagFile -Value "[LAYER $Layer PASS] $Message"
    } else {
        Write-Host "  [FAIL] $Message" -ForegroundColor Red
        Add-Content -Path $diagFile -Value "[LAYER $Layer FAIL] $Message"
        if ($Details) {
            Add-Content -Path $diagFile -Value "    DETAILS: $Details"
            Write-Host "         $Details" -ForegroundColor Yellow
        }
    }
}

function Test-LayerActive {
    param([int]$N)
    return ($OnlyLayer -eq 0 -or $OnlyLayer -eq $N)
}

function Append-CommandOutput {
    param([string]$Command, [string]$Output, [int]$ExitCode)
    $maxLen = [Math]::Min($Output.Length, 2000)
    @"

--- COMMAND ---
$Command
--- EXIT CODE: $ExitCode ---
--- OUTPUT (truncated to 2000 chars) ---
$($Output.Substring(0, $maxLen))
--- END OUTPUT ---
"@ | Add-Content -Path $diagFile
}

# Pre-flight
if (-not $env:VIRTUAL_ENV) {
    Write-Host "[FATAL] venv not active. Run: .\.venv\Scripts\Activate.ps1" -ForegroundColor Red
    exit 100
}

Write-Host ''
Write-Host '======================================================================' -ForegroundColor Cyan
Write-Host '   DC-EPMS PRO - Batch 2 Validator (v2)' -ForegroundColor Cyan
Write-Host '   Diagnostic log: ' -NoNewline
Write-Host $diagFile -ForegroundColor Yellow
Write-Host '======================================================================' -ForegroundColor Cyan

# ----------------------------------------------------------------------------
# Layer 1: Files in place
# ----------------------------------------------------------------------------
if (Test-LayerActive 1) {
    Write-Layer 1 'Files in place'

    $required = @(
        '.dockerignore'
        'Dockerfile'
        'docker-compose.yml'
        'backend\metrics_router.py'
        'tests\test_metrics.py'
        'backend\main.py'
        'pyproject.toml'
    )

    $allPresent = $true
    foreach ($f in $required) {
        if (Test-Path $f) {
            $size = (Get-Item $f).Length
            Write-Result 1 $true "$f ($size bytes)"
        } else {
            Write-Result 1 $false "$f MISSING"
            $allPresent = $false
        }
    }

    if (-not $allPresent) {
        Write-Host ''
        Write-Host "Layer 1 failed. Run: .\apply_batch2.ps1 first" -ForegroundColor Yellow
        Write-Host "Diag log: $diagFile" -ForegroundColor Cyan
        exit 1
    }
}

# ----------------------------------------------------------------------------
# Layer 2: Python imports
# ----------------------------------------------------------------------------
if (Test-LayerActive 2) {
    Write-Layer 2 'Python imports'

    $cmd2a = 'python -c "from backend.metrics_router import setup_metrics, LATENCY_BUCKETS, EXCLUDED_PATHS; assert callable(setup_metrics); print(''OK'')"'
    $out2a = & cmd /c $cmd2a 2>&1 | Out-String
    $exit2a = $LASTEXITCODE
    if ($out2a -match 'OK') {
        Write-Result 2 $true "backend.metrics_router imports clean"
    } else {
        Write-Result 2 $false "backend.metrics_router import failed" $out2a
        Append-CommandOutput $cmd2a $out2a $exit2a
    }

    $cmd2b = 'python -c "from backend.main import app; assert app is not None; print(''OK'')"'
    $out2b = & cmd /c $cmd2b 2>&1 | Out-String
    $exit2b = $LASTEXITCODE
    if ($out2b -match 'OK') {
        Write-Result 2 $true "backend.main imports clean (metrics wired)"
    } else {
        Write-Result 2 $false "backend.main import failed" $out2b
        Append-CommandOutput $cmd2b $out2b $exit2b
    }

    $cmd2c = "pip show prometheus-fastapi-instrumentator"
    $out2c = & cmd /c $cmd2c 2>&1 | Out-String
    $exit2c = $LASTEXITCODE
    if ($exit2c -eq 0) {
        $verLine = ($out2c -split "`n") | Where-Object { $_ -match '^Version:' } | Select-Object -First 1
        Write-Result 2 $true "prometheus-fastapi-instrumentator: $verLine"
    } else {
        Write-Result 2 $false "prometheus-fastapi-instrumentator NOT installed"
        Append-CommandOutput $cmd2c $out2c $exit2c
    }
}

# ----------------------------------------------------------------------------
# Layer 3: Pytest test_metrics.py
# ----------------------------------------------------------------------------
if (Test-LayerActive 3) {
    Write-Layer 3 'Pytest test_metrics.py'

    $cmd3 = "pytest tests/test_metrics.py --timeout=30 -v"
    $out3 = & cmd /c "$cmd3 2>&1" | Out-String
    $exit3 = $LASTEXITCODE

    if ($exit3 -eq 0) {
        $summary = ($out3 -split "`n") | Where-Object { $_ -match '\d+\s+passed' } | Select-Object -Last 1
        Write-Result 3 $true "test_metrics.py: $summary"
    } else {
        Write-Result 3 $false "test_metrics.py failed (exit $exit3)" "Last 30 lines saved to log"
        $tail30 = ($out3 -split "`n") | Select-Object -Last 30 | Out-String
        Append-CommandOutput $cmd3 $tail30 $exit3
    }
}

# ----------------------------------------------------------------------------
# Layer 4: Pytest aggregate
# ----------------------------------------------------------------------------
if (Test-LayerActive 4) {
    Write-Layer 4 'Pytest aggregate (no Batch 1 regression)'

    $cmd4 = "pytest tests/test_procedure_engine.py tests/test_site_model.py tests/test_graphrag.py tests/test_metrics.py --timeout=30 -q"
    $out4 = & cmd /c "$cmd4 2>&1" | Out-String
    $exit4 = $LASTEXITCODE

    if ($exit4 -eq 0) {
        $summary = ($out4 -split "`n") | Where-Object { $_ -match '\d+\s+passed' } | Select-Object -Last 1
        Write-Result 4 $true "Aggregate green: $summary"
    } else {
        Write-Result 4 $false "Aggregate failed (exit $exit4) - POSSIBLE REGRESSION"
        $tail30 = ($out4 -split "`n") | Select-Object -Last 30 | Out-String
        Append-CommandOutput $cmd4 $tail30 $exit4
    }
}

# ----------------------------------------------------------------------------
# Layer 5: Docker image build
# ----------------------------------------------------------------------------
if (Test-LayerActive 5) {
    Write-Layer 5 'Docker image build'

    if ($SkipDocker) {
        Write-Result 5 $true "SKIPPED (SkipDocker flag set)"
    } elseif (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Result 5 $false "docker CLI not found in PATH"
    } else {
        $dockerInfo = & docker info 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) {
            Write-Result 5 $false "Docker daemon not running" $dockerInfo
        } else {
            Write-Host "  [INFO] Building image (may take 2-5 min on first build)..." -ForegroundColor Yellow
            $cmd5 = "docker build --target runtime -t dc-epms-pro:batch2-validate ."
            $out5 = & cmd /c "$cmd5 2>&1" | Out-String
            $exit5 = $LASTEXITCODE

            if ($exit5 -eq 0) {
                $sizeRaw = & docker images dc-epms-pro:batch2-validate --format "{{.Size}}" 2>&1
                Write-Result 5 $true "Image built. Size: $sizeRaw"
            } else {
                Write-Result 5 $false "Image build failed (exit $exit5)"
                $tail50 = ($out5 -split "`n") | Select-Object -Last 50 | Out-String
                Append-CommandOutput $cmd5 $tail50 $exit5
            }
        }
    }
}

# ----------------------------------------------------------------------------
# Layer 6: docker-compose config valid
# ----------------------------------------------------------------------------
if (Test-LayerActive 6) {
    Write-Layer 6 'docker-compose config valid'

    if ($SkipDocker) {
        Write-Result 6 $true "SKIPPED (SkipDocker flag set)"
    } else {
        $cmd6 = "docker compose config --quiet"
        $out6 = & cmd /c "$cmd6 2>&1" | Out-String
        $exit6 = $LASTEXITCODE

        if ($exit6 -eq 0) {
            Write-Result 6 $true "docker-compose.yml syntactically valid"
        } else {
            Write-Result 6 $false "docker-compose config failed (exit $exit6)" $out6
            Append-CommandOutput $cmd6 $out6 $exit6
        }
    }
}

# ----------------------------------------------------------------------------
# Layer 7: Container starts and healthcheck
# ----------------------------------------------------------------------------
if (Test-LayerActive 7) {
    Write-Layer 7 'Container starts + healthcheck'

    if ($SkipDocker) {
        Write-Result 7 $true "SKIPPED (SkipDocker flag set)"
    } else {
        Write-Host "  [INFO] Starting epms-backend (max 90s for health pass)..." -ForegroundColor Yellow

        & docker compose down --timeout 5 2>&1 | Out-Null

        $cmd7a = "docker compose up -d --no-build epms-backend"
        $out7a = & cmd /c "$cmd7a 2>&1" | Out-String

        if ($LASTEXITCODE -ne 0) {
            Write-Result 7 $false "compose up failed" $out7a
            Append-CommandOutput $cmd7a $out7a $LASTEXITCODE
        } else {
            $maxWait = 90
            $waited = 0
            $healthy = $false
            $finalHealth = "unknown"
            while ($waited -lt $maxWait) {
                Start-Sleep -Seconds 5
                $waited += 5

                $health = & docker inspect --format='{{.State.Health.Status}}' epms-backend 2>&1
                $finalHealth = $health
                Write-Host "    [t+${waited}s] container health: $health" -ForegroundColor Gray

                if ($health -eq 'healthy') {
                    $healthy = $true
                    break
                }
                if ($health -eq 'unhealthy') {
                    Write-Host "    [t+${waited}s] container reported unhealthy" -ForegroundColor Red
                    break
                }
            }

            if ($healthy) {
                Write-Result 7 $true "Container healthy in ${waited}s"
            } else {
                $logs = & docker logs --tail 50 epms-backend 2>&1 | Out-String
                Write-Result 7 $false "Container not healthy in ${maxWait}s (status: $finalHealth)"
                Append-CommandOutput "docker logs --tail 50 epms-backend" $logs 0
            }
        }
    }
}

# ----------------------------------------------------------------------------
# Layer 8: /metrics endpoint live
# ----------------------------------------------------------------------------
if (Test-LayerActive 8) {
    Write-Layer 8 '/metrics endpoint live'

    if ($SkipDocker) {
        Write-Result 8 $true "SKIPPED (SkipDocker flag set)"
    } else {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:8080/metrics" -TimeoutSec 10 -ErrorAction Stop
            $body = $resp.Content

            $checks = @{
                'HTTP 200'              = ($resp.StatusCode -eq 200)
                'Has HELP comments'     = ($body -match '# HELP')
                'Has TYPE comments'     = ($body -match '# TYPE')
                'Has dc_epms_ namespace' = ($body -match 'dc_epms_')
            }

            $allPassed = $true
            foreach ($check in $checks.Keys) {
                if ($checks[$check]) {
                    Write-Host "    [OK] $check" -ForegroundColor Green
                } else {
                    Write-Host "    [FAIL] $check" -ForegroundColor Red
                    $allPassed = $false
                }
            }

            if ($allPassed) {
                Write-Result 8 $true "/metrics endpoint returns valid Prometheus exposition"
            } else {
                Write-Result 8 $false "/metrics endpoint failed validation"
                $maxBodyLen = [Math]::Min($body.Length, 2000)
                Append-CommandOutput "GET /metrics" ($body.Substring(0, $maxBodyLen)) $resp.StatusCode
            }
        } catch {
            Write-Result 8 $false "Cannot reach /metrics endpoint" $_.Exception.Message
            Append-CommandOutput "GET /metrics" $_.Exception.Message 0
        }
    }
}

# ----------------------------------------------------------------------------
# Final summary
# ----------------------------------------------------------------------------
Write-Host ''
Write-Host '======================================================================' -ForegroundColor Cyan
Write-Host '   VALIDATION SUMMARY' -ForegroundColor Cyan
Write-Host '======================================================================' -ForegroundColor Cyan

$passedCount = ($layerResults.Values | Where-Object { $_ }).Count
$totalCount = $layerResults.Count
$failedLayers = @($layerResults.Keys | Where-Object { -not $layerResults[$_] } | Sort-Object)

foreach ($n in 1..8) {
    if ($layerResults.ContainsKey($n)) {
        if ($layerResults[$n]) {
            Write-Host "  Layer $n`: [PASS]" -ForegroundColor Green
        } else {
            Write-Host "  Layer $n`: [FAIL]" -ForegroundColor Red
        }
    } else {
        Write-Host "  Layer $n`: [SKIP]" -ForegroundColor Gray
    }
}

Write-Host ''
if ($failedLayers.Count -eq 0) {
    Write-Host "  $passedCount of $totalCount layers passed" -ForegroundColor Green
} else {
    Write-Host "  $passedCount of $totalCount layers passed" -ForegroundColor Yellow
}
Write-Host ''
Write-Host "  Diagnostic log: $diagFile" -ForegroundColor Cyan

if ($failedLayers.Count -gt 0) {
    Write-Host ''
    Write-Host '======================================================================' -ForegroundColor Yellow
    Write-Host '   PASTE-TO-CLAUDE: send diagnostic log content for instant debug' -ForegroundColor Yellow
    Write-Host '======================================================================' -ForegroundColor Yellow
    Write-Host "   Get-Content $diagFile" -ForegroundColor White
    Write-Host ''
    exit ($failedLayers | Select-Object -First 1)
} else {
    Write-Host ''
    Write-Host '   BATCH 2 VALIDATED - All systems green.' -ForegroundColor Green
    Write-Host ''
    exit 0
}
