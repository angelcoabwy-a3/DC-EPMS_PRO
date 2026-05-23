# DC-EPMS PRO - Claude Code Project Memory

**Project**: DC-EPMS PRO (Edge Operations Platform for Tier IV AI factories)
**Repository**: `C:\dev\DC-EPMS_PRO`
**Maintainer**: Wilmer Y. Angel Beltran (a3semi - A-Cubed Semiconductor Systems Inc.)
**Target**: CET role at Microsoft Cloud Operations + Innovation (CO+I) division
**Interview target**: early August 2026

## 🎯 What this project is

DC-EPMS PRO is an AI-native edge operations platform simulating **A3-Alpha Toronto Area** under **Path C2** (sealed 2026-05-05): a 67 MW Tier IV AI factory with 368 racks total.

- Phase 1 (Buildings A/B deployed): **118 NVIDIA GB200 NVL72 racks @ 142 kW**, 480 VAC trifásico 2N, UPS Schneider Galaxy VX, chillers York YZ N+1
- Phase 2 (Building D target Q2 2026): **250 NVIDIA GB300 NVL144 racks @ 200 kW**, upstream 3-phase AC at 35 kVAC trifásico into MV Rectifier, 800 VDC unipolar TN-S downstream, SSCB 1-100 microsecond clearing per IEC 60947-2, BESS 2.5 MWh, full DLC retrofit to 12 VDC at GPU
- Rubin Ultra excluded from V9 scope

**Vocabulary discipline (CRITICAL)**: "trifásico" applies ONLY to AC upstream of MV Rectifier. The 800 VDC bus is unipolar (no phases). Saying "800 VDC trifásico" is a credibility-destroying error in panel review.

## 📊 CURRENT STATE (synced 2026-05-23)

```
HEAD:  <Epic-4 batch — pending commit>  branch master  —  ahead of origin.
       Stable baseline = **v0.13.0 "Proactive Edge"** (cut 2026-05-19).
       Post-release: **EPIC 4 OPENED + delivered (ADR-011 Forensic Ledger
       + Proposer-chain closure + Rollback Harness)**, on top of EPIC 3
       Batches 3.A + 3.C. 6-agent fleet still (Architect / Safety
       Officer / Diagnostician / Analyst / Capacity Planner / Carbon-Grid).

       Epic 4 (this session) — closes the 4 CRITICAL findings from the
       2026-05-22 MSD v2.0 forensic audit:
       * ADR-011 written (HMAC-SHA256 chained, append-only ledger,
         TimescaleDB-backed, IEC 62443-3-3 SR 6.1 / 6.2 / 7.3 / 7.4).
       * backend/ledger/ package: ForensicLedger + InMemoryPersistence
         + PostgresPersistence + wrap_bms_write_fn (the single seam
         every BMS write traverses). S-LEDGER-01 in the skill registry.
       * /api/bms/write now accepts optional proposal_id and
         cross-checks the Optimizer ApprovalLog (HTTP 404/409 on
         missing/mismatched). S-PROPOSER-01.
       * /api/bms/revert/{entry_id} (SME_L6): reads the original
         BMS_WRITE_REQUESTED entry, restores its prev_value via the
         same wrapped seam, appends a BMS_REVERT marker — full
         rollback harness, IEC 62443-3-3 SR 7.3/7.4.
       * /api/ledger/entries + /api/ledger/verify for forensic replay.
       * Migration 2026_05_W4_forensic_ledger.sql — DDL artifact, NOT
         auto-applied (DC-EPMS-040 lesson); operator runs
         `psql -f` and restarts. Until then the lifespan falls back to
         InMemoryPersistence with a loud WARNING.
       * 41 new tests (18 ledger + 14 proposer-chain + 9 rollback);
         pytest 830 -> 871; ruff 0 violations.

       3.C — Carbon/Grid: Ontario IESO carbon-intensity + Time-of-Use
       perspective for the CO+I 2030 carbon-negative commitment.
       Verdict bands: HARD_STOP at carbon ≥ 200 g/kWh AND on-peak TOU;
       CAUTION when either trips alone; APPROVE on clean low-carbon
       off-peak. Reuses _collect_kalman_lines + _gemma_complete
       verbatim (T3.3 pattern). **No VETO authority** — Safety Officer
       remains the sole vetoer (S-DET-02); a Carbon/Grid HARD_STOP
       propagates via the standard "any agent hard_stop" rank-2 rule,
       NEVER the rank-1 VETO branch (binding test:
       test_carbon_grid_has_no_veto_authority).

       Dep-prep delivered (commit 9267667): backend/grid_provider.py —
       a deterministic Ontario IESO mock keyed to time-of-day +
       weekend status, with self-contained UTC-4 fallback so it works
       on Windows without IANA tzdata. Real-IESO API integration is a
       drop-in replacement (function-as-DI-seam pattern).

       3.B (OT Security via Morpheus) still **deferred** pending
       explicit GO — real dep-prep work (Morpheus stub / live engine)
       before the agent class itself. Tag = v0.13.x patch / v0.14.0
       next.
Working tree: .claude/ untracked (intentional).

Tags chronological (41 total):
  v0.5.0 .. v0.8.5-cmms-core-v1               foundation → Sprint 6 CMMS Core
  v0.9.0-cmms-predictive                      Sprint 9.1 predictive WO trigger (Kalman→auto-WO)
  v0.9.5..v0.9.9-tech-assist*                 Sprint 7.1a-d Tech Assist (QA, PDF ingest, voice, OCR) + view
  v0.9.10-demo-snapshot / v0.9.11-consolidation
  v0.9.12-multi-agent-facade                  Sprint 10.1 (4 agents + Safety Officer veto)
  v0.9.13-demo-veto-sample
  v0.9.14-pue-physics                         Sprint 5.5b PUE physics widget + ADR-004
  v0.9.15-voice-closure-modal / v0.9.16-asset-enrichment
  v0.10.0..v0.10.2                            HMI Tier A/B/C polish (topology, flow, anomaly heatmap)
  v0.10.3-b1-spike / v0.10.4-b1-production    B1 Mission Control (three.js Tesla-Megapack)
  v0.10.5-power-sld-v2                        Lead Engineer Mode + V11 roadmap committed
  v0.10.6..v0.10.8                            2.5D isometric SLD + DAG engine + iso camera
  v0.10.9..v0.10.11                           SCADA asset panel, PBR polish, DDU/busway expansion
  v0.10.12-maint-fix / v0.10.13-modal-fix     maintenance routing + closure-modal fixes
  v0.11.0  (2026-05-18)                       RELEASE "Monolith Deconstruction" —
   56 commits post-v0.10.13: ProcedureGenerator C0+G1-G6, hyperscale RBAC,
   E2E security audit + F3-4/F3-5/F3-6 remediation (claim-RBAC, XSS sanitizer,
   externalized DB creds), SRE cleanup, DC-EPMS-021 ruff hygiene, structural
   compaction (cmms_classification dedup + orphan purge), T2.1 IIFE dismantle
   (scenarios + maintenance + incidents + mops + power + cooling + copilot),
   T3.1 Hermes WebSocket EDA plane + CET-gated edge healing, T3.3/T3.3b
   live-Gemma Diagnostician + Safety Officer, Tier IV Power SLD upgrade
   (5-layer + paralleling bus + SCADA restyle + Hermes binding) + L3 control
   plane, Cooling orthogonal SCADA SLD + L3 control plane.
  v0.12.0  (2026-05-19)                       RELEASE "Monolith Eradicated" —
   EPIC T2.1 CLOSED: the app.js IIFE monolith (4003 LOC) fully dismantled
   into ES modules and DELETED. T2.1 Vectors 1-4 — BMS / LOTO / Topology /
   Overview views extracted, legacy Site Topology eradicated, the router
   residual promoted to core/bootstrap.js. The HMI is fully modular: 12
   views/*.js + core/*.js engines, all routed by the declarative
   core/router.js. index.html loads a single ES-module entry point.
  v0.13.0  (2026-05-19)                       RELEASE "Proactive Edge" —
   EPIC 2 CLOSED. Full proactive PUE/WUE edge-agent ("The Optimizer")
   shipped across Batches 2.A-2.E: deterministic control law + drift /
   pacing guards (2.A), multi-agent consensus integration with Safety
   VETO uncrossable + proposal queue + Optimizer Gemma narrative +
   Hermes WS producer (2.B), POST /api/optimizer/approve|reject with
   strict SME_L6 RBAC + audit chain (2.C), HMI proposal-queue view
   with F3-5 sanitizeHTML on LLM narratives + Hermes consumer (2.D),
   BMS catalogue wired to live tags (HVAC.CHILLER1.CW_SETPOINT +
   new HVAC.CTOWER1.FAN_VFD) + Toronto-baseline calibration notes +
   live smoke verified (default-OFF + ENABLED postures, HTTP 403 RBAC
   gate proven against running stack) (2.E). 5 AST Proposer-Pattern
   invariants enforce ADR-006 on backend/optimizer.py at commit time.
   Default OFF (env-gated). Backend pytest 726 → 797 (+71 across
   test_optimizer.py + test_optimizer_routes.py); frontend Vitest
   176 → 193 (+17 across optimizer.test.js + hermes_events.test.js).

Tests:   backend 875 passed, 5 deselected (slow/FAISS) — full pytest ~44s, 0 fail.
         (+41 in Epic 4: 18 in test_forensic_ledger.py — HMAC chain,
         tamper detection, immutability, key rotation, ephemeral-key
         warning; 14 in test_bms_write_proposer_chain.py — wrapper
         pre/post entries, prev_value capture, proposal_id stamping,
         deadlock-refusal, endpoint RBAC + ApprovalLog cross-check;
         9 in test_rollback_harness.py — restore, double-revert,
         SME_L6 gate, 404/422 paths, marker payload linkage.)
         (+4 in DC-EPMS-MSD-005 fix: test_forensic_ledger_postgres.py
         — verify_chain through asyncpg, UUID->str boundary coercion,
         DB-side trigger immutability, cross-backend HMAC parity.)
         (+8 in tests/test_multi_agent.py for Epic 3 Batch 3.A —
         Capacity Planner: 4 verdict-class tests across the warn/crit
         bands + the 4-test T3.3 narrative pattern.)
         frontend 193 passed (19 Vitest files) — 16 new in
         tests/frontend/optimizer.test.js cover 2.D render + S-SEC-01
         XSS (img/script/proposal_id) + fetchQueue + S-SEC-02 approve
         POST + reject POST + route registration + Hermes refresh; +1
         test in hermes_events.test.js for the optimizer_proposal
         stream subscription. ruff: 0 violations in backend/.
         frontend 176 passed — Vitest (npm test, 18 files): mission_control +
         scenarios + incidents + mops + power + cooling + copilot + bms + loto +
         topology + overview + bootstrap + sanitize + hermes (slice / cutover /
         EDA) + maintenance + rack_heatmap + site_topology. Both green.
         ruff: 0 violations in backend/.

Perf baseline (2026-05-09 AMD Ryzen + Windows — Sprint 5 era, still valid):
  - Numba JIT cold compile: 4.8 ms
  - Hot compute() over 238 channels: 5.11 ms / window
  - Per-step Kalman: 4.3 us (well under SSCB target 1-100 us)

Runtime: backend = `python backend\main.py` on :8080 (native, NOT docker).
         epms-db container = TimescaleDB pg16 — DB `dcepms`, user `epms`.

V9 scope: feature-complete. Post-v0.10.13: ProcedureGenerator (C0+G1-G6 —
dual-graph taxonomy / SOP-MOP-EOP-EMP factories / recursive micro-LOTO),
hyperscale RBAC, E2E security audit + CRITICAL remediation, SRE cleanup,
T2.1 (IIFE dismantle: scenarios + maintenance views → ES modules), and
T3.1 PROJECT HERMES — multiplexed WebSocket EDA plane (telemetry +
cmms_alerts + agent_consensus), SSE→WS telemetry cutover, CET-gated
closed-loop edge-healing, and T3.6 (anomaly heatmap on live Kalman
z-scores). ALL client-side HTTP polling now eliminated — mission_control
+ maintenance refresh on Hermes events. Power-SLD sprint (2026-05-18): the
Power & UPS view extracted to views/power.js (T2.1); the 2.5D iso engine
(power_ups_iso/sld/grid/cam) preserved + enriched with the Layer-2 genset
paralleling bus (N+1) → explicit 5-layer Tier IV topology; aggressive
dark-SCADA CSS restyle (skin-only, #sld-iso-stage-scoped); 5 s poll
eradicated → bound to the Hermes telemetry stream (live Kalman Z-score →
node severity); the iso + flat renderers reinvented (orthogonal SVG SLD,
flat 2.5D); L3 control plane — RBAC-gated breaker actuation to
/api/bms/write, isolated What-If DAG simulation sandbox, telemetry
sparklines. Cooling sprint (2026-05-18): the DLC P&ID view extracted to
views/cooling.js, rebuilt as an orthogonal thermodynamic SCADA SLD, +
an L3 control plane (RBAC pump actuation, What-If sandbox, sparklines).
Copilot sprint (2026-05-18): the Facility Co-Pilot agent view extracted
to views/copilot.js — LLM-authored DOM surfaces routed through the F3-5
sanitizeHTML XSS filter, wired to the Hermes hermes:agent-consensus EDA
event. T2.1 monolith-eradication vectors (2026-05-18, post-v0.11.0):
V1 — the BMS Connector view extracted to views/bms.js (showBmsAudit
re-exposed on window so the copilot audit deep-link survives); V2 —
the LOTO Auditor view extracted to views/loto.js (the legacy
click-delegation zombie-router hack retired for core/router.js
registerRoute); V3 — the legacy Site Topology tree+detail view
ADJUDICATED as dead code (force-directed views/site_topology.js owns
the route) and ERADICATED (-277 LOC); V4 — the HLD/LLD Topology view
extracted to views/topology.js (4a), then the Overview/landing
dashboard extracted to views/overview.js + the IIFE residual promoted
to core/bootstrap.js (4b/4c). **EPIC T2.1 IS CLOSED**: app.js DELETED
(4003 → 0 LOC); index.html loads a single ES-module entry point
(main.js). The HMI is fully modular — 12 views/*.js + core/*.js
engines, all routed by the declarative core/router.js. Live backlog =
docs/ROADMAP-V11.md (v11.7, 2026-05-19). NOTE: OBS demo-recording descoped.
```

