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

## 📊 CURRENT STATE (verified 2026-05-09 mid-cycle)

```
Tags chronological:
  v0.5.0
  v0.6.0-batch3
  v0.6.1-batch3.5
  v0.7.0-batch4
  v0.7.2-camino1
  v0.7.3-sprint5-patches
  v0.7.4-frontend-pivot     ← Sprint 5.5 hybrid frontend pivot (browser milestone)
  v0.7.5-telemetry-stream   ← Sprint 5 C1: synthetic telemetry simulator + SSE wired
  v0.7.6-kalman-pipeline    ← Sprint 5 C2: Kalman + SoD pipeline + 60-min anomaly counter
  v0.8.0-sprint5-kalman     ← Sprint 5 C3: per-channel YAML calibration + perf-verified

System completion:
  Backend:   91% (Sprint 5 closed, telemetry_channels.yml replaces hardcoded R/Q)
  Frontend:  88%
  Total V9:  90%

Tests:   457+ passing
         - 412 baseline
         - 17 telemetry_simulator (Sprint 5 C1)
         - 12 telemetry_pipeline (Sprint 5 C2)
         - 12 telemetry_channels_config (Sprint 5 C3)
         - 4 telemetry_perf (Sprint 5 C3 — Numba JIT verified)
         - Pillar 4-5-6: 14/14 GREEN
         - 4 pre-existing failures in test_loto_auditor_pillars.py
           (DC-EPMS-036 fixture drift, non-regressive)

Perf baseline (2026-05-09 AMD Ryzen + Windows):
  - Numba JIT cold compile: 4.8 ms
  - Hot compute() over 238 channels: 5.11 ms / window
  - Per-step Kalman: 4.3 us (well under SSCB target 1-100 us)
  - Anomaly log trim over 10k entries: 1.83 ms

Validation layers: 8 of 8 PASS
```

**Recent commits (latest at top)**:
```
HEAD                                feat(backend): Sprint 5 C1 telemetry simulator + SSE wiring
26b9b1d (tag: v0.7.4-frontend-pivot) feat(frontend): Bite B SHI trend sparkline
c42187b                             feat(frontend): Bites A1+A2+A3 telemetry activity strip
b872396                             feat(frontend): Bite 1.3 stale-data badge
b8065db                             feat(frontend): Phase 1.0 setup (Chart.js local + skeletons)
8f3f2e6                             docs(sprint5): C0 architecture locked + PAUSE_STATE
509be04                             fix(loto): DC-EPMS-034 witness_engine call site
```

## 🛰 ROADMAP_V9_NEXT_STEPS — Sprint 5 C0 Architecture (locked 2026-05-09)

> **1-pager produced during C0 read-only phase 2026-05-09 ~04:00 by Claude Opus 4.7 (1M ctx).**
> Source files read: `backend/cyber_physical_tools.py` (248 LOC, orphan), `backend/physics_engine.py` (369 LOC, live), `backend/main.py:459-491` (current `/api/telemetry/stream` placeholder).
> When resuming Sprint 5: re-read this section first, then `git status` + `docker ps` + `curl /api/health`.

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
├── backend/                     ← FastAPI + SQLAlchemy + asyncpg
│   ├── main.py                  ← 1823 lines, 5 routers, ~50 endpoints
│   ├── physics_engine.py        ← 369 lines, facade for 4 physics modules
│   ├── physics/                 ← 4 sub-modules (it_thermal, mechanical, electrical, heat_rejection), 85 unit tests
│   ├── agent_copilot.py         ← 894 lines, primary agent with 6 tools
│   ├── agent_engine.py          ← 294 lines, dual-AI fallback (NeMo Guardrails + Claude Sonnet)
│   ├── procedure_engine.py      ← 641 lines, 8-state machine, 32 tests
│   ├── witness_engine.py        ← 290 lines, multi-signature drafts, 26 tests
│   ├── cmms_mcp.py              ← 492 lines, LOR scoring, 51 tests
│   ├── site_model.py            ← 462 lines, declarative YAML parser, 44 tests + 41 integration
│   ├── graphrag_service.py      ← 166 lines, NetworkX MultiDiGraph + FAISS, 20 tests
│   ├── rag_service.py           ← 234 lines, ChromaDB primary, 20-doc operational corpus
│   ├── loto_auditor_agent.py    ← 1100+ lines, 6-pillar paranoid validator
│   ├── loto_auditor_pillar_helpers.py  ← Helpers for Pillar 1-6
│   ├── loto_auditor_routes.py   ← 4 REST endpoints under /api/loto
│   ├── shift_briefing.py        ← (NOT YET) Sprint 5.5a target
│   ├── cyber_physical_tools.py  ← 248 lines ORPHAN (Sprint 5 Telemetry target)
│   ├── dpo_edge_healing.py      ← 352 lines ORPHAN (Sprint 6 target)
│   ├── mcp_server.py            ← 531 lines, Claude Desktop subprocess
│   └── hal/                     ← Cummins, ASCO, Russelectric adapters
├── frontend/                    ← Production-grade HMI
│   ├── index.html               ← 105KB, 13 nav routes, includes LOTO Auditor view
│   └── assets/
│       ├── app.js               ← 3601 lines, IIFE pattern
│       └── app.css              ← 71KB
├── config/
│   ├── site_model.yml           ← 91 components, 50 racks (will expand to 368 in Sprint 5)
│   ├── knowledge/               ← 5 GraphRAG markdown docs
│   └── pue_targets.yml          ← (NOT YET) Sprint 5.5b target
├── data/
│   └── chroma_db/               ← 20-doc 4-tier corpus (Safety/Vendor/Standards/MOPs)
├── tests/                       ← 412+ tests
├── docs/
│   ├── adr/                     ← 7 ADRs (MADR format)
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

