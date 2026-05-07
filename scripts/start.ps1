# =============================================================
#  DC-EPMS PRO - One-click startup for Windows
#  Bootstraps: venv, dependencies, DB, seed, simulator, backend
#
#  First run:     .\scripts\start.ps1 -Install
#  Normal run:    .\scripts\start.ps1
#  Stop all:      .\scripts\start.ps1 -Stop
#  Simulator:     .\scripts\start.ps1 -Simulator
# =============================================================

[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Stop,
    [switch]$Simulator,
    [switch]$Minimal,
    [string]$Scenario = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Write-Step { param($msg) Write-Host ""; Write-Host ">> $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Err  { param($msg) Write-Host "  [ERROR] $msg" -ForegroundColor Red }

# ------------------------------------------------------------
#  Stop all
# ------------------------------------------------------------
if ($Stop) {
    Write-Step "Stopping DC-EPMS services"
    Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "backend\\main.py|simulator.py"
    } | Stop-Process -Force -ErrorAction SilentlyContinue

    docker stop epms-db 2>&1 | Out-Null
    Write-Ok "Services stopped"
    exit 0
}

# ------------------------------------------------------------
#  Install: first-time setup
# ------------------------------------------------------------
if ($Install) {
    Write-Step "First-time setup: Python + venv"
    python --version
    if (-not (Test-Path ".venv")) {
        python -m venv .venv
        Write-Ok "Created .venv"
    }
    & .\.venv\Scripts\Activate.ps1

    Write-Step "Installing dependencies"
    $reqFile = if ($Minimal) { "requirements-minimal.txt" } else { "requirements.txt" }
    python -m pip install --upgrade pip --quiet
    pip install -r $reqFile
    Write-Ok "Installed $reqFile"

    Write-Step "Setting up config"
    if (-not (Test-Path "config\.env")) {
        Copy-Item "config\.env.example" "config\.env"
        Write-Warn "Created config\.env - edit with your API keys"
    } else {
        Write-Ok "config\.env already exists"
    }

    if (-not $Minimal) {
        Write-Step "Starting PostgreSQL/TimescaleDB via Docker"
        docker ps 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Docker not running. Start Docker Desktop first."
            exit 1
        }

        $dbRunning = docker ps --filter "name=epms-db" --format "{{.Names}}" 2>&1
        $dbExists  = docker ps -a --filter "name=epms-db" --format "{{.Names}}" 2>&1

        if ($dbRunning -eq "epms-db") {
            Write-Ok "epms-db already running"
        } elseif ($dbExists -eq "epms-db") {
            docker start epms-db | Out-Null
            Write-Ok "Started existing epms-db container"
            Start-Sleep -Seconds 5
        } else {
            docker run -d --name epms-db --restart=always `
                -e POSTGRES_PASSWORD=epms2026 -e POSTGRES_DB=epms `
                -p 5432:5432 timescale/timescaledb:latest-pg16 | Out-Null
            Write-Ok "Docker container epms-db created"
            Start-Sleep -Seconds 8
        }

        Write-Step "Seeding RAG knowledge base"
        python scripts\seed_rag_v2.py
    }

    Write-Ok "Setup complete"
    Write-Host ""
    Write-Host "Next: .\scripts\start.ps1" -ForegroundColor Cyan
    exit 0
}

# ------------------------------------------------------------
#  Normal start: launch backend
# ------------------------------------------------------------
Write-Step "DC-EPMS PRO starting"

if (-not (Test-Path ".venv")) {
    Write-Err "Virtual environment missing. Run: .\scripts\start.ps1 -Install"
    exit 1
}

& .\.venv\Scripts\Activate.ps1

$dbRunning = docker ps --filter "name=epms-db" --format "{{.Names}}" 2>&1
if ($dbRunning -ne "epms-db") {
    Write-Warn "PostgreSQL not running - starting it"
    docker start epms-db 2>&1 | Out-Null
    Start-Sleep -Seconds 3
}
Write-Ok "PostgreSQL container: epms-db"

try {
    $lm = Invoke-WebRequest -Uri "http://127.0.0.1:1234/v1/models" -TimeoutSec 2 -UseBasicParsing 2>&1
    if ($lm.StatusCode -eq 200) {
        Write-Ok "LM Studio responsive on 127.0.0.1:1234"
    }
} catch {
    Write-Warn "LM Studio not responding - agent will fall back to Claude Sonnet"
}

if ($Simulator) {
    Write-Step "Launching telemetry simulator (background)"
    $simArgs = "scripts\simulator.py --interval 3 --incidents"
    if ($Scenario) { $simArgs += " --scenario $Scenario --duration 60" }

    Start-Process -FilePath "python" -ArgumentList $simArgs -WindowStyle Minimized
    Write-Ok "Simulator started in minimized window"
}

Write-Step "Launching FastAPI backend on :8080"
Write-Host ""
Write-Host "  Dashboard: http://localhost:8080" -ForegroundColor Yellow
Write-Host "  Health:    http://localhost:8080/api/health" -ForegroundColor Yellow
Write-Host "  API docs:  http://localhost:8080/docs" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Press Ctrl+C to stop backend" -ForegroundColor DarkGray
Write-Host ""

python backend\main.py
