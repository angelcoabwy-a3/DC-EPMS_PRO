# Sprint 3 demo — single window, simulates initiator + witness simultaneously
$ErrorActionPreference = "Continue"
Write-Host "=== SPRINT 3 DEMO: Witness Workflow ===" -ForegroundColor Cyan

# Start procedure as alice
$body = @{ operator = "alice" } | ConvertTo-Json
$started = Invoke-RestMethod -Uri http://localhost:8080/api/procedures/MOP-ATS-MONTHLY-001/start `
                             -Method Post -ContentType "application/json" -Body $body
$execId = $started.execution_id
Write-Host "[A] Started by alice: execId=$execId state=$($started.state)" -ForegroundColor Green

# Background job: bob signs all pending witness requests
$signerJob = Start-Job -ScriptBlock {
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        try {
            $pending = Invoke-RestMethod -Uri http://localhost:8080/api/witness/pending
            foreach ($req in $pending.requests) {
                if ($req.initiator -ne "bob") {
                    $body = @{ witness = "bob" } | ConvertTo-Json
                    try {
                        Invoke-RestMethod -Uri "http://localhost:8080/api/witness/$($req.request_id)/sign" `
                                          -Method Post -ContentType "application/json" -Body $body | Out-Null
                        Write-Output "[B] Signed $($req.step_id) as bob"
                    } catch {}
                }
            }
        } catch {}
        Start-Sleep -Milliseconds 300
    }
}

Start-Sleep -Seconds 1   # let signer job start

# Advance the procedure as alice — blocks until signed/aborted
$body = @{ operator = "alice" } | ConvertTo-Json
$result = Invoke-RestMethod -Uri "http://localhost:8080/api/procedures/executions/$execId/advance" `
                            -Method Post -ContentType "application/json" -Body $body

Write-Host "`n[A] Final state: $($result.state)" -ForegroundColor $(if ($result.state -eq "COMPLETED") {"Green"} else {"Red"})
Write-Host "[A] Steps executed: $($result.execution_log.Count)"
foreach ($s in $result.execution_log) {
    Write-Host "  [$($s.status)] $($s.step_id) witness=$($s.witness_acknowledged_by)"
}

# Show what bob did
Write-Host "`n=== Background signer (bob) output: ==="
Receive-Job -Job $signerJob
Remove-Job -Job $signerJob -Force

# Verify the audit trail
$ex = Invoke-RestMethod -Uri "http://localhost:8080/api/procedures/executions/$execId"
Write-Host "`n=== Witness signatures captured: ==="
foreach ($sig in $ex.metadata.witness_signatures) {
    Write-Host "  step=$($sig.step_id) witness=$($sig.witness)"
}