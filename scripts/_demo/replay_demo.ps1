# =====================================================================
#  scripts/_demo/replay_demo.ps1
#  =====================================================================
#  One-click demo state reset for the CO+I panel walkthrough.
#
#  What it does (in order):
#    1. Verifies prerequisites (epms-db running, uvicorn reachable on 8080)
#    2. WIPES the work_orders table (assets are preserved)
#    3. Replays the snapshot SQL to restore the post-demo state
#    4. Resets three Path A predictive_kalman P1 LOTO WOs to
#       pending_approval so you have fresh click-through targets:
#          rpp_a_01    -> THDi excursion         (IEEE 519-2014 §5.1)
#          cdu_a_01    -> coolant flow drift     (DLC manifold)
#          genset_a_01 -> oil pressure drop      (NFPA 110)
#       (rejected probe artifacts from the snapshot are dropped)
#    5. Injects a 4th sample WO for the Multi-Agent VETO demo:
#          genset_b_01 -> manual draft, requires_loto=true, NO MOP
#       The Safety Officer agent VETOes this on consult - used in
#       Act 3 of the canonical walkthrough. Permanent baseline so
#       the operator never has to use a terminal mid-demo.
#    6. Prints the resulting backlog so you can confirm the state
#       matches what the Maintenance view will render after F5.
#
#  Usage:
#    .\scripts\_demo\replay_demo.ps1                # default
#    .\scripts\_demo\replay_demo.ps1 -SkipWipe      # keep current WOs
#    .\scripts\_demo\replay_demo.ps1 -DryRun        # preview only
#
#  Idempotent: re-running brings state back to the same baseline.
# =====================================================================

