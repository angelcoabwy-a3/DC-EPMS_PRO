# DC-EPMS PRO — Roadmap V11

- **Status**: v11.5 (2026-05-18) — structural compaction · T3.3b Safety Officer · T2.1 mops view
- **Decision-maker**: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
- **Locked**: 2026-05-10 · **Synced**: 2026-05-18 (v11.5)
- **Supersedes**: ad-hoc "what's next" decisions across the v0.10.x arc; and the
  2026-05-10 lock of this file's own status fields
- **v11.5 sync (2026-05-18)**: consolidation sprint — structural compaction
  (4 duplicated CMMS helpers consolidated to `backend/cmms_classification.py`,
  5 frontend `_escape` copies to `core/sanitize.js`, 3 orphan functions purged),
  T3.3b live-Gemma Safety Officer (advisory narrative; VETO stays deterministic),
  T2.1 `mops` view extracted to an ES module.
- **v11.4 sync (2026-05-17)**: master-pipeline sprint — DC-EPMS-021 ruff hygiene
  (124 → 0 violations), T3.3 live-Gemma Diagnostician delivered, T2.1 `incidents`
  view extracted to an ES module. DC-EPMS-022 closed (verified stale).
- **v11.2 sync (2026-05-17)**: T3.1 Project Hermes DELIVERED — multiplexed WS
  EDA plane (telemetry + cmms_alerts + agent_consensus), SSE→WS telemetry
  cutover, CET-gated edge-healing engine, and the maintenance.js poll→event
  cutover. T2.1 advanced (scenarios + maintenance views off the IIFE).
- **v11.1 sync (2026-05-17)**: T1.4 / T1.5 / T2.2 delivered; T2.4 / T2.5 partial;
  OBS demo-recording (T1.1 / T1.3) descoped; T3.8 DPO file eradicated; Hermes
  ADR corrected to ADR-011.

This document is the queued backlog after `v0.10.5-power-sld-v2`. Each
tier is independently fundable — pick by available time, panel
proximity, or career trajectory. Items are intentionally specific so
review (mine, the panel's, or future Claude's) can verify the cut.

---

## Tier 1 — Demo Readiness (~8h, target: any 1-day burst)

The platform is panel-ready as code. **Delivery is the unfinished
business.**

### T1.1 — Browser-validation of B1 Mission Control (~1 h)

The Tesla-Megapack mission control was shipped (`v0.10.4-b1-production`)
but never validated by human eyes on a real WebGL canvas. Verify:

- 4 cards project correctly onto each building anchor as the camera/
  viewport changes
- Glassmorphism `backdrop-filter` renders (Chrome / Edge / Safari OK;
  Firefox needs flag)
- 28 InstancedMesh particles flow visibly Yard → A and Yard → B
- Building A card flips to amber CAUTION when 3 anomalies are queued
  (current demo state)
- Click drill-down to `#rack-heatmap` / `#site_topology` /
  `#tech-assist` works smoothly
- FPS sustained ≥ 60 (spike measured 144)

Iterate on whatever fails.

### T1.2 — DEMO_SCRIPT v5 (~2 h)

Current `DEMO_SCRIPT.md` (v4) does not mention:
- Mission Control (`v0.10.4`)
- Rack Anomaly Heatmap (`v0.10.2`)
- Force-directed Site Topology graph (`v0.10.1`)
- Path-coded Power flow (`v0.10.1`)
- Sound + boot splash + keyboard shortcuts (`v0.10.0`)
- Voice closure modal (`v0.9.15`)
- Asset enrichment loop (`v0.9.16`)

V5 must reorganise the 13-15 min walkthrough around **Mission Control
as the new opening visual** (replaces the bare KPI grid as the
panel-impression frame), then drill into Maintenance → Multi-Agent →
LOTO Auditor → Tech Assist with the new affordances cited.

### T1.3 — Recording rehearsal × 3 + final OBS take (~3 h)

OBS Studio split-screen (terminal left, browser right). Three
rehearsal takes minimum before the actual recording. Final cut to
DaVinci Resolve / kdenlive for trimming, captions, lower-thirds.

### T1.4 — ✅ DELIVERED `7be472b` — `PRIMER_PROMPT.md` polishing + commit

Untracked file currently. Update it to reflect everything through
`v0.10.5-power-sld-v2`. Commit so future Claude sessions can absorb
the project context in 30 seconds without re-reading 50 sprints.

### T1.5 — ✅ DELIVERED `6b38a16` — `replay_demo.ps1` / twin-script injector

Add:
- Reset Mission Control simulation state to nominal
- Set sessionStorage flags to a known-clean state
- Print a "browser hard-reload Ctrl+Shift+R" reminder at the end

### T1.6 — Backend bug closeout (~1 h, opportunistic)