**Recent commits (latest at top)**:
```
491e9f6  fix(ledger): DC-EPMS-MSD-005 -- coerce UUID->str in PostgresPersistence row->entry
de41703  docs: sync compass -- Epic 4 delivered (Forensic Ledger + Proposer chain)
5b0cb68  feat(bms): Epic 4 -- close Proposer chain + Rollback Harness on /api/bms
89b6930  feat(ledger): Epic 4 -- Forensic Ledger module + migration + 18 tests
07cc39a  docs(adr): ADR-011 -- Forensic Ledger (HMAC-chained, append-only)
ce4059c  docs: sync compass — Epic 3 Batch 3.C delivered (Carbon/Grid agent, 6-agent fleet)
79ed614  feat(ai): Epic 3 Batch 3.C — Carbon/Grid agent (6th member of the multi-agent fleet)
9267667  feat(grid): IESO Ontario grid-intensity mock provider (Epic 3 Batch 3.C prep)
911068b  docs: sync compass — Epic 3 OPEN, Batch 3.A delivered (Capacity Planner)
c132eff  feat(ai): Epic 3 Batch 3.A — Capacity Planner agent (5th member of the multi-agent fleet)
e829cab  docs: sync compass — EPIC 2 CLOSED, v0.13.0 cut
8ce48fb  chore(release): bump internal manifests and documentation to v0.13.0  [tag v0.13.0]
79e8ddd  chore(optimizer): wire to real BMS catalog + Toronto-baseline calibration notes (2.E prep)
4d1a611  feat(optimizer): Epic 2 Batch 2.D — HMI proposal queue view + Hermes WS producer
a567060  docs: sync compass — Epic 2 Batch 2.C delivered (approve/reject endpoints)
18b66b1  feat(optimizer): Epic 2 Batch 2.C — operator approve/reject endpoints with SME_L6 RBAC
7f06871  docs: sync compass — Epic 2 Batch 2.B delivered (consensus + queue + Hermes)
c19e853  feat(optimizer): Epic 2 Batch 2.B — multi-agent consensus + proposal queue + Hermes emission
6366275  docs: sync compass — Epic 2 Batch 2.A delivered (Optimizer core)
6a6c786  feat(optimizer): Epic 2 Batch 2.A — deterministic control law + asyncio scaffold
f24ea94  docs: define Epic 2 — The Optimizer (proactive edge-agent design brief)
502f51b  docs: initialize platform engram and skill registry harness (epic 1 closure)
aa86f8f  docs: sync compass — Epic 1 complete (full 4-agent fleet LLM-augmented)
691fd11  feat(ai): wire Architect agent to Gemma LLM for structural redundancy narratives
d6208ae  feat(ai): wire Analyst agent to Gemma LLM for CapEx/OpEx financial narratives
66115dd  chore(release): bump internal manifests and documentation to v0.12.0  [tag v0.12.0]
7eca2c2  docs: sync compass — Epic T2.1 CLOSED (app.js monolith eradicated)
5ae535d  refactor(ui): eradicate app.js monolith — Overview + bootstrap to ES modules, Epic T2.1 CLOSED (Vector 4b+4c)
f0a9620  refactor(ui): extract HLD/LLD Topology view from monolith (Vector 4a)
1ab76ec  docs: sync compass to T2.1 Vectors 2 + 3 completion
3b98449  refactor(ui): adjudicate and eradicate legacy Site Topology (Vector 3)
fc3ead6  refactor(ui): extract LOTO Auditor view from monolith (Vector 2)
807185e  refactor(ui): extract BMS Connector view from monolith + preserve copilot deep-link (T2.1)
0fb7168  chore(release): bump internal manifests and documentation to v0.11.0  [tag v0.11.0]
38605d3  refactor(ui): extract Copilot AI view from monolith — XSS-sanitized ES6 module (T2.1)
```

## 🛰 [HISTORICAL] Sprint 5 C0 Architecture (delivered — preserved as design record)

> **STATUS 2026-05-16: Sprint 5 fully shipped.** C1-C3 closed at tags
> `v0.7.5-telemetry-stream` → `v0.7.6-kalman-pipeline` → `v0.8.0-sprint5-kalman`;
> C3.5 MOPs bundled. The telemetry simulator + Kalman pipeline + per-channel YAML
> calibration are all LIVE in `backend/` and wired into `/api/telemetry/stream`.
> Everything below is the original C0 1-pager, kept ONLY as a historical design
> record — do NOT treat its "What's MISSING / to build" lists as open work.
> Current roadmap is `docs/ROADMAP-V11.md` (locked 2026-05-10).

### Architectural intent

DC-EPMS PRO Sprint 5 wires the dormant `cyber_physical_tools.py` orphan into a live telemetry pipeline that:
- emits synthetic 67 MW Path C2 measurements distinguishing Phase 1 (480 VAC trifásico, 118 GB200 racks) from Phase 2 (800 VDC unipolar TN-S, 250 GB300 racks).
- compresses 12x at steady state via Send-on-Delta (ASHRAE TC 9.9 ±1 K tolerance).
- forwards only Kalman innovation residuals to the LLM agent (information-theoretic minimality: ODE-explained behaviour is filtered locally).
- completes µs-grade per-channel decision via Numba `@njit` native compile, with pure-Python fallback already wired for AMD Ryzen + Windows hardware quirks.

### What `cyber_physical_tools.py` already provides (orphan, ready to wire)

| Symbol | Type | Behaviour |
|---|---|---|
| `send_on_delta_mask()` | `@njit` | Lebesgue temporal compression. Mutable `last_emitted[0]` anchor across batches. `SEND_ON_DELTA_K=0.5` K (ASHRAE-justified, sits below 1 K SLA breach, above 0.05 K PT100 noise floor). |
| `kalman_innovation_step()` | `@njit` | Scalar discrete Kalman per channel. Returns `(innovation, innovation_var, normalized_z)`. Mutates `x_hat[0]`, `P[0]` in place. Standard short-form P-update. |
| `get_telemetry_payload()` | composed | Cold-start init: `R=0.05² K²` (PT100), `F=exp(-dt/60)` (tau=60s default), `P_0=10R`. Returns per-channel `{n_emissions, max_z, mean_z, is_anomalous, last_emission}`. NO raw arrays leak to LLM. |
| `ANOMALY_Z_THRESHOLD` | constant | 3.0 (3-sigma rule). |
| Numba fallback | guarded | `try: from numba import njit; except: noop_decorator`. Module imports clean even on hardware where Numba misbehaves. |

### What's MISSING (Sprint 5 to build)

1. **Synthetic stream generator** — no equivalent exists. Must produce raw samples per channel, baselined on Path C2 spec.
2. **Process-singleton `filter_state` persistence** across SSE ticks (currently only documented in `cyber_physical_tools` tuning notes).
3. **Endpoint replacement** of `/api/telemetry/stream` (currently a 5-second DB-poll placeholder at `main.py:459-491`).
4. **Per-channel Q/R/F YAML config** (currently hard-coded in tuning notes lines 287-313 of `cyber_physical_tools.py`).

### Channel inventory (Path C2 fidelity — vocabulary fence enforced)