param(
    [switch]$SkipWipe,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$REPO_ROOT   = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$SNAPSHOT    = Join-Path $PSScriptRoot 'postgres_demo_state_2026-05-09.sql'
$API         = 'http://127.0.0.1:8080/api'
$PG_CONTAINER = 'epms-db'
$PG_USER     = 'epms'
$PG_DB       = 'dcepms'

function Write-Section($title) {
    Write-Host ""
    Write-Host "=== $title ===" -ForegroundColor Cyan
}

function Assert-Prereq {
    Write-Section "Prereq checks"
    $running = (docker ps --filter "name=$PG_CONTAINER" --format "{{.Names}}") -eq $PG_CONTAINER
    if (-not $running) {
        throw "Container '$PG_CONTAINER' is not running. Start with: docker compose up -d $PG_CONTAINER"
    }
    Write-Host "  [OK] container '$PG_CONTAINER' is running"

    try {
        $health = Invoke-RestMethod -Uri "$API/health" -TimeoutSec 5
        if ($health.postgres.status -ne 'up') {
            throw "API up but postgres status='$($health.postgres.status)'"
        }
        Write-Host "  [OK] uvicorn reachable, postgres=up ($($health.postgres.latency_ms) ms)"
    } catch {
        throw "uvicorn not reachable on 8080: $_"
    }

    if (-not (Test-Path $SNAPSHOT)) {
        throw "Snapshot SQL not found: $SNAPSHOT"
    }
    Write-Host "  [OK] snapshot present: $SNAPSHOT"
}

function Invoke-Sql([string]$Sql) {
    if ($DryRun) {
        Write-Host "  [DRY] $Sql"
        return $null
    }
    $Sql | docker exec -i $PG_CONTAINER psql -U $PG_USER -d $PG_DB -t -A 2>&1
}

function Wipe-WorkOrders {
    Write-Section "Wipe work_orders table"
    if ($SkipWipe) { Write-Host "  [SKIP] -SkipWipe set"; return }
    $before = Invoke-Sql "SELECT count(*) FROM work_orders;"
    Write-Host "  before: $before WOs"
    Invoke-Sql "TRUNCATE TABLE work_orders;" | Out-Null
    if (-not $DryRun) {
        $after = Invoke-Sql "SELECT count(*) FROM work_orders;"
        Write-Host "  after:  $after WOs"
    }
}

function Replay-Snapshot {
    Write-Section "Replay snapshot SQL"
    # Gap E: snapshot provenance visibility.
    $snapInfo = Get-Item $SNAPSHOT
    Write-Host ("  snapshot: {0}  (last modified {1:yyyy-MM-dd HH:mm})" -f `
        $snapInfo.Name, $snapInfo.LastWriteTime)
    if ($DryRun) {
        Write-Host "  [DRY] would pipe $SNAPSHOT through psql"
        return
    }
    $psqlOut = Get-Content $SNAPSHOT -Raw |
        docker exec -i $PG_CONTAINER psql -U $PG_USER -d $PG_DB 2>&1

    # Gap C: a snapshot/schema-drift error must abort, not slip through.
    $errLines = @($psqlOut | Select-String -Pattern '^ERROR' -Context 0,0)
    if ($errLines.Count -gt 0) {
        Write-Host "  [FAIL] snapshot replay produced $($errLines.Count) SQL ERROR line(s):" -ForegroundColor Red
        $errLines | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        throw "Snapshot replay aborted on SQL ERROR - the snapshot has likely drifted from the current schema."
    }

    $psqlOut | Select-String -Pattern '^INSERT' -Context 0,0 |
        Group-Object Line |
        ForEach-Object { Write-Host "  $($_.Count)x $($_.Name.Substring(0, [Math]::Min(40, $_.Name.Length)))" }

    # The snapshot left rejected probe rows from the original session;
    # drop them so the demo backlog stays clean (six-row narrative arc).
    $dropped = Invoke-Sql "DELETE FROM work_orders WHERE status = 'rejected' RETURNING work_order_id;"
    if ($dropped) {
        Write-Host "  dropped rejected probe artifacts: $dropped"
    }

    # Drop the three predictive_kalman approvals from the snapshot -
    # the Reset-PredictiveTargets step recreates them in pending_approval
    # so the demo has fresh click-through buttons.
    $cleared = Invoke-Sql "DELETE FROM work_orders WHERE trigger_source='predictive_kalman' RETURNING work_order_id;"
    if ($cleared) {
        Write-Host "  cleared predictive_kalman rows for fresh injection: $cleared"
    }

    # Sprint 7.1d-followup: revert the nameplate-enrichment demo asset
    # (ups_a) to its null-vendor seed state so the operator can repeat
    # the seed_new_asset -> enrich -> link_to_existing demo cycle on
    # every replay. The snapshot uses ON CONFLICT DO NOTHING which
    # cannot overwrite existing rows.
    $reverted = Invoke-Sql "UPDATE assets SET vendor=NULL, model=NULL, rated_capacity_kw=2500.0, rated_capacity_unit='kW', metadata_json='{""runtime_full_load_min"": 7}'::jsonb WHERE asset_id='ups_a' RETURNING asset_id;"
    if ($reverted) {
        Write-Host "  reverted ups_a to seed state (null vendor/model) for repeatable enrichment demo"
    }
}

function Inject-PredictiveWO {
    param([string]$AssetId, [string]$Channel, [string]$Metric,
          [double]$MaxZ, [double]$LastEmission, [string]$Rationale,
          [string]$Standard, [string]$LinkedMop)

    $payload = @{
        asset_id              = $AssetId
        issue_summary         = "Predictive anomaly: $Metric on $AssetId max_z=$MaxZ sustained 3 windows. Last emission: $LastEmission. $Rationale Reference: $Standard."
        work_class_hint       = 'CM'
        likelihood_idx        = 4
        consequence_idx       = 5
        requires_loto         = $true
        trigger_source        = 'predictive_kalman'
        requested_by          = 'predictive_trigger_kalman'
        predictive_metadata   = @{
            max_z              = $MaxZ
            mean_z             = [Math]::Round($MaxZ * 0.74, 2)
            metric             = $Metric
            channel_id         = $Channel
            last_emission      = $LastEmission
            sustain_count      = 3
            first_anomaly_at   = (Get-Date).ToUniversalTime().AddMinutes(-7).ToString("o")
            trigger_basis      = 'kalman_innovation_3sigma_sustained'
            asset_criticality  = 'high'
            standard_reference = $Standard
        }
        telemetry_snapshot_json = @{
            "${AssetId}:${Metric}" = $LastEmission
            captured_at            = (Get-Date).ToUniversalTime().ToString("o")
        }
    }
    $json = $payload | ConvertTo-Json -Depth 6 -Compress

    if ($DryRun) {
        Write-Host "  [DRY] inject $AssetId / $Metric (z=$MaxZ)"
        return
    }
    try {
        $resp = Invoke-RestMethod -Uri "$API/cmms/work-orders" `
            -Method POST -ContentType 'application/json' -Body $json -TimeoutSec 10
        Write-Host ("  [OK] {0,-12} -> {1}  P{2} LOR={3}  status={4}" -f `
            $AssetId, $resp.work_order_id, $resp.priority.Substring(1), $resp.lor, $resp.status) -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] $AssetId injection: $_" -ForegroundColor Red
        throw
    }
}

function Reset-PredictiveTargets {
    Write-Section "Inject 3 fresh predictive_kalman P1 LOTO targets"

    Inject-PredictiveWO `
        -AssetId      'rpp_a_01' `
        -Channel      'rpp_a_01:thd_i_pct' `
        -Metric       'thd_i_pct' `
        -MaxZ         12.8 `
        -LastEmission 18.4 `
        -Rationale    'IEEE 519 limit 8% at V<69kV; rated baseline 5-7% for GB200 PSU load. Suggested: PQ analyzer scan + verify upstream UPS rectifier capacitor bank.' `
        -Standard     'IEEE 519-2014 Section 5.1' `
        -LinkedMop    $null

    Inject-PredictiveWO `
        -AssetId      'cdu_a_01' `
        -Channel      'cdu_a_01:loop_flow_lpm' `
        -Metric       'loop_flow_lpm' `
        -MaxZ         15.6 `
        -LastEmission 142.0 `
        -Rationale    'DLC manifold flow drifted 22% below GB200 spec (rated 180 LPM). Risk: GPU Tj excursion at next training step burst. Suggested: pump curve check + filter dP scan.' `
        -Standard     'ASHRAE TC 9.9 (2021) Class W17 spec' `
        -LinkedMop    $null

    Inject-PredictiveWO `
        -AssetId      'genset_a_01' `
        -Channel      'genset_a_01:oil_pressure_psi' `
        -Metric       'oil_pressure_psi' `
        -MaxZ         19.2 `
        -LastEmission 38.0 `
        -Rationale    'Oil pressure dropped to 38 psi during weekly load-bank exercise (rated 45-65 psi at 1800 RPM). Risk: failure to start during utility outage. Suggested: oil pump inspection + filter change.' `
        -Standard     'NFPA 110-2022 Section 8.4 (Level 1 EPSS)' `
        -LinkedMop    $null
}

function Inject-VetoSampleWO {
    # Manual draft, requires_loto=true, linked_mop_id=null. The
    # Multi-Agent Safety Officer will VETO this on consult - the
    # demo-killer "shift handover review" narrative. Permanent
    # baseline so the operator never has to touch a terminal mid-demo.
    Write-Section "Inject VETO sample WO (Multi-Agent Safety Officer trigger)"

    $payload = @{
        asset_id              = 'genset_b_01'
        issue_summary         = 'Manual draft from prior shift: genset_b_01 quarterly inspection + oil sample. Tech submitted without linking the MOP - caught during shift handover review. Multi-Agent Safety Officer should VETO until MOP T4-MOP-GEN-001 is attached.'
        work_class_hint       = 'PM'
        likelihood_idx        = 3
        consequence_idx       = 4
        requires_loto         = $true
        requires_oem_specialist = $false
        trigger_source        = 'manual'
        requested_by          = 'shift_handover_audit'
        # NOTE: linked_mop_id intentionally omitted -> null. This is
        # what triggers the Safety Officer veto in multi_agent.py.
    }
    $json = $payload | ConvertTo-Json -Depth 4 -Compress
    if ($DryRun) {
        Write-Host "  [DRY] inject genset_b_01 manual draft (no MOP, requires_loto=true)"
        return
    }
    try {
        $resp = Invoke-RestMethod -Uri "$API/cmms/work-orders" `
            -Method POST -ContentType 'application/json' -Body $json -TimeoutSec 10
        Write-Host ("  [OK] {0,-12} -> {1}  P{2} LOR={3}  status={4}  loto=YES  mop=null" -f `
            'genset_b_01', $resp.work_order_id, $resp.priority.Substring(1), $resp.lor, $resp.status) -ForegroundColor Yellow
        Write-Host "       ^ this WO is the live VETO target - paste its id into Multi-Agent during the demo"
    } catch {
        Write-Host "  [FAIL] genset_b_01 VETO sample injection: $_" -ForegroundColor Red
        throw
    }
}

function Show-Backlog {
    Write-Section "Resulting open-WO backlog (what the Maintenance view will render)"
    if ($DryRun) { Write-Host "  [DRY] skipped"; return }
    try {
        $wos = Invoke-RestMethod -Uri "$API/cmms/work-orders?only_open=true&limit=200" -TimeoutSec 5
        Write-Host ("  open WO count: {0}" -f $wos.count) -ForegroundColor Yellow
        $statuses = $wos.work_orders | Group-Object status |
                    ForEach-Object { "$($_.Name)=$($_.Count)" }
        Write-Host "  by status: $($statuses -join ', ')"
        Write-Host ""
        $wos.work_orders | ForEach-Object {
            $loto = if ($_.requires_loto) { 'YES' } else { 'no ' }
            $cet  = if ($_.approved_by_cet) { $_.approved_by_cet } else { '-' }
            Write-Host ("  {0,-32} {1,-14} {2}  {3,-18}  src={4,-18} loto={5} cet={6}" -f `
                $_.work_order_id, $_.asset_id, $_.priority, $_.status, $_.trigger_source, $loto, $cet)
        }
    } catch {
        Write-Host "  [FAIL] could not fetch backlog: $_" -ForegroundColor Red
    }
}

# ─── main ─────────────────────────────────────────────────────────────
$start = Get-Date
Write-Host ""
Write-Host "DC-EPMS PRO demo state reset" -ForegroundColor Magenta
Write-Host "(snapshot: $($SNAPSHOT | Split-Path -Leaf))"
if ($DryRun) { Write-Host "[DRY-RUN MODE]" -ForegroundColor Yellow }

try {
    Assert-Prereq
    Wipe-WorkOrders
    Replay-Snapshot
    Reset-PredictiveTargets
    Inject-VetoSampleWO
    Show-Backlog

    # Gap B: twin-script verification. The reset is NOT "done" until the
    # certification pass confirms the exact baseline. No silent successes.
    Write-Section "Post-condition: pre-flight certification"
    if ($DryRun) {
        Write-Host "  [DRY] would run preflight_demo_check.ps1"
    } else {
        & (Join-Path $PSScriptRoot 'preflight_demo_check.ps1')
        if ($LASTEXITCODE -ne 0) {
            throw "Pre-flight certification FAILED (exit $LASTEXITCODE). Baseline not trustworthy - do NOT record."
        }
        Write-Host "  [OK] pre-flight certified the baseline" -ForegroundColor Green
    }

    $elapsed = ((Get-Date) - $start).TotalSeconds
    Write-Host ""
    Write-Host ("[OK] demo reset complete + certified in {0:N1}s" -f $elapsed) -ForegroundColor Green

    $reminder = @'

  ================================================================
  ==                                                            ==
  ==   [PRE-FLIGHT REMINDER] : purge stale browser state         ==
  ==                                                            ==
  ==   Open DevTools  ->  Run  'localStorage.clear()'            ==
  ==   ->  Hit  Ctrl+Shift+R                                     ==
  ==                                                            ==
  ==   Purges 'mc_panel_layout_v1' HUD-layout data so the 4      ==
  ==   panels load in their default corners.                     ==
  ==   Then open  http://127.0.0.1:8080/#maintenance             ==
  ==                                                            ==
  ================================================================
'@
    Write-Host $reminder -ForegroundColor Yellow
} catch {
    Write-Host ""
    Write-Host "[FAIL] demo reset aborted: $_" -ForegroundColor Red
    exit 1
}