### Open / Deferred

**DC-EPMS-029b** (MED) - DEFERRED post-C3 (prediction of natural resolution was WRONG)
- Symptom: `simulate_loto_measurements` produces `shi_pre == shi_post` (no delta)
- Root cause hypothesis: `physics_engine.validate_site()` uses thermal fields (hall_inlet_temp_c, chiller_supply_temp_c, cdu_pressure_bar) that simulate_loto doesn't modify
- Sprint 5 C2 closure 2026-05-09: prediction that C2 would resolve this naturally was WRONG. simulate_loto is independent of the simulator/pipeline path. Resolution requires a translation layer mapping simulator channel-level output to physics_engine measurements dict format. Deferred to dedicated bite post-C3 or V10.

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

**DC-EPMS-036** (MED) - NEW (opened 2026-05-09, test-fixture drift)
- Symptom: 4 tests in `tests/test_loto_auditor_pillars.py` fail on HEAD:
  - `TestPillar1Topology::test_pillar1_graphrag_inconsistency_noted_not_failed`
  - `TestPillar1Topology::test_pillar1_cooling_chain_integration`
  - `TestPillar2Redundancy::test_pillar2_happy_path_path_a`
  - `TestPillar2Redundancy::test_pillar2_shi_below_threshold_hard_fail`
- Root cause: test fixtures expect pre-fix behavior of Pillar 1 (calling nonexistent
  `query_topology()`) and Pillar 2 (treating physics result as `dict.get('site_health')`).
  When DC-EPMS-029, DC-EPMS-030, DC-EPMS-031 fixed production code in commits 160be89,
  da995e1, 324d87f, the test mocks were not updated. Verified pre-existing (failures
  reproduce on clean HEAD 17dfded without DC-EPMS-034 patch via stash test).
- Runtime impact: NONE. Production code is correct; only test mocks are stale.
- CI impact: pytest aggregate fails on these 4 cases.
- Resolution path: update Pillar 1 mocks to match `loto_with_knowledge` payload
  (returns `{edges, evidence_chunks}` not `{topology}`), and update Pillar 2 mocks
  to return `SiteValidation` object (with `.site_health` attribute) not bare dict.
  Estimated effort: 1-2h surgical mock refactor + re-run aggregate.
- Target: Sprint 5 Telemetry sprint (covered by DC-EPMS-029b natural resolution
  of physics_engine surface area).

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

**DC-EPMS-019** (LOW) - investigated but mitigation deferred
- ResourceWarning on logs/epms_pro.log file held open at module import
- Root cause: logging.basicConfig in backend/main.py:117 without close on shutdown
- Mitigation: lifespan cleanup hook in main.py