| Domain | Phase 1 channels (deployed Buildings A/B) | Phase 2 channels (Building D Q2 2026) |
|---|---|---|
| IT thermal | `rack_inlet_T` (118× GB200), `gpu_Tj` (118×), `dlc_supply_T`, `dlc_return_T` | `rack_inlet_T` (250× GB300), `gpu_Tj` (250×), `dlc_supply_T_12vdc` (DLC retrofit) |
| Mechanical | `chiller_LWT` (3-4× York YZ N+1), `pump_NPSH_margin`, `q_secondary_kW` per hall, `q_primary_kW` | same + Building D DLC pumps |
| Electrical | `ups_a_soc`, `ups_b_soc`, `ats_state`, `voltage_v_phase_ab`/`bc`/`ca` (480 VAC trifásico, balanced ±1%), per-rack `voltage_v`, `batt_runtime_min` | `voltage_v_dc_bus` (800 VDC unipolar — **SINGLE channel, NO phases**), `mv_rectifier_output_v`, `bess_soc` (2.5 MWh), `sscb_clearing_us` |
| Heat rejection | `ecwt_c`, `outdoor_wet_bulb_c`, `cop_per_chiller` | same |

**Vocabulary fence (CRITICAL for CO+I panel credibility)**: Phase 1 voltage telemetry uses 3-channel AC schema (V_AB / V_BC / V_CA). Phase 2 voltage telemetry uses 1-channel DC schema (V_dc_bus). NEVER label Phase 2 fields as "trifásico" — the 800 VDC bus is unipolar TN-S. Schema names must encode polarity.

### Pipeline flow (Sprint 5 end state)

```
site_model.yml inventory
    ↓
telemetry_simulator.py (NEW C1, ~250 LOC)
    ├─ steady-state baselines per Path C2 spec
    │     - GB200 rack inlet 22-24 °C, gpu_Tj 60-75 °C
    │     - GB300 rack inlet 22-24 °C, gpu_Tj 70-80 °C (DLC retrofit)
    │     - DLC supply 30-32 °C, chiller LWT 6-8 °C rated
    │     - 480 VAC trifásico: V phase ≈ 480 V ± 1%, balanced
    │     - 800 VDC unipolar: V_dc_bus ≈ 800 V ± 0.5% (tighter regulation by design)
    │     - SSCB clearing target ∈ [1, 100] µs per IEC 60947-2 + IEC TR 63282 §5.2
    ├─ bounded noise (PT100 R=0.05²K², thermistor R=0.5²K²)
    └─ injectable anomalies (thermal runaway / pump cavitation / phase imbalance / DC bus drop / SSCB event)
    ↓
channel_window: dict[ch_id, np.ndarray]  (per tick)
    ↓
get_telemetry_payload()  in cyber_physical_tools.py  (orphan→live)
    ├─ Stage 1: send_on_delta_mask    → ~12x compression at steady state
    └─ Stage 2: kalman_innovation_step → per surviving emission, scalar Kalman
    ↓
compact payload {ch_id: {n_emissions, max_z, mean_z, is_anomalous, last_emission}}
    ↓
SSE /api/telemetry/stream  (REPLACE main.py:459-491 placeholder; legacy DB fallback retained)
    ↓
HMI heat map + agent_copilot anomaly tools
```

### Module layout

| File | Status | Purpose |
|---|---|---|
| `backend/cyber_physical_tools.py` | EXISTS (orphan) | `@njit` hot path: SoD + Kalman. Untouched in C1; integrated in C2. |
| `backend/telemetry_simulator.py` | NEW (C1, ~250 LOC) | Synthetic stream from `site_model.yml`. NO physics dependency — just baselines + noise + anomaly injection. |
| `backend/telemetry_pipeline.py` | NEW (C2, ~180 LOC) | Glue: simulator ⊕ `cyber_physical_tools`. Persists `filter_state` singleton. Exposes `get_payload_async()`. |
| `backend/main.py:459-491` | REWRITE (C2/C3) | `/api/telemetry/stream` now drives from pipeline. Legacy DB-fallback path retained behind feature flag. |
| `config/telemetry_channels.yml` | NEW (C3) | Per-channel `Q`, `R`, `F` (tau) calibration. Replaces hard-coded defaults. |
| `tests/test_telemetry_simulator.py` | NEW (C1, ~6-8 tests) | Inventory coverage, anomaly injection, deterministic seed. |
| `tests/test_telemetry_pipeline.py` | NEW (C2, ~6-8 tests) | Cold start, steady-state suppression, anomaly detection, multi-channel state isolation. |
| `tests/test_telemetry_perf.py` | NEW (C3, 1-2 tests) | Numba JIT cold→hot timing. Target: cold <500 ms, hot <100 µs/step. |
| `tests/test_dc_epms_029b_resolution.py` | NEW (C2 closure) | Re-run `simulate_loto_measurements` with simulator-driven physics input. Assert SHI delta. |

### Equinix-scale + Orbital fidelity considerations

- **Per-channel state isolation**: each channel owns `(x_hat, P, Q, R, F, last_emitted)`. Memory cost ~40 bytes per channel. Scales to 10K+ channels (Equinix-class fleet) without quadratic blowup.
- **Send-on-Delta as orbital uplink discipline**: 12x bandwidth reduction at steady state is critical for LEO satellite telemetry windows (limited contact time, high latency to ground). The same compression that saves API tokens here saves spectrum on orbital downlinks.
- **Innovation residual as cross-orbit anomaly signal**: ODE-explained behaviour is filtered locally; only anomalies traverse the network. ADR-006 Deterministic Sandbox compatible (edge-local explanation, no cloud round-trip required for normal operation).
- **Numerical stability for long-running orbital nodes**: current Kalman P-update form `(1.0 - K*H) * P_predict` is the standard short-form. For multi-month uninterrupted runs, the Joseph form `(I - K*H) P (I - K*H)^T + K R K^T` would preserve symmetry / positive-definiteness more robustly. Defer to V10 unless precision drift observed during C3 perf testing.
- **Bus polarity awareness**: simulator must encode 480 VAC trifásico (3 phases, 120° apart, balanced ±1%) DISTINCTLY from 800 VDC unipolar (1 channel, ±0.5% tighter regulation by design). Schema names: `voltage_v_phase_ab/bc/ca` for AC, `voltage_v_dc_bus` for DC. CO+I panel credibility hinges on this fence.
- **SSCB µs decision metric (Phase 2)**: synthetic clearing events with latency ∈ [1, 100] µs band per IEC 60947-2 + IEC TR 63282 §5.2. Phase 2 simulator emits these as discrete µs samples, not 1 Hz rolling.

### Atomic batch ladder (C1 → C2 → C3)

| Batch | Effort | Output | Tag | Bug resolved |
|---|---|---|---|---|
| C0 (DONE 2026-05-09) | 15 min | 1-pager architecture. No code. | — | — |
| C1 (DONE 2026-05-09) | 1.5 h | `telemetry_simulator.py` (354 LOC) + 17 tests + SSE wiring with feature flag `DC_EPMS_USE_SIMULATOR` | `v0.7.5-telemetry-stream` | — |
| C2 (DONE 2026-05-09) | 2 h | `telemetry_pipeline.py` (172 LOC) + 12 tests + per-channel R/Q calibration + F=1 random-walk model + 60-min anomaly counter wired to frontend Activity Strip | `v0.7.6-kalman-pipeline` | DC-EPMS-029b (deferred, see notes below) |
| C3 (DONE 2026-05-09) | 1.5 h | `config/telemetry_channels.yml` (17 metrics calibrated) + `TelemetryChannelConfig` loader + 11 config tests + 4 perf tests (Numba JIT cold 4.8 ms, hot 5.1 ms / window, per-step 4.3 us) | `v0.8.0-sprint5-kalman` | DC-EPMS-037 RESOLVED |
| C3.5 MOPs (DONE 2026-05-09) | 1 h | `config/procedures/T4-MOP-CHI-001.yml` (19 steps, 6h chiller PM) + `config/procedures/T4-MOP-UPS-001.yml` (17 steps, 4h UPS PM) + 26 schema/provenance tests. Decision 4-B closed. | (no tag — bundled) | — |

**Note**: tag scheme renamed mid-flight to avoid `v0.7.4-*` namespace
collision with `v0.7.4-frontend-pivot` (Sprint 5.5 hybrid milestone,
shipped 2026-05-09 between C0 and C1). C1 closure is now `v0.7.5-*`,
C2 is `v0.7.6-*`, C3 final stays at `v0.8.0-*`.

**C2 surfaced TWO design issues in cyber_physical_tools.py orphan that
required pipeline-side overrides** (documented as DC-EPMS-037 in bugs
registry):

1. Cold-start R = 0.05^2 K^2 was calibrated only for PT100 thermal
   sensors. Voltage / pressure / flow channels with native std orders
   of magnitude larger were producing 92% false-positive anomaly rate.
   Pipeline pre-initializes filter_state with R = std^2 read from
   `telemetry_simulator.PHASE1_BASELINES`.

2. Default F = exp(-dt/60) modeled exponential decay toward zero, but
   simulator emits stationary signals around constant baselines. With
   F<1 the Kalman x_hat converged to non-physical equilibrium between
   decay and observation (e.g. tracking 480V UPS as 401). Pipeline
   pre-initializes F=1.0 (random-walk tracker) for stationary signals.

DC-EPMS-029b (SHI delta in simulate_loto_measurements) was originally
predicted to resolve naturally during C2. It does NOT — simulate_loto
is independent of the simulator/pipeline path. Resolution requires a
new translation layer (channel-level samples -> physics_engine
measurements format) that maps simulator output to the thermal fields
physics_engine.validate_site() expects. Deferred to a dedicated bite
post-C3 or to V10.

### Risks + countermeasures

- **Numba `@njit` fails on AMD Ryzen + Windows** (FAISS-style hardware bug DC-EPMS-001 lineage). Counter: orphan already has `try/except` fallback to pure Python; functionality preserved, performance degraded. Detect at C3 perf test; document as DC-EPMS-NNN if fired.
- **Synthetic stream drift from real Path C2 specs erodes credibility**. Counter: cite NVIDIA GB200 / GB300 thermal specs, Schneider Galaxy VX datasheet, York YZ chiller curves in module docstrings. Reviewable.
- **DC-EPMS-029b doesn't actually resolve naturally**. Counter: explicit reproducer test in C2 closure. If not resolved, opens DC-EPMS-029c targeted at `simulate_loto_measurements` specifically.
- **DC-EPMS-036** (4 pre-existing pillar mock failures) blocks pytest aggregate. Counter: out of Sprint 5 scope; resolved separately. C2 may incidentally align mocks if simulator surface matches `SiteValidationResult` shape, but not guaranteed.

### Entry conditions for C1 (when resuming next session)

1. Working tree clean (`git status` shows only `.claude/`, `DEMO_SCRIPT.md`, `PRIMER_PROMPT.md` untracked — these are intentional).
2. `epms-db` Docker container healthy (`docker ps`).
3. Backend uvicorn accessible at http://127.0.0.1:8080 — **restart needed** if stale (B2 `loto_auditor_agent.py` patch not yet active in running process).
4. `.venv` activated: `.\.venv\Scripts\Activate.ps1`.
5. This section reread; no shortcuts.

### Success criteria for C2 closure (DC-EPMS-029b natural resolution proof)

- Test `tests/test_dc_epms_029b_resolution.py` exists.
- It instantiates `LotoAuditorAgent` with simulator-driven `physics_engine` input populating thermal fields (`hall_inlet_temp_c`, `chiller_supply_temp_c`, `cdu_pressure_bar`).
- Asserts `shi_pre != shi_post` (delta > 0.01 for a non-trivial LOTO event on `ups_a` or equivalent target).
- Pillar 4-5-6 tests remain GREEN (no regression on B2 fix).

### Out of scope (explicitly deferred)

- Real PostgreSQL TimescaleDB persistence of innovation history → Sprint 6+.
- HMI heat map UI for `is_anomalous` flag rendering → Sprint 5.5a.
- Joseph-form Kalman P-update → V10 if precision drift observed.
- Physical I/O (BACnet / Modbus) ingest → Phase 2 hardware integration.
- Resolving DC-EPMS-036 mock drift in `tests/test_loto_auditor_pillars.py` → separate surgical batch.

## 🏗️ ARCHITECTURE

### Directory layout
```
C:\dev\DC-EPMS_PRO\
├── backend/                     ← FastAPI + asyncpg — 40+ modules
│   ├── main.py                  ← central hub, ~50+ endpoints, lifespan boot
│   ├── physics_engine.py + physics/   ← facade + 4 first-principles modules (it_thermal, mechanical, electrical, heat_rejection)
│   ├── agent_copilot.py / agent_engine.py        ← primary tool-calling agent + dual-AI fallback (NeMo + Sonnet)
│   ├── agent_site_tool.py / agent_graph_tool.py  ← agent tools (site model, GraphRAG)
│   ├── multi_agent.py / multi_agent_routes.py    ← Sprint 10.1 façade (4 agents + Safety Officer veto)
│   ├── procedure_engine.py / witness_engine.py   ← MOP 8-state machine + multi-signature drafts
│   ├── procedure_generator.py / procedure_routes.py  ← SOP/MOP/EOP/EMP factories + recursive micro-LOTO + RBAC gates (post-v0.10.13)
│   ├── cmms_*.py                ← Sprint 6 CMMS Core: mcp, models, repository, routes, seeder, predictive_trigger, site_enrichment
│   ├── loto_auditor_*.py        ← 6-pillar validator: agent, models, pillar_helpers, report_renderer, repository, routes
│   ├── telemetry_simulator.py / telemetry_pipeline.py / cyber_physical_tools.py  ← Sprint 5 Kalman pipeline (WIRED, live)
│   ├── site_model.py / site_routes.py            ← declarative YAML parser + /api/site/*
│   ├── graphrag_service.py / graphrag_index.py / graphrag_routes.py / knowledge_graph.py  ← GraphRAG (NetworkX + FAISS)
│   ├── rag_service.py           ← ChromaDB primary, 20-doc 4-tier operational corpus
│   ├── shift_report.py          ← PDF shift report via /api/shift/report
│   ├── database.py / bms_connector.py / metrics_router.py  ← persistence + BMS stub + Prometheus
│   ├── migrations/              ← SQL migrations (e.g. 2026_05_W3_g1_taxonomy.sql — taxonomy + Arc Flash columns)
│   ├── mcp_server.py            ← Claude Desktop stdio subprocess
│   └── hal/                     ← Cummins, ASCO, Russelectric adapters
├── frontend/                    ← Production-grade HMI (fully modular ES — T2.1 closed, no IIFE)
│   ├── index.html               ← entry; loads a single ES-module entry point (js/main.js)
│   └── assets/
│       ├── app.css              ← stylesheet (the app.js IIFE was eradicated — T2.1 Vector 4)
│       ├── js/main.js           ← the single ES-module entry point
│       ├── js/core/             ← engines: router, bootstrap, telemetry_engine, hermes_events, power_sld/grid/cam, pue_widget, shi_sparkline, heat_overlay, activity_strip, state, sound, keyboard, staleness, sanitize, asset_metadata
│       ├── js/views/            ← 12 views: overview, topology, mission_control, site_topology, rack_heatmap, maintenance, asset_panel, tech_assist, multi_agent, power_ups_iso, scenarios, incidents, mops, power, cooling, copilot, bms, loto
│       └── vendor/              ← chart.umd 4.4.1 + three.module.min.js (local, no CDN)
├── config/
│   ├── site_model.yml           ← 91 components (50 racks Phase 1; DDU/busway expanded v0.10.11)
│   ├── telemetry_channels.yml   ← per-channel Kalman R/Q/F calibration (Sprint 5 C3)
│   ├── pue_targets.yml          ← architecture-aware PUE thresholds (Sprint 5.5b)
│   ├── procedures/              ← executable MOP YAMLs (T4-MOP-CHI-001, T4-MOP-UPS-001, ...)
│   ├── knowledge/               ← GraphRAG markdown docs
│   ├── .env                     ← secrets + PG creds (gitignored — see DC-EPMS-DB-001)
│   └── bms_tags.yml / scenarios.yml / paperclip_org.yml / config.yml
├── data/
│   └── chroma_db/               ← 20-doc 4-tier corpus (Safety/Vendor/Standards/MOPs)
├── tests/                       ← 30+ files, 690 tests (`pytest -m "not slow"`)
├── docs/
│   ├── adr/                     ← 9 ADRs (MADR format; ADR-010 = dual-graph taxonomy)
│   ├── ROADMAP-V11.md           ← live backlog (locked 2026-05-10)
│   └── architecture/sre_layers.md
├── scripts/
│   └── _archive/                ← Session helpers archive
├── CHANGELOG.md
├── pyproject.toml               ← PEP 621, 10 extras
├── pytest.ini
├── .pre-commit-config.yaml      ← 17 hooks
└── docker-compose.yml
```

### Key endpoints (~50 total)

**Health + telemetry**: `/api/health`, `/api/telemetry`, `/api/telemetry/stream` (SSE)
**Site model**: `/api/site/components`, `/api/site/loto-impact/{id}`, `/api/site/health`
**GraphRAG**: `/api/graph/query`, `/api/graph/loto`, `/api/graph/upstream`
**RAG**: `/api/rag/query`, `/api/rag/docs`
**LOTO Auditor** (4 endpoints under `/api/loto`): `POST /api/loto/audit`, `GET /api/loto/audit/{audit_id}`, `GET /api/loto/audit/{audit_id}/markdown`, `GET /api/loto/audits/recent`
**Procedures**: `/api/procedures`, `/api/procedures/{id}/execute`
**CMMS**: `/api/cmms/draft`, `/api/cmms/drafts/{id}`, `/api/cmms/approve/{id}`
**Witness**: `/api/witness/sign`, `/api/witness/drafts`
**Agent Copilot**: `/agent/stream` (SSE)
**MOPs**: `/api/mops` + `/api/mops/{doc_id}` + `/api/mops/generate`
**Procedure Generator** (post-v0.10.13, via `procedure_routes.py`, commit `11861dc`): SOP/MOP/EOP/EMP generation + RBAC promotion-gate routes

### LOTO Auditor 6-Pillar architecture

| Pillar | Function | Status |
|---|---|---|
| 1 | Topology + GraphRAG impact radius | ✅ FIXED (DC-EPMS-030/031/032) |
| 2 | Redundancy 2N validation | ✅ FIXED (DC-EPMS-029) |
| 3 | Capacitor discharge per NEC 460.6 | ✅ Working |
| 4 | Witness Gate per CSA Z462 | ✅ FIXED (DC-EPMS-034) |
| 5 | Cooling chain check | ✅ Working |
| 6 | PPE matrix per NFPA 70E | ✅ FIXED (DC-EPMS-033) |

## 🐛 BUGS REGISTRY

### Closed in v0.7.3-sprint5-patches (2026-05-09)
- **DC-EPMS-029** (HIGH): Pillar 2 SHI calculation (`pre_validation.get` vs `.site_health` attribute)
- **DC-EPMS-029a** (LOW): SHI threshold calibration (was already 0.5, NO-OP)
- **DC-EPMS-FE-001** (MED): Path C2 drift in frontend (40 MW to 67 MW total, v4.0 to v8.1.0)
- **DC-EPMS-FE-002** (LOW): LOTO Auditor view ausente in HMI
- **DC-EPMS-033** (MED): voltage_v fallback in get_voltage_nominal (site_model.yml uses voltage_v for switchgear/transformer)
- **DC-EPMS-030** (MED): cooling_chain_for() doesn't exist; replaced with impact_set(chain="cooling")
- **DC-EPMS-031** (MED): query_topology() doesn't exist; replaced with loto_with_knowledge(target_id)
- **DC-EPMS-032** (LOW): walk direction polarity comment block

### Closed in v0.10.12 / v0.10.13 (2026-05-15)
- **DC-EPMS-MAINT-001** (LOW, cosmetic/race) — RESOLVED v0.10.12 (`409e695`).
  Maintenance nav-click flicker: legacy IIFE `MODULES` dict in `app.js` had no
  `maintenance` key, so `navigateTo('maintenance')` hit the `!cfg` fallback and
  flashed `view-overview` before `views/maintenance.js` re-routed. Fix: declared
  `MODULES.maintenance` + dedicated `navigateTo` branch.
- **DC-EPMS-MAINT-002** (MED, functional regression from v0.10.9) — RESOLVED
  v0.10.12 (`409e695`). Asset-panel "Open in Maintenance" handoff dead:
  `asset_panel.js` set `sessionStorage.cmms_focus_asset_id` but
  `views/maintenance.js` never read it. Fix: `_consumeFocusHandoff()` reads +
  clears the key, applies `asset_id` filter, renders a FOCUS banner.
- **DC-EPMS-MAINT-003** (MED) — RESOLVED v0.10.13 (`7f6ea55`). Closure modal
  would not close ("zombie modal"): `app.css .m-modal-overlay` used
  `display: flex`, overriding the UA `[hidden]{display:none}` on specificity.
  Fix: `.m-modal-overlay[hidden]{display:none !important}` + inline validation
  UX (shake/hint, replacing silent `alert()`) + force-close on 200 OK.

### Closed in this session (2026-05-16 / 05-17)
- **DC-EPMS-DB-001** (HIGH, environmental) — RESOLVED 2026-05-16. Backend
  reported `postgres: down` despite a healthy `epms-db` container. Root cause:
  the container was (re)provisioned with `docker-compose.yml` credentials
  (`POSTGRES_USER=epms`, `POSTGRES_DB=dcepms`) while `backend/main.py` defaults
  remained `postgres`/`epms` — a role + database that never existed. The app
  ran in silent degraded mode (CMMS boot skipped). Fix: added `PG_HOST/PG_PORT/
  PG_DB/PG_USER/PG_PASSWORD` to `config/.env` (gitignored, local-only). On
  restart: `PostgreSQL connected to database 'dcepms'`, 91 assets re-seeded.

