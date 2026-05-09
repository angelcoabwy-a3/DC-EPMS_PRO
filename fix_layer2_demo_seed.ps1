# fix_layer2_demo_seed.ps1
# DC-EPMS-005 followup: demo_seed_procedures.py belongs in scripts/, not root.

$ErrorActionPreference = "Stop"

if (-not (Test-Path "demo_seed_procedures.py")) {
    Write-Host "  [INFO] demo_seed_procedures.py not at root, skipping" -ForegroundColor Cyan
    exit 0
}

if (-not (Test-Path "scripts")) { New-Item -ItemType Directory -Path "scripts" | Out-Null }

Move-Item "demo_seed_procedures.py" "scripts\demo_seed_procedures.py" -Force
Write-Host "  [OK] Moved demo_seed_procedures.py to scripts/" -ForegroundColor Green

$ErrorActionPreference = "Continue"
& git add -A 2>&1 | Out-Null
$msg = "chore(layer2): move demo_seed_procedures.py to scripts/" + "`n`n" +
       "Layer 2 of validate_batch3.ps1 flagged demo_seed_procedures.py as" + "`n" +
       "an iteration script at root. It is a legitimate demo helper but" + "`n" +
       "belongs under scripts/ by project convention (DC-EPMS-005 cleanup" + "`n" +
       "policy). Restores Layer 2 to PASS." + "`n`n" +
       "Note: --no-verify per V9 Closing Discipline."
& git commit --no-verify -m $msg 2>&1 | Out-Null
$exit = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if ($exit -eq 0) {
    Write-Host "  [OK] Layer 2 fix committed" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] commit failed (exit $exit)" -ForegroundColor Red
}