**DC-EPMS-021** (MED) - 90 ruff legacy errors
- B904, F821, E402, SIM102, RUF005, RUF013 across many files
- Pre-existing tech debt, target Batch 3.6 (~6-8h)

**DC-EPMS-022** (LOW) - 6 ADRs use asterisk bullets violating MD004
- 5 min mass sed replacement, target Batch 3.6

## 🗺️ ROADMAP V9 - what's next

### Sprint 5 Telemetry + Kalman (W5-6, 1.5 sem) ⭐ IMMEDIATE NEXT

> **Locked architecture**: see `## 🛰 ROADMAP_V9_NEXT_STEPS — Sprint 5 C0 Architecture` above for the full 1-pager (C0 done 2026-05-09). Atomic ladder C1 → C2 → C3.

**Backend goal**: integrate `cyber_physical_tools.py` orphan (248 lines, Kalman + Numba `@njit` + Send-on-Delta) via two new modules (`telemetry_simulator.py`, `telemetry_pipeline.py`) and rewrite `/api/telemetry/stream`. Resolves DC-EPMS-029b naturally during C2.

**Tag target**: `v0.8.0-sprint5-kalman` (C3 closure).

### Sprint 5.5a Pre-Operational Briefing Orchestrator (W6.5, 6-8h)

**New backend module**: `backend/shift_briefing.py` (~250 lines)

5-step pipeline:
1. `_step1_subsystem_status()` -> physics_engine.validate_site() (<50ms)
2. `_step2_topology_awareness()` -> graphrag.query("redundancy") (~100ms)
3. `_step3_incidents_12h()` -> TimescaleDB (<30ms)
4. `_step4_relevant_procedures()` -> ChromaDB tier-priority (~200ms)
5. `_step5_llm_synthesis()` -> LM Studio gemma-4-e2b-it (2-5s, timeout 10s)

**Endpoint**: `POST /api/shift/briefing`
**Persistence**: `shift_briefings` table (PostgreSQL)
**Tag target**: `v0.8.5-sprint55a-briefing`

### Sprint 5.5b PUE Logic + ADR-004 (W7, 5-6h)

- `physics_engine.compute_pue()` with first-law cross-check (<2% residual)
- `config/pue_targets.yml` architecture-aware:
  - Phase 1 (480 VAC trifásico): 1.30 / 1.45
  - Phase 2 (800 VDC unipolar TN-S): 1.15 / 1.25
- ADR-004 (agent_engine.py dual-AI rationale)

**Tag target**: `v0.9.0-sprint55b-pue`

### Sprint 6 DPO Capture-Only + ADR-005 (W8-9, 2-3 days)

**Backend**: integrate `dpo_edge_healing.py` orphan (352 lines)
- `dpo_pairs` table capturing (original_draft, corrected_draft, rejection_reason, ts)
- `POST /api/dpo/capture` (auto-disparado en CMMS WO rejection)
- `POST /api/dpo/recompile` (manual trigger)
- DPO compute: CPU bitsandbytes (preserves edge-local property)
- ADR-005 (DPO compute strategy)

**Tag target**: `v0.9.5-sprint6-dpo`

### Sprint 7 Alarm Storm Mitigation (W9-10, ~1 sem)
Bayesian network for alarm correlation. 10-100 alarms burst -> topological graph reduction -> 1-5 root causes.

### Sprint 8 EOP Abort under 100ms (W11-12, ~1 sem)
Mission-critical async event bus per NFPA 70E Section 130 + IEC 62443-3-3 SR 3.4/7.6.

**Tag target**: `v1.0.0-v9-complete`

## 🛠️ TOOLING CONSTRAINTS

- **Hardware**: ASUS Zephyrus G14, AMD Ryzen, RTX 3060 6GB, CUDA 13.2, Windows 11 + WSL2 + Docker Desktop
- **Python**: 3.12.10, venv at `C:\dev\DC-EPMS_PRO\.venv`
- **Activation**: `.\.venv\Scripts\Activate.ps1` (always activate before running tests/uvicorn)
- **LM Studio**: gemma-4-e2b-it on `127.0.0.1:1234`
- **TimescaleDB**: Docker container `epms-db` on port 5432 (postgres user)
- **FastAPI backend**: port 8080
- **Claude Desktop**: MCP server `dc-epms-pro` (stdio)
- **NetworkX 3.6.1, FAISS 1.13.2, sentence-transformers 3.2.1** (lazy-loaded)
- **ChromaDB persistent client** at `data/chroma_db/`
- **pre-commit installed** (Batch 3 closure), but USE `--no-verify` for orchestrator commits