- **DC-EPMS-040** (HIGH, deployment) — RESOLVED 2026-05-17. `GET
  /api/cmms/assets` returned HTTP 500 for every caller (Maintenance, Rack
  Heatmap, Mission Control) after the ProcedureGenerator sprint (bites
  G1-G6). Root cause: the W3 migration (`backend/migrations/2026_05_W3_
  g1_taxonomy.sql`) was applied to the live `dcepms` database — adding 5
  columns to `assets` (`asset_level`, `parent_asset_id`, `fault_current_
  ka`, `incident_energy_cal`, `arc_flash_boundary_m`) — while the backend
  process kept running pre-G1 code. `cmms_repository.list_assets_async`
  does `SELECT * FROM assets`; `_row_to_asset` calls
  `Asset.model_validate(row)`; the stale `Asset` model has
  `ConfigDict(extra="forbid")` and no knowledge of the 5 new columns →
  `ValidationError` → `CMMSRepositoryError` → HTTP 500. The schema moved
  ahead of the running code. Fix: restart the backend — the current
  `Asset` model carries the 5 fields (added in G1) and is consistent with
  the W3-migrated schema. No code change. **Rule (lesson):** applying a
  schema migration to a live DB MUST be paired with an app restart in the
  same step — a migration is not truly "applied" until the running
  process is reloaded against the new schema.

- **F3-1 / F3-2 / F3-3** (CRITICAL, security) — RESOLVED 2026-05-17 (`b34efb1`).
  The E2E security audit (`39f217e`; `docs/audit/E2E_Security_Orphan_Audit.md`)
  found 3 CRITICAL RBAC gaps — CMMS approve/reject, procedure/witness routes,
  and `/api/bms/write` had no role enforcement. Fix: `assert_can_approve_work_
  order` on approve/reject, `_require_actor_role` helper on the proc/witness
  routers, SME_L6 gate on BMS-write. Frontend `actor_role` payload synced in
  `169457f`. The audit's WARNING-tier findings remain open.

- **Dead-code eradication** — DONE 2026-05-17 (`d495c7b`). Purged 4 confirmed-
  orphan files (`dpo_edge_healing.py`, `cmms_mcp.py.design-artifact`,
  `frontend/site_topology_view.html`, `archive/app.js.legacy`; -5706 LOC) and
  resolved the DC-EPMS-039 test-suite hang. The DPO file is recoverable from
  git history if V11 T3.8 revives it.

### Closed in Epic 4 (2026-05-23)

- **DC-EPMS-MSD-001** (CRITICAL) — RESOLVED 2026-05-23.
  Forensic Ledger module (`backend/ledger/forensic_ledger.py`) added per
  ADR-011. HMAC-SHA256 chained entries, append-only, key-version-aware,
  with `InMemoryPersistence` (tests) + `PostgresPersistence` (production).
  `verify_chain()` returns the divergence index on tamper, `None` clean.
  IEC 62443-3-3 SR 6.1 / 6.2 / NIST SP 800-53r5 AU-9 / AU-10 satisfied
  at the construction level.

- **DC-EPMS-MSD-002** (CRITICAL) — RESOLVED 2026-05-23.
  Migration `backend/migrations/2026_05_W4_forensic_ledger.sql` adds
  `ledger_entries` table with `BEFORE UPDATE / BEFORE DELETE / BEFORE
  TRUNCATE` triggers raising exceptions (DB-side immutability), CHECK
  constraints on HMAC length, gapless `BIGSERIAL sequence_no`,
  TimescaleDB hypertable when the extension is present. NOT
  auto-applied (DC-EPMS-040 lesson) — operator runs `psql -f` then
  restarts; until then the lifespan falls back to InMemoryPersistence
  with a loud WARNING. The `bms_connector.write_audit_log[-200:]`
  ring buffer remains as a non-authoritative informational view (the
  legacy `/api/bms/audit` endpoint docstring now points readers to
  `/api/ledger/entries` for the binding record).

- **DC-EPMS-MSD-003** (CRITICAL) — RESOLVED 2026-05-23.
  `/api/bms/write` (`backend/main.py`) now accepts an optional
  `proposal_id`; when provided it MUST resolve to an `approved` row
  in the Optimizer `ApprovalLog` with matching `bms_tag_id` (HTTP 404
  / 409 otherwise). The Optimizer approve path (`optimizer_routes.
  approve_proposal`) stamps `proposal_id` into the ledger entry via
  `backend.ledger.set_proposal_context()` and dispatches the seam
  call via `asyncio.to_thread`. Skill `S-PROPOSER-01` added.

- **DC-EPMS-MSD-004** (CRITICAL) — RESOLVED 2026-05-23.
  `POST /api/bms/revert/{entry_id}` (SME_L6) added. Reads the original
  `BMS_WRITE_REQUESTED` ledger entry, extracts `tag_id` + `prev_value`,
  appends a `BMS_REVERT` marker capturing the causal link (`reverts_
  entry_id`, `from_value`, `restoring_value`, `reason`), then executes
  the counter-write through the same wrapped seam (creating its own
  `BMS_WRITE_REQUESTED` + `BMS_WRITE_RESULT` pair with
  `source="revert"`). Revert-of-revert is allowed; the chain captures
  the full causal graph. IEC 62443-3-3 SR 7.3 / SR 7.4 satisfied.

- **DC-EPMS-MSD-005** (HIGH) -- RESOLVED 2026-05-23 (`491e9f6`).
  `/api/ledger/verify` returned HTTP 500 against Postgres-backed
  deployments. Root cause: asyncpg deserialises the `entry_id` UUID
  column to `asyncpg.pgproto.pgproto.UUID` (native Python UUID-like
  object, NOT `str`). `_compute_hmac()` calls `.encode("utf-8")` on
  it -- which exists on `str` but raises `AttributeError` on the
  asyncpg UUID type. Pre-fix, the WRITE path worked (entry_id is
  freshly generated as `str`), but every `verify_chain()` call
  against the Postgres backend exploded on the first entry it
  touched. The 18 unit tests in `test_forensic_ledger.py` ONLY
  exercise `InMemoryPersistence` (its own docstring admits the gap)
  so the bug never surfaced in CI -- a **false-positive test gate**.
  Discovered during the post-restart runtime smoke after applying
  the W4 migration. Fix: one line in `_row_to_entry` coerces
  `entry_id=str(row["entry_id"])` at the asyncpg boundary so the
  `LedgerEntry.entry_id: str` dataclass contract holds uniformly
  across persistence backends. No defence-in-depth in `_compute_hmac`
  -- per CLAUDE.md "trust internal code; validate only at boundaries"
  the seam is the right place. Added
  `tests/test_forensic_ledger_postgres.py` (4 integration tests in a
  per-PID isolated schema, `DROP SCHEMA CASCADE` teardown, skip if
  asyncpg / epms-db unreachable) to close the false-positive gap.
  Floor moves pytest 871 -> 875.

### Open / Deferred

**DC-EPMS-029b** (MED) - RESOLVED 2026-05-09 (Sprint 5 follow-up, commit pending)
- Symptom: `simulate_loto_measurements` produced `shi_pre == shi_post` (no delta).
- Root cause: `build_steady_state_measurements` and `simulate_loto_measurements`
  operated on virtual fields (chiller_count_online, ups_a_online,
  hall_inlet_temp_c) that physics modules did NOT read. Physics modules
  consume canonical fields like chiller_X_load_kw, ups_mode, dlc_supply_c,
  loop_flow_m3_s. The two namespaces were disjoint.
- Fix: build_steady_state_measurements now also includes physics-canonical
  fields (electrical, mechanical, heat_rejection inputs). simulate_loto_
  measurements modifies BOTH legacy redundancy fields (Pillar 2 SPOF
  detection) AND canonical physics fields per LOTO type. Verified by
  14/14 tests/test_dc_epms_029b_resolution.py — at least 2 LOTO types
  (UPS, CDU) produce SHI delta > 0.05.

**DC-EPMS-029c** (LOW) - NEW (opened 2026-05-09 during DC-EPMS-029b closure)
- Symptom: physics_engine.validate_site() pass/fail thresholds insensitive
  to several LOTO scenarios. Even when simulate_loto correctly modifies
  physics-canonical fields per chiller/cooling_tower/chw_pump/RPP LOTO,
  the per-module health does not move because the modifications stay
  inside the broad acceptance band of the module's checks.
- Examples: chiller LOTO zeros chiller_1_load_kw and doubles chiller_2,
  but heat_rejection.cop_vs_curve still passes because COP=load/power
  is recomputed from the doubled values and stays in spec.
  cooling_tower LOTO raises ECWT +6 C but heat_rejection accepts a wide
  ECWT range. RPP LOTO halves utility_kw + ups_input_kw + xfmr_load_kva
  but electrical's checks evaluate ratios that stay in spec.
- Runtime impact: NONE. simulate_loto output is structurally correct;
  only the SHI rollup is unreactive for some LOTO types. UPS and CDU
  LOTO scenarios DO produce SHI delta, sufficient for demo and audit.
- Resolution path: tune physics_engine module checks to be more sensitive
  to LOTO-relevant deltas. Either (a) lower the pass thresholds, (b) add
  new checks specifically for LOTO scenarios, or (c) introduce a "loto_
  mode" multiplier in validate(). Effort: 2-3h surgical work in each of
  the 4 physics modules. Target: V10 or dedicated bite post-Sprint 5.

**DC-EPMS-034** (LOW) - RESOLVED 2026-05-09 (commit pending Phase B closure)
- Symptom: `witness_engine_protection: "engine present but interface unknown"` in Pillar 4
- Root cause: helper in `backend/loto_auditor_agent.py:_check_witness_engine_protection`
  looked for 3 method names (`get_protection_status`, `is_identity_collision_protected`,
  `validate_signer_identity`) that do not exist on the canonical `WitnessStore` instance
  injected by `backend/main.py:2218`.
- Fix: extended helper to recognize WitnessStore canonical interface (triple-attr
  duck-type `sign + create + reject` with `inspect.signature(sign)` parameter
  verification to guard against false positives) and WitnessGate interface
  (`await_witness + store`). Legacy named methods preserved for forward compat.
- Verified: 5/5 smoke tests pass (real WitnessStore, None, unknown, false-positive
  guard, legacy method). Pillar 4-5-6 test suite: 14/14 GREEN.

**DC-EPMS-036** (MED) - RESOLVED 2026-05-09 (commit pending)
- Original symptom: 4 tests in `tests/test_loto_auditor_pillars.py` failed on HEAD:
  test_pillar1_graphrag_inconsistency_noted_not_failed,
  test_pillar1_cooling_chain_integration,
  test_pillar2_happy_path_path_a,
  test_pillar2_shi_below_threshold_hard_fail.
- Root cause: test fixtures expected pre-fix Pillar 1 / Pillar 2 behavior.
  When DC-EPMS-029, DC-EPMS-030, DC-EPMS-031 fixed production code, the test
  mocks were not updated.
