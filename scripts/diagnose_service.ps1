# diagnose_service.ps1
# Identifies why http://127.0.0.1:8080 returns connection refused.

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "===== Service Connectivity Diagnostic =====" -ForegroundColor Cyan
Write-Host ""

Write-Host "1. Docker container state for epms-backend:" -ForegroundColor Yellow
& docker ps -a --filter "name=epms-backend" --format "table {{.Names}}`t{{.Status}}`t{{.Ports}}"
Write-Host ""

Write-Host "2. Docker logs (last 30 lines):" -ForegroundColor Yellow
& docker logs --tail 30 epms-backend 2>&1
Write-Host ""

Write-Host "3. Port 8080 listener check (Windows):" -ForegroundColor Yellow
$ErrorActionPreference = "SilentlyContinue"
$tcp = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
$ErrorActionPreference = "Continue"
if ($tcp) {
    $tcp | Format-Table LocalAddress, LocalPort, State, OwningProcess -AutoSize
    foreach ($conn in $tcp) {
        try {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction Stop
            Write-Host "  Process: $($proc.ProcessName) (PID $($conn.OwningProcess))"
        } catch {}
    }
} else {
    Write-Host "  NO LISTENER on port 8080" -ForegroundColor Red
}
Write-Host ""

Write-Host "4. docker-compose status (if applicable):" -ForegroundColor Yellow
if (Test-Path "docker-compose.yml") {
    & docker-compose ps 2>&1
} else {
    Write-Host "  No docker-compose.yml at root"
}
Write-Host ""

Write-Host "===== Recovery options =====" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Option A: Direct uvicorn (no docker)" -ForegroundColor Green
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host "    uvicorn backend.main:app --host 127.0.0.1 --port 8080 --log-level info"
Write-Host ""
Write-Host "  Option B: docker-compose up" -ForegroundColor Green
Write-Host "    docker-compose down"
Write-Host "    docker-compose up -d"
Write-Host "    docker-compose logs -f epms-backend"
Write-Host ""
Write-Host "  Option C: docker run from rebuild" -ForegroundColor Green
Write-Host "    docker stop epms-backend; docker rm epms-backend"
Write-Host "    docker run -d --name epms-backend -p 8080:8080 dc-epms-pro:latest"
Write-Host ""
