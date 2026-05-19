# DC-EPMS PRO — Operational Engram (main-context)

> **Purpose.** This file is the single-document operational briefing for any
> future session. It captures the *current* architectural posture, the
> deterministic-AI rules, the testing gates, and the runtime invariants — so
> a fresh session can re-acquire the project compass without re-reading the
> entire codebase. It is intentionally redundant with `CLAUDE.md`; the
> engram is the *state snapshot*, `CLAUDE.md` is the *living guidance file*.
>
> **Last snapshot:** 2026-05-19, HEAD `aa86f8f` (post-v0.12.0, Epic 1 complete).
> **Companion:** `docs/skills/skill-registry.md` (the explicit rule harness).

---

## 1. Project identity

- **Name:** DC-EPMS PRO — Edge Operations Platform for Tier IV AI factories.
- **Maintainer:** Wilmer Y. Angel Beltran · a3semi (A-Cubed Semiconductor Systems Inc.).
- **Target:** the CET (Critical Environment Technician / Critical Engineering) role at Microsoft Cloud Operations + Innovation (CO+I). Interview window: **early August 2026**.
- **Demonstrable scope (single laptop):** A3-Alpha Toronto Area under Path C2.

## 2. Path C2 posture (the physical reference design)

A 67 MW Tier IV AI factory simulated against real specs. Two phases:

- **Phase 1 — Buildings A / B (deployed):** 118 NVIDIA **GB200 NVL72** racks @ 142 kW; **480 VAC trifásico 2N**; UPS Schneider Galaxy VX; chillers York YZ N+1.
- **Phase 2 — Building D (target Q2 2026):** 250 NVIDIA **GB300 NVL144** racks @ 200 kW; upstream **3-phase AC at 35 kVAC** into MV Rectifier; downstream **800 VDC unipolar TN-S** with **SSCB clearing 1-100 µs** per IEC 60947-2 / IEC TR 63282 §5.2; BESS 2.5 MWh; full DLC retrofit to 12 VDC at GPU.
- **Rubin Ultra:** excluded from V9 scope.

**VOCABULARY FENCE (CRITICAL).** "trifásico" applies **only** to AC upstream of the MV Rectifier. The 800 VDC bus is **unipolar (no phases)**. The phrase *"800 VDC trifásico"* is a credibility-destroying error in panel review. Schema names encode polarity: `voltage_v_phase_ab/bc/ca` for AC; `voltage_v_dc_bus` for DC.

## 3. Stable baseline

- **Tag:** **`v0.12.0` "Monolith Eradicated"** (cut 2026-05-19).
- **HEAD at snapshot:** `aa86f8f` — post-release Epic 1 doc-sync.
- **Branch:** `master`, pushed to `https://github.com/angelcoabwy-a3/DC-EPMS_PRO`.

## 4. Frontend architecture — post-Epic-T2.1 (fully modular)

`app.js` is **DELETED**. The IIFE monolith (4003 LOC at T2.1 open) is fully dismantled into ES modules. `index.html` loads a **single** ES-module entry point: `frontend/assets/js/main.js`.

**Topology:**

```
frontend/assets/
├── app.css                              ← stylesheet only (no JS)
├── index.html                           ← <script type="module" src="…/main.js"></script>
└── js/
    ├── main.js                          ← imports + init for every engine + view
    ├── core/   (18 modules)             ← shared engines
    │   ├── router.js          declarative route registry — registerRoute(routeId, {viewId, activate})
    │   ├── bootstrap.js       MODULES table + navigateTo + setupRouter + renderPlaceholder
    │   ├── sanitize.js        F3-5 XSS — escapeHTML + sanitizeHTML allowlist
    │   ├── state.js           reactive store (Proxy-based) — setState/getState/subscribe
    │   ├── telemetry_engine.js owns the SSE → reactive store (replaces legacy EventSource)
    │   ├── hermes_events.js   re-emits WS frames as DOM CustomEvents
    │   ├── power_grid.js / power_sld.js / power_cam.js  DAG + render
    │   ├── shi_sparkline.js / pue_widget.js / activity_strip.js / heat_overlay.js
    │   ├── staleness.js / focus_trap.js / sound.js / keyboard.js / asset_metadata.js
    └── views/  (18 views)
        ├── overview.js        landing dashboard (health, KPIs, PUE, agent chat, SHI, incidents, voice)
        ├── topology.js        HLD/LLD topology — What-If + Mission Control insights
        ├── site_topology.js   force-directed 2N graph
        ├── mission_control.js three.js Tesla-Megapack 3D
        ├── rack_heatmap.js    GPU/DLC rack grid
        ├── maintenance.js     CMMS — MutationObserver-driven
        ├── asset_panel.js     Phase 4 contextual SCADA panel
        ├── scenarios.js       failure scenario simulator
        ├── incidents.js       postgres audit log
        ├── mops.js            MOP/SOP/EOP library
        ├── tech_assist.js     RAG QA + PDF ingest + voice + OCR
        ├── multi_agent.js     4-agent consensus UI
        ├── power.js           Power & UPS SLD data plane
        ├── power_ups_iso.js   2.5D isometric SLD
        ├── cooling.js         DLC P&ID SCADA SLD + L3 control plane
        ├── copilot.js         Facility Co-Pilot agent chat — sanitizeHTML-routed
        ├── bms.js             BMS Connector + RBAC write modal + audit log
        └── loto.js            LOTO Auditor — 6-pillar
```