While in cleanup mode, knock out the cosmetic bugs that have lingered:
- DC-EPMS-019 logging file handle on shutdown (30 min)
- DC-EPMS-022 6 ADRs MD004 asterisks (5 min sed)
- DC-EPMS-039 chromadb posthog + pydantic warnings (30 min)

DC-EPMS-021 (90 ruff legacy errors) and DC-EPMS-029c (physics LOTO
sensitivity) deferred — they don't affect demo quality.

---

## Tier 2 — Architectural Polish (~7-10 days, target: 2-3 weeks)

For Senior+/Staff Engineer interview ammunition. The platform is
demonstrable; the architecture has visible debt that a deep-dive
reviewer can find in 30 seconds with DevTools.

### T2.1 — Dismantle `app.js` IIFE (4003 LOC) — 8 vistas legacy (~3-4 days)

The single largest visible piece of architectural debt. Migrate one
view per session, in order of demo relevance:

1. ✅ `views/scenarios.js` — failure scenario simulator (DELIVERED `480f03b`)
2. ✅ `views/incidents.js` — postgres audit log (DELIVERED `3aa944b`)
3. ✅ `views/mops.js` — MOPs/SOPs/EOPs library (DELIVERED `de7404f`)
4. `views/cooling.js` (~350 LOC) — P&ID renderer
5. ✅ `views/power.js` — SLD data plane extracted; the 2.5D iso engine
   preserved + enriched to an explicit 5-layer Tier IV topology
   (paralleling bus N+1), aggressive dark-SCADA restyle, Hermes-bound
   (DELIVERED `b5a82ed`)
6. `views/bms.js` (~250 LOC) — BMS connector
7. `views/copilot.js` (~400 LOC) — full-screen agent chat
8. `views/site_topology_legacy.js` (~600 LOC) — old tree+detail UI
   (current force-directed is in `views/site_topology.js`)

**Result**: `app.js` shrinks to ~200 LOC residual (router + bootstrap).

### T2.2 — ✅ DELIVERED `42ecdf7` — Declarative router

Replace `navigateTo()` switch statement + 5 `setTimeout(0)` LOTO-pattern
hacks with:

```typescript
// core/router.ts
const routes = new Map<string, RouteHandler>();
export function registerRoute(path: string, handler: RouteHandler) { … }
export function navigateTo(path: string) {
    history.pushState({}, '', `#${path}`);
    routes.get(path)?.activate();
}
```

Each ES module view auto-registers in its `init()`. Eliminates the 5
`setTimeout(0)` overrides and the zombie-router (where overview shows
for one frame before being hidden).

### T2.3 — Vite + TypeScript strict (~2 days)

Pre-condition for Module Federation if we ever want it. Fast HMR
unlocks 10× dev velocity. Type safety catches the kind of dead-code
+ phantom-button drift that would otherwise accumulate.

```
+ pnpm/npm + vite + typescript
+ frontend/package.json (at last)
+ frontend/vite.config.ts (with Module Federation plugin already
                           installed even if not yet activated)
+ tsconfig.json strict (noImplicitAny, strictNullChecks, etc.)
+ FastAPI serves dist/ build, NOT raw source
+ Cache busting via vite content hashing (no more ?v=8.1.0-s66)
```

### T2.4 — 🟡 PARTIAL `6c77f41`/`ec8effb` (Vitest harness + mission_control suite) — Frontend tests (Vitest + happy-dom, ~2 days)

Backend has 549 tests. Frontend has 0. Smoke per view minimum:
- mission_control: renders 4 buildings + cards bind data correctly
- rack_heatmap: 50-cell grid renders, click flips selection
- site_topology: graph layout converges in ≤ 500ms with 91 nodes
- maintenance: WO row click opens approve/reject correctly
- multi_agent: VETO scenario flips banner red

### T2.5 — 🟡 PARTIAL `f384937` (A11y-1: focus-trap, keyboard drill-down, skip-link) — A11y audit (~1 day)

Keyboard-only navigation completeness, ARIA labels on every action
control, focus management on modal open/close, prefers-reduced-motion
already honored — extend to prefers-color-scheme + high-contrast mode.

### T2.6 — Cache busting + asset hashing (~2 h)

Currently every asset has a hardcoded `?v=8.1.0-s66` query that we
never bump. Move to vite content-hashed filenames so each deploy
self-busts.

---

## Tier 3 — Capability Expansion (~3-4 weeks, target: open-ended)

The capabilities that push **past** demo-ready into a competitive
differentiator. Pick selectively; do NOT attempt all in one push.

### T3.1 — WebSocket Hermes pipeline — ✅ DELIVERED 2026-05-17

**The architectural inflection point — shipped.** Delivered across
`caf5cc1` (WS vertical slice) → `bf20042` (live Kalman tap + SSE→WS
telemetry cutover) → `66abc30` (unified EDA plane: cmms_alerts +
agent_consensus + CET-gated edge-healing) → maintenance.js poll→event
cutover. Still open: retiring the remaining per-view polls
(`mission_control.js`), and PUE / power_sld over the socket. The
original plan below is kept as the design record.

Replace REST+polling for PUE + CMMS + Multi-Agent + Power SLD with a
single multiplexed WebSocket stream:

```
GET   /api/physics/pue                  ← 15 s polling → REPLACE
GET   /api/cmms/work-orders?only_open   ← 15 s polling → REPLACE
GET   /api/multi-agent/consult          ← on-demand → KEEP (req/res)

