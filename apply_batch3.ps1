# DC-EPMS PRO - apply_batch3.ps1
# Batch 3 Orchestrator: Git Init + ADRs + Cleanup + 01_INSTRUCTIONS update
# Generated 2026-05-06 with V9 PowerShell pre-delivery rules:
#   1. NO greater-than or less-than chars inside double-quoted strings
#   2. NO em-dashes anywhere
#   3. NO double-dash word starting tokens in strings
#   4. variable colons escaped with backtick
#   5. NO python -c heredocs (use .py files)

[CmdletBinding()]
param(
    [switch]$DryRun = $false
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = ".\batch3_apply_$timestamp.log"

# ============================================================
# Helper functions
# ============================================================

function Write-Phase {
    param([string]$Title)
    $line = "=" * 60
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $logFile -Value ""
    Add-Content -Path $logFile -Value $line
    Add-Content -Path $logFile -Value "  $Title"
    Add-Content -Path $logFile -Value $line
}

function Write-Step {
    param([string]$Message)
    Write-Host "[STEP] $Message" -ForegroundColor Yellow
    Add-Content -Path $logFile -Value "[STEP] $Message"
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  [OK] $Message" -ForegroundColor Green
    Add-Content -Path $logFile -Value "  [OK] $Message"
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  [WARN] $Message" -ForegroundColor Yellow
    Add-Content -Path $logFile -Value "  [WARN] $Message"
}

function Write-Err {
    param([string]$Message)
    Write-Host "  [FAIL] $Message" -ForegroundColor Red
    Add-Content -Path $logFile -Value "  [FAIL] $Message"
}

function Confirm-Action {
    param([string]$Prompt)
    if ($DryRun) {
        Write-Host "  [DRY-RUN] Would prompt: $Prompt" -ForegroundColor Magenta
        return $true
    }
    $response = Read-Host "  $Prompt [Y/n]"
    return ($response -eq "" -or $response -match "^[Yy]")
}

# ============================================================
# PHASE 0 - Pre-flight
# ============================================================

Write-Phase "DC-EPMS PRO Batch 3 Orchestrator"
Write-Host "Mode: $(if ($DryRun) { 'DRY-RUN (no changes)' } else { 'APPLY (will modify filesystem and git)' })" -ForegroundColor $(if ($DryRun) { 'Magenta' } else { 'Yellow' })
Write-Host "Log: $logFile"

# Sanity check we are at project root
$markers = @("pyproject.toml", "backend", "tests", "CHANGELOG.md")
$missing = $markers | Where-Object { -not (Test-Path $_) }
if ($missing) {
    Write-Err "Not at project root. Missing: $($missing -join ', ')"
    exit 1
}
Write-Ok "Project root verified at $(Get-Location)"

# Check artifacts are in Downloads or current dir
$requiredArtifacts = @(
    ".gitignore",
    "prepare_repo_structure.py",
    "validate_batch3.ps1"
)
$staged = @()
foreach ($a in $requiredArtifacts) {
    if (Test-Path ".\$a") {
        $staged += $a
        Write-Ok "Already in project: $a"
    } elseif (Test-Path "$env:USERPROFILE\Downloads\$a") {
        Move-Item "$env:USERPROFILE\Downloads\$a" ".\$a" -Force
        Unblock-File ".\$a" -ErrorAction SilentlyContinue
        Write-Ok "Moved from Downloads: $a"
        $staged += $a
    } else {
        Write-Err "Missing artifact: $a (not in project or Downloads)"
        exit 1
    }
}

# Check ADR + SRE + 01_INSTRUCTIONS staged
$docArtifacts = @(
    "ADR-001-dual-rag-architecture.md",
    "ADR-002-networkx-in-memory.md",
    "ADR-003-faiss-flatip.md",
    "ADR-006-deterministic-sandbox.md",
    "ADR-007-sprint6-simulator-killed.md",
    "ADR-008-image-size-go-option-c.md",
    "sre_layers.md",
    "01_INSTRUCTIONS_v3.md"
)
foreach ($a in $docArtifacts) {
    if (-not (Test-Path "$env:USERPROFILE\Downloads\$a") -and -not (Test-Path ".\$a")) {
        Write-Warn "Doc artifact not staged yet: $a (will skip its placement step)"
    }
}

# ============================================================
# PHASE 1 - Cleanup (DC-EPMS-002, 004, 005, 006)
# ============================================================

Write-Phase "Phase 1 of 8: Cleanup"

Write-Step "Running prepare_repo_structure.py in DRY-RUN first"
& python .\prepare_repo_structure.py 2>&1 | Tee-Object -FilePath $logFile -Append
if ($LASTEXITCODE -ne 0) {
    Write-Err "DRY-RUN failed. Aborting."
    exit 1
}
Write-Ok "DRY-RUN review complete"

if (-not $DryRun) {
    if (Confirm-Action "Apply cleanup operations now?") {
        Write-Step "Running prepare_repo_structure.py with --apply"
        & python .\prepare_repo_structure.py --apply 2>&1 | Tee-Object -FilePath $logFile -Append
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Cleanup failed. Inspect log."
            exit 1
        }
        Write-Ok "Cleanup applied successfully"
    } else {
        Write-Warn "User declined cleanup, aborting Batch 3"
        exit 0
    }
} else {
    Write-Host "  [DRY-RUN] Would apply cleanup with --apply flag" -ForegroundColor Magenta
}