**Critical operational notes**:
- Docker container `epms-backend` from old deployment auto-restarts and steals port 8080. Always `docker ps` and `docker stop epms-backend` if conflict.
- FAISS has AVX2 access violation on AMD Ryzen + Windows (DC-EPMS-001). Mitigated via `not slow` markers.
- The `epms-db` Docker container should ALWAYS stay running. Don't stop it.

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

## 🎬 RECENT SESSION HIGHLIGHTS (2026-05-08 to 2026-05-09)

**9.5-hour overnight session 7+8 closed**:
- 11 commits + 2 tags (v0.7.2-camino1, v0.7.3-sprint5-patches)
- 8 bugs closed (1 HIGH + 4 MED + 3 LOW)
- Backend 75% to 80%, Frontend 70% to 82%
- LOTO Auditor view production-grade in HMI
- Path C2 drift sync (40 MW to 67 MW)
- Sprint 5 patches verified in browser smoke test:
  - 16 sources_consulted, 14 OK + 1 deferred (ADR-009) + 1 warning (DC-EPMS-034)
  - decision_time_ms ~12ms maintained
- Real-world bug discovery: MOP-ATS-MONTHLY-001 + ups_a target = NEC 460.6 violation in 12ms (demo killer for CO+I panel)

## 📝 COMMUNICATION PREFERENCES

- **Language**: Spanish-English mix. Respond in the language Wilmer uses.
- **Pushback recognition**: When Wilmer pushes back ("ninguna de tus opciones evalua"), recognize as legitimate critical thinking. Re-analyze, do not capitulate.
- **Reality check first**: ALWAYS verify state before suggesting work. `git log --oneline -n 5` + `git status` before proposing.
- **Path C2 vocabulary**: USE precise terminology. "Upstream 3-phase AC into MV Rectifier downstream 800 VDC unipolar TN-S" - NOT "800 VDC trifásico".

## 🎯 IMMEDIATE NEXT STEPS (when resuming)

1. **Read `## 🛰 ROADMAP_V9_NEXT_STEPS`** — Sprint 5 architecture is locked there (C0 done 2026-05-09 ~04:00).
2. **Verify state**: `git log --oneline -n 6` (HEAD must be `509be04` or descendant), `git status` (only `.claude/` + `DEMO_SCRIPT.md` + `PRIMER_PROMPT.md` untracked), `docker ps` (`epms-db` healthy), `curl http://127.0.0.1:8080/api/health` (200).
3. **Restart uvicorn** if backend health check shows stale code (DC-EPMS-034 fix in `backend/loto_auditor_agent.py` not yet active in running process). Browser smoke optional but recommended before C1.
4. **Activate venv**: `.\.venv\Scripts\Activate.ps1`.
5. **Wait for explicit GO** from Wilmer before starting C1 (`telemetry_simulator.py`).

## ⏸ PAUSE_STATE (last updated 2026-05-09 mid-cycle)

> Original pause was PROACTIVE per Zero-Incidents discipline. Resumption was driven by user re-engagement; backend C1 + frontend Sprint 5.5 hybrid pivot were both completed in this same calendar day in alternating turns. PAUSE_STATE preserved as resumption protocol record.

### Session arc (commits beyond v0.7.3-sprint5-patches, oldest first)