WS    /api/hermes/stream                ← NEW, multiplexed:
        type: 'pue.snapshot'            phase_1 + phase_2 every 1 s
        type: 'cmms.delta'              WO state transitions
        type: 'cmms.snapshot'           full backlog every 30 s
        type: 'multi_agent.broadcast'   consensus events as they fire
        type: 'telemetry.kalman'        z-score + sustain per channel
        type: 'power_sld.event'         simulated faults / real faults
```

**Frontend backpressure**: RxJS `bufferTime(50ms) → distinctUntilChanged
→ throttleTime(33ms)` per channel. Web Worker for JSON parsing if a
single tick > 200 messages.

**Backend**: a single `hermes_orchestrator.py` that fans out to all
existing services and serializes to JSON Lines.

### T3.2 — Voice closure transcription (~3-4 days)

Sprint 7.1c V2: integrate `faster-whisper` (already a Python dep)
behind `POST /api/tech-assist/closure/{wo_id}/transcribe-and-dictate`.
Frontend audio capture via MediaRecorder + WebRTC.

### T3.3 — Multi-Agent ML upgrade — ✅ DELIVERED 2026-05-17 (`c811865`)

The Diagnostician now makes a real call to the local Gemma model. The
agent's VERDICT stays pure-Python deterministic (ADR-006 — no LLM in the
critical decision path); Gemma is wired as an *advisory narrative* layer
that runs AFTER the verdict and never alters it.

Delivered:
  - `AgentEngine.complete_gemma()` — non-streaming Gemma completion.
  - `hermes.latest_kalman_channels()` — public live Kalman Z-score tap.
  - `DiagnosticianAgent` takes an `llm_client` + `telemetry_provider`;
    after the deterministic verdict it grounds a prompt in the asset's
    live Kalman Z-scores and stores the synthesized narrative in
    `AgentVerdict.llm_narrative`. Any LLM/telemetry failure degrades to
    an empty narrative.
  - 4 tests mock the external LLM call (narrative grounding, verdict
    immutability under a contradicting LLM, graceful degradation,
    no-client baseline).

NOTE: the original brief proposed RAG-corpus-chunk grounding; the
delivered cut grounds on live Kalman telemetry instead — closer to the
real physical state and consistent with the Hermes EDA plane.

**T3.3b — ✅ DELIVERED 2026-05-18 (`10fd664`)**: the same advisory-narrative
pattern extended to the **Safety Officer**. Two shared helpers
(`_collect_kalman_lines` / `_gemma_complete`) were extracted; the
Diagnostician was slimmed onto them. The Safety Officer's verdict —
including its HARD_STOP **VETO**, which outranks every other agent —
stays 100% deterministic; Gemma only writes the advisory narrative in a
verdict-independent `_finalize()`. 4 LLM-mocked tests. Architect and
Analyst remain fully deterministic with no LLM layer.

### T3.4 — Power flow live tied to current_a (~1 day)

Currently 28 InstancedMesh particles in Mission Control and SLD
flow at fixed velocity. Hook to `current_a_phase_*` from the
telemetry stream (after T3.1 lands). Speed and density per Path
modulated by real load.

### T3.5 — Mission Control glass-panel polish (~2 days)

Selective bloom on healthy edges (cyan glow), `CSS3DRenderer` for
the floating cards instead of HTML overlay (eliminates the
projection math each frame). **Risk**: bloom is the kitsch knife
edge; if it crosses, kill it.

### T3.6 — Anomaly heatmap real-time integration — ✅ DELIVERED 2026-05-17

`views/rack_heatmap.js` now subscribes to the `channels` state key (the
Hermes `telemetry` channel_innovations payload) and maps each rack's
real Kalman `max_z` + `last_emission` onto the cell color band + anomaly
blink. The deterministic sinusoid is retained only as a stale-fallback
(resumes after a 15 s live-data gap). The last client-side `setInterval`
HTTP poll was also eliminated — `mission_control.js` → Hermes events.

### T3.7 — Module Federation (~5-7 days)

Pre-condition: T2.3 (Vite + TS). After:

```typescript
// vite.config.ts with @originjs/vite-plugin-federation
federation({
    name: 'shell',
    remotes: {
        maintenance: 'http://...:8081/maintenance/remoteEntry.js',
        tech_assist: 'http://...:8082/tech-assist/remoteEntry.js',
    }
})
```

**Only valid if separate teams need to deploy independently.** For
single-developer single-laptop, this is over-engineering. Documented
here as a future option.

### T3.8 — DPO edge healing (~4-5 days)

Sprint 6 deferred capability. `backend/dpo_edge_healing.py` (352 LOC) was
**eradicated 2026-05-17 in `d495c7b`** as a confirmed orphan — never wired,
and the "Sprint 6 = DPO" plan was superseded by CMMS Core. Reviving this epic
now requires first restoring the file from git history
(`git show d495c7b^:backend/dpo_edge_healing.py`) or re-authoring it, then
surfacing it as `POST /api/dpo/capture` (auto-fires on CMMS WO rejection) +
`POST /api/dpo/recompile` (manual trigger). Edge-local LLM fine-tuning loop.
ADR-007 documents the original reuse decision (amended 2026-05-17).

### T3.9 — 3D Mission Control orbit camera + Building D walkthrough (~3 days)

Optional: relax the "fixed iso" constraint when the user explicitly
clicks an "orbit mode" toggle. Still bounded; nothing free-roam.
Building D click could trigger a fly-through to Q2 2026 design view.

### T3.10 — Print/PDF export (~1-2 days)

Operations panels often need this for audit trails. Server-rendered
HTML → headless Chrome via Playwright → PDF for any backlog snapshot,
LOTO audit, or PUE report.

---

## Hermes Vision (Confederation, queued)

The original elite-architect prompt described "Hermes" as a central
Multi-Agent Consensus orchestrator — a confederation pattern where
the frontend is a high-throughput telemetry receiver and not a REST
poller. After T3.1 (WebSocket pipeline) lands, the building blocks
exist:

```
                    ┌──────────────────────────────────────────────┐
                    │                  HERMES ORCHESTRATOR          │
                    │  (backend/hermes_orchestrator.py — NEW)       │
                    │                                                │
                    │  1. Fan-in:                                    │
                    │     - Kalman pipeline (telemetry events)       │
                    │     - CMMS state machine (WO transitions)      │
                    │     - Predictive trigger (z-score breaches)    │
                    │     - Multi-agent consensus (deterministic)    │
                    │     - Physics validators (PUE, SHI, BBC)       │
                    │                                                │
                    │  2. Filtering + dedup:                         │
                    │     - bufferTime(50ms) per channel             │
                    │     - distinctUntilChanged on payload          │
                    │     - rate-limited rebroadcast                 │
                    │                                                │
                    │  3. Multiplex to clients via WS                │
                    └──────────────────────────────────────────────┘
                                          │
                          ┌───────────────┴───────────────┐
                          ▼                               ▼
                    Frontend client                 ML training pipeline
                    (Mission Control,               (DPO edge healing,
                     Maintenance, etc.)              Sprint 6)
