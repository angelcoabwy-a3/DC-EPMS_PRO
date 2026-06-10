# =====================================================================
# DC-EPMS PRO -- Pre-Flight Demo Verifier (docs/DEMO_SCRIPT.md v6 companion)
#
# Idempotent stack-readiness check before the CO+I demo. Run 15 min
# before the panel. Refuses to declare GREEN if ANY check fails.
#
# Verifies (in order):
#   1. epms-db docker container is HEALTHY (CMMS depends on it)
#   2. Port :8080 is FREE (no orphan python from prior session)
#   3. Backend starts cleanly via python backend\main.py
#   4. Boot log contains [BUILD] DC-EPMS_PRO=v0.16.0
#   5. Boot log contains [BOOT] Architect library pre-seeded with 23
#   6. Boot log contains [graphrag] loaded 10 knowledge documents
#   7. GET /api/health reports version=0.16.0, pg=up
#   8. GET /api/procedures/architect/library?source=catalog reports
#      total=23, every audit_verdict=approve
#
# Exits with code 0 only when ALL checks pass.
#
# Locked: 2026-05-24, v0.16.0 "Procedure Architect Universal".
#
# File encoding: ASCII-only. PowerShell 5.1 on Windows interprets
# files without BOM as cp1252 -- non-ASCII chars (box-drawing dashes,
# accented vowels) trigger spurious "string missing terminator"
# parse errors. Keep this script ASCII-only.
# =====================================================================

$ErrorActionPreference = "Stop"

$REPO_ROOT  = "C:\dev\DC-EPMS_PRO"
$LOG_FILE   = "$REPO_ROOT\logs\epms_pro.log"
$VENV_PY    = "$REPO_ROOT\.venv\Scripts\python.exe"
$BACKEND_PY = "$REPO_ROOT\backend\main.py"
$EXPECTED_VERSION = "0.16.0"
$EXPECTED_LIB     = 23
$EXPECTED_GRAPHRAG = 10

# Boot-signature patterns the script must see in the log to declare ready.
$BOOT_BUILD_PAT   = "DC-EPMS_PRO=v$EXPECTED_VERSION"
$BOOT_LIB_PAT     = "Architect library pre-seeded with $EXPECTED_LIB catalog MOP"
$BOOT_GRAPHRAG_PAT = "loaded $EXPECTED_GRAPHRAG knowledge documents"

# Boot deadline.
$BOOT_TIMEOUT_S = 90

# ---------------------------------------------------------------------
# Helper: status reporters
# ---------------------------------------------------------------------
$results = [ordered]@{}

function Set-Check([string]$name, [bool]$ok, [string]$detail) {
    $results[$name] = @{ ok = $ok; detail = $detail }
    $tag = if ($ok) { "[GREEN]" } else { "[RED  ]" }
    $color = if ($ok) { "Green" } else { "Red" }
    Write-Host "$tag $name -- $detail" -ForegroundColor $color
}

function Test-Final {
    Write-Host ""
    Write-Host "---------------------------------------------------------"
    $failed = @($results.GetEnumerator() | Where-Object { -not $_.Value.ok })
    if ($failed.Count -eq 0) {
        Write-Host "  ALL CHECKS GREEN -- demo stack ready" -ForegroundColor Green
        Write-Host "---------------------------------------------------------"
        Write-Host ""
        Write-Host "Next: hard-reload browser (Ctrl+Shift+R) on tabs 1-4"
        Write-Host "      pre-stage terminal with /api/ledger/verify command"
        Write-Host "      review docs/DEMO_SCRIPT.md beats 0-5"
        exit 0
    } else {
        Write-Host "  $($failed.Count) CHECK(S) FAILED -- do NOT demo" -ForegroundColor Red
        Write-Host "---------------------------------------------------------"
        foreach ($f in $failed) {
            Write-Host "  - $($f.Key): $($f.Value.detail)" -ForegroundColor Red
        }
        exit 1
    }
}

# ---------------------------------------------------------------------
# Check 1 -- epms-db container
# ---------------------------------------------------------------------
try {
    $health = & docker inspect --format "{{.State.Health.Status}}" epms-db 2>$null
    if ($health -eq "healthy") {
        Set-Check "docker epms-db" $true "container healthy"
    } else {
        # Try to start it if container exists but is exited
        & docker start epms-db 2>$null | Out-Null
        Start-Sleep -Seconds 8
        $health = & docker inspect --format "{{.State.Health.Status}}" epms-db 2>$null
        if ($health -eq "healthy") {
            Set-Check "docker epms-db" $true "container healthy (restarted)"
        } else {
            Set-Check "docker epms-db" $false "container status=$health -- run docker start epms-db manually"
            Test-Final
        }
    }
} catch {
    Set-Check "docker epms-db" $false "docker inspect failed: $_"
    Test-Final
}

# ---------------------------------------------------------------------
# Check 2 -- :8080 free (kill any orphans)
# ---------------------------------------------------------------------
$conns = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
$pids = @($conns | Where-Object { $_.OwningProcess -gt 0 } | Select-Object -ExpandProperty OwningProcess -Unique)
if ($pids.Count -gt 0) {
    Write-Host "[INFO ] killing $($pids.Count) orphan process(es) on :8080: $($pids -join ', ')" -ForegroundColor Yellow
    foreach ($pid_to_kill in $pids) {
        try { & taskkill /F /PID $pid_to_kill 2>$null | Out-Null } catch {}
    }
    Start-Sleep -Seconds 5
}
$remaining = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -gt 0 }
if ($remaining) {
    Set-Check "port 8080 free" $false "still bound by $($remaining[0].OwningProcess) -- manual intervention required"
    Test-Final
} else {
    Set-Check "port 8080 free" $true "no orphan processes"
}