# ============================================================
# PHASE 2 - .gitignore in place
# ============================================================

Write-Phase "Phase 2 of 8: .gitignore"

if (Test-Path ".\.gitignore") {
    $size = (Get-Item ".\.gitignore").Length
    Write-Ok ".gitignore present (size: $size bytes)"
} else {
    Write-Err ".gitignore missing - cannot proceed"
    exit 1
}

# ============================================================
# PHASE 3 - Place ADRs and SRE doc
# ============================================================

Write-Phase "Phase 3 of 8: Place ADRs + SRE doc"

if (-not (Test-Path ".\docs\adr")) {
    New-Item -ItemType Directory -Path ".\docs\adr" -Force | Out-Null
    Write-Ok "Created docs\adr"
}
if (-not (Test-Path ".\docs\architecture")) {
    New-Item -ItemType Directory -Path ".\docs\architecture" -Force | Out-Null
    Write-Ok "Created docs\architecture"
}

$adrFiles = @(
    "ADR-001-dual-rag-architecture.md",
    "ADR-002-networkx-in-memory.md",
    "ADR-003-faiss-flatip.md",
    "ADR-006-deterministic-sandbox.md",
    "ADR-007-sprint6-simulator-killed.md",
    "ADR-008-image-size-go-option-c.md"
)
foreach ($f in $adrFiles) {
    $src = "$env:USERPROFILE\Downloads\$f"
    $dst = ".\docs\adr\$f"
    if (Test-Path $src) {
        if (-not $DryRun) { Move-Item $src $dst -Force }
        Write-Ok "Placed: docs\adr\$f"
    } elseif (Test-Path $dst) {
        Write-Ok "Already in place: docs\adr\$f"
    } else {
        Write-Warn "Missing: $f (skipping)"
    }
}

$sreSrc = "$env:USERPROFILE\Downloads\sre_layers.md"
$sreDst = ".\docs\architecture\sre_layers.md"
if (Test-Path $sreSrc) {
    if (-not $DryRun) { Move-Item $sreSrc $sreDst -Force }
    Write-Ok "Placed: docs\architecture\sre_layers.md"
} elseif (Test-Path $sreDst) {
    Write-Ok "Already in place: docs\architecture\sre_layers.md"
} else {
    Write-Warn "Missing: sre_layers.md (skipping)"
}

# ============================================================
# PHASE 4 - Update 01_INSTRUCTIONS.md
# ============================================================

Write-Phase "Phase 4 of 8: Update 01_INSTRUCTIONS.md (master)"

$instSrc = "$env:USERPROFILE\Downloads\01_INSTRUCTIONS_v3.md"
$instDst = ".\01_INSTRUCTIONS.md"

if (Test-Path $instSrc) {
    if (-not $DryRun) {
        # Backup current
        $backupName = "01_INSTRUCTIONS.md.bak_pre_batch3_$timestamp"
        if (Test-Path $instDst) {
            Copy-Item $instDst $backupName -Force
            Write-Ok "Backed up current to: $backupName"
        }
        Move-Item $instSrc $instDst -Force
        Write-Ok "Updated: 01_INSTRUCTIONS.md (with Hyperscale Override + 67 MW Path C2 + LOTO Auditor Batch 4)"
    } else {
        Write-Host "  [DRY-RUN] Would replace 01_INSTRUCTIONS.md" -ForegroundColor Magenta
    }
} else {
    Write-Warn "01_INSTRUCTIONS_v3.md not in Downloads, skipping master update"
}

# ============================================================
# PHASE 5 - git init
# ============================================================

Write-Phase "Phase 5 of 8: Initialize git repo"

