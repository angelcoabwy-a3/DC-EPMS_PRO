# DC-EPMS PRO - a3semi Edge Operations Platform

**A-Cubed Semiconductor Systems Inc. (a3semi)** - proprietary EPMS for
critical semiconductor infrastructure and NVIDIA Blackwell Fleet management.

Deployed at **A3-Alpha Toronto Area** (Tier IV 2N, 40 MW,
118 x NVIDIA GB200 NVL72 Blackwell racks).

**Version 1.0** — includes Sovereign Operator features (dual utility 2N,
What-If simulation, AI Mission Control) and MCP server for Claude Desktop
integration. See `DEMO_SCRIPT.md` for the Microsoft CO+I demo flow.

---

## Quick start — 3 tiers

### Tier 1 — Minimal (UI preview, ~60 MB, 2 min)
Just enough to see the dashboard and test the SPA.
```powershell
cd DC-EPMS_PRO
.\scripts\start.ps1 -Install -Minimal
.\scripts\start.ps1
```
Browse → `http://localhost:8080`. Status pills all show down (expected). Layout, KPIs (empty), PDF button work.

### Tier 2 — Full stack (~800 MB, 8 min)
PostgreSQL + TimescaleDB + ChromaDB RAG + all features.
```powershell
# Requires Docker Desktop running
cd DC-EPMS_PRO
.\scripts\start.ps1 -Install
.\scripts\start.ps1
```
Opens dashboard with real PostgreSQL and RAG. Status pills green.

### Tier 3 — Full + simulator (demo mode)
Continuously generates telemetry and incidents for demo.
```powershell
.\scripts\start.ps1 -Simulator -Scenario chillerFail
```
Dashboard fills with live data. Advisory banners appear when PUE > 1.40.

---

## Architecture

```
                Frontend SPA (index.html)
                  - SSE: token-by-token agent response
                  - SSE: telemetry every 5s
                  - Chart.js PUE trend (60 samples)
                  - Voice stub (Riva-ready)
                  - Shift report PDF download
                         |
                         | HTTP/SSE :8080
                         v
                FastAPI (backend/main.py)
                  - /agent/stream   NeMo -> Gemma/Claude
                  - /api/telemetry  PostgreSQL
                  - /api/rag/query  ChromaDB
                  - /api/shift/report  reportlab PDF
                  - /lm/*           LM Studio proxy
                         |
         +---------------+---------------+
         v               v               v
      Postgres       ChromaDB        LM Studio
      + Timescale    + MiniLM        Gemma 4 + GPU
      :5432          (local)         :1234
```

---

## Project layout

```
DC-EPMS_PRO/
  backend/
    main.py              FastAPI orchestrator (556 lines)
    agent_engine.py      NeMo Guardrails + Gemma/Claude stream
    database.py          asyncpg + TimescaleDB hypertable
    rag_service.py       ChromaDB thread-safe
    shift_report.py      reportlab PDF generator
  frontend/
    index.html           Clean SPA (158 lines)
    assets/
      app.css            Industrial styling (562 lines)
      app.js             SSE + Chart.js + voice (555 lines)
  config/
    config.yml           NeMo Guardrails rails
    actions.co           Colang dialog flows
    .env.example         Credentials template
  scripts/
    start.ps1            One-click Windows launcher
    seed_rag.py          Index 14 Schneider + ASHRAE + IEC docs
    simulator.py         Physics-based telemetry generator
    migrate_from_legacy.py
  tests/
    test_smoke.py        8 pytest validations (all pass)
  docker-compose.yml     PostgreSQL + backend
  Dockerfile             Production container
  requirements-minimal.txt    UI only (60 MB)
  requirements-full.txt       Full stack (800 MB)
  requirements.txt            Alias -> requirements-full
```

---

## API Reference

### Agent streaming
`POST /agent/stream` — SSE token stream with NeMo rails + RAG grounding
```json
{ "query": "...", "model_hint": "auto|gemma|claude", "max_tokens": 500 }
```

### Telemetry
- `POST /api/telemetry` — Write point (fires PUE advisory if > 1.40)
- `GET /api/telemetry?limit=60` — Recent points
- `GET /api/telemetry/stream` — SSE push every 5s

### Incidents (SQL-injection safe, JSONB validated)
- `POST /api/incidents` — Create with physics_json
- `GET /api/incidents?limit=50` — Recent

### RAG
- `POST /api/rag/query` — Semantic search (cosine similarity)
- `GET /api/rag/docs` — Indexed count

### LM Studio proxy (CORS bypass, uses 127.0.0.1 not localhost)
- `GET /lm/v1/models`
- `POST /lm/v1/chat/completions`

### Reports
`POST /api/shift/report` — Generate PDF with telemetry + incidents + open items

### Ops
`GET /api/health` — Unified: Postgres + ChromaDB + Gemma + GPU

### Voice (Riva-ready stub)
`POST /api/voice/transcribe` — WSL2 integration point

---

## Standards

- CSA Z462 / NFPA 70E — Arc flash Cat 2, LOTO
- NFPA 110 Type 10 — Emergency power (10-second transfer)
- ASHRAE A2 — Thermal envelope 10-35C
- IEC 62443 — OT cybersecurity SL-0 through SL-3
- ISO 22301 — P1 RTO=15min RPO=0
- Schneider WP122 — Critical power and cooling

## Hardware model

- 118 x NVIDIA GB200 NVL72 Blackwell racks @ 142 kW DLC = 16,756 kW nominal
- Tier IV 2N 40 MW total facility capacity
- DLC inlet 18C, outlet max 45C, flow 40 L/min glycol

## Author

Wilmer Angel — CET Night Shift Candidate, A-Cubed Semiconductor Systems

---

## Claude Desktop / MCP integration

DC-EPMS PRO ships with a Model Context Protocol (MCP) server that exposes
the live facility state to Claude Desktop and other MCP clients.

### Setup

1. Copy the example config:
   ```powershell
   copy config\claude_desktop_config.example.json `
        $env:APPDATA\Claude\claude_desktop_config.json
   ```

2. Edit the new file and replace `{PROJECT_PATH}` with your absolute path
   (e.g., `C:/dev/DC-EPMS_PRO`). Use forward slashes.

3. Restart Claude Desktop.

### What's exposed

**4 resources** (read-only data):
- `a3semi://telemetry/current` — latest telemetry snapshot
- `a3semi://physics/site-health` — Site Health Index + per-module health
- `a3semi://scenarios/list` — 10 failure scenarios catalog
- `a3semi://incidents/recent` — last 20 incidents from PostgreSQL

**3 tools** (callable functions):
- `simulate_failure(scenario_id, horizon_s)` — physics-engine simulation
- `read_bms_tag(tag_id)` — read any BACnet/Modbus tag
- `list_bms_tags(category?)` — browse 42 tags by category

### Test the MCP server standalone

```powershell
cd DC-EPMS_PRO
python backend\mcp_server.py
# Type a JSON-RPC request:
#   {"jsonrpc":"2.0","id":1,"method":"resources/list","params":{}}
# Then press Enter; the server replies with the resource list.
# Ctrl+C to exit.
```