# ---------------------------------------------------------------------
# Check 3 -- start backend
#
# Capture $bootStart BEFORE spawning so the boot-signature checks
# below can filter out stale log lines from prior runs. The log file
# is append-only across reboots; without the timestamp filter, the
# script can falsely match a prior boot's signatures and declare
# ready before the new process is actually up.
# ---------------------------------------------------------------------
$bootStart = Get-Date
try {
    Start-Process -FilePath $VENV_PY -ArgumentList $BACKEND_PY -WorkingDirectory $REPO_ROOT -PassThru | Out-Null
    Set-Check "backend started" $true "spawned python backend\main.py at $($bootStart.ToString('HH:mm:ss'))"
} catch {
    Set-Check "backend started" $false "spawn failed: $_"
    Test-Final
}

# ---------------------------------------------------------------------
# Checks 4-6 -- wait for boot signatures within timeout
#
# Each log line is prefixed with `YYYY-MM-DD HH:MM:SS,fff` -- we parse
# it and skip lines older than $bootStart so prior runs don't fool us.
# ---------------------------------------------------------------------
$deadline = (Get-Date).AddSeconds($BOOT_TIMEOUT_S)
$seenBuild = $false
$seenLib   = $false
$seenGraphRAG = $false
# Match the leading timestamp + capture as a [datetime].
$tsPattern = '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{3})'

while ((Get-Date) -lt $deadline) {
    if (Test-Path $LOG_FILE) {
        $recentLines = @()
        try {
            # Read more lines than the seen-window to be safe; the
            # post-spawn count of new log lines could be in the
            # hundreds during GraphRAG warm-up.
            $recentLines = Get-Content $LOG_FILE -Tail 1000 -ErrorAction SilentlyContinue
        } catch {
            Start-Sleep -Seconds 2
            continue
        }
        foreach ($line in $recentLines) {
            # Skip line if it has a parseable timestamp older than the
            # bootStart we captured. Lines without a leading timestamp
            # (e.g. multi-line tracebacks) are accepted by default --
            # they're rare and most often emit AFTER the new boot.
            if ($line -match $tsPattern) {
                try {
                    $lineTs = [datetime]::ParseExact(
                        "$($matches[1]).$($matches[2])",
                        "yyyy-MM-dd HH:mm:ss.fff",
                        $null)
                    if ($lineTs -lt $bootStart) { continue }
                } catch {
                    # Unparseable timestamp -- fall through and consider
                    # the line.
                }
            }
            if (-not $seenBuild    -and ($line -match $BOOT_BUILD_PAT))    { $seenBuild = $true }
            if (-not $seenLib      -and ($line -match $BOOT_LIB_PAT))      { $seenLib = $true }
            if (-not $seenGraphRAG -and ($line -match $BOOT_GRAPHRAG_PAT)) { $seenGraphRAG = $true }
        }
        if ($seenBuild -and $seenLib -and $seenGraphRAG) { break }
    }
    Start-Sleep -Seconds 2
}

Set-Check "[BUILD] v$EXPECTED_VERSION"      $seenBuild     ("seen in log: $seenBuild")
Set-Check "[BOOT] library 23 catalog MOPs"  $seenLib       ("seen in log: $seenLib")
Set-Check "[graphrag] loaded $EXPECTED_GRAPHRAG docs" $seenGraphRAG ("seen in log: $seenGraphRAG")

if (-not ($seenBuild -and $seenLib -and $seenGraphRAG)) {
    Write-Host "  Boot signatures not all seen within $BOOT_TIMEOUT_S s -- investigate log: $LOG_FILE" -ForegroundColor Red
    Test-Final
}

# ---------------------------------------------------------------------
# Helper: HTTP retry wrapper (belt-and-suspenders).
#
# Even after boot signatures appear, uvicorn binding to :8080 can lag
# by a few seconds. Retry 5x with 3s sleep before declaring failure.
# ---------------------------------------------------------------------
function Invoke-WithRetry([scriptblock]$action, [int]$retries = 5, [int]$sleepSec = 3) {
    $lastErr = $null
    for ($i = 1; $i -le $retries; $i++) {
        try {
            return & $action
        } catch {
            $lastErr = $_
            if ($i -lt $retries) {
                Start-Sleep -Seconds $sleepSec
            }
        }
    }
    throw $lastErr
}

# ---------------------------------------------------------------------
# Check 7 -- /api/health (with retry)
# ---------------------------------------------------------------------
try {
    $health = Invoke-WithRetry { Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/health" -TimeoutSec 10 -ErrorAction Stop }
    $ok = ($health.version -eq $EXPECTED_VERSION) -and ($health.postgres.status -eq "up")
    Set-Check "api health" $ok ("version=$($health.version), pg=$($health.postgres.status)")
} catch {
    Set-Check "api health" $false "request failed after retries: $_"
}

# ---------------------------------------------------------------------
# Check 8 -- library has 23 catalog MOPs all audit=approve (with retry)
# ---------------------------------------------------------------------
try {
    # Single-quoted URL avoids PowerShell ampersand parsing.
    $libUrl = 'http://127.0.0.1:8080/api/procedures/architect/library?source=catalog&limit=100'
    $lib = Invoke-WithRetry { Invoke-RestMethod -Uri $libUrl -TimeoutSec 10 -ErrorAction Stop }
    $approveCount = @($lib.items | Where-Object { $_.audit_verdict -eq "approve" }).Count
    $ok = ($lib.total -eq $EXPECTED_LIB) -and ($approveCount -eq $EXPECTED_LIB)
    Set-Check "library catalog audit" $ok ("total=$($lib.total), audit=approve count=$approveCount")
} catch {
    Set-Check "library catalog audit" $false "request failed after retries: $_"
}

# ---------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------
Test-Final