| Commit | Phase | Bugs / milestones |
|---|---|---|
| `17dfded` chore(sprint5): close session 7+8 + recovery from shell friction [DC-EPMS-035] | Phase A | DC-EPMS-035 opened+closed |
| `509be04` fix(loto): DC-EPMS-034 witness_engine call site (LOW) | Phase B | DC-EPMS-034 RESOLVED, DC-EPMS-036 opened |
| `8f3f2e6` docs(sprint5): C0 architecture locked + PAUSE_STATE | C0 | — (read-only 1-pager) |
| `b8065db` feat(frontend): Phase 1.0 setup (Chart.js local + skeletons) | Frontend pivot | Edge-first ADR-006 reinforced |
| `b872396` feat(frontend): Bite 1.3 stale-data badge | Frontend pivot | Stream pill 4-state |
| `c42187b` feat(frontend): Bites A1+A2+A3 telemetry activity strip | Frontend pivot | 6-field strip, C2-ready |
| `26b9b1d` (tag: v0.7.4-frontend-pivot) feat(frontend): Bite B SHI trend sparkline | Frontend pivot CLOSED | SVG sparkline + breach markers |
| HEAD (tag: v0.7.5-telemetry-stream) feat(backend): Sprint 5 C1 telemetry simulator + SSE wiring | Sprint 5 C1 | 17 tests GREEN, simulator emits 238 channels |

### Pending from this session (NOT blocking next session)

- **Browser smoke verification of DC-EPMS-034 fix** (older): requires uvicorn restart. Audit on `MOP-ATS-MONTHLY-001` + `ups_a`, confirm `sources_consulted.witness_engine_protection = "confirmed via WitnessStore.sign + IdentityCollisionError (IEC 62443 SR 6.1)"`.
- **Browser smoke verification of Sprint 5 C1** (current): requires uvicorn restart. After restart, hard-reload `http://127.0.0.1:8080/`. Activity Strip "SCHEMA" cell should flip from `legacy_kpi` (gray) to `channel_innovations` (neon-cyan, glow). Anomaly counter remains 0 until C2 wires real Kalman residuals.
- **Optional rollback for C1**: set env var `DC_EPMS_USE_SIMULATOR=0` and restart uvicorn — reverts to legacy DB-poll without code change.

### Resumption protocol (next session entry)

1. Read this `PAUSE_STATE` section.
2. Read `## 🛰 ROADMAP_V9_NEXT_STEPS` for Sprint 5 architecture (above).
3. Verify state per `IMMEDIATE NEXT STEPS` step 2.
4. Restart uvicorn if needed.
5. Activate `.venv`.
6. Wait for Wilmer's explicit GO before starting C1.

### Open bugs at pause time

- DC-EPMS-019 (LOW, deferred): logging file handle on shutdown.
- DC-EPMS-021 (MED, deferred): 90 ruff legacy errors.
- DC-EPMS-022 (LOW, deferred): 6 ADRs MD004 asterisks.
- DC-EPMS-029b (MED, deferred to Sprint 5 C2): SHI delta in `simulate_loto_measurements`. Natural resolution expected during C2.
- DC-EPMS-035 (LOW, closed): shell-friction recovery (V9.1 PowerShell Native Mandate adopted).
- DC-EPMS-036 (MED, deferred to Sprint 5): 4 test-fixture drifts in `tests/test_loto_auditor_pillars.py` from DC-EPMS-029/030/031 production fixes that did not propagate to mocks. NON-regressive (verified pre-existing on clean HEAD `17dfded` via `git stash`).
- DC-EPMS-034 (LOW): RESOLVED 2026-05-09 in commit `509be04`. Stays in registry as historical record.

### V9.1 PowerShell Native Mandate (in force after DC-EPMS-035)

- **Filesystem ops on Windows**: PowerShell-native ONLY. NEVER `mkdir scripts\path` via Bash (backslash collapse).
- **Use**: `New-Item -ItemType Directory -Path 'a/b/c' -Force` (forward slashes), `Get-ChildItem`, `Move-Item`, `Remove-Item`, `Test-Path`.
- **Defensive**: `Test-Path -PathType Container` MUST verify destination is a directory BEFORE bulk `Move-Item`. `Move-Item -Force` to a non-existent directory creates a FILE; subsequent moves overwrite it.
- **Filtering**: `Select-String` (not `findstr` / `grep`).
- **Heredocs**: NO `python -c '...'` heredocs — write a `.py` file and invoke it (Rule 5 PowerShell Pre-Delivery).

## 🚨 DO NOT TOUCH

- `epms-db` Docker container (always running)
- `_legacy_backup/` directory (Batch 1+2 archived materials)
- `.venv/` directory (regenerate via `pip install -e .[dev]` if needed)
- Any commits older than v0.5.0 (foundation, brittle)
- `agent_engine.py` (dual-AI fallback per ADR-004 future, do NOT delete)