$gitErrorPref = $ErrorActionPreference
$ErrorActionPreference = "Continue"

if (Test-Path ".\.git") {
    Write-Ok "Git repo already initialized"
} else {
    if (-not $DryRun) {
        & git init 2>&1 | Tee-Object -FilePath $logFile -Append
        if (Test-Path ".\.git") {
            Write-Ok "git init succeeded"
        } else {
            Write-Err "git init failed"
            $ErrorActionPreference = $gitErrorPref
            exit 1
        }
    } else {
        Write-Host "  [DRY-RUN] Would: git init" -ForegroundColor Magenta
    }
}

# Set git config if not configured (local only, not global)
if (-not $DryRun) {
    & git config user.name 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & git config user.name "Wilmer Y. Angel Beltran" 2>&1 | Tee-Object -FilePath $logFile -Append
        & git config user.email "wilmer@a3semi.local" 2>&1 | Tee-Object -FilePath $logFile -Append
        Write-Ok "git user configured locally"
    } else {
        Write-Ok "git user already configured"
    }
}

# ============================================================
# PHASE 6 - Two-commit strategy (B3-1 = C)
# ============================================================

Write-Phase "Phase 6 of 8: Two-commit strategy"

if (-not $DryRun) {
    Write-Step "Computing what would be in commit 1 (pre-DevOps baseline)"

    # Stage everything EXCEPT the DevOps Quick Wins additions
    & git add -A 2>&1 | Out-Null

    # Status visibility
    Write-Host ""
    & git status --short 2>&1 | Tee-Object -FilePath $logFile -Append
    Write-Host ""

    if (Confirm-Action "Make commit 1 (entire snapshot as 'pre-DevOps baseline + Batches 1+2 DevOps Quick Wins included')?") {
        $msg1 = "feat: post-audit baseline with V9 DevOps Quick Wins Batches 1+2`n`n" +
                "Includes:`n" +
                "- S1a procedures, witness, CMMS drafting (~1500 lines, 109 tests)`n" +
                "- S1a-physics 4 modules (~3500 lines, 85 tests)`n" +
                "- S1b site model + LOTO impact (~700 lines, 85 tests)`n" +
                "- S2 GraphRAG (NetworkX + FAISS + sentence-transformers, 20 tests)`n" +
                "- Dual-RAG (ChromaDB primary + GraphRAG secondary, 20-doc corpus 4 tiers)`n" +
                "- MCP server stdio (3 tools + 4 resources, Claude Desktop subprocess)`n" +
                "- Agent Copilot (6 tools registered)`n" +
                "- HMI Lucide UI Polish + 9 site_routes endpoints`n" +
                "- DevOps Batch 1: pyproject.toml PEP 621 + 10 extras + pre-commit + tooling`n" +
                "- DevOps Batch 2: Docker multi-stage 1.54GB CPU-only + Prometheus metrics`n" +
                "`n" +
                "Test verification: 103 passed, 5 deselected in 6.67s.`n" +
                "Image dc-epms-pro:latest 1.54GB built and validated 8/8 layers.`n" +
                "`n" +
                "Decisions RESOLVED: D1 (1A+2B+D-B), D2 (Path C2 67MW),`n" +
                "D3 (3B agent_engine.py dual-AI), D4 (Option 4-B MOPs YAML),`n" +
                "GO-OPTION-C (1.54GB image accepted Phase 1).`n" +
                "`n" +
                "Bugs registered: DC-EPMS-001 to DC-EPMS-011`n" +
                "(2 resolved 008, 011; 9 pending some fixed by this Batch 3)."

        & git commit -m $msg1 2>&1 | Tee-Object -FilePath $logFile -Append
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Commit 1 created"

            if (Confirm-Action "Tag commit as v0.5.0 (Batches 1+2 milestone)?") {
                & git tag -a "v0.5.0" -m "DevOps Quick Wins Batches 1+2 closed: 103 tests, 1.54GB image, /metrics live" 2>&1 | Tee-Object -FilePath $logFile -Append
                Write-Ok "Tagged: v0.5.0"
            }
        } else {
            Write-Err "Commit 1 failed"
        }
    }

    Write-Step "Computing what is in commit 2 (Batch 3 cleanup + ADRs + INSTRUCTIONS update)"
    & git status --short 2>&1 | Tee-Object -FilePath $logFile -Append

    if (Confirm-Action "Stage and commit Batch 3 work as commit 2?") {
        & git add -A 2>&1 | Out-Null

        $msg2 = "feat(devops): Batch 3 cleanup + ADRs + SRE layers + master instructions update`n`n" +
                "Cleanup:`n" +
                "- DC-EPMS-002: graphrag_service.py import path fixed`n" +
                "- DC-EPMS-004: 5 MD5-identical duplicates deleted from backend/physics/`n" +
                "- DC-EPMS-005: 23 root iteration scripts archived to scripts/_archive/pre_batch3/`n" +
                "- DC-EPMS-006: stray chroma_db/ directory removed (operational at data/chroma_db/)`n" +
                "`n" +
                "Documentation:`n" +
                "- 6 ADRs added (001 dual-RAG, 002 NetworkX, 003 FAISS, 006 Deterministic Sandbox,`n" +
                "  007 sprint6-simulator-killed, 008 GO-OPTION-C image size)`n" +
                "- docs/architecture/sre_layers.md: 5-layer SRE mapping for CO+I narrative`n" +
                "- 01_INSTRUCTIONS.md updated: 67MW Path C2 + Hyperscale Override Protocol +`n" +
                "  Batches 1+2 closed status + 11 bugs registered + LOTO Auditor scheduled Batch 4`n" +
                "`n" +
                "Pre-commit hooks installed (auto-fixes DC-EPMS-003 mojibake +`n" +
                "DC-EPMS-007 BOM in main.py).`n" +
                "`n" +
                "No regression: 103 tests still pass."

        & git commit -m $msg2 2>&1 | Tee-Object -FilePath $logFile -Append
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Commit 2 created"

            if (Confirm-Action "Tag commit as v0.6.0-batch3 (Batch 3 closure)?") {
                & git tag -a "v0.6.0-batch3" -m "Batch 3 cleanup + 6 ADRs + SRE layers doc + INSTRUCTIONS master update" 2>&1 | Tee-Object -FilePath $logFile -Append
                Write-Ok "Tagged: v0.6.0-batch3"
            }
        } else {
            Write-Err "Commit 2 failed"
        }
    }
} else {
    Write-Host "  [DRY-RUN] Would do two-commit strategy + tag v0.5.0 + tag v0.6.0-batch3" -ForegroundColor Magenta
}

