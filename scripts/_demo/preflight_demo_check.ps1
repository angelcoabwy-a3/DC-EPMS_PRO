# =============================================================
#  DC-EPMS PRO - scripts/_demo/preflight_demo_check.ps1
#
#  Pre-flight verification before an OBS demo recording.
#  Confirms the backend is up and the demo baseline is loaded so
#  Building A reads CAUTION (amber) with Anom 3 in Mission Control.
#  Anomaly logic mirrors frontend mission_control.js _fetchLiveData.
#
#  Run:  .\scripts\_demo\preflight_demo_check.ps1
#  Exit: 0 = PASS (safe to record), 1 = FAIL (do not record)
# =============================================================
$ErrorActionPreference = 'Stop'
$base = 'http://127.0.0.1:8080'
$pass = $true

# 1. Backend health
try {
    $h = Invoke-RestMethod -Uri "$base/api/health" -TimeoutSec 5
    if ($h.postgres.status -eq 'up') {
        Write-Host '[OK]   postgres up' -ForegroundColor Green
    } else {
        Write-Host '[FAIL] postgres not up' -ForegroundColor Red
        $pass = $false
    }
} catch {
    Write-Host '[FAIL] backend unreachable on :8080' -ForegroundColor Red
    $pass = $false
}

# 2. Explicit Phase 1 target verification. The 3 named demo targets must
#    all be present; stray rack_* WOs from the live predictive trigger
#    are a non-blocking WARN (they inflate the HUD counters but do not
#    break the scripted narrative, which clicks the 3 named WOs).
$CORE_TARGETS = @('rpp_a_01', 'cdu_a_01', 'genset_a_01')
try {
    $url = "$base/api/cmms/work-orders?trigger_source=predictive_kalman&only_open=true&limit=200"
    $wos = Invoke-RestMethod -Uri $url -TimeoutSec 5
    $open = @($wos.work_orders | Where-Object { $_.status -eq 'pending_approval' })

    $coreFound = @(@($open | Where-Object { $CORE_TARGETS -contains $_.asset_id }).asset_id |
                   Sort-Object -Unique)
    $strays = @($open | Where-Object { $CORE_TARGETS -notcontains $_.asset_id })

    if ($coreFound.Count -eq 3) {
        Write-Host '[OK]   Building A: 3 named Phase 1 targets present (CAUTION amber)' -ForegroundColor Green
        Write-Host '         rpp_a_01 / cdu_a_01 / genset_a_01' -ForegroundColor DarkGray
    } else {
        $missing = @($CORE_TARGETS | Where-Object { $coreFound -notcontains $_ })
        Write-Host "[FAIL] Building A: only $($coreFound.Count) of 3 named targets present" -ForegroundColor Red
        Write-Host "         missing: $($missing -join ', ')" -ForegroundColor Red
        $pass = $false
    }

    if ($strays.Count -gt 0) {
        $strayIds = @($strays.asset_id | Sort-Object -Unique) -join ', '
        Write-Host "[WARN] Stray background alerts detected (Count: $($strays.Count))" -ForegroundColor Yellow
        Write-Host "         $strayIds" -ForegroundColor DarkGray
        Write-Host '         non-blocking, but HUD anomaly counters will read high' -ForegroundColor DarkGray
    } else {
        Write-Host '[OK]   Building B: 0 stray alerts (HEALTHY)' -ForegroundColor Green
    }
} catch {
    Write-Host '[FAIL] /api/cmms/work-orders query failed' -ForegroundColor Red
    $pass = $false
}

# 3. Verdict
Write-Host ''
if ($pass) {
    Write-Host '=== PRE-FLIGHT PASS. Safe to roll OBS. ===' -ForegroundColor Green
    exit 0
} else {
    Write-Host '=== PRE-FLIGHT FAIL. Do NOT record. ===' -ForegroundColor Red
    Write-Host 'Likely fix: .\scripts\_demo\replay_demo.ps1 then hard-reload the browser.'
    exit 1
}