**Routing invariant.** Every view registers on `core/router.js` via `registerRoute('<id>', {viewId, activate})`. The legacy "zombie router" pattern (`document.addEventListener('click', ...) + setTimeout(0)`) — the DC-EPMS-MAINT-001/002/003 root cause — is **forbidden** for new views.

## 5. Backend architecture

FastAPI + asyncpg on `:8080`, native python (NOT docker — `python backend\main.py`). 40+ modules.

**Module groups:**

- `main.py` — central hub, lifespan boot, 50+ endpoints. FastAPI `version="4.1.0-pro"` is the public **product** version (separate namespace from the git tag scheme).
- `physics_engine.py` + `physics/` — 4 first-principles modules (it_thermal, mechanical, electrical, heat_rejection).
- `agent_copilot.py` / `agent_engine.py` — primary tool-calling agent atop a **Heterogeneous Multi-Model Pipeline (NeMo + Sonnet)**: a specialised tool-calling tier intentionally decoupled from the SLM (Gemma) consensus layer used by the multi-agent façade. The two tiers solve different problems — NeMo/Sonnet handle higher-cognition tool orchestration; Gemma handles fast local advisory narratives under ADR-006 — and must not be conflated. `AgentEngine.complete_gemma(prompt, max_tokens)` is the canonical non-streaming Gemma entry point — the seam at which the two tiers connect.
- `multi_agent.py` / `multi_agent_routes.py` — 4-agent façade (see §7).
- `procedure_engine.py` / `witness_engine.py` — MOP 8-state machine + multi-signature drafts.
- `procedure_generator.py` / `procedure_routes.py` — SOP/MOP/EOP/EMP factories + recursive micro-LOTO + RBAC promotion gates.
- `cmms_*.py` (Sprint 6) — `mcp`, `models`, `repository`, `routes`, `seeder`, `predictive_trigger`, `site_enrichment`.
- `loto_auditor_*.py` — 6-pillar validator: `agent`, `models`, `pillar_helpers`, `report_renderer`, `repository`, `routes`.
- `telemetry_simulator.py` / `telemetry_pipeline.py` / `cyber_physical_tools.py` — Sprint 5 Kalman pipeline (wired, live).
- `hermes.py` — Project Hermes WS plane (§6). `latest_kalman_channels()` at `hermes.py:218` is the live Kalman Z-score tap consumed by the multi-agent narrative helpers.
- `bms_connector.py` — BACnet/Modbus tag registry, audit log, RBAC write path.
- `site_model.py` + `site_routes.py` — declarative YAML inventory parser.
- `graphrag_service.py` + `graphrag_index.py` + `knowledge_graph.py` — NetworkX + FAISS.
- `rag_service.py` — ChromaDB persistent client; 20-doc 4-tier operational corpus.
- `database.py` + `metrics_router.py` — TimescaleDB pool + Prometheus.
- `hal/` — Cummins / ASCO / Russelectric adapters.
- `migrations/` — schema migrations (notably `2026_05_W3_g1_taxonomy.sql` with Arc Flash columns).

## 6. Project Hermes — EDA plane (T3.1, DELIVERED)

A multiplexed **WebSocket** at `/api/hermes` carrying three streams: `telemetry`, `cmms_alerts`, `agent_consensus`. SSE → WS telemetry cutover complete. **All client-side HTTP polling is eliminated.** `core/hermes_events.js` re-emits each server frame as a decoupled DOM `CustomEvent` (`hermes:cmms-alert`, `hermes:agent-consensus`, `hermes:edge-healing`). CET-gated closed-loop edge-healing is live (per `ADR-006`).

## 7. Multi-Agent Façade — Epic 1 COMPLETE (full 4-agent fleet LLM-augmented)

`backend/multi_agent.py` runs four specialised agents in parallel via `asyncio.gather` for any operator consult against an asset / procedure / work order. The orchestrator is exposed at `POST /api/multi-agent/consult`.

