# =====================================================================
# gen_telemetry_proto_stubs.ps1
# =====================================================================
# Regenerate Python protobuf stubs from backend/telemetry_proto/v1/
# telemetry.proto. Idempotent -- re-running is safe.
#
# Per V9.1 PowerShell Native Mandate: filesystem ops in PowerShell only.
#
# Pre-flight:
#   * The repo's .venv must exist at C:\dev\DC-EPMS_PRO\.venv.
#   * grpcio-tools must be installed inside that venv. The script will
#     install it on demand if absent.
#
# Output:
#   backend/telemetry_proto/v1/telemetry_pb2.py
#
# Skill: S-TELEMETRY-01 (wire-format invariants are the gate).
# =====================================================================

$ErrorActionPreference = 'Stop'

# Resolve repo root from this script's location (..\.. from scripts\).
# When running inside a worktree, this lands in the worktree directory --
# the .proto + stub destination live here. The .venv may NOT live here
# (worktrees share the parent repo's venv), so we resolve $Python
# separately via git rev-parse --git-common-dir.
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ProtoSrc = Join-Path $RepoRoot 'backend\telemetry_proto\v1\telemetry.proto'
$OutRoot  = $RepoRoot

# Find the venv: prefer the worktree's own .venv; fall back to the
# main repo's .venv (worktrees share it).
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    Push-Location $RepoRoot
    try {
        $GitCommonDir = (& git rev-parse --git-common-dir 2>$null)
        if ($LASTEXITCODE -eq 0 -and $GitCommonDir) {
            # git may return absolute or relative; handle both.
            if ([System.IO.Path]::IsPathRooted($GitCommonDir)) {
                $GcdResolved = $GitCommonDir
            } else {
                $GcdResolved = (Resolve-Path (Join-Path $RepoRoot $GitCommonDir)).Path
            }
            $MainRepo = (Split-Path $GcdResolved -Parent)
            $Python = Join-Path $MainRepo '.venv\Scripts\python.exe'
        }
    }
    finally {
        Pop-Location
    }
}

if (-not (Test-Path $Python)) {
    Write-Error "venv python not found at $Python -- run scripts\start.ps1 to bootstrap"
    exit 1
}
if (-not (Test-Path $ProtoSrc)) {
    Write-Error "telemetry.proto not found at $ProtoSrc"
    exit 1
}

# Probe for grpc_tools; install only if missing.
$probe = & $Python -c "import grpc_tools" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host '[stubs] grpcio-tools not installed; installing...' -ForegroundColor Yellow
    & $Python -m pip install grpcio-tools
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'pip install grpcio-tools failed'
        exit 1
    }
}

Write-Host "[stubs] regenerating from $ProtoSrc" -ForegroundColor Cyan

# proto_path = repo root so generated imports resolve as
# `backend.telemetry_proto.v1.telemetry_pb2` cleanly.
& $Python -m grpc_tools.protoc `
    "--proto_path=$RepoRoot" `
    "--python_out=$OutRoot" `
    "$ProtoSrc"

if ($LASTEXITCODE -ne 0) {
    Write-Error 'protoc failed -- check .proto syntax against the schema invariants test'
    exit 1
}

$GeneratedStub = Join-Path $RepoRoot 'backend\telemetry_proto\v1\telemetry_pb2.py'
if (-not (Test-Path $GeneratedStub)) {
    Write-Error "expected stub at $GeneratedStub but not found"
    exit 1
}

# Verify the generated module imports cleanly via the canonical path.
Push-Location $RepoRoot
try {
    & $Python -c "from backend.telemetry_proto.v1 import telemetry_pb2; print('[stubs] OK ', telemetry_pb2.__name__)"
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'generated stub failed to import via canonical path'
        exit 1
    }
}
finally {
    Pop-Location
}

Write-Host '[stubs] done.' -ForegroundColor Green
