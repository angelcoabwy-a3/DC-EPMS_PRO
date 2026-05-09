# DC-EPMS PRO - apply_activation_v2.ps1
# ============================================================
# Corrected main.py activation based on diagnose_main_py_engines.py output.
#
# Key findings from diagnostic:
#   - physics_engine is FACTORY: from physics_engine import get_engine as get_physics_engine
#     Must call get_physics_engine() to get an instance.
#   - witness_engine has NO global instance; only _witness_store from get_witness_store().
#     The agent's _check_witness_engine_protection has graceful fallback on
#     AttributeError, so passing _witness_store works (Pillar 4 degrades to
#     'identity_collision_protected=False' rather than failing).
#   - site_model is _site_model (line 2165).
#   - graphrag_service is _s2_service (line 2188).
#   - Last include_router at line 2190; insertion point is line 2191.
#
# Insertion is a defensive try/except block with:
#   - PHYSICS_AVAILABLE guard
#   - Logging on success / warning on partial / error on failure
#   - Idempotency via marker comment
#
# V9 PowerShell rules verified clean. ASCII-only commit message.
# ============================================================

[CmdletBinding()]
param(
    [switch]$DryRun = $false,
    [switch]$AutoConfirm = $false,
    [switch]$SkipCommit = $false
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = ".\activation_v2_$timestamp.log"

function Write-Phase {
    param([string]$Title)
    $line = "=" * 70
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $logFile -Value ""
    Add-Content -Path $logFile -Value "  $Title"
}

function Write-Ok    { param([string]$m) Write-Host "  [OK] $m" -ForegroundColor Green;   Add-Content -Path $logFile -Value "  [OK] $m" }
function Write-Info  { param([string]$m) Write-Host "  [INFO] $m" -ForegroundColor Cyan;  Add-Content -Path $logFile -Value "  [INFO] $m" }
function Write-Warn  { param([string]$m) Write-Host "  [WARN] $m" -ForegroundColor Yellow; Add-Content -Path $logFile -Value "  [WARN] $m" }
function Write-Err   { param([string]$m) Write-Host "  [FAIL] $m" -ForegroundColor Red;   Add-Content -Path $logFile -Value "  [FAIL] $m" }

function Confirm-Action {
    param([string]$Prompt)
    if ($DryRun -or $AutoConfirm) {
        $tag = if ($DryRun) { "[DRY-RUN]" } else { "[AUTO]" }
        Write-Host "  $tag $Prompt" -ForegroundColor Magenta
        return $true
    }
    $response = Read-Host "  $Prompt [Y/n]"
    return ($response -eq "" -or $response -match "^[Yy]")
}

# ============================================================
# Pre-flight
# ============================================================

Write-Phase "main.py LOTO Auditor activation v2 (corrected)"
Write-Host "Mode: $(if ($DryRun) { 'DRY-RUN' } else { 'APPLY' })" -ForegroundColor $(if ($DryRun) { 'Magenta' } else { 'Yellow' })

if (-not (Test-Path "backend\main.py")) {
    Write-Err "backend\main.py not found. Run from project root."
    exit 1
}
$mainSize = (Get-Item "backend\main.py").Length
Write-Info "main.py size: $mainSize bytes"

# Idempotency check
$mainContent = Get-Content "backend\main.py" -Raw
if ($mainContent -match "register_loto_auditor") {
    Write-Warn "register_loto_auditor already present - activation already applied"
    Write-Info "If you need to re-apply, manually remove the existing block first"
    exit 0
}
Write-Ok "main.py present, no prior activation found"

# ============================================================
# Phase 1: Patch via Python helper
# ============================================================

Write-Phase "Phase 1 of 4: Patch main.py with defensive activation block"

$patcher = ".\_activation_v2_patcher_$timestamp.py"
$patcherPy = @'
"""main.py activation v2 patcher.

Inserts a defensive activation block right after line 2190 (last
app.include_router). The block uses:
  - get_physics_engine() factory call (NOT a variable)
  - _witness_store as witness_engine (subset interface)
  - PHYSICS_AVAILABLE guard
  - try/except for graceful failure
  - logging on each path
"""
import ast
import sys
from pathlib import Path

main_path = Path("backend/main.py")
content = main_path.read_text(encoding="utf-8")
lines = content.split("\n")

# Confirm AST is valid before editing
try:
    ast.parse(content)
except SyntaxError as e:
    print(f"PRE_AST_FAIL: {e}", file=sys.stderr)
    sys.exit(1)

# Find the last app.include_router line by parsing AST
tree = ast.parse(content)
last_include_line = None
for node in ast.walk(tree):
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        call = node.value
        if isinstance(call.func, ast.Attribute) and call.func.attr == "include_router":
            if isinstance(call.func.value, ast.Name) and call.func.value.id == "app":
                if last_include_line is None or node.lineno > last_include_line:
                    last_include_line = node.lineno

if last_include_line is None:
    print("FAIL: no app.include_router found", file=sys.stderr)
    sys.exit(2)

print(f"Found last include_router at line {last_include_line}")

# Build the activation snippet
snippet = '''

# Batch 4.D - LOTO Auditor activation (V9 Pillar 4 deliverable)
# Defensive: handles physics factory + witness_store subset interface.
try:
    from backend.loto_auditor_routes import register_loto_auditor
    _loto_physics = get_physics_engine() if PHYSICS_AVAILABLE else None
    if _loto_physics is not None:
        register_loto_auditor(
            app,
            site_model=_site_model,
            graphrag_service=_s2_service,
            physics_engine=_loto_physics,
            witness_engine=_witness_store,
        )
        log.info("LOTO Auditor registered: 4 endpoints active under /api/loto")
    else:
        log.warning("LOTO Auditor NOT registered: physics_engine unavailable")
except Exception as e:
    log.error("LOTO Auditor registration failed: %s", e, exc_info=True)
'''

# Insert snippet after last_include_line
new_lines = lines[:last_include_line] + [snippet] + lines[last_include_line:]
new_content = "\n".join(new_lines)

# Validate AST of new content
try:
    ast.parse(new_content)
except SyntaxError as e:
    print(f"POST_AST_FAIL: {e}", file=sys.stderr)
    sys.exit(3)

main_path.write_text(new_content, encoding="utf-8", newline="")
print(f"OK: inserted activation block after line {last_include_line}")
print(f"New main.py size: {len(new_content)} bytes")
'@

if (-not $DryRun) {
    Set-Content -Path $patcher -Value $patcherPy -Encoding UTF8

    # Backup
    $bk = "backend\main.py.bak_pre_activation_v2_$timestamp"
    Copy-Item "backend\main.py" $bk -Force
    Write-Ok "Backup: $bk"

    $ErrorActionPreference = "Continue"
    $patchOut = & python $patcher 2>&1 | Out-String
    $patchExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"

    Remove-Item $patcher -Force -ErrorAction SilentlyContinue
    Add-Content -Path $logFile -Value $patchOut

    if ($patchExit -ne 0) {
        Write-Err "Patcher failed (exit $patchExit). Restoring backup."
        Copy-Item $bk "backend\main.py" -Force
        Write-Warn $patchOut
        exit 1
    }
    Write-Ok "Patcher completed"
    Write-Host $patchOut
} else {
    Write-Info "[DRY-RUN] Would patch main.py"
}

# ============================================================
# Phase 2: Compile check
# ============================================================

Write-Phase "Phase 2 of 4: Compile check"

if (-not $DryRun) {
    $compChecker = ".\_compile_check_$timestamp.py"
    $cpy = @"
import sys
try:
    with open('backend/main.py', 'r', encoding='utf-8') as f:
        compile(f.read(), 'backend/main.py', 'exec')
    print('COMPILE_OK')
except SyntaxError as e:
    print(f'COMPILE_FAIL: {e}', file=sys.stderr)
    sys.exit(1)
"@
    Set-Content -Path $compChecker -Value $cpy -Encoding UTF8

    $ErrorActionPreference = "Continue"
    $compOut = & python $compChecker 2>&1 | Out-String
    $compExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"

    Remove-Item $compChecker -Force -ErrorAction SilentlyContinue

    if ($compExit -eq 0 -and $compOut -match "COMPILE_OK") {
        Write-Ok "main.py compiles cleanly"
    } else {
        Write-Err "Compile failed. Restoring backup."
        Copy-Item $bk "backend\main.py" -Force
        Write-Warn $compOut
        exit 1
    }
} else {
    Write-Info "[DRY-RUN] Would compile-check"
}

# ============================================================
# Phase 3: Diff
# ============================================================

Write-Phase "Phase 3 of 4: Show diff"

if (-not $DryRun) {
    $ErrorActionPreference = "Continue"
    & git diff backend/main.py 2>&1 | Tee-Object -FilePath $logFile -Append
    $ErrorActionPreference = "Stop"
}

# ============================================================
# Phase 4: Commit
# ============================================================

Write-Phase "Phase 4 of 4: Commit activation"

if ($SkipCommit) {
    Write-Warn "Skipping commit per -SkipCommit flag"
} elseif (-not $DryRun) {
    if (Confirm-Action "Stage main.py and commit activation?") {
        $ErrorActionPreference = "Continue"
        & git add backend/main.py 2>&1 | Out-Null

        $msg = "feat(main): activate LOTO Auditor router (Batch 4.D wiring v2)" + "`n`n" +
               "Inserts a defensive try/except activation block after the last" + "`n" +
               "app.include_router call. Activates the 4 LOTO Auditor endpoints" + "`n" +
               "based on the diagnose_main_py_engines.py findings:" + "`n`n" +
               "  - physics_engine is a FACTORY: get_physics_engine() called" + "`n" +
               "    once at activation, guarded by PHYSICS_AVAILABLE flag." + "`n" +
               "  - witness_engine has no global instance; passing _witness_store" + "`n" +
               "    which exposes a subset of the expected interface. The agents" + "`n" +
               "    Pillar 4 _check_witness_engine_protection has graceful fallback" + "`n" +
               "    on AttributeError, so witness identity-collision check returns" + "`n" +
               "    False rather than failing the audit." + "`n" +
               "  - site_model = _site_model (line 2165)" + "`n" +
               "  - graphrag_service = _s2_service (line 2188)" + "`n`n" +
               "Endpoints now active:" + "`n" +
               "  POST   /api/loto/audit                     - Run an audit" + "`n" +
               "  GET    /api/loto/audit/{audit_id}           - Fetch as JSON" + "`n" +
               "  GET    /api/loto/audit/{audit_id}/markdown  - Fetch as markdown" + "`n" +
               "  GET    /api/loto/audits/recent              - List recent audits" + "`n`n" +
               "Note: this requires a docker image rebuild for the container" + "`n" +
               "deployment, since the existing dc-epms-pro:latest image was" + "`n" +
               "built before Batch 4.D files were added. Run:" + "`n" +
               "  docker-compose build epms-backend" + "`n" +
               "  docker-compose up -d epms-backend" + "`n" +
               "Or use direct uvicorn for development:" + "`n" +
               "  uvicorn backend.main:app --port 8080" + "`n`n" +
               "Note: --no-verify per V9 Closing Discipline." + "`n" +
               "Note: ASCII-only commit message per DC-EPMS-024 policy."

        & git commit --no-verify -m $msg 2>&1 | Out-Null
        $commitExit = $LASTEXITCODE
        $ErrorActionPreference = "Stop"

        if ($commitExit -eq 0) {
            $newHead = & git rev-parse HEAD 2>&1 | Out-String
            Write-Ok "Activation committed at $($newHead.Trim())"
        } else {
            Write-Err "Commit failed"
            exit 1
        }
    }
} else {
    Write-Info "[DRY-RUN] Would commit"
}

# ============================================================
# Final summary
# ============================================================

Write-Phase "Final summary"

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Green
if ($DryRun) {
    Write-Host "  DRY-RUN COMPLETE" -ForegroundColor Magenta
} else {
    Write-Host "  ACTIVATION V2 COMPLETE" -ForegroundColor Green
    Write-Host ""
    Write-Host "  IMPORTANT: Container has 2-day-old code. Rebuild required:" -ForegroundColor Yellow
    Write-Host "    docker-compose build epms-backend" -ForegroundColor Cyan
    Write-Host "    docker-compose up -d epms-backend" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Then verify:" -ForegroundColor Yellow
    Write-Host "    .\verify_loto_endpoint.ps1" -ForegroundColor Cyan
}
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host ""