- Fix surfaces in mocks:
  1. `MockSiteModel.impact_set(canonical_id, chain="cooling")` added (production
     uses this since DC-EPMS-030).
  2. `MockGraphRAG.loto_with_knowledge(target_id)` added; `query_topology` retained
     as legacy alias (production uses loto_with_knowledge since DC-EPMS-031).
  3. `MockPhysicsEngine.validate_site()` returns object with `.site_health` attribute
     instead of `{"site_health_index": v}` dict (DC-EPMS-029 fix).
  4. Test bound updates: `shi_threshold == 0.7` -> `== 0.5` (DC-EPMS-029a calibration);
     `shi_post=0.5` -> `0.4` to be clearly below threshold for HARD_FAIL test.
- Verified: 18/18 test_loto_auditor_pillars.py GREEN. Full pytest aggregate:
  497 passed, 5 deselected (FAISS slow, DC-EPMS-001), 1 unrelated error in
  test_smoke (DC-EPMS-039, pre-existing).

**DC-EPMS-039** (LOW) - RESOLVED 2026-05-17 (cosmetic facet `ebefdb6` + hang facet `d495c7b`)
- Symptom: `tests/test_smoke.py::test_health_endpoint_reachable` errors during
  fixture setup (NOT test logic). Captured logs show:
  1. `[v8] Agent Copilot mount failed: Field "model_id" in ChatResponse has
     conflict with protected namespace "model_"` (Pydantic v2 deprecation).
  2. `PostgreSQL init failed: [WinError 1225] The remote computer refused the
     network connection` (epms-db Docker reachability flaky during pytest bootstrap).
  3. `chromadb.telemetry.posthog: capture() takes 1 positional argument but 3
     were given` (chromadb version incompatibility with installed posthog).
- Verified pre-existing on clean HEAD via `git stash` test — NOT caused by
  DC-EPMS-036 fix.
- Runtime impact: smoke endpoint is reachable in production; only test setup
  pathway hits these errors due to import ordering.
- Resolution: (a) add `model_config = ConfigDict(protected_namespaces=())` to
  ChatResponse, (b) wrap PostgreSQL init in test fixture with retry/skip,
  (c) suppress chromadb telemetry. Effort: 30 min surgical. Target: V10.

- RESOLUTION (2026-05-17) — two facets, both closed:
  1. Cosmetic facet — `ebefdb6` resolved the Pydantic `model_id` protected-
     namespace conflict (restoring the Copilot mount), silenced chromadb
     posthog telemetry, and fixed the log-file handle leak (this also closes
     DC-EPMS-019).
  2. Hang facet — `d495c7b` found the real suite-killer: `test_smoke.py`'s
     `client` fixture used `with TestClient(app)`, triggering the full app
     lifespan (~35s GraphRAG pre-warm + LM-Studio probes) → indefinite freeze.
     Fixed by dropping the lifespan (plain `TestClient(app)`; the smoke tests
     are graceful-degradation checks needing no backend state). Full untargeted
     pytest now: 690 passed, 0 fail, 41s, no hang.

**DC-EPMS-037** (LOW) - RESOLVED 2026-05-09 in Sprint 5 C3 (commit pending)
  Per-channel calibration moved to `config/telemetry_channels.yml`. Pipeline
  loads YAML at init via `TelemetryChannelConfig.load()`. All 17 simulator
  metrics have explicit R = std^2 + Q values + F=1 random-walk model.
  Defaults section provides safe fallbacks for unlisted metrics. The original
  symptom (description below) is fully gone — verified by 12 config tests +
  steady-state false-positive rate test (~2% of 238 channels at 3-sigma).

  ORIGINAL SYMPTOM:
  ----- (preserved as historical context) -----
**DC-EPMS-037** (HISTORICAL) - cyber_physical_tools default miscalibration
- Symptom: cyber_physical_tools.py defaults (R=0.05^2 K^2, F=exp(-dt/60))
  miscalibrated for non-thermal channels and stationary signals.
- Root cause:
  1. Hard-coded cold-start R was tuned for PT100 thermal sensors only.
     Voltage / pressure / flow channels with native std orders of magnitude
     larger produced 92% false-positive anomaly rate.
  2. F<1 modeled exponential decay toward zero, but simulator emits
     stationary signals around constant baselines (e.g. UPS at 480V is
     not decaying). x_hat converged to ~401V instead of 480V.
- Mitigation: telemetry_pipeline.py pre-initializes filter_state per
  channel with R = std^2 from PHASE1_BASELINES and F = 1.0 (random walk).
  False-positive rate now ~2% (matches 3-sigma rule). x_hat tracks
  baselines correctly.
- Target resolution: Sprint 5 C3 introduces config/telemetry_channels.yml
  for full per-channel calibration including SoD threshold. The pipeline
  override is a pragmatic interim, not the final design.

**DC-EPMS-035** (LOW) - NEW (opened 2026-05-09, recovery-loss-tooling)
- Symptom: 13 untracked session helpers (.ps1 + diagnose_output.txt) lost during
  Phase A archive operation. Only `frontend_pre_camino1_20260508_215625.zip`
  recovered intact.
