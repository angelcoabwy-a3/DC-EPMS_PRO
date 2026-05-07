# Fase 3 Deploy - Tier-Aware RAG + Training Manual

## What's new in this package

### Corpus (20 professional documents, 4 tiers)
- **Tier 1 (5 docs)** Safety: LOTO, arc flash, confined space, fire suppression, EPO
- **Tier 2 (5 docs)** Vendor: Schneider WP122/Galaxy VX, York YZ chiller, Starline busway, NVIDIA GB200 NVL72
- **Tier 3 (4 docs)** Standards: ASHRAE A2, IEC 62443, ISO 22301, Newton thermal model
- **Tier 4 (6 docs)** a3semi-specific MOPs/EOPs: UPS/Chiller/PDU/Generator/VESDA PM, EOP-003 emergency cooling

Each document has YAML front-matter for metadata-driven retrieval.

### Backend changes
- `backend/rag_service.py` - **rewritten** with tier-based priority boosting
  - Detects safety keywords (LOTO, arc flash, PPE, EPO, fire, etc.)
  - Boosts Tier 1 results +0.30 for safety queries, +0.10 otherwise
  - Boosts Tier 2 (vendor) results +0.05
  - Accepts metadata filter: `tier_filter`, `min_priority`
  - New `build_context()` method formats results with citations

- `backend/agent_engine.py` - **system prompt updated** with:
  - Explicit 4-tier knowledge base reference
  - MANDATORY safety citation protocol (cite Tier 1 first for safety queries)
  - Two-person rule reference for energized work
  - Citation format: `[Tier X: doc_id]`

### New scripts
- `scripts/seed_rag_v2.py` - walks `data/corpus/**/*.md`, parses YAML, indexes with metadata
  - Usage: `python scripts/seed_rag_v2.py --clean` (fresh index)
  - Usage: `python scripts/seed_rag_v2.py --tier 1` (only safety)
  - Usage: `python scripts/seed_rag_v2.py --test-query "arc flash PPE"` (test after indexing)

- `scripts/generate_training_manual.py` - generates `a3semi_CET_Training_Manual.pdf`
  - 109-page professional PDF with a3semi cyan branding
  - Cover, executive summary, TOC, all 20 docs organized by tier
  - Color-coded tier sections, industrial dark theme

## Deploy sequence

### 1. Backup current state (optional)
```powershell
cd C:\dev\DC-EPMS_PRO
Copy-Item -Recurse . "..\DC-EPMS_PRO_backup_$(Get-Date -Format 'yyyyMMdd')"
```

### 2. Extract the new package
```powershell
cd C:\dev\DC-EPMS_PRO
Expand-Archive "$env:USERPROFILE\Downloads\DC-EPMS_PRO.zip" -DestinationPath . -Force
```

### 3. Install reportlab for the PDF generator
```powershell
.\.venv\Scripts\activate
pip install reportlab
```

### 4. Stop the backend if running (Ctrl+C)

### 5. Re-seed ChromaDB with the new tier-aware corpus
```powershell
python scripts\seed_rag_v2.py --clean
```

Expected output:
```
Found 20 markdown files in .../data/corpus
Indexed: 20 / 20
By tier: T1=5 T2=5 T3=4 T4=6
Collection size: 20
```

### 6. Test retrieval with a safety query
```powershell
python scripts\seed_rag_v2.py --test-query "What PPE for arc flash on 480V panel?"
```

You should see Tier 1 (T1-SAF-ARC-002) at the top with `boost=+0.30`.

### 7. (Optional) Generate the CET Training Manual PDF
```powershell
python scripts\generate_training_manual.py
```

The PDF will be written to `C:\dev\DC-EPMS_PRO\a3semi_CET_Training_Manual.pdf`.

### 8. Start the backend
```powershell
python backend\main.py
```

Verify the dashboard at http://localhost:8080 shows:
- **RAG pill**: 20 docs (up from 14)
- **Agent responses** now include `[Tier X: doc_id]` citations

### 9. Run the simulator to generate traffic
```powershell
python scripts\simulator.py --scenario chillerFail --duration 60 --incidents
```

## Architecture notes

### Tier boost math
When a query contains safety keywords (see `SAFETY_KEYWORDS` in `rag_service.py`):

| Tier | Base similarity | Boost | Final score |
|------|-----------------|-------|-------------|
| 1    | 0.75            | +0.30 | 1.05 (ceiling effect)|
| 2    | 0.80            | +0.05 | 0.85         |
| 3    | 0.85            | 0     | 0.85         |
| 4    | 0.70            | 0     | 0.70         |

This ensures Tier 1 safety docs are retrieved even when their semantic
similarity is slightly lower than Tier 2/3/4 equivalents.

### Safety keyword list
Queries trigger safety boost when they contain any of:
- LOTO, lockout, tagout
- arc flash, electrocution, shock, PPE
- confined space, EPO, emergency power off
- fire, smoke, suppression, VESDA, evacuation
- NFPA 70E, CSA Z462

### Agent prompt enforcement
The system prompt explicitly instructs the LLM to:
1. Cite Tier 1 safety doc ID FIRST when query involves safety
2. Never provide operational guidance before safety framing
3. Explicitly state PPE requirements for electrical work
4. Reference two-person rule for energized work

## For your Microsoft CET portfolio

The `a3semi_CET_Training_Manual.pdf` demonstrates:
- **Domain expertise** - 20 professional procedures citing CSA Z462, NFPA 70E/110/72/2001, ASHRAE A2, IEC 62443, ISO 22301, AHRI 550/590, Schneider WP122
- **Systems thinking** - procedures cross-reference each other (LOTO referenced by UPS MOP, EPO referenced by cooling EOP)
- **Facility specificity** - every procedure is tailored to A3-Alpha Toronto (Tier IV 2N, 40 MW, 118 Blackwell racks)
- **Standards compliance** - every doc has traceable standard references
- **Operational maturity** - MOP/EOP framework with pre-work, hazards, step-by-step, acceptance criteria, failure modes

This is a tangible artifact you can attach to a Microsoft interview as
evidence of CET capability beyond theoretical knowledge.