```

The vision is intentionally **deferred until T3.1 + T3.3 land** —
without those building blocks, Hermes is premature abstraction.

When ready, the Hermes orchestrator gets:
- Its own ADR — **ADR-011** (the original "ADR-010" reservation is void:
  ADR-010 was assigned to the dual-graph asset taxonomy on 2026-05-17) —
  documenting the consensus protocol
- An async test harness simulating 1000 events/sec
- A backpressure metrics dashboard (built on the existing telemetry
  Activity Strip pattern)
- A "kill switch" feature flag so the legacy REST endpoints stay
  available for emergency rollback

**Acceptance criteria for Hermes V1.0**:
- 100 Hz sustained throughput from backend → multiplexed WS
- Frontend stays at 60 FPS with all modules subscribing
- One subscriber crash does not kill the orchestrator
- Hermes itself observable: `GET /api/hermes/health` shows queue
  depths per channel + WS connection count + backpressure metrics

---

## Recommended sequencing

For a CET interview at Microsoft CO+I in early August 2026:

```
NOW (this session)         T1.1-T1.6        ~8h     PANEL READINESS
+1 week                    T2.1 (IIFE)      3-4d    Cleaner DevTools view
+2 weeks                   T2.2-T2.4        4-5d    Tests + router + Vite
+3 weeks                   T3.1 (Hermes WS) 5-7d    Real-time differentiator
+4 weeks                   T3.3 (Diag ML)   3d      Multi-agent depth
+5 weeks                   Hermes V1.0      ~5d     Confederation arrives

INTERVIEW WINDOW           early August 2026
```

For continued V11 development without panel pressure: pick by
appetite. Tier 3 in any order. Hermes after T3.1 + T3.3.

---

**Locked: 2026-05-10. Updates require explicit version-bump of this
file with a new "supersedes" line at the top.**