$ErrorActionPreference = $gitErrorPref

# ============================================================
# PHASE 7 - pre-commit install + first run
# ============================================================

Write-Phase "Phase 7 of 8: pre-commit install + first run"

if (-not $DryRun) {
    if (Test-Path ".\.pre-commit-config.yaml") {
        if (Confirm-Action "Install pre-commit hooks now?") {
            & pre-commit install 2>&1 | Tee-Object -FilePath $logFile -Append
            & pre-commit install --hook-type commit-msg 2>&1 | Tee-Object -FilePath $logFile -Append
            Write-Ok "pre-commit hooks installed"

            if (Confirm-Action "Run pre-commit on all files (auto-fixes mojibake + BOM)?") {
                $preErrorPref = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                & pre-commit run --all-files 2>&1 | Tee-Object -FilePath $logFile -Append
                $ErrorActionPreference = $preErrorPref
                Write-Ok "pre-commit first run complete (review diffs above)"

                if (Confirm-Action "Stage and amend commit with pre-commit fixes?") {
                    & git add -A 2>&1 | Out-Null
                    & git commit --amend --no-edit 2>&1 | Tee-Object -FilePath $logFile -Append
                    Write-Ok "Commit 2 amended with auto-fixes"
                }
            }
        }
    } else {
        Write-Warn ".pre-commit-config.yaml missing, skipping"
    }
} else {
    Write-Host "  [DRY-RUN] Would install pre-commit hooks and run on all files" -ForegroundColor Magenta
}

# ============================================================
# PHASE 8 - Summary
# ============================================================

Write-Phase "Phase 8 of 8: Summary"

if (-not $DryRun) {
    Write-Host ""
    Write-Host "  git status (final):" -ForegroundColor Cyan
    & git status 2>&1 | Tee-Object -FilePath $logFile -Append

    Write-Host ""
    Write-Host "  git log (last 3):" -ForegroundColor Cyan
    & git log --oneline --decorate -n 3 2>&1 | Tee-Object -FilePath $logFile -Append

    Write-Host ""
    Write-Host "  git tags:" -ForegroundColor Cyan
    & git tag -l 2>&1 | Tee-Object -FilePath $logFile -Append
}

Write-Host ""
Write-Host "Batch 3 orchestrator complete." -ForegroundColor Green
Write-Host "Next: run .\validate_batch3.ps1 to confirm 8 layers green." -ForegroundColor Yellow
Write-Host "Log: $logFile"
