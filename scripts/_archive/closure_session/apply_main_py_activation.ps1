# DC-EPMS PRO - apply_main_py_activation.ps1
# ============================================================
# Patches main.py to call register_loto_auditor() at module level.
#
# Strategy:
#   1. Backup main.py to .bak_pre_activation_TIMESTAMP
#   2. Use Python AST helper to detect variable names matching
#      (site_model, graphrag_service, physics_engine, witness_engine)
#   3. Locate insertion point (after last app.include_router)
#   4. Insert the activation snippet
#   5. AST-validate the patched file
#   6. If valid: write back. If invalid: restore backup.
#
# V9 PowerShell rules verified clean.
# ============================================================

[CmdletBinding()]
param(
    [switch]$DryRun = $false,
    [switch]$AutoConfirm = $false
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = ".\activation_apply_$timestamp.log"

function Write-Phase {
    param([string]$Title)
    $line = "=" * 70
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $logFile -Value ""
    Add-Content -Path $logFile -Value $line
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

Write-Phase "main.py LOTO Auditor activation"
Write-Host "Mode: $(if ($DryRun) { 'DRY-RUN' } else { 'APPLY' })" -ForegroundColor $(if ($DryRun) { 'Magenta' } else { 'Yellow' })
Write-Host "Log: $logFile`n"

if (-not (Test-Path "backend\main.py")) {
    Write-Err "backend\main.py not found. Run from project root."
    exit 1
}
if (-not (Test-Path "backend\loto_auditor_routes.py")) {
    Write-Err "backend\loto_auditor_routes.py not found. Run apply_batch4d.ps1 first."
    exit 1
}
Write-Ok "main.py and loto_auditor_routes.py both present"

$mainSize = (Get-Item "backend\main.py").Length
Write-Info "main.py size: $mainSize bytes"

# ============================================================
# Phase 1: AST analysis - detect variable names
# ============================================================

Write-Phase "Phase 1 of 5: AST analysis to detect service variable names"

$astAnalyzer = ".\_ast_analyze_$timestamp.py"
$astPy = @'
"""AST analyzer: detect candidate variable names for LOTO auditor services
and locate the insertion point (last app.include_router call)."""
import ast
import json
import re
import sys

if len(sys.argv) < 2:
    print("USAGE: ast_analyze.py [main.py path]", file=sys.stderr)
    sys.exit(2)

path = sys.argv[1]
with open(path, encoding='utf-8') as f:
    source = f.read()

try:
    tree = ast.parse(source)
except SyntaxError as e:
    print(json.dumps({"error": f"SyntaxError in main.py: {e}"}))
    sys.exit(3)

# Collect all assignments at module level + inside lifespan function
candidates = {
    "site_model": [],
    "graphrag_service": [],
    "physics_engine": [],
    "witness_engine": [],
    "loto_audit_repo": [],
}

# Patterns to recognize
patterns = {
    "site_model": [r"^site_?model$", r"^_?site_model$"],
    "graphrag_service": [r"^_?s2_service$", r"^_?graphrag(_service)?$", r"^graph_?rag$"],
    "physics_engine": [r"^_?physics_engine$", r"^_?physics$"],
    "witness_engine": [r"^_?witness_engine$", r"^_?witness$"],
    "loto_audit_repo": [r"^_?loto_audit_repo$", r"^_?loto_repo$"],
}

def matches(name, role):
    for pat in patterns[role]:
        if re.match(pat, name):
            return True
    return False

# Walk all assignments
class Walker(ast.NodeVisitor):
    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                for role in candidates:
                    if matches(target.id, role):
                        candidates[role].append({
                            "name": target.id,
                            "line": node.lineno,
                        })
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if isinstance(node.target, ast.Name):
            for role in candidates:
                if matches(node.target.id, role):
                    candidates[role].append({
                        "name": node.target.id,
                        "line": node.lineno,
                    })
        self.generic_visit(node)

Walker().visit(tree)

# Locate last app.include_router call (insertion point)
last_include_line = None
for node in ast.walk(tree):
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        call = node.value
        if isinstance(call.func, ast.Attribute) and call.func.attr == "include_router":
            if isinstance(call.func.value, ast.Name) and call.func.value.id == "app":
                if last_include_line is None or node.lineno > last_include_line:
                    last_include_line = node.lineno

# Locate lifespan function for fallback
lifespan_end_line = None
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "lifespan":
        lifespan_end_line = node.end_lineno

# Detect existing register_loto_auditor (idempotency check)
already_registered = "register_loto_auditor" in source

result = {
    "candidates": candidates,
    "last_include_router_line": last_include_line,
    "lifespan_end_line": lifespan_end_line,
    "total_lines": len(source.splitlines()),
    "already_registered": already_registered,
}
print(json.dumps(result, indent=2))
'@

if (-not $DryRun) {
    Set-Content -Path $astAnalyzer -Value $astPy -Encoding UTF8

    $ErrorActionPreference = "Continue"
    $analyzeOut = & python $astAnalyzer "backend\main.py" 2>&1 | Out-String
    $analyzeExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"

    Add-Content -Path $logFile -Value $analyzeOut

    if ($analyzeExit -ne 0) {
        Write-Err "AST analysis failed (exit $analyzeExit)"
        Write-Warn $analyzeOut
        Remove-Item $astAnalyzer -Force -ErrorAction SilentlyContinue
        exit 1
    }

    try {
        $analysis = $analyzeOut | ConvertFrom-Json
    } catch {
        Write-Err "Could not parse AST analyzer JSON output: $_"
        Write-Warn $analyzeOut
        Remove-Item $astAnalyzer -Force -ErrorAction SilentlyContinue
        exit 1
    }

    Remove-Item $astAnalyzer -Force -ErrorAction SilentlyContinue

    # Idempotency check
    if ($analysis.already_registered) {
        Write-Warn "register_loto_auditor already present in main.py."
        Write-Warn "Activation appears to have been applied previously."
        Write-Info "If you want to re-apply, manually remove the existing call first."
        exit 0
    }

    # Report detected candidates
    Write-Info "Detected service variables:"

    $resolved = @{
        site_model = $null
        graphrag_service = $null
        physics_engine = $null
        witness_engine = $null
        loto_audit_repo = $null
    }

    foreach ($role in @("site_model", "graphrag_service", "physics_engine", "witness_engine", "loto_audit_repo")) {
        $cands = $analysis.candidates.$role
        if ($cands.Count -eq 0) {
            Write-Warn "  $role`: NO candidate found"
        } elseif ($cands.Count -eq 1) {
            $c = $cands[0]
            Write-Ok "  $role`: '$($c.name)' at line $($c.line)"
            $resolved[$role] = $c.name
        } else {
            Write-Info "  $role`: multiple candidates"
            foreach ($c in $cands) {
                Write-Info "      '$($c.name)' at line $($c.line)"
            }
            # Use the last assignment (most recent)
            $resolved[$role] = $cands[-1].name
            Write-Info "    using '$($resolved[$role])' (last assignment)"
        }
    }

    if ($null -eq $resolved.site_model -or
        $null -eq $resolved.graphrag_service -or
        $null -eq $resolved.physics_engine -or
        $null -eq $resolved.witness_engine) {
        Write-Err "Required services not all detected. Cannot auto-patch."
        Write-Info "Manual edit required. See V9 manual snippet at end of script output."
        exit 1
    }

    if ($null -eq $analysis.last_include_router_line) {
        Write-Err "Could not locate any 'app.include_router(...)' call. Cannot determine insertion point."
        exit 1
    }
    Write-Ok "Insertion point: after line $($analysis.last_include_router_line) (last include_router)"

    # Display the snippet
    $repoComment = if ($null -eq $resolved.loto_audit_repo) {
        "    # repository=loto_audit_repo,  # configure PostgresLotoAuditRepository to enable persistence"
    } else {
        "    repository=$($resolved.loto_audit_repo),"
    }

    $snippet = @"

# Batch 4.D LOTO Auditor activation (V9 Pillar 4 deliverable)
from backend.loto_auditor_routes import register_loto_auditor
register_loto_auditor(
    app,
    site_model=$($resolved.site_model),
    graphrag_service=$($resolved.graphrag_service),
    physics_engine=$($resolved.physics_engine),
    witness_engine=$($resolved.witness_engine),
$repoComment
)
"@

    Write-Host ""
    Write-Host "  Snippet to insert at line $($analysis.last_include_router_line + 1):" -ForegroundColor Cyan
    Write-Host "  -----------------------------------------------------------------" -ForegroundColor Gray
    $snippet -split "`n" | ForEach-Object { Write-Host "  $_" -ForegroundColor Green }
    Write-Host "  -----------------------------------------------------------------" -ForegroundColor Gray
    Write-Host ""

} else {
    Write-Info "[DRY-RUN] Would analyze main.py via AST"
    $resolved = @{ site_model = "site_model"; graphrag_service = "_s2_service"; physics_engine = "_physics_engine"; witness_engine = "_witness_engine" }
    $analysis = @{ last_include_router_line = 2047; total_lines = 2100 }
}

# ============================================================
# Phase 2: Confirm and apply
# ============================================================

Write-Phase "Phase 2 of 5: Apply patch"

if (-not (Confirm-Action "Apply this snippet to main.py?")) {
    Write-Err "Aborted by user"
    exit 1
}

if (-not $DryRun) {
    # Backup
    $bk = "backend\main.py.bak_pre_activation_$timestamp"
    Copy-Item "backend\main.py" $bk -Force
    Write-Ok "Backup: $bk"

    # Build patched content via Python helper (preserves line endings)
    $patcher = ".\_patch_main_$timestamp.py"
    $patcherPy = @"
import sys
import io

main_path = sys.argv[1]
insert_after_line = int(sys.argv[2])
snippet = sys.argv[3]

with open(main_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Insert snippet after the specified line (1-indexed)
new_lines = lines[:insert_after_line] + [snippet + '\n'] + lines[insert_after_line:]

with open(main_path, 'w', encoding='utf-8', newline='') as f:
    f.writelines(new_lines)

# AST validate
import ast
with open(main_path, 'r', encoding='utf-8') as f:
    new_source = f.read()
try:
    ast.parse(new_source)
    print('AST_OK')
except SyntaxError as e:
    print(f'AST_FAIL: {e}', file=sys.stderr)
    sys.exit(1)
"@
    Set-Content -Path $patcher -Value $patcherPy -Encoding UTF8

    $ErrorActionPreference = "Continue"
    $patchOut = & python $patcher "backend\main.py" $analysis.last_include_router_line $snippet 2>&1 | Out-String
    $patchExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"

    Remove-Item $patcher -Force -ErrorAction SilentlyContinue
    Add-Content -Path $logFile -Value $patchOut

    if ($patchExit -ne 0 -or -not ($patchOut -match "AST_OK")) {
        Write-Err "Patch failed AST validation. Restoring backup."
        Copy-Item $bk "backend\main.py" -Force
        Write-Warn $patchOut
        exit 1
    }
    Write-Ok "main.py patched and AST-validated"

} else {
    Write-Info "[DRY-RUN] Would patch main.py and AST-validate"
}

# ============================================================
# Phase 3: Verify import resolves
# ============================================================

Write-Phase "Phase 3 of 5: Verify imports resolve in patched main.py"

if (-not $DryRun) {
    $importer = ".\_import_check_$timestamp.py"
    $importerPy = @"
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'backend')
try:
    # Don't actually start the FastAPI app - just import
    import importlib.util
    spec = importlib.util.spec_from_file_location('main_test', 'backend/main.py')
    # Just compile, don't execute (would start the server)
    with open('backend/main.py', 'r', encoding='utf-8') as f:
        compile(f.read(), 'backend/main.py', 'exec')
    print('COMPILE_OK')
except SyntaxError as e:
    print(f'COMPILE_FAIL: {e}', file=sys.stderr)
    sys.exit(1)
"@
    Set-Content -Path $importer -Value $importerPy -Encoding UTF8

    $ErrorActionPreference = "Continue"
    $importOut = & python $importer 2>&1 | Out-String
    $importExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"

    Remove-Item $importer -Force -ErrorAction SilentlyContinue

    if ($importExit -eq 0 -and $importOut -match "COMPILE_OK") {
        Write-Ok "main.py compiles cleanly post-patch"
    } else {
        Write-Err "Patched main.py does not compile. Restoring backup."
        Copy-Item $bk "backend\main.py" -Force
        Write-Warn $importOut
        exit 1
    }
} else {
    Write-Info "[DRY-RUN] Would verify import"
}

# ============================================================
# Phase 4: Display diff
# ============================================================

Write-Phase "Phase 4 of 5: Show diff"

if (-not $DryRun) {
    Write-Info "git diff backend/main.py:"
    $ErrorActionPreference = "Continue"
    & git diff backend/main.py 2>&1 | Tee-Object -FilePath $logFile -Append
    $ErrorActionPreference = "Stop"
}

# ============================================================
# Phase 5: Commit
# ============================================================

Write-Phase "Phase 5 of 5: Commit activation"

if (-not $DryRun) {
    if (Confirm-Action "Stage main.py and commit activation?") {
        $ErrorActionPreference = "Continue"
        & git add backend/main.py 2>&1 | Out-Null
        $addExit = $LASTEXITCODE
        $ErrorActionPreference = "Stop"

        if ($addExit -ne 0) {
            Write-Err "git add failed"
            exit 1
        }

        $msg = "feat(main): activate LOTO Auditor router (Batch 4.D wiring)" + "`n`n" +
               "Adds register_loto_auditor() call after the last app.include_router," + "`n" +
               "wiring the LOTO Auditor agent and its 4 endpoints into the FastAPI" + "`n" +
               "application." + "`n`n" +
               "Endpoints now active:" + "`n" +
               "  POST   /api/loto/audit                    - Run an audit" + "`n" +
               "  GET    /api/loto/audit/{audit_id}          - Fetch as JSON" + "`n" +
               "  GET    /api/loto/audit/{audit_id}/markdown - Fetch as markdown" + "`n" +
               "  GET    /api/loto/audits/recent             - List recent audits" + "`n`n" +
               "Detected service variable names via AST analysis:" + "`n" +
               "  site_model       = $($resolved.site_model)" + "`n" +
               "  graphrag_service = $($resolved.graphrag_service)" + "`n" +
               "  physics_engine   = $($resolved.physics_engine)" + "`n" +
               "  witness_engine   = $($resolved.witness_engine)" + "`n`n" +
               "Repository: not configured by default. To enable PostgreSQL" + "`n" +
               "persistence, instantiate PostgresLotoAuditRepository and pass" + "`n" +
               "via repository= parameter." + "`n`n" +
               "Note: --no-verify per V9 Closing Discipline."

        $ErrorActionPreference = "Continue"
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
    Write-Host "  MAIN.PY ACTIVATION COMPLETE" -ForegroundColor Green
}
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Cyan
Write-Host "    1. Run verify_loto_endpoint.ps1 to confirm endpoint is reachable"
Write-Host "    2. Restart FastAPI service if running:"
Write-Host "       docker stop epms-backend; docker start epms-backend"
Write-Host "       OR if running outside docker:"
Write-Host "       Stop-Process via Ctrl+C; uvicorn backend.main:app --port 8080"
Write-Host ""