| Agent | Verdict basis (deterministic) | LLM narrative tag |
|---|---|---|
| **Architect** | 2N / N+1 / N redundancy pillar + criticality class + path (A/B). HARD_STOP on critical-single pillar; CAUTION on critical-2N. | **T3.3d** — Tier IV / Uptime Institute concurrent-maintainability framing |
| **Safety Officer** | LOTO + PPE compliance. **HARD_STOP VETO** outranks every other agent (CSA Z462 / NFPA 70E §130 / NEC 460.6). | **T3.3b** — CSA Z462 / NFPA 70E safety narrative |
| **Diagnostician** | Recurrence — CAUTION if ≥3 completed WOs in trailing 18 months OR ≥2 open WOs. | **T3.3** — Kalman-grounded diagnostic narrative |
| **Analyst** | CapEx / OpEx breakeven — CAUTION when cumulative OpEx ≥ 40 % of CapEx. | **T3.3c** — financial-impact narrative |

**Consensus rule (deterministic):**

1. Safety Officer `hard_stop` → consensus `hard_stop` (**VETO**, `safety_officer_veto=True`).
2. Else any agent `hard_stop` → `hard_stop`.
3. Else any agent `caution` → `caution`.
4. Else → `approve`. **CET signature is still required** per ADR-006.

**Shared narrative helpers** in `multi_agent.py`:

- `_collect_kalman_lines(telemetry_provider, asset_id, top_n=4)` → list of human-readable Z-score lines, [asset]-tagged + [site]-anomalous-tagged.
- `_gemma_complete(llm_client, prompt, max_tokens=240)` → best-effort; returns `""` on any failure (missing client, `[Gemma error …]` sentinel, exception). Graceful degradation is the contract.

**Runtime verified live (smoke test, 2026-05-19 18:11):** consult against `asset_id=ups_a` returns 4 grounded narratives in 7.8 s total (parallel Gemma calls). Each narrative cites real data (literal cost figures, real Z-scores, the canonical standards). Deterministic verdicts unaltered by the LLM in every case.

## 8. ADR-006 — Deterministic Sandbox (the load-bearing invariant)

> **Every agent verdict, every safety-critical decision, every consensus rule is computed by pure-Python deterministic logic. No LLM in the critical decision path.** The LLM layer is *advisory only*: it may attach an `llm_narrative` that runs *after* the verdict and never alters it.

This is the **single most important rule** in the codebase. It is reinforced by:

- The `verdict_unchanged_by_llm` unit test for every agent (a contradicting LLM reply must not move the verdict).
- The `graceful_when_llm_raises` test (a crashing LLM client degrades to an empty narrative — operations continue).
- The `no_llm_client_no_narrative` test (pre-LLM behaviour is byte-for-byte preserved when `llm_client=None`).
- The Safety Officer prompt explicitly forbids overriding the verdict (`"DETERMINISTIC VERDICT (already decided, do not override)"`).
- The Analyst prompt additionally forbids inventing cost figures (cost heuristics are authoritative).

**See `docs/adr/ADR-006-deterministic-sandbox.md` for the full architecture decision record.**

## 9. L3 SCADA Control Planes (Power + Cooling)

Both the Power & UPS SLD and the DLC P&ID carry an interactive L3 control layer:

- **RBAC-gated actuation** — breakers (Power) / pumps (Cooling) POST to `/api/bms/write` with `actor_role: SME_L6`. The endpoint enforces `role_rank(actor_role) ≥ 6`; below that → HTTP 403.
- **Real ISA-95 BMS tags.** Actuators map to seeded dotted tag ids in `config/bms_tags.yml` (50 tags total, 9 writable). Examples: `PWR.ATS_A.BREAKER`, `HVAC.CHWP1.STATUS`.
- **What-If Predictive Sandbox.** A local DAG engine (`core/power_grid.js`) propagates a hypothetical fault through the topology — **zero writes** to the live BMS. The operator can model contingencies before acting.
- **Live telemetry sparklines** bound to the Hermes Kalman stream — node severity colours flip on live Z-score changes.
- **Orthogonal SVG renderers** (correctness-by-construction, 90°-only routing, strict tier columns) for both SLDs.

## 10. Testing gates (the commit-time floors)

| Gate | Floor | Detail |
|---|---|---|
| `pytest -m "not slow"` | **726** passed | ~48 s; 5 deselected (FAISS / slow). `tests/` carries 30+ files. |
| `npm test` (Vitest, happy-dom) | **176** passed, 18 files | mission_control + scenarios + incidents + mops + power + cooling + copilot + bms + loto + topology + overview + bootstrap + sanitize + hermes (slice / cutover / EDA) + maintenance + rack_heatmap + site_topology |
| `ruff check backend/` | **0** violations | enforced since DC-EPMS-021 (`136c7ef`) |
| `node --check` on modified `.js` | clean | use `node --input-type=module --check < file.js` for ES modules |

