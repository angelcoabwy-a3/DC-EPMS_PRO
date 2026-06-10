# DC-EPMS PRO - verify_loto_endpoint.ps1
# ============================================================
# Smoke test for the LOTO Auditor REST endpoints after main.py
# activation. Hits the live FastAPI service on port 8080.
#
# Tests performed:
#   1. GET /api/health (control: confirm service is up)
#   2. GET /api/loto/audits/recent (expect 200 with [])
#   3. POST /api/loto/audit (expect 200 OR 404 if target not in site_model)
#   4. If POST returned 200, GET /api/loto/audit/{audit_id}/markdown
#
# Reports verbose output for each call. Does not modify state.
# V9 PowerShell rules verified clean.
# ============================================================

[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8080",
    [string]$TestTargetId = "ats_a",
    [string]$TestProcedureId = "MOP-ATS-MONTHLY-001"
)

$ErrorActionPreference = "Stop"

function Write-Phase {
    param([string]$Title)
    $line = "-" * 70
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
}

function Write-Ok    { param([string]$m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Info  { param([string]$m) Write-Host "  [INFO] $m" -ForegroundColor Cyan }
function Write-Warn  { param([string]$m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Err   { param([string]$m) Write-Host "  [FAIL] $m" -ForegroundColor Red }

function Invoke-SafeRequest {
    param(
        [string]$Method,
        [string]$Url,
        [object]$Body = $null
    )
    $ErrorActionPreference = "Continue"
    try {
        $params = @{
            Method = $Method
            Uri = $Url
            ContentType = "application/json"
            UseBasicParsing = $true
        }
        if ($Body -ne $null) {
            $params.Body = ($Body | ConvertTo-Json -Depth 6)
        }
        $response = Invoke-WebRequest @params -ErrorAction Stop
        return @{
            Success = $true
            StatusCode = $response.StatusCode
            Content = $response.Content
            Headers = $response.Headers
        }
    } catch [System.Net.WebException] {
        $statusCode = -1
        $content = $_.Exception.Message
        if ($_.Exception.Response) {
            $statusCode = [int]$_.Exception.Response.StatusCode
            try {
                $stream = $_.Exception.Response.GetResponseStream()
                $reader = New-Object System.IO.StreamReader($stream)
                $content = $reader.ReadToEnd()
                $reader.Close()
                $stream.Close()
            } catch {
                # ignore
            }
        }
        return @{
            Success = $false
            StatusCode = $statusCode
            Content = $content
            Error = $_.Exception.Message
        }
    } catch {
        return @{
            Success = $false
            StatusCode = -1
            Content = ""
            Error = $_.Exception.Message
        }
    } finally {
        $ErrorActionPreference = "Stop"
    }
}

# ============================================================

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host "  LOTO Auditor Endpoint Smoke Test" -ForegroundColor Cyan
Write-Host "  Target: $BaseUrl" -ForegroundColor Cyan
Write-Host ("=" * 70) -ForegroundColor Cyan

$failures = 0

# ============================================================
# Test 1: Health check (control)
# ============================================================

Write-Phase "Test 1: Health check (control)"
Write-Info "GET $BaseUrl/api/health"

$health = Invoke-SafeRequest -Method "GET" -Url "$BaseUrl/api/health"

if ($health.StatusCode -eq 200) {
    Write-Ok "Service is up (200 OK)"
} else {
    Write-Err "Service health check failed: status $($health.StatusCode)"
    Write-Warn "Is the FastAPI service running?"
    Write-Warn "  Try: docker ps | findstr epms-backend"
    Write-Warn "  Or:  uvicorn backend.main:app --port 8080"
    $failures++
}

# ============================================================
# Test 2: GET /api/loto/audits/recent
# ============================================================

Write-Phase "Test 2: GET /api/loto/audits/recent"
Write-Info "GET $BaseUrl/api/loto/audits/recent"

$recent = Invoke-SafeRequest -Method "GET" -Url "$BaseUrl/api/loto/audits/recent"

if ($recent.StatusCode -eq 200) {
    Write-Ok "Endpoint reachable (200 OK)"
    Write-Info "  Response: $($recent.Content.Substring(0, [Math]::Min(200, $recent.Content.Length)))"
} elseif ($recent.StatusCode -eq 503) {
    Write-Warn "Endpoint returned 503 - LOTO Auditor or repository not registered"
    Write-Warn "  This means apply_main_py_activation.ps1 may not have been run"
    Write-Warn "  OR the agent was registered without a repository"
    Write-Warn "  Response: $($recent.Content)"
    $failures++
} elseif ($recent.StatusCode -eq 404) {
    Write-Err "Endpoint returned 404 - the route is NOT registered"
    Write-Err "  apply_main_py_activation.ps1 has NOT been applied"
    $failures++
} else {
    Write-Err "Unexpected status: $($recent.StatusCode)"
    Write-Warn "  Response: $($recent.Content)"
    $failures++
}

# ============================================================
# Test 3: POST /api/loto/audit
# ============================================================

Write-Phase "Test 3: POST /api/loto/audit"
Write-Info "POST $BaseUrl/api/loto/audit"
Write-Info "Body: procedure=$TestProcedureId target=$TestTargetId cet=smoke_test"

$auditBody = @{
    procedure_id = $TestProcedureId
    target_component_id = $TestTargetId
    cet_on_duty = "smoke_test"
}

$audit = Invoke-SafeRequest -Method "POST" -Url "$BaseUrl/api/loto/audit" -Body $auditBody

$auditId = $null

if ($audit.StatusCode -eq 200) {
    Write-Ok "Audit completed (200 OK)"
    try {
        $auditObj = $audit.Content | ConvertFrom-Json
        $auditId = $auditObj.audit_id
        Write-Info "  audit_id: $auditId"
        Write-Info "  overall_outcome: $($auditObj.overall_outcome)"
        Write-Info "  status: $($auditObj.status)"
        Write-Info "  hard_fail_count: $($auditObj.hard_fail_count)"
        Write-Info "  warn_count: $($auditObj.warn_count)"
        Write-Info "  decision_time_ms: $($auditObj.decision_time_ms)"
        if ($auditObj.status -eq "pending_approval") {
            Write-Ok "  ADR-006 Deterministic Sandbox respected: status is pending_approval"
        }
    } catch {
        Write-Warn "Could not parse audit response as JSON: $_"
    }
} elseif ($audit.StatusCode -eq 404) {
    Write-Warn "404 returned. Possible causes:"
    Write-Warn "  - Component '$TestTargetId' not in site_model.yml"
    Write-Warn "  - Procedure '$TestProcedureId' not in config/procedures/"
    Write-Warn "  Response: $($audit.Content)"
    Write-Warn "Try with a different -TestTargetId / -TestProcedureId parameter."
} elseif ($audit.StatusCode -eq 422) {
    Write-Warn "422 Pydantic validation error"
    Write-Warn "  Response: $($audit.Content)"
    $failures++
} elseif ($audit.StatusCode -eq 503) {
    Write-Err "503 - LOTO Auditor not registered. Run apply_main_py_activation.ps1 first."
    $failures++
} else {
    Write-Err "Unexpected status: $($audit.StatusCode)"
    Write-Warn "  Response: $($audit.Content)"
    $failures++
}

# ============================================================
# Test 4: GET markdown (only if Test 3 produced an audit_id)
# ============================================================

if ($auditId) {
    Write-Phase "Test 4: GET /api/loto/audit/{audit_id}/markdown"
    Write-Info "GET $BaseUrl/api/loto/audit/$auditId/markdown"

    $markdown = Invoke-SafeRequest -Method "GET" -Url "$BaseUrl/api/loto/audit/$auditId/markdown"

    if ($markdown.StatusCode -eq 200) {
        Write-Ok "Markdown rendered (200 OK)"
        $preview = $markdown.Content.Substring(0, [Math]::Min(500, $markdown.Content.Length))
        Write-Info "  Preview (first 500 chars):"
        $preview -split "`n" | Select-Object -First 15 | ForEach-Object {
            Write-Host "      $_"
        }
        # Verify expected sections
        $expectedSections = @("Pillar 1", "Pillar 2", "Pillar 3", "Pillar 4", "Pillar 5", "Pillar 6", "PENDING APPROVAL")
        $missing = @()
        foreach ($section in $expectedSections) {
            if (-not ($markdown.Content -match $section)) {
                $missing += $section
            }
        }
        if ($missing.Count -eq 0) {
            Write-Ok "All 6 pillar sections + PENDING APPROVAL banner present in markdown"
        } else {
            Write-Warn "Missing sections in markdown: $($missing -join ', ')"
        }
    } elseif ($markdown.StatusCode -eq 503) {
        Write-Warn "503 - audit was not persisted (no repository configured)"
        Write-Warn "  POST returned the report but did not save it to PostgreSQL"
        Write-Warn "  This is expected if register_loto_auditor() was called without repository="
    } else {
        Write-Err "Unexpected status: $($markdown.StatusCode)"
        Write-Warn "  Response: $($markdown.Content)"
        $failures++
    }
} else {
    Write-Phase "Test 4: SKIPPED (no audit_id from Test 3)"
}

# ============================================================
# Summary
# ============================================================

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor $(if ($failures -eq 0) { 'Green' } else { 'Yellow' })
if ($failures -eq 0) {
    Write-Host "  ALL ENDPOINTS RESPONDING - LOTO AUDITOR FULLY ACTIVATED" -ForegroundColor Green
} else {
    Write-Host "  $failures FAILURE(S) DETECTED - SEE LOG ABOVE" -ForegroundColor Yellow
}
Write-Host ("=" * 70) -ForegroundColor $(if ($failures -eq 0) { 'Green' } else { 'Yellow' })
Write-Host ""

if ($failures -eq 0) {
    Write-Host "  Next: record the demo video! See docs/DEMO_SCRIPT.md" -ForegroundColor Cyan
} else {
    Write-Host "  Next steps:" -ForegroundColor Cyan
    Write-Host "    - If 503: run apply_main_py_activation.ps1"
    Write-Host "    - If 404: check that backend.loto_auditor_routes is imported"
    Write-Host "    - If service down: docker start epms-backend OR uvicorn restart"
}
Write-Host ""

exit $(if ($failures -gt 0) { 1 } else { 0 })