- Root cause (shell-friction): `mkdir scripts\_archive\sesion_sprint5` invoked via
  Bash tool collapsed Windows-style backslashes (Bash interprets `\` as escape) and
  created a single FILE named `sesion_sprint5` instead of the directory. Subsequent
  `Move-Item -Force` loop overwrote that file 14 times, preserving only the last
  source (the ZIP).
- Lesson learned: in Windows + PowerShell hybrid environment, NEVER invoke `mkdir`
  with backslash paths via Bash. Always use PowerShell-native `New-Item -ItemType
  Directory -Force` and validate destination with `Test-Path -PathType Container`
  before bulk Move-Item operations.
- Mitigation: Rule V9.1 (PowerShell Native Mandate) added — Bash forbidden for
  filesystem ops on Windows. ZIP recovered to canonical path. Effects of all 13
  lost orchestrators ARE preserved in committed code (commits 00caff1, da995e1,
  324d87f, d853907, 160be89, 2f33a59) and CHANGELOG entries v0.7.2-camino1 +
  v0.7.3-sprint5-patches. Forensic reproducibility lost; functional state intact.
- Target: closed by V9.1 rule adoption + commit (this entry).

**DC-EPMS-019** (LOW) - RESOLVED 2026-05-17 (`ebefdb6`)
- ResourceWarning on logs/epms_pro.log file held open at module import
- Root cause: logging.basicConfig in backend/main.py:117 without close on shutdown
- Fix: log-file handle leak closed in `ebefdb6` (the same commit that resolved
  the DC-EPMS-039 cosmetic facet — Pydantic model_id + chromadb telemetry).

**DC-EPMS-021** (MED) - RESOLVED 2026-05-17 (`136c7ef`)
- 124 ruff violations in backend/ cleared to 0. 66 auto-fixed (`ruff
  --fix` + `--unsafe-fixes`); 56 B904 fixed by an AST orchestrator
  (`scripts/_fix_b904.py` — attributes each re-raise to its nearest
  except handler, appends `from <exc>` / `from None`); 17 manual
  (SIM117/SIM102 collapse, N818 RBACDenied→RBACDeniedError rename across
  5 files, F821/F401 imports, E402 `import threading` hoist, RUF006
  `_BACKGROUND_TASKS` strong-ref set, B005 lstrip dedup, B027 + N802
  per-line noqa on the optional-override hook + the dT/dt ODE-derivative
  functions). pytest 712 held green.

**DC-EPMS-022** (LOW) - RESOLVED 2026-05-17 (stale entry — no change needed)
- Audit found `docs/adr/*.md` already use dash bullets and
  `.markdownlint.json` enforces `MD004: style=dash`; no asterisk/plus
  bullets exist. The registry entry was stale; closed by verification.

## 🗺️ ROADMAP — V9 delivered, V11 is the live backlog

**V9 scope is feature-complete** (tags `v0.5.0` → `v0.10.13`). The live,
authoritative backlog is **`docs/ROADMAP-V11.md`** (locked 2026-05-10). The
section below is a delivery summary; the Sprint 5 1-pager above is historical.

### Delivered (v0.8.5 → v0.10.13)

| Track | Tag(s) | Status |
|---|---|---|
| Sprint 5 — Telemetry + Kalman pipeline | v0.7.5 → v0.8.0 | ✅ |
| Sprint 5.5b — PUE physics widget + ADR-004 | v0.9.14 | ✅ |
| Sprint 6 — CMMS Core v1.0 (91 assets seeded) | v0.8.5 | ✅ |
| Sprint 9.1 — Predictive WO trigger (Kalman → auto-WO) | v0.9.0 | ✅ |
| Sprint 7.1 — Tech Assist (QA, PDF ingest, voice, OCR) + view | v0.9.5 → v0.9.9 | ✅ |
| Sprint 10.1 — Multi-Agent façade (4 agents + Safety Officer veto) | v0.9.12 | ✅ |
| HMI Tier A/B/C polish (topology, flow, anomaly heatmap) | v0.10.0 → v0.10.2 | ✅ |
| B1 Mission Control (three.js Tesla-Megapack) | v0.10.3 → v0.10.4 | ✅ |
| Power SLD — 2.5D isometric + DAG engine + iso camera | v0.10.5 → v0.10.8 | ✅ |
| SCADA asset panel + PBR polish + DDU/busway expansion | v0.10.9 → v0.10.11 | ✅ |

### Not built — deferred to V11

- **DPO edge-healing** — `dpo_edge_healing.py` (352 LOC) was **ERADICATED**
  2026-05-17 (`d495c7b`) as a confirmed orphan: never wired, and the original
  "Sprint 6 = DPO" plan was superseded by CMMS Core. Recoverable from git
  history (`git show d495c7b^:backend/dpo_edge_healing.py`) if V11 revives it
  — see ROADMAP-V11 T3.8. ADR-007 documents the original reuse decision
  (now amended).
- **Alarm Storm Mitigation** (Bayesian alarm correlation) — V11 candidate.
- **EOP Abort < 100 ms** (async event bus, NFPA 70E §130) — V11 candidate.

### V11 Tier 1 — partially delivered

Per `docs/ROADMAP-V11.md` (v11.1): T1.4 (`PRIMER_PROMPT.md`) + T1.5
(`replay_demo.ps1` twin-script injector) shipped; T2.2 declarative router
shipped; T2.4/T2.5 partial. OBS demo-recording (T1.1/T1.3) DESCOPED by
Wilmer 2026-05-17.

## 🛠️ TOOLING CONSTRAINTS

- **Hardware**: ASUS Zephyrus G14, AMD Ryzen, RTX 3060 6GB, CUDA 13.2, Windows 11 + WSL2 + Docker Desktop
- **Python**: 3.12.10, venv at `C:\dev\DC-EPMS_PRO\.venv`
- **Activation**: `.\.venv\Scripts\Activate.ps1` (always activate before running tests/uvicorn)
- **LM Studio**: gemma-4-e2b-it on `127.0.0.1:1234`
- **TimescaleDB**: Docker container `epms-db` on port 5432 — DB `dcepms`, user `epms`, pwd `epms_dev_only_change_me` (provisioned per `docker-compose.yml`). Backend reads `PG_DB`/`PG_USER`/`PG_PASSWORD` from `config/.env`; these MUST be set or it falls back to stale defaults `postgres`/`epms` — a role + DB that do NOT exist (see DC-EPMS-DB-001).
- **FastAPI backend**: port 8080, launched native via `python backend\main.py` (NOT docker). `scripts/start.ps1` bootstraps venv + DB + backend.
- **Claude Desktop**: MCP server `dc-epms-pro` (stdio)
- **NetworkX 3.6.1, FAISS 1.13.2, sentence-transformers 3.2.1** (lazy-loaded)
- **ChromaDB persistent client** at `data/chroma_db/`
- **pre-commit installed** (Batch 3 closure), but USE `--no-verify` for orchestrator commits

**Critical operational notes**:
- Docker container `epms-backend` from old deployment auto-restarts and steals port 8080. Always `docker ps` and `docker stop epms-backend` if conflict.
- FAISS has AVX2 access violation on AMD Ryzen + Windows (DC-EPMS-001). Mitigated via `not slow` markers.
- The `epms-db` container should stay running. If found `Exited` (e.g. after a host reboot or Docker Desktop restart), bring it back with `docker start epms-db` and wait for `docker inspect --format "{{.State.Health.Status}}" epms-db` = `healthy` BEFORE launching the backend — otherwise PostgreSQL boots `down` and CMMS is skipped (DC-EPMS-DB-001).

## 🎓 WORKING STYLE - "Fine Tuning Quirúrgico"

These are non-negotiable principles for all work on this project:

1. **Never assume defaults silently** - surface every decision with explicit rationale and reality check before coding
2. **Reality check over hype** - if something is not genuinely demonstrable on a 6 GB RTX 3060 laptop, say so and propose what IS demonstrable
3. **Approve-then-execute** - present plan in clear bullets, wait for explicit "GO" before generating code (Wilmer says "GO" or "approved" or "luz verde")
4. **Atomic batches** - break sprints into 2-3 batches per session, each independently validatable before proceeding
5. **Defensive coding** - backup files (.bak_pre_*) before patching, AST validation before disk writes, syntax checks before tests
6. **Honest scope** - 6 weeks means 6 weeks. No padding, no hidden buffers
7. **Architectural Decision Records** - significant decisions get ADRs in MADR format under `docs/adr/`
8. **Tag is not closure** - verify with `git log --oneline --decorate -n 5` that tag points to a NEW commit, not the predecessor

## 🔒 V9 AI-FACTORY SPEED PROTOCOL (5 RULES - DEFAULT MODE)

These apply to ALL work, not just override mode:

1. **Ingesta Total**: Every response begins from a conscious read of project state (current bugs, decisions, container state, test count, latest commit hash). No cached assumptions.
2. **Migración CLI**: Every multi-step operation gets a PowerShell or Python orchestrator. No copy-paste of 20-line snippets.
3. **Multi-Agente Lógica + QA**: Every code artifact comes with its test artifact in the same turn. Tests are not deferred.
4. **Grounding Forzado**: Architectural decisions cite the standard, the file path, and the specific section. No vague hand-waves.
5. **CI/CD LOCAL**: All validation is local. ZERO `.github/workflows/` for this project (edge-first autonomy means no cloud CI dependency).

## 🛡️ HYPERSCALE OVERRIDE PROTOCOL (7 RULES)

When Wilmer initiates `[SYSTEM OVERRIDE: HYPERSCALE DEVELOPMENT MODE INITIATED]`, standard limits suspend:

1. **Zero-Placeholder Policy**: NO `pass`, `TODO`, "agrega tu lógica aquí". Production-ready even if 800+ lines.
2. **Deep Chain of Thought**: Open `<architecture_analysis>` block before any code, exhaustively analyzing physical dependencies (Thermodynamics, 800 VDC), 2N redundancy impact, race conditions.
3. **Multi-Agente Full Stack Delivery**: Single turn delivers core code + integration tests (pytest + fixtures) + local PowerShell injection script.
4. **Defensive Coding Agresivo**: Industrial-grade exception handling. Assume network failures and hardware degradation.
5. **Silencio Administrativo**: Text outside code blocks limited to architectural decisions (ADRs) and reality checks.
6. **Documentation Drift Prevention**: Auto-update CLAUDE.md if work alters architectural baseline.
7. **Honest Tech Debt Registry**: Every batch closure generates DC-EPMS-NNN entry if any check failed during execution. Pre-commit hook fails, partial commits, false [OK] reports - all get tracked.

## ⚠️ POWERSHELL PRE-DELIVERY RULES (8 RULES + ASCII-only)

Hard rules for every PowerShell artifact, distilled from Batches 1+2+3+3.5+5 and Camino 1:

1. **No `<` or `>` chars** inside double-quoted strings. PowerShell parses as redirection operators. Includes `->` arrow notation.
2. **No em-dashes anywhere** in PowerShell code. Replace with hyphen-minus or remove.
3. **No double-dash word starting tokens** in argument-like positions inside strings.
4. **Variable colons escape with backtick**: write `` `$variable: `` not `$variable:`.
5. **No `python -c` heredocs** with embedded code. Always write a `.py` file and invoke it.
6. **Wrap native command invocations** with `$ErrorActionPreference = 'Continue'` when stderr might be non-error (git, docker).
7. **AST-validate Python before disk write**, TOML-validate `pyproject.toml` before disk write.
8. **Validate $LASTEXITCODE before declaring [OK]** (Rule from Batch 3.5 Recovery). When invoking native commands, warning text on stderr can be misinterpreted as success.
9. **ASCII-only commit messages**.
10. **Use Convert-Path or Get-AbsolutePath** for .NET I/O calls. `[System.IO.File]::*` resolves relative paths against system PWD, not PowerShell CWD.
11. **String.Replace, NOT [regex]::Replace** when replacement contains $N patterns (interpreted as RegexOptions enum, breaks).
12. **Use UTF8NoBOM encoding** when writing Python files. `Set-Content -Encoding UTF8` preserves BOM; use `[System.IO.File]::WriteAllText` with `New-Object System.Text.UTF8Encoding($false)`.
13. **Multi-variant tolerance for special chars** (middle-dot U+00B7, multiplication sign U+00D7) - check all encoding variants when matching.

## 📜 CLOSING DISCIPLINE (Lesson from Batch 3.5 Recovery)

A batch is not closed merely by tagging:

- **Tag is not closure**. After tagging, verify with `git log --oneline --decorate -n 5` that tag actually points to NEW commit.
- **Pre-commit hooks recursively modify**. Use `git commit --no-verify` for orchestrator commits IF (and only if) changes have already passed manual AST validation and pytest.
- **Honest failure reporting**. Every batch closure must report what was attempted but failed.
- **Forensic tarball before destructive ops**. Save `.tar.gz` before any operation that rewrites git history.

## 🗂️ CONNECTORS / TOOLS DECLARATION

When making changes that need to coordinate with external services:
- **Docker**: prefer `docker compose` (V2) over `docker-compose` (V1)
- **Git**: always `--no-verify` on orchestrator commits with manual AST + pytest validation
- **Tests**: `pytest -m "not slow" --tb=short` (slow markers exclude FAISS AVX2 issue)
- **Browser**: http://127.0.0.1:8080/ for HMI smoke tests
- **MCP**: stdio server `dc-epms-pro` for Claude Desktop integration

## 🎬 RECENT SESSION HIGHLIGHTS (2026-05-17)

**ProcedureGenerator sprint + security hardening + SRE cleanup** (post-v0.10.13,
24 commits, HEAD `d495c7b`):
- C0 + G1-G6: dual-graph hierarchical asset taxonomy (ADR-010), W3 taxonomy
  migration, SOP/MOP/EOP/EMP procedure factories, recursive containment-tree
  micro-LOTO isolation, Kalman EOP factory, hyperscale RBAC + promotion gates,
  HTTP routes, macro-to-micro drill-down UI.
- E2E read-only security audit (`docs/audit/E2E_Security_Orphan_Audit.md`); the
  3 CRITICAL RBAC gaps remediated (`b34efb1`); frontend `actor_role` synced.
- DC-EPMS-040 diagnosed (stale process vs W3 schema). SRE cleanup: 4 dead files
  eradicated (-5706 LOC); DC-EPMS-039 test-suite hang fixed — full pytest now
  690 passed, 0 fail, 41s end-to-end.
- Doc-sync (this commit): CLAUDE.md + ROADMAP-V11 + ADR-007 aligned to reality.

**Prior (2026-05-16) — environment troubleshooting + doc sync**:
- Found the dev stack down: `epms-db` container `Exited`, backend not running.
- Brought it up: `docker start epms-db` → healthy; relaunched backend on :8080.
- Diagnosed + fixed **DC-EPMS-DB-001** (HIGH): PostgreSQL credentials mismatch —
  container is `epms`/`dcepms`, backend defaulted to nonexistent `postgres`/`epms`.
  Fixed via `config/.env` (`PG_DB`/`PG_USER`/`PG_PASSWORD`). On restart: PostgreSQL
  `up`, 91 CMMS assets re-seeded, all boot stages green.
- Synced this CLAUDE.md to real state: it was stale at v0.8.5 / Sprint 6 while the
  project is at v0.10.13 (~28 commits — Sprints 6-10 + full HMI / SLD /
  Mission-Control tracks). Updated CURRENT STATE, bugs registry, roadmap, tooling,
  directory layout, vision-deck trajectory.

**Prior (2026-05-08/09) — preserved**: 9.5h overnight session 7+8 — 11 commits,
8 bugs closed, LOTO Auditor HMI view, Path C2 drift sync (40 → 67 MW). Demo-killer
finding: MOP-ATS-MONTHLY-001 + `ups_a` = NEC 460.6 violation flagged in ~12 ms.

## 📝 COMMUNICATION PREFERENCES

- **Language**: Spanish-English mix. Respond in the language Wilmer uses.
- **Pushback recognition**: When Wilmer pushes back ("ninguna de tus opciones evalua"), recognize as legitimate critical thinking. Re-analyze, do not capitulate.
- **Reality check first**: ALWAYS verify state before suggesting work. `git log --oneline -n 5` + `git status` before proposing.
- **Path C2 vocabulary**: USE precise terminology. "Upstream 3-phase AC into MV Rectifier downstream 800 VDC unipolar TN-S" - NOT "800 VDC trifásico".

## 🎯 IMMEDIATE NEXT STEPS (when resuming)

1. **Verify state**: `git log --oneline -n 6` (HEAD must be `d495c7b` or a
   descendant), `git status` (only `.claude/` + `PRIMER_PROMPT.md` untracked,
   `DEMO_SCRIPT.md` modified).
2. **Bring up the stack**:
   - `docker start epms-db` → wait for `docker inspect --format
     "{{.State.Health.Status}}" epms-db` = `healthy`.
   - `python backend\main.py` (native, :8080) — confirm `curl
     http://127.0.0.1:8080/api/health` reports `postgres: up` /
     `database: dcepms`. If it says `down`, see DC-EPMS-DB-001.
   - One-shot alternative: `.\scripts\start.ps1`.
3. **Activate venv** for any test / CLI work: `.\.venv\Scripts\Activate.ps1`.
4. **Read `docs/ROADMAP-V11.md`** — the live backlog. Tier 1 = demo readiness.
5. **Wait for explicit GO** from Wilmer before starting any V11 work.

## ⏸ PAUSE_STATE (last updated 2026-05-17)

> No active pause. V9 is feature-complete; the live backlog is
> `docs/ROADMAP-V11.md` (v11.1). Since v0.10.13 the project shipped the
> ProcedureGenerator sprint (C0 + G1-G6), hyperscale RBAC, an E2E security
> audit + CRITICAL remediation, and an SRE dead-code eradication — 24
> untagged commits, HEAD `d495c7b`.

### State at sync time

- HEAD `d495c7b`; `master` is 24 commits AHEAD of `origin/master` (unpushed)
  and of tag `v0.10.13-modal-fix`. Tree clean (`.claude/` + `PRIMER_PROMPT.md`
  + modified `DEMO_SCRIPT.md` aside).
- Test suite: 690 passed, 0 fail, 41s end-to-end (DC-EPMS-039 hang eradicated).
- `config/.env` carries the PG credentials (DC-EPMS-DB-001 fix) — local-only,
  gitignored, persistent across restarts.

### Resumption protocol (next session entry)

1. Run the `## 🎯 IMMEDIATE NEXT STEPS` checklist (verify state, bring up stack).
2. Read `docs/ROADMAP-V11.md` for the live backlog.
3. Wait for Wilmer's explicit GO before starting any V11 work.

### Open bugs at sync time (see BUGS REGISTRY for detail)

- DC-EPMS-029c (LOW): physics_engine SHI rollup insensitive to some LOTO types.
- E2E audit WARNING-tier findings (`docs/audit/E2E_Security_Orphan_Audit.md`) —
  the 3 CRITICAL RBAC findings are closed (`b34efb1`); WARNINGs remain open.

RESOLVED since the last sync: DC-EPMS-021 + DC-EPMS-022 (`136c7ef`);
DC-EPMS-019 + DC-EPMS-039 (`ebefdb6` + `d495c7b`).

### V9.1 PowerShell Native Mandate (in force after DC-EPMS-035)

- **Filesystem ops on Windows**: PowerShell-native ONLY. NEVER `mkdir scripts\path` via Bash (backslash collapse).
- **Use**: `New-Item -ItemType Directory -Path 'a/b/c' -Force` (forward slashes), `Get-ChildItem`, `Move-Item`, `Remove-Item`, `Test-Path`.
- **Defensive**: `Test-Path -PathType Container` MUST verify destination is a directory BEFORE bulk `Move-Item`. `Move-Item -Force` to a non-existent directory creates a FILE; subsequent moves overwrite it.
- **Filtering**: `Select-String` (not `findstr` / `grep`).
- **Heredocs**: NO `python -c '...'` heredocs — write a `.py` file and invoke it (Rule 5 PowerShell Pre-Delivery).

## 📜 VISION DECK v1.0 — appendix de diseños arquitecturales (Wilmer #1..#7)

> Persistido por directiva 2026-05-09: "Commitea todos los diseños y visiones para que no se pierda la brújula." Estos prompts fueron procesados como design exercises sin implementar literalmente todo. Sprint 6 (CMMS Core v1.0) ES la primera materialización de Wilmer #1+#2.

### #1 — CMMS Engine Integration (base directive)
- Asset Registry con telemetry_mapping + linked_mop_id
- Predictive Work Orders desde Kalman C2 anomalies
- MOP linking automático (hardcoded heuristic Sprint 6, GraphRAG fallback Sprint 7)
- REST router /api/cmms con CRUD + state machine
- SHI degradación por overdue WOs (Sprint 6 Fase 5 deferred)

### #2 — Tesla/SpaceX Vision (Sprint 6 schema enrichment)
- assets.path (A / B / C2-P1 / C2-P2)
- assets.redundancy_pillar (2N / N+1 / N / single)
- assets.telemetry_channels JSONB array de "<asset_id>:<metric>" simulator IDs
- assets.criticality_class para escalation de WO priority
- work_orders.priority (P1..P4) auto-derived from LOR × criticality
- work_orders.telemetry_snapshot_json (forensic snapshot del trigger)
- work_orders.mop_resolution_method (hardcoded / graphrag / manual)
- View asset_health_aggregate per path + pillar + asset_type

### #3 — Asistencia Técnica Aumentada (MaintainX-AI clone, Sprint 7 deferred)
- Document ingestion (PDFs, diagrams, P&IDs) → ChromaDB vectors
- Photo → AI-generated SOP YAML (procedure_engine compatible)
- Real-time troubleshoot QA combinando manual chunks + WO history
- Diagram parser CV (LOTO point + Arc Flash zone extraction) — V2 cloud or LLaVA local
- Smart Time Estimates basado en complexity heuristic + historical p50/p90
- AI Order Closure: voice (Whisper) → LLM-normalized professional report

### #4 — Real-time CoPilot + NLP (Sprint 9 deferred)
- In-line WO step suggestions
- Photo upload → component identification + past-WO photo similarity (CLIP)
- Voice-to-summary auto-generates follow-up WO if degradation detected
- NLP-to-SQL dashboards (manager queries: "chillers with most failures last 3 months")
- CapEx vs OpEx priorization (replace vs repair recommendation)

### #5 — Equinix Edge-AI Integration (Sprint 11 design-only)
- Local-first inference: gemma-2b primary, Claude fallback
- Multi-IBX confederation pattern (msgpack over private link)
- AI Labs distributed training (sovereign data, NO leak)
- Cross-DC KB sync (eventual consistency)
- Honest reality: single-laptop demonstrable = local-first only; multi-DC is design pattern

### #6 — Multi-Agent Orchestration (Sprint 10 deferred)
- 4 specialized agents:
  - Architect (vision/engineering, parses diagrams + photos)
  - Safety Officer (CSA Z462 / NFPA 70E veto power, mandatory LOTO insertion)
  - Diagnostician (history + KB cross-reference, recurrence detection)
  - Analyst (KPIs, NLP-to-SQL, CapEx vs OpEx)
- Consensus protocol: Safety Officer HARD_STOP outranks all
- Manual-vs-history conflict surfaces both options to technician
- agent_performance_log table for SLO tracking + accuracy KPIs

### #7 — Agent AI OS + Self-Healing (Sprint 12 design-only)
- CodeAuditor: vulture + ruff + AST walk for orphan/dead code
- Dependency graph (NetworkX) for agent relationships, FAILSAFE_MODE on agent silence
- SLM lifecycle pool with VRAM-budget LRU eviction
- compliance_failsafe.yml preloaded rules survive total LLM failure

### Sprint trajectory mapping (updated 2026-05-17)

| Sprint | Vision deck items | Status |
|---|---|---|
| 5 | telemetry simulator + Kalman + frontend | ✅ v0.8.0 |
| 6 | #1 CMMS Core + #2 Tesla/SpaceX Vision | ✅ v0.8.5 |
| 7.1 | #3 Tech Assist V1 (QA + PDF ingest + voice + nameplate OCR) | ✅ v0.9.5–v0.9.9 |
| 8 | #3 Tech Assist V2 (diagram CV) | deferred → V11 |
| 9.1 | #4 partial — predictive WO trigger (Kalman → auto-WO) | ✅ v0.9.0 |
| 9 (full) | #4 Real-time CoPilot + NLP-to-SQL dashboards | deferred → V11 |
| 10.1 | #6 Multi-Agent façade (4 agents + Safety Officer veto) | ✅ v0.9.12 |
| 11 | #5 Equinix multi-IBX | design-only (single-laptop) |
| 12 | #7 Agent AI OS Self-Healing | deferred → V11 |
| G (post-v0.10.13) | ProcedureGenerator: dual-graph taxonomy (ADR-010) + SOP/MOP/EOP/EMP factories + recursive micro-LOTO + hyperscale RBAC | ✅ d495c7b |

Plus an unplanned HMI / visualization track (v0.10.x): Tier A/B/C polish, B1
Mission Control (three.js), 2.5D isometric SLD + DAG engine, SCADA asset panel.

### CO+I demo readiness (target: early August 2026)

The "demonstrable minimum" is built. Remaining work is delivery, not features —
see `docs/ROADMAP-V11.md` Tier 1 (~8h): browser-validate B1 Mission Control,
DEMO_SCRIPT v5, 3× OBS recording rehearsals.

- ✅ Sprint 5 / 6 / 7.1 / 9.1 / 10.1 — all shipped
- ✅ HMI Mission Control + 2.5D isometric SLD — shipped (v0.10.x)
- 🟡 Demo recording + DEMO_SCRIPT v5 — pending (V11 Tier 1)

## 🧠 OPERATIONAL HARNESS (post-v0.12.0 — Engram + Skill Registry binding)

This section binds the persistent operational artefacts created at Epic 1 closure
(2026-05-19). Two strict constraints apply to **every** future session:

- **OPERATIONAL RULE.** Apply the *"Skill Digestion Harness"* for all future
  tasks. Before modifying any file, you MUST consult
  `docs/skills/skill-registry.md`, extract the **3-4 relevant rules** for that
  specific task (cited by skill ID, e.g. `S-DET-01`, `S-SEC-01`), and strictly
  adhere to them. If a directive conflicts with a skill, surface the conflict
  before executing — do not silently override. The architectural state snapshot
  lives at `docs/engram/main-context.md`; read it whenever the working context
  has drifted (new session, long compaction, ambiguous baseline).

- **RUNTIME CONSTRAINT.** The Python backend does **not** hot-reload. After any
  backend or agent-wiring change, the active process MUST be restarted and the
  `[BOOT]` log signature in `logs/epms_pro.log` verified alongside
  `/api/health` before conducting multi-agent smoke tests — to prevent
  stale-code false positives (the post-Epic-1 smoke-test surfaced exactly this
  failure mode: PID 46172 ran a pre-T3.3 module for 2+ days while unit tests +
  the frontend smoke test all passed, silently returning empty narratives).
  See `S-RUNTIME-01` for the verification protocol.

**Companion files (binding):**
- `docs/engram/main-context.md` — architectural state snapshot.
- `docs/skills/skill-registry.md` — 16 explicit skills across 8 categories.

## 🚨 DO NOT TOUCH

- `epms-db` Docker container (always running)
- `_legacy_backup/` directory (Batch 1+2 archived materials)
- `.venv/` directory (regenerate via `pip install -e .[dev]` if needed)
- Any commits older than v0.5.0 (foundation, brittle)
- `agent_engine.py` (dual-AI fallback per ADR-004, do NOT delete)