**Every commit must pass the targeted slice + the full suite before merging.** Targeted file run first for fast feedback, then the full suite as the gate.

## 11. Operational runtime

- **Backend:** `python backend\main.py` on `127.0.0.1:8080` — **native, NOT docker**.
- **PostgreSQL:** docker container `epms-db` on `5432`, TimescaleDB pg16, DB `dcepms`, user `epms`. Credentials in `config/.env` (gitignored — see DC-EPMS-DB-001).
- **Gemma:** LM Studio at `127.0.0.1:1234`, model `gemma-4-e2b-it`. Required for the multi-agent narrative layer.
- **Venv:** `C:\dev\DC-EPMS_PRO\.venv` (Python 3.12.10). Activate: `.\.venv\Scripts\Activate.ps1`.
- **Hardware:** ASUS Zephyrus G14, AMD Ryzen, RTX 3060 6 GB, CUDA 13.2, Windows 11 + WSL2 + Docker Desktop.
- **Geography:** development + edge-latency testing run from **North York, Toronto (Ontario, Canada)** — the same metro the A3-Alpha Toronto Area facility is sited in. This is *not* incidental: the cooling / PUE / WUE simulators are calibrated against Toronto's ambient wet-bulb and dry-bulb baselines (cold-aisle inlet curves, cooling-tower approach, free-cooling hours). When tuning thermal envelopes or seasonal load profiles, the Toronto climate file is the implicit reference — assume Toronto conditions unless explicitly overridden.
- **One-shot start:** `.\scripts\start.ps1`.

**Stale-process trap (smoke-tested 2026-05-19).** Python does not hot-reload. After any backend code change, the running process must be **restarted** before any AI-feature smoke test — otherwise unit tests pass against new code while the in-process service runs the old code, silently returning empty narratives. The pre-T3.3 `[BOOT]` log line lacks the `"Diagnostician live-Gemma narrative %s"` suffix; that signature is the cheapest stale-process detector.

## 12. Working-style essentials

- **Approve-then-execute** for anything genuinely risky or with a real architectural fork. The user has consistently rewarded SRE halts.
- **Atomic batches** — never bundle unrelated changes in one commit.
- **`-F` file-based commit messages** via `.git/COMMITMSG.txt` (deleted after commit) — the PowerShell 5.1 embedded-quote bug splits `-m` arguments containing `"`. ASCII-only. End with the canonical `Co-Authored-By` line.
- **Doc-sync as a separate commit** after architectural changes — `CLAUDE.md` CURRENT STATE + `docs/ROADMAP-V11.md`.
- **PowerShell native** for Windows file ops (per Rule V9.1, DC-EPMS-035 lesson).
- **Real ISA-95 BMS tag ids** in SLD actuators — `PWR.<NODE>.<POINT>` / `HVAC.<NODE>.<POINT>`.
- **F3-5 XSS routing** for LLM-authored DOM only — structured UI with `<button>` keeps per-value `escapeHTML` instead (sanitizeHTML drops buttons by design).

## 13. Known constraints + open items

- **DC-EPMS-029c** (LOW) — `physics_engine.validate_site()` SHI rollup insensitive to some LOTO scenarios (chiller/cooling_tower/RPP). UPS + CDU LOTO do produce SHI delta; sufficient for demo. Target V10.
- **WARNING-tier findings** in `docs/audit/E2E_Security_Orphan_Audit.md` — non-blocking, untriaged.
- **OBS demo-recording** — descoped (Wilmer, 2026-05-17).
- **CO+I demo readiness** — feature-complete; remaining work is delivery (DEMO_SCRIPT v5, 3× OBS rehearsals).

**Epic 2 (PENDING) — proactive edge-agents.** Epic 1 closed the *reactive* fleet (the four consultative agents that respond to operator queries). Epic 2 targets *proactive* edge-agents that act on the platform without an operator prompt — notably **The Optimizer**, a continuous-loop agent for dynamic PUE / WUE adjustment (chiller setpoints, pump speeds, cooling-tower fan modulation) bounded by ADR-006: the Optimizer authors **proposed** setpoint changes, but every actuation still routes through the RBAC-gated `/api/bms/write` path with a CET sign-off. The deterministic What-If sandbox (`core/power_grid.js`) is the validation gate for any Optimizer proposal before it leaves advisory mode. Triggered by Hermes telemetry; no autonomous BMS writes. Sequencing target: post-CO+I demo.

## 14. Companion documents

- `docs/skills/skill-registry.md` — explicit rule harness (the digestion list).
- `docs/ROADMAP-V11.md` — live backlog (v11.8, Epic 1 complete).
- `docs/adr/` — 9 ADRs in MADR format (ADR-006 deterministic-sandbox is the load-bearing one).
- `CLAUDE.md` — living guidance (every session reads this first).
