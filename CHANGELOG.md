# Changelog

All notable changes to **DC-EPMS PRO** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Project**: DC-EPMS PRO — AI-native edge operations platform for Tier IV AI factories
> **Facility simulated**: A3-Alpha Toronto Area (67 MW AI factory hyperscale, Path C2)
> **Maintainer**: Wilmer Y. Angel Beltran — a3semi (A-Cubed Semiconductor Systems Inc.)

---

## [Unreleased]

### T4 - printable drill report + relay tags (2026-11-15)

- "Print report (PDF)" in the coach: print-styled HTML report saved as
  PDF from the browser (`core/training_print.js`).
- Report `integrity` block: the SHA-256 recorded in the Forensic
  Ledger and what it covers.
- Relay row per path on the Power SLD (`core/relay_tags.js`): 27 and 25
  simulated; 50/51, 59, 87T identification only (N/M, no protection
  model).
- pytest 1958 / vitest 878 (49 files).

### Training rubric v2 (2026-11-15)

- Unplanned switching: a command outside the drill's
  `procedure_commands` costs -10, like a refused command.
- Steps with a `holds` condition show REVERTED / restored in the coach,
  the report (`step_reverts`) and the SOE.
- Trigger: operator DRILL-04 run (PASS 77) repeated the transfer cycle
  after a clean close. Same run under v2 scores 10 points less.
- pytest 1958 / vitest 869 (48 files).

### UI-1 - Power SLD fits the screen (2026-11-15)

- Named views (Phase 1, Path A, Path B, Phase 2, Farm, All), wheel
  zoom, drag pan (`core/sld_viewport.js`); canvas takes the viewport
  height; incidents rail hidden on the Power route; inspector toggle.
- Drill HUD over the diagram with the current step and ACK ALL.
- Trigger: the operator needed 50 % browser zoom to read the SLD.
- Phones unchanged (DC-EPMS-064 layout). vitest 868 (48 files).

### T3b - sync-check supervised close + DC-EPMS-074 (2026-11-15)

- Closed-transition close is now sync-check supervised: EXECUTE arms
  it, the server closes 52-U at the computed instant of window entry
  (up to 30 s, then cancels). Window ETA and armed banner in the
  faceplate; `POST /api/devices/{id}/sync-cancel`.
- Trigger: the operator's DRILL-04 run on Render failed on timing,
  not on governor control.
- **DC-EPMS-074 RESOLVED**: report SOE kept the authority event's own
  `source` over the report label; now `origin`.
- Ledger records the arming, not the later close instant (in the SOE).
- pytest 1953 / vitest 847 (46 files).

### T3 - synchroscope and closed-transition training mode (2026-11-15, `5cb337a`, `b4e47a6`)

- Operator decision: closed transition is a TRAINING MODE, off by
  default and labelled outside the A3 design (open transition stays
  the design). 52-TIE not added.
- Plant: generator bus frequency and phase angle against a 60 Hz
  utility; CLOSED_TRANSITION_RETRANSFER with the ANSI 25 sync-check
  evaluated at EXECUTE (training values: +/-10 deg, 0.10 Hz slip);
  100 ms model overlap, then 52-GM opens. Governor raise / lower
  (`POST /api/devices/{id}/governor`, direct, bounded, not ledgered).
- DRILL-04: trim, close in sync, stop the sets; an open-transition
  retransfer fails it.
- HMI: synchroscope with governor buttons in the MV transfer
  faceplate; needle extrapolated between polls, lamp is a display
  estimate.
- Checked live: out-of-phase close blocked, then PASS 90.
- Floors (Linux): pytest 1943 passed (3 pre-existing optimizer
  errors), vitest 845 / 46 files.

### T1 + T2 - operator training on the simulated plant (2026-11-15, `61531a8`, `41911fe`, `a166776`)

- Plant (T1): utility loss per path with ANSI 27 trip of 52-U (new
  transfer state OPEN, dead 13.8 kV bus), AUTO transfer sequence,
  master start / stop of the generator bus, battery SOC per path
  (linear in energy from runtime_full_load_min; no Peukert, chemistry
  not in the design), critical load loss latch, UPS inverter
  over-temperature fault, training reset. New alarms: UTILITY_LOST,
  MV_BUS_DEAD, ON_BATTERY, BATTERY_LOW, LOAD_LOST, INVERTER_FAULT.
- Drill engine (T1): `backend/training.py` + `/api/training/*`, drills
  DRILL-01 (utility loss, manual recovery), DRILL-02 (retransfer in
  open transition, stop sets), DRILL-03 (UPS inverter fault, bypass,
  isolate). Rubric "DC-EPMS training rubric v1" is ours, not an
  industry standard. Report JSON with SOE; start, result (report
  SHA-256) and reset in the Forensic Ledger.
- HMI (T2): training coach and select-before-operate faceplate on the
  Power SLD, Web Audio cues (off by default).
- Checked live: DRILL-01 from the HMI only, PASS 100 in 18.5 s.
- Not done (need operator decisions): synchroscope / closed
  transition (T3), 52-TIE, AI instructor; PDF report and relay
  indicators (T4). Drills reset the SHARED simulated plant and need a
  FACILITY_MANAGER session: one trainee at a time.
- Floors (Linux): pytest 1935 passed (3 pre-existing optimizer errors
  on py3.13), vitest 839 / 45 files.

### DC-EPMS-073 RESOLVED - LIVE Power SLD follows the Power Controls plant (2026-11-15, `5d7d397`)

- `core/plant_mirror.js` maps `GET /api/devices` onto a copy of the
  DAG (transfer, generator bus, UPS blocks out, static bypass /
  Dynamic Online caption); `core/power_grid.js` exposes the pure flow
  pass as `propagateStatic`. LIVE only; What-If and Replay keep the
  DAG; plant unreachable -> nominal drawing with a marker.
- Not covered: Replay records the DAG, not the mirror; the N-1 shadow
  evaluates the DAG. Utility loss, battery SOC and Building D are not
  in the plant model.
- vitest 823 / 44 files (backend unchanged).

### HMI H4 - alarm banner, ISA-18.2 states (2026-11-14, `b1ad2c4`)

- `backend/alarm_engine.py` + `backend/alarm_routes.py`: alarm states
  NORM / UNACK / ACKED / RTNUN over the simulated Power Controls
  plant; `GET /api/alarms`, `POST /api/alarms/{id}/ack`,
  `POST /api/alarms/ack-all` (L1_OPERATOR minimum, session actor,
  Forensic Ledger `ALARM_ACK`). ACK changes no plant state.
- Power view banner: live alarms from the backend, sandbox alarms in
  What-If (local ack, never logged). UNACK flashes, priority by colour
  and text, ms timestamps.
- Honest scope: observation times, not field SOE; no shelving;
  priorities are a first rationalisation.
- **DC-EPMS-073 (MEDIUM, resolved 2026-11-15 in `5d7d397`)**: the Power SLD drawing followed the
  browser DAG, not the Power Controls plant. A transfer or a UPS
  bypass done in Power Controls raises a live alarm on the banner,
  but the drawing does not show it.

### HMI H2 + H3 - interlock, unit-substation breakers, MODEL tags (2026-11-14, `78d3c23`)

- 52-U / 52-GM interlock drawn; unit-substation primary and secondary
  breakers drawn in the design normal lineup (not modelled or metered).
- MV bus data tag per path (P, Q, S, PF 0.90, 13.8 kV, 60 Hz) marked
  MODEL; 60 Hz at the utility, 480 V at the RPP, battery autonomy as
  the 10-minute spec. Transformer losses not modelled.
- Old action-bar legend (cyan / violet / amber) removed: it
  contradicted H1.
- Floors (Linux): pytest 1904 passed (3 pre-existing optimizer errors
  on py3.13), vitest 812 / 43 files.

### HMI H1 - ISA-101 style pass on the Power SLD (2026-11-14, `0aeddff`)

- Breaker convention in one constant (`core/hmi_scheme.js`). Default
  `ansi` for the Ontario site: red filled = CLOSED, green hollow =
  OPEN; `iec` is the inverse. The state is also written as text
  (CLOSED / OPEN / XFER / TRIP). An MV transfer controller trip shows
  TRIP on the breaker that was carrying the bus.
- Grey matte canvas, grey = normal, colour = exception; solid feeders
  and buses; animated dashes removed, static direction chevrons per
  run instead. Generator-fed runs are no longer amber (that colour is
  the 800 VDC legend colour).
- Legend split in two blocks; status strip follows the scheme.
- Phase 2 DESIGN branch unchanged. Not yet done: H2 topology, H3 data
  tags labelled MODEL, H4 ISA-18.2 alarm banner (each needs a GO).
- Honest scope: neither breaker palette is mandated by one standard
  the HMI can cite; ISA-101 leaves the palette to the site HMI
  philosophy. vitest 794 / 42 files.

### DC-EPMS-068 lote C2 — topology, procedures, fixtures (2026-11-14, `4a862cc`)

- Topology HLD labels on the closed design; Procedure Architect
  presets from `/api/site/model` roles (static fallback).
- Legacy-id fixtures resolved by role: the backend suite now passes
  on both models (1886 with the flag unset, 1886 with `v2`; was 5
  failures under v2). vitest 786 / 41 files.
- Remaining for DC-EPMS-068: procedure YAMLs (operator review),
  simulator check of the v2 points, then v2 as default.

### Power SLD "vida 2" (2026-11-14, `3768abe`)

- `core/power_status.js`: per-path status strip (source, load and
  share, UPS and generator N / N+1, 52-U / 52-GM) and a clocked
  sequence of events derived by diffing DAG snapshots (utility lost,
  52-U opens, crank, running, 52-GM closes, battery on / off, blocks
  or sets out). The sequence shows in What-If; t = 0 is the first
  event of the session.
- Checked at 1600 px and 440 px. vitest +10.

### Power SLD "vida 1" (2026-11-14, `1ef07cf`)

- Operator review of the C1 drawing: the numbers contradicted the
  design (a 300 kW UPS, a 1,800 kVA transformer from the legacy
  physics samples), breakers were text only, the MV switchgear and
  unit substations were missing, labels collided.
- `core/power_flow.js`: drawn numbers from the design (2N 50/50,
  per-block load, losses at eta 0.97, kVA at pf 0.9). Same 259 kW
  path losses as Power Controls. Design model, not metering.
- SLD: ANSI 52-U / 52-GM drawn open, closed or in transfer; 13.8 kV
  switchgear and 8 x 3.5 MVA unit substations; animated power flow
  (speed scales with MW, colour by source, dead runs dimmed), MW
  labels on the feeder, generator drop and UPS output.
- Asset panel: UPS bank opens into its 8 blocks with N / N+1.
- Fixes: label overlaps, standby generator no longer painted as a
  fault by the DAG (a red or orange G can still come from telemetry
  severity: the simulator's generator channels trip the anomaly
  counter, see DC-EPMS-043).
- Tests +15 vitest; vitest 773 / 40 files.

### DC-EPMS-068 lote C1 — Power SLD on the closed design (2026-11-14, `8fa0b96`)

- The Power & UPS single-line diagram and its What-If DAG now draw the
  closed Phase 1 design from `config/power_plant.yml` on every host
  (Power Controls already did): utility 27.5 kV, transformer
  27.5 / 13.8 kV, MV transfer controller 52-U / 52-GM (replaces the
  480 V ATS), generator bus 9 x 2.75 MW, UPS bank 8 x Trinergy 2500.
- One tick per installed unit, with capacity and N+1 / N only / BELOW
  N. In What-If a tick takes a unit out or returns it. Live mode never
  actuates from the SLD; the MV transfer controller is switched only
  from Power Controls.
- Live readings still come from whichever site model the backend runs
  (legacy on the public host); the node registry maps both id sets.
- NOT in C1: the 13.8 kV MV switchgear and the unit substations are
  not drawn as separate nodes (the caption names the path), the
  topology (HLD) view, Mission Control, procedures. Those are lote C2.
- Pre-existing, not fixed: on the SLD the UPS load metric and the
  battery label overlap slightly.
- Tests +16 vitest; vitest 758 / 39 files.

### DC-EPMS-068 lote B — backend by role, not by literal id (2026-11-14, `56c7124`)

- New `backend/site_roles.py` (pure): resolves the path transfer
  device, UPS blocks and utility transformer per path from the loaded
  model. Legacy: `ats_a`, `ups_a`, `xfmr_a`. v2: `mvtc_a`,
  `ups_a_01..08`, `mv_xfmr_a`.
- `power_chain_for` groups feeds by the transfer device (it was
  hard-coded to `ats_a` / `ats_b`, so on v2 no rack had a path A / B
  feed).
- LOTO auditor pillar 2: a single UPS block LOTO on v2 keeps the path
  (7 x 2.5 MW = 17.5 MW >= 16.76 MW full facility IT load) and now
  passes; path state `block_loto_path_keeps_n`. On legacy (one UPS per
  path) nothing changes: still a path loss and HARD_FAIL. Two blocks
  out at once in the same path is NOT modelled (overlapping
  maintenance check is still deferred, ADR-009).
- Boot warmup, copilot `query_unified_graph` (maps `ups_a_04` or
  `mv_xfmr_a` to its HLD group and lists the members), CMMS seeder
  (declared path wins; MV transfer controller and MV switchgear are
  2N), `GET /api/site/model` roles, tool descriptions.
- NOT changed: the HLD aggregate keys of `get_topology_state`
  (`utility_north`, `xfmr_a`, `ups_a` ...) are a display namespace
  shared with the topology view; they move with the frontend lote.
- Under `DC_EPMS_SITE_MODEL=v2` the full suite gives 5 failures, all
  test fixtures written for legacy ids (`test_api_procedures` 3,
  `test_site_integration` 2). Default (legacy) suite: all pass.
- **DC-EPMS-072 (open, MEDIUM)**: only 10 of the 50 modelled Phase 1
  racks carry a power chain, on BOTH variants. LOTO impact and rack
  counts under-report. Fenced in `tests/test_site_roles.py`, not fixed.
- DC-EPMS-064 confirmed by the operator on a real iPhone (2026-11-14).
- Tests +28 pytest. Floors (Linux, Python 3.13): pytest 1886 passed,
  3 pre-existing `test_optimizer` errors; vitest 742 / 38 files.

### DC-EPMS-064 RESOLVED — phone layout (2026-11-14, `b101d1b`)

- Target: iPhone 16 Pro Max and 17 Pro Max, 440 x 956 CSS px, safe
  area 62 px top / 34 px bottom in portrait (third-party device
  tables; not measured on a device).
- Below 900 px: drawer navigation (`core/mobile_nav.js`), compact
  header (logo + health dots), one scrolling column with the rail
  under the view, safe-area padding (`viewport-fit=cover`), `100dvh`,
  44 px nav targets, 16 px inputs, pinch zoom kept. SLD and P&ID keep
  an 860 px drawing and pan sideways. Desktop unchanged.
- Checked with headless Chrome at 440 x 956: no horizontal page
  overflow on 22 views; Power Controls operable by tap, GEN-N1-001
  PASS. NOT checked on a real iPhone (Safari rendering may differ).
- Tests +11 vitest. Floors: vitest 742 / 38 files.

### DC-EPMS-068 lote A — runtime switch (2026-11-14, `d90f4ef`)

- `DC_EPMS_SITE_MODEL`: unset / `legacy` (default, the public host) or
  `v2`. Unknown values raise `SiteModelConfigError` (fail closed).
- v2 is refused when stale (rebuild from `site_model.yml` +
  `power_plant.yml` differs from the committed file) or when the
  validator reports a problem.
- `GET /api/site/model` reports variant, file, components, retired
  ids present. Boot log: `model=legacy|v2`.
- Under v2 the backend boots with 177 components and the main routes
  answer 200. Consumers on retired ids are NOT ported (lote B on).
- Tests +20 pytest. Floors (Linux, Python 3.13): pytest 1858 passed,
  3 pre-existing `test_optimizer` errors.

### Deploy — public release live on Render (2026-11-14)

- `master` fast-forwarded `2fa40c7..941f002` and pushed with
  `release/public-full-app` by the operator from the Windows
  workstation. Render (`dc-epms-pro.onrender.com`) runs `941f002`:
  boot log shows the power plant control with 9 scenarios, OT
  Security, USD export, CMMS in memory, warmup skipped, and the IAM
  gate refusing repo-default passwords (only users with a
  `DC_EPMS_PWD_<USER>` set are seeded).
- Verified live: anonymous `GET /api/devices` -> `{"detail":
  "authentication required"}`; `GET /api/health` -> 200 (public by
  design for the platform health check).
- Operator Windows floors (Python 3.12, `epms-db` down):
  **pytest 1832 passed, 8 skipped** (7 PostgreSQL integration, 1
  `pxr` absent), 0 failed; **vitest 728 / 37 files**. Browser flow
  on the Power Controls view validated by the operator.
- Security note: one pair of JWT / ledger secrets was printed in a
  shared terminal transcript; the operator was told to rotate both
  on Render. Treat any value seen outside Render as revoked.

### Fix — DC-EPMS-071: public /api/health leaked internals (2026-11-14)

- On a gated deployment the anonymous health payload showed
  postgres / rag / gemma / gpu as `down` (absent by design, read as
  a fault) and published the loopback LM Studio URL.
- Now: gate on -> `status: "disabled"` + reason, `mode: "public"`,
  no URL, no exception text, loopback LLM not probed. Gate off ->
  unchanged. Overview header pills render `disabled` neutral.
- Tests +9 pytest, +3 vitest. Linux floors: pytest 1838 / vitest
  731 (37 files). Deployed in `610070e`.
- Test-only follow-up: on the operator Windows venv (chromadb
  installed) `TestPublicHealth` failed (`rag` reported `up`) because
  the lifespan rebinds `rag_service` after the fixture patched it.
  The fixture now forces "no RAG" after startup. Reproduced on Linux
  with a fake `RAGService` bound in the lifespan: old fixture fails,
  new one passes. Production behaviour was correct (Render has no
  chromadb); the defect was in the test.

### Fix — DC-EPMS-069: boot warmup crashes the test run on AMD + Windows (2026-11-14)

- **Found** on the operator workstation (Windows, Python 3.12, AMD
  Ryzen) while applying the R3-C bundle: pytest stopped at about 48
  percent with `Windows fatal exception: access violation` in
  `pyarrow`, imported by the lifespan GraphRAG warmup
  (`sentence_transformers -> transformers -> sklearn -> pyarrow`).
  Same family as DC-EPMS-001.
- **Cause, mine:** `tests/test_no_database_mode.py` (R1) and
  `tests/test_ot_security.py` (R2-A) boot the full app lifespan. The
  pre-existing suite never does. In the Linux sandbox the embedding
  stack is not installed, the warmup failed softly and the problem
  stayed hidden. The earlier "pytest passed" floors were therefore not
  representative of the operator machine.
- **Fixed:** `DC_EPMS_SKIP_WARMUP=1` skips both warmup stages; the two
  fixtures set it. +2 tests prove the switch (spy on both stages).
- **Second pass (same day):** the operator run then reached 73 percent
  and died in `tests/test_session_gate.py::TestRealApp` (also mine, R1),
  this time in FAISS AVX2. Fixed at the root: `tests/conftest.py` turns
  the warmup off for the whole session; a test that wants it must opt
  back in. Verified by emulation: stand-in `sentence_transformers`,
  `faiss` and `pyarrow` modules that abort on import. Without the
  conftest the run aborts like the workstation (exit 134); with it the
  whole suite completes (1829 passed, 3 pre-existing errors that are a
  pytest 9 deprecation of this sandbox).
- **Operator workstation, 2026-11-14:** vitest 728 passed / 37 files.
- **DC-EPMS-070 (LOW, pre-existing, open):** `tests/frontend/demo_mode.test.js`
  prints six `ECONNREFUSED 127.0.0.1:3000` errors (a real fetch against
  the happy-dom origin). Present on master `2fa40c7`; the tests pass.

### Release R3-C — Generation N+1 on total load + site_model v2 (2026-11-14)

> Operator document `Estructura_Repositorio_y_Resolucion_DC-EPMS_066_067_068.md`
  (copied to `docs/design/operator/`).

- **DC-EPMS-066 RESOLVED** (`613d32f`, ADR-013): generators 9 x 2.75 MW
  at 13.8 kV per path. N = 24.75 MW, N+1 = 22.0 MW against the 21.5 MW
  design total.
- **DC-EPMS-067 RESOLVED** (`613d32f`, ADR-013): generation floor =
  max(current total path load, computed full-path demand, design
  total). Drives the withdrawal interlock (R10), the isolation goal and
  the generation N / N+1 checks. Consequence: one generator per path
  out at a time. The panel shows total-load and IT-only floors.
- **Changed** generator ids `gen_p_NN` -> `genset_p_NN` to match the
  site model. Scenarios bumped to 1.1.0; new `GEN-N1-001`.
- **DC-EPMS-068 IN PROGRESS** (`d282904`): `backend/site_model_v2.py` +
  `scripts/build_site_model_v2.py` generate `config/site_model_v2.yml`
  (177 components) and `config/telemetry_mapping_v2.yml` (516 points,
  symmetric) from `site_model.yml` + `power_plant.yml`; `--check` fails
  on drift. The validator reproduces DC-EPMS-058 on the legacy model and
  passes on v2. Runtime still on the legacy model: 13 backend, 10
  frontend, 5 procedure and 39 test files reference retired ids
  (`docs/design/DC-EPMS-068_MIGRATION.md`).
- **DC-EPMS-060**: closed at specification level (symmetric points in
  the telemetry mapping); runtime pending with 068.
- **Not done, with reason**: physical repository restructure (mapped
  instead, `docs/design/REPO_STRUCTURE_MAPPING.md`: digit-prefixed
  folders are not importable, 214 Python files would move); incident
  energy (no fault-level or clearing-time data; the IEEE 1584 documents
  referenced in the operator tree were not received).
- **Tests**: +26 pytest net (1826 passed / 3 pre-existing errors);
  vitest 728 passed / 37 files (assertions updated).

### Release R3-B — Closed plant design, MV switching safety, scenario library (2026-11-14)

> Operator closed the design (8 x Vertiv Trinergy 2500 and 9 x 2.5 MW
  generators at 13.8 kV per path, MV transfer, 2N, Tier IV target) and
  set safe medium-voltage switching as the first priority.
  **The plant is SIMULATED**; the view and the API say so.

- **Added** `config/power_plant.yml`: the closed design. The 25 percent
  cooling and auxiliaries share is an assumption (the operator
  documents leave it open).
- **Changed** `backend/device_control.py`: roster built from the design
  (16 UPS blocks, 2 MV transfer controllers, 18 generators); path
  capacity checks (UPS and generation, N and N+1); UPS losses as
  `P_out * (1 / eta - 1)` (259 kW per path in normal 2N, 518 kW with a
  full path, 85 kW in Dynamic Online); Dynamic Online mode; UPS block
  isolation that keeps N; transfer only with enough generation
  synchronised. The R3-A roster from `site_model.yml` (one UPS, 480 V
  ATS) is gone from the panels.
- **Added** `backend/mv_switching.py`: pure interlock engine for a
  generator bay (52-G, disconnector, earthing switch, LOTO), rules R1
  to R10, fail-safe; forced switching procedures (only the next step
  runs); two-person rule on earthing and LOTO.
- **Added** `backend/power_scenarios.py` + `config/power_scenarios/`:
  8 versioned executable scenarios run in a sandbox; a scenario fails
  if an expected block does not happen.
- **Added** routes `/api/mv/bays/{id}/procedure`,
  `/api/mv/procedures/{id}/witness|step|abort`, `/api/power-scenarios`,
  `/api/power-scenarios/{id}/run`.
- **Changed** `views/device_control.js`: path tabs, capacity tiles, bay
  indications, procedure stepper with in-panel witness, scenario
  library.
- **Tests**: +49 pytest, +11 vitest. Floors (Linux, Python 3.13, no
  PostgreSQL): pytest 1800 passed / 3 pre-existing errors; vitest 728
  passed / 37 files.
- **Finding DC-EPMS-066 (HIGH, design, open):** 9 x 2.5 MW generators
  give N but not N+1 once cooling is counted. Full-path demand is
  21.5 MW with the 25 percent assumption; 8 sets give 20 MW. The
  operator document's own band (20.5 to 23 MW) is above 20 MW
  throughout. Needs 10 sets, or 2.75 MW sets (8 x 2.75 = 22 MW), or a
  smaller cooling share on generators.
- **Finding DC-EPMS-067 (MEDIUM, design, open):** the operator rule for
  taking a generator out ("residual capacity at least 16.76 MW")
  counts IT load only. The interlock implements the rule as written,
  so it permits an isolation that leaves the path below its full
  demand. The capacity tile shows it as "N: NOT MET".
- **DC-EPMS-068 (MEDIUM, open):** two sources of truth. The panels use
  `power_plant.yml`; the SLD, physics, telemetry and LOTO auditor
  still use `site_model.yml` with the old design (DC-EPMS-057..061).
- **Not done** (from the operator documents): arc-flash incident
  energy and PPE category, thermal model and survival time, scenarios
  TH-001 / TH-002 / COMB-001 (need the thermal model), protection
  relays, utility-outage dynamics and battery discharge, permit-to-work
  gate, link to the LOTO auditor, IEC 61850 bindings, HAL binding.
  DC-EPMS-063, -064 and -065 remain open.

### Release R3-A — Power Controls: UPS, transfer and generator panels (2026-11-13)

> Operator request: a readings and control panel per UPS, transfer
  switch and generator, with manual switching and remote control.
  **Devices are SIMULATED**; the view and the API say so.

- **Added** `backend/device_control.py`: deterministic supervisory
  model built from the site model (types `ups`, `ats`, `genset`).
  Authority AUTO / REMOTE / LOCAL per device, select-before-operate
  (single-use token, 30 s, bound to device and operator, interlocks
  evaluated twice), role from the session token (FACILITY_MANAGER),
  every authority change and operate attempt chained in the Forensic
  Ledger (ADR-011). Routes: `GET /api/devices`, `GET /api/devices/{id}`,
  `POST /api/devices/{id}/authority | select | operate`.
- **Added** `frontend/assets/js/views/device_control.js` (route
  `device-control`, nav "Power Controls") and `dvc-*` styles.
- **Added** `docs/design/R3_POWER_CONTROLS_EVALUATION.md`: product
  check (Vertiv, Schneider, Eaton) and findings on the operator's UPS
  2N documents.
- **Tests**: +46 pytest, +23 vitest. Floors (Linux, Python 3.13, no
  PostgreSQL): pytest 1751 passed / 3 pre-existing errors; vitest 717
  passed / 37 files.
- **Not done**: no HAL binding, no protection functions, no panel for
  the 800 VDC side, site model still on the old Phase 1 design.
- **DC-EPMS-063 (MEDIUM, open):** the OT Security posture does not yet
  inventory the device-control surface (it lists BMS writable tags
  only). Add checks for it in R3-B.
- **DC-EPMS-064 (LOW, open, pre-existing):** the application shell is
  not responsive; at 390 px the sidebar leaves the content off-screen
  on every view.
- **DC-EPMS-065 (MEDIUM, open, pre-existing):** `/api/bms/write` and
  `/api/bms/revert` take `actor_role` from the request body. With the
  session gate on they still accept any authenticated user who sends
  `SME_L6`. Move them to the token role, as device control does.

### Release R2-C — USD export (2026-11-13)

> Operator GO "procede". Replaces the Omniverse 3D stub. **Static,
> schematic export. There is no Omniverse live-link and no telemetry
> in the stage; the view and the file both say so.** Same branch
> `release/public-full-app`. Not tagged, not pushed.

### Added

- `backend/usd_export.py`: `build_usda(model)` renders
  `config/site_model.yml` as an OpenUSD ASCII layer. One prim per
  building, room, row and component (113 cubes), metadata as typed
  `a3semi:meta:*` attributes, power and cooling chains as
  `a3semi:powerFeeds` / `a3semi:coolingFeeds` relationships (54 + 24).
  Pure text generation (no `pxr` at runtime), deterministic,
  7-bit ASCII. A prim-path collision raises instead of overwriting.
- `GET /api/site/usd` (download, `Content-Disposition` filename from
  the site id) and `GET /api/site/usd/summary`. Read-only (ADR-006),
  behind the session gate.
- `frontend/assets/js/views/usd_export.js` + styles + nav entry
  "USD Export" (route `usd-export`).
- The layout is SCHEMATIC: the site model has no coordinates, so
  positions are a deterministic grid and sizes are per asset type.
  22 components have no building and are exported under `unplaced`.

### Verified (Linux, Python 3.13, no PostgreSQL)

- The generated layer opens with the USD runtime (`usd-core` 26.11):
  113 Cube prims, 78 relationship targets, none dangling, Z-up,
  metres. **Not opened in NVIDIA Omniverse or usdview: neither is
  available in the authoring environment.**
- Downloaded through the UI on a gated instance and re-opened.
- pytest 1705 passed (+38), 0 failed, same 3 pre-existing errors.
  The USD-runtime test is skipped when `usd-core` is not installed.
- **DC-EPMS-062 (LOW, pre-existing, not fixed):**
  `tests/test_subprocess_cleanup.py` reloads `main`; any test that
  boots `main.app` afterwards fails with "Duplicated timeseries"
  (Prometheus in-progress gauge). It was latent because no such test
  sorted after it. The new route tests use a minimal app instead.
- vitest 694 passed across 36 files (+14).

### Open — UPS and medium-voltage audit (operator question, NOT fixed)

Asked "is the UPS and MV module complete?". It is not. What exists:
UPS one-line with Q1-Q5 discipline and IEC 62040-3 modes, UPS
efficiency + battery physics, genset NFPA 110 sequence, Phase 2
branch drawn as DESIGN, MOP-001 + T4-MOP-UPS-001. What does not
close, verified against `config/site_model.yml` at this commit:

- **DC-EPMS-057 (HIGH) — Phase 1 electrical sizing does not carry the
  load.** Per path: UPS 2.5 MW, switchgear 480 V x 4000 A = 3.33 MVA,
  gensets 2 x 2.75 MW = 5.5 MW. Phase 1 IT load is 16.76 MW (118
  racks) and 7.1 MW even for the 50 racks actually modelled. In 2N
  each path must carry the full load. The model is short by a factor
  of about 6.7 on UPS capacity.
- **DC-EPMS-058 (HIGH) — ATS and gensets sit on the wrong side of the
  transformer.** `power_chains` reads utility 27.5 kV -> ATS -> xfmr
  (27.5 kV to 480 V) -> switchgear. The ATS is declared 480 V /
  4000 A and the gensets are 480 V machines, yet both are upstream of
  the step-down transformer, i.e. at 27.5 kV.
- **DC-EPMS-059 (MEDIUM) — medium voltage is a pair of nodes, not a
  system.** No MV switchgear or breaker at 27.5 kV or 35 kV, no
  protection relaying, no MV metering, no grounding scheme. Phase 2
  is drawn but non-operable by design.
- **DC-EPMS-060 (MEDIUM) — asymmetric instrumentation.** UPS A has 10
  BMS tags, UPS B only its 5 breaker positions; transformer A has 3
  tags, transformer B none. UPS telemetry carries SoC, runtime and
  phase voltages but no load, output current or bypass state. There
  is no UPS HAL adapter (Cummins, ASCO and Russelectric only).
- **DC-EPMS-061 (LOW) — drift.** Site metadata still says
  `it_capacity_mw: 40.0` / `total_capacity_mw: 56.0` (Path C2 is
  67 MW). `PWR.XFMR_A.OIL_TEMP` exists while MOP-002 treats the
  transformer as dry-type.

### Release R2-A — OT Security view (2026-11-13)

> Operator GO "OT Security". Replaces the Morpheus OT stub with a
> read-only posture view built only on state the platform can prove
> about itself. **No network traffic is inspected and no NVIDIA
> Morpheus pipeline exists; the view states that permanently and
> reports it as an open finding (OT-NET-01).** Same branch
> `release/public-full-app`. Not tagged, not pushed.

### Added

- `backend/ot_security.py` + `GET /api/ot-security/posture`
  (read-only, ADR-006; deterministic, no LLM, S-DET-01). Twelve
  checks over five fact sections: access (session gate, JWT secret
  source, accounts still on repository-default passwords), forensic
  ledger (chain verification, HMAC key source, persistence), control
  surface (writable BMS tags by protocol, connector audit buffer),
  edge ingest counters, and what is not monitored. A section that
  cannot be read fails closed. The response carries booleans, counts
  and names only: no secret, password, hash or token.
- `frontend/assets/js/views/ot_security.js` + styles + nav entry
  "OT Security" (route `ot-security`). Severity is carried by a text
  badge, never colour alone. Polls every 15 s only while visible.
- `app.state.edge_channel_store`: the ingest store returned by
  `register_telemetry_ingest` was discarded; it is now kept so its
  counters can be reported.
- IEC 62443-3-3 SR references on every check are a design-time
  mapping by requirement title (SR 1.1, 1.2, 1.5, 2.1, 2.8, 3.5, 3.9,
  5.1, 6.2). **Not a conformance assessment; verify the SR wording
  against the standard before quoting it externally.**

### Fixed

- **DC-EPMS-056 (HIGH, documentation defect introduced in R1)** —
  `docs/DEPLOY_PUBLIC.md` told the operator to set
  `DC_EPMS_LEDGER_HMAC_KEY` to "32+ random characters" generated with
  `token_urlsafe`. The ledger requires a HEX string of at least 32
  bytes and raises at boot otherwise, which would have left the
  public instance without a forensic ledger. Corrected to
  `secrets.token_hex(32)`; the OT Security view now also shows the
  key posture.

### Findings the new view reports on this codebase (open by design)

- OT-DEV-01: the edge gateway presents no device credential.
- OT-NET-01: no OT traffic inspection.
- OT-NET-02: `config/site_model.yml` assigns no zone or conduit.
- OT-AUD-03 on any instance without PostgreSQL.

### Verified (Linux, Python 3.13, no PostgreSQL)

- pytest 1667 passed (+22), 0 failed, same 3 pre-existing errors.
- vitest 680 passed across 35 files (+29).
- Browser: view rendered on a default local instance (2 high,
  5 medium, 1 low, 2 passing) and on a hardened gated instance
  (0 high, 3 medium, 1 low, 6 passing), no failed request.

### Release R1 — public full-app deployment (2026-11-13)

> **Theme:** make the whole platform runnable and honest on a public
> URL: mandatory login that actually gates the API, no PostgreSQL
> required, and the two views that had shipped without any styling
> finished. Driven by a clean-clone audit (boot + 23-view browser
> sweep), not by the documented state. Commits `26f0318`, `e564246`,
> `e0c8621`, `b2bab87` on branch `release/public-full-app`.
> **Not tagged.** Not pushed from the authoring session (no push
> access); delivered as a patch series.
>
> ID note: commit `26f0318` cites the PyJWT defect as "DC-EPMS-040".
> That ID was already taken (CMMS re-approve guard). The canonical ID
> is **DC-EPMS-050**; the commit message was left as written.

### Fixed

- **DC-EPMS-050 (HIGH)** — `PyJWT` was imported by
  `backend/auth/jwt_handler.py` but declared nowhere. Clean install:
  IAM store failed to seed, login answered 503. Declared in
  `pyproject.toml` and the three `requirements*.txt`.
- **DC-EPMS-042 (HIGH)** — the Epic 10 login gated the HMI only; every
  API route, the SSE stream and the Hermes WebSocket were reachable
  with no session. New `backend/auth/session_gate.py` (pure ASGI, http
  + websocket), enabled by `DC_EPMS_REQUIRE_AUTH`; login sets an
  httpOnly session cookie. Default OFF.
- **DC-EPMS-044 (HIGH)** — without PostgreSQL the CMMS boot block was
  skipped, and with it the Tech Assist, Multi-Agent, predictive
  trigger and Optimizer routes (404 across four views). Falls back to
  the in-memory repository; `/api/cmms/health` reports the backend.
- **DC-EPMS-046 (HIGH)** — `views/optimizer.js` (113 classes) and
  `views/procedures.js` (45 classes) had zero CSS rules and rendered
  as browser-default HTML. Styled; a vitest class-coverage fence now
  fails on any new unstyled `opt-` / `proc-` class.
- **DC-EPMS-047 (HIGH)** — `/#route` bypassed the login view.
  `core/auth_gate.js` + router/bootstrap guard.
- **DC-EPMS-045 (MEDIUM)** — Overview KPI cards (hall temperature, IT
  load, fleet) empty unless the external `scripts/simulator.py` wrote
  the legacy table. `/api/telemetry/latest` falls back to an
  in-process row (`backend/kpi_fallback.py`), source labelled.
- **DC-EPMS-048 (MEDIUM)** — empty main area after sign-in until a nav
  click.
- **DC-EPMS-049 (MEDIUM)** — `requirements-minimal.txt` booted but
  silently lost Procedure Generator, GraphRAG, LOTO Auditor and edge
  ingest (numpy / networkx / scipy / protobuf missing).
- **DC-EPMS-041 (LOW)** — pytest refused to configure / collect on a
  fresh install (asyncio loop-scope + anyio alias deprecation under
  `filterwarnings = error`).
- Stub views (Morpheus OT, Gemini ER 1.6, Omniverse 3D) described
  running systems that do not exist and mis-attributed Gemini
  Robotics-ER (Google) to NVIDIA. Rewritten as "Not implemented" and
  tagged `planned` in the nav.
- README: 40 MW -> 67 MW Path C2; Tier 1 text matches behaviour.
- Smaller HMI items: login form styling, Tech Assist 503 message,
  Mission Control status chip hidden under the Building A card,
  `* ` bullets in the procedure renderer.

### Added

- `DC_EPMS_PWD_<USERNAME>` password overrides; on a gated deployment a
  user without one is not seeded (repo-default passwords refused).
- `DC_EPMS_CMMS_FALLBACK` (`memory` default, `off` restores the skip).
- `docs/DEPLOY_PUBLIC.md`.
- `frontend/assets/demo_config.json` now `demo_mode: false`; the
  hackathon view remains at `?demo=1` without a login.

### Verified (authoring environment: Linux, Python 3.13, no PostgreSQL)

- pytest: 1645 passed, 0 failed, 3 errors, 2 skipped, 5 deselected
  (baseline before any change: 1568 passed, 1 failed, 3 errors). The
  3 errors (`test_optimizer::TestProposerPatternInvariant`) predate
  this work and are attributed to the environment (Python 3.13 / newer
  pytest); the baseline failure (`test_skill_audit ... last_3_commits`)
  was a shallow-clone artefact that cleared once the branch had three
  commits. **Not re-verified on the project's Windows / Python 3.12
  environment.** +76 tests.
- vitest: 651 passed across 34 files (baseline 622 / 33). +29 tests.
- Browser sweep (headless Chrome): 23 of 23 views render with no
  failed API call other than the designed 503 postures (Optimizer OFF,
  Tech Assist library without RAG). Repeated with the gate ON.
- Clean virtualenv from `requirements-minimal.txt`: boots with no
  missing-module error.

### Open — found by the audit, NOT fixed (need an operator decision)

- **DC-EPMS-043 (HIGH, alarm management)** — the ANOMALIES (60M)
  counter saturates on a healthy plant. Measured: 30 unique channels
  after 10 ticks, 128 after 60, 254 of 281 after 300, with no injected
  anomaly and SHI 1.00. Cause is statistical, not calibration: a
  single-sample 3-sigma test over 5 samples per tick gives about 1.35 %
  false positives per channel per tick. Fix needs a persistence rule
  (k-of-n) and changes `is_anomalous` semantics used by the predictive
  trigger and edge healing — ISA-18.2 rationalization, operator call.
- **DC-EPMS-051 (MEDIUM)** — Overview advisory thresholds are
  hard-coded (warn > 1.30, crit > 1.40) while `config/pue_targets.yml`
  says Phase 1 warn 1.45 / crit 1.60. The simulated PUE sits near
  1.32-1.34, so the Overview shows a permanent "PUE trending upward"
  banner while the PUE panel says "good".
- **DC-EPMS-052 (LOW)** — LOTO Auditor registration raises NameError
  (`_s2_service`) when GraphRAG fails to import (masked now that
  networkx is in the minimal set).
- **DC-EPMS-053 (LOW)** — ruff 0.9.x reports 6 errors in
  `backend/shift_copilot.py` (UP017 x5) and `backend/llm_providers.py`
  (UP035); CLAUDE.md claims 0. Not touched.
- **DC-EPMS-054 (LOW)** — Mission Control is tagged `spike` in the nav
  and `B1 PRODUCTION` in its header.
- **DC-EPMS-055 (known)** — the site model carries 50 racks; headers
  and the README state 118. Mission Control now shows 30 + 20.
- Sessions last 1 hour with no refresh and no sign-out control.

> **CHANGELOG reconstruction note (2026-05-16)**: the entries from
> `v0.7.2-camino1` through `v0.10.13-modal-fix` below were reconstructed from
> annotated git tags. The CHANGELOG was not maintained during the rapid
> 2026-05-08..10 iteration arc; the tag annotations are the authoritative
> record and are transcribed faithfully here. Forward planning lives in
> `docs/ROADMAP-V11.md` (locked 2026-05-10).

## [v0.17.0] — 2026-05-24 (Life Safety + Combustible — catalog expansion to 29 canonical MOPs)

> **Theme:** asset-category expansion. The catalog grows from 23
> to 29 canonical MOP bodies with 2 new vector layers (Life Safety
> + Combustible) the system prompt already enumerated since v0.16.0
> but had no canonical bodies for. Built ON TOP of the v0.16.1
> hardened audit gate; no audit changes were needed. Minor version
> bump because the new asset categories are user-facing feature
> surface (HMI chips + library + GraphRAG).

### Added

- **3 Life Safety canonical bodies** (`docs/operaciones/mops/`):
  MOP-024 VESDA Zone Functional Test (FM 7745 annual), MOP-025
  Novec/FM-200 Cylinder Pressure Annual Verification (NFPA 12
  §4.7.4 dual manómetro + balanza cross-check), MOP-026 Clean
  Agent Discharge Reset (post-event recovery + bomberos clearance
  + SCBA + multi-gas).
- **3 Combustible canonical bodies** (`docs/operaciones/mops/`):
  MOP-027 Day Tank Bulk Fuel Transfer (NFPA 30/110 + IEC 60079 +
  bonding cable + spill containment), MOP-028 Day Tank Fuel
  Polishing (ASTM D6304 Karl Fischer + circuit cerrado), MOP-029
  Generator Extended Runtime > 12 h (NFPA 110 §A.5.6.4 + winding
  temp 110 °C critical + fuel sampling cada 24 h).
- **`config/knowledge/life-safety-combustible-references.md`**
  (GraphRAG 10 → 11): NFPA 12/72/75/110/30 + FM 7745 + ISO 14520 +
  ASTM D2276/D6304 + IEC 60079 + ANSI/AIHA Z9.5 cross-references +
  physics + chemistry (VESDA aspirating, Novec NOAEL, diesel
  biofilm, Karl Fischer method, Arrhenius insulation, ISO 10816).
- **HMI chip categorías 10 → 12** in
  `frontend/assets/js/views/procedures.js`:
  - `life_safety` (3 chips) + `combustible` (3 chips).
  - Total chips 32 → 38.
  - Each chip pre-seeds the full safety contract + category-specific
    vocabulary (SCBA, bonding cable, Maintenance Mode, ASTM
    sampling, Karl Fischer, winding temp monitoring).

### Changed

- **Architect library** pre-seeds **23 → 29** catalog entries at
  boot. Boot log: `[BOOT] Architect library pre-seeded with 29
  catalog MOP(s)`.
- **GraphRAG corpus** loads **10 → 11** knowledge documents at
  boot.
- **CLAUDE.md** updated: CURRENT STATE block reflects v0.17.0
  expansion.
- Backend `__version__` 0.16.1 → 0.17.0; mirrored in 5 stack
  locations.

### Not changed (deliberate)

- **Audit gate** — no changes. The hardened contract supports Life
  Safety + Combustible as 2 of the 6 enumerated vectors since
  v0.16.0. Audit verification: 29/29 verdict=APPROVE end-to-end.
- **Skills registry** — 24 skills unchanged. Existing S-SAFETY-01 +
  S-VECTOR-01 + S-MCP-HEALTH-01 + S-HOLD-POINT-01 contracts cover
  the new MOPs.
- **Test floors** — pytest 1143 + vitest 313 unchanged. Pure
  content expansion; chip shape assertions updated in place
  (12 categorías, 38 chips).

## [v0.16.1] — 2026-05-24 (Procedure Architect Universal: deterministic vendor lookup + MCP runtime probe)

> **Theme:** post-v0.16.0 architectural close-out. Two explicit TODOs
> tracked in the skill registry since Commit 11 are now closed in
> code + tests + tagged release. No new user-facing features; both
> changes harden the deterministic Safety Officer audit gate.

### Added

- **`backend/agents/procedure_architect.py` -- deterministic Eaton
  vendor lookup** (closes the S-VENDOR-EATON-01 TODO from Commit 11).
  Module-level `_vendor_cache: dict[asset_id.lower(), vendor.lower() | None]`
  populated at boot from `cmms_repository.list_assets_async()`.
  Audit gate now resolves vendor in this order:
  - **(a) deterministic** -- if `draft.asset_id` is in the cache,
    registry vendor wins (no fallback even on non-eaton -- registry
    is authoritative). vendor=None is a deterministic answer.
  - **(b) string-match fallback** -- only when asset_id is missing
    or not in cache.
  Findings annotate the resolution source: `[deterministic lookup
  (asset_id=X, vendor=Y)]` or `[string-match fallback (cache miss)]`.
  New `set_vendor_cache(dict)` injection + `_reset_vendor_cache_for_test()`
  test helper.
- **`backend/mcp_health.py` -- MCP runtime probe (option ii)**
  (closes the S-MCP-HEALTH-01 "future option (ii)" TODO).
  Feature-flagged behind `DC_EPMS_MCP_PROBE` (default OFF). When
  enabled, an asyncio background task polls a configured URL
  (`DC_EPMS_MCP_PROBE_URL`, default `http://127.0.0.1:1234/v1/models`
  -- LM Studio's OpenAI-compatible endpoint) every
  `DC_EPMS_MCP_PROBE_INTERVAL_S` seconds (default 60s, 5s timeout).
  Audit gate reads cached state sync via `get_mcp_health()`. Tri-state:
  - **None** (probe disabled) -- behavior identical to v0.16.0
  - **True** (probe up) -- no extra finding
  - **False** (probe failing) -- CAUTION finding annotating the
    probe reason, e.g. `MCP health probe FAILED [URLError:
    Connection refused] -- Discipline AI agents may not be
    reachable; operator should verify before signing`
- **`backend/main.py` lifespan hooks** prime both the vendor cache
  (after CMMS seed) and the MCP probe background task (after vendor
  cache). MCP probe task pinned onto `app.state.mcp_probe_task` and
  cancelled cleanly on shutdown.

### Changed

- **`docs/skills/skill-registry.md`** -- S-VENDOR-EATON-01 + S-MCP-
  HEALTH-01 entries rewritten. The "TODO future option (ii)" / "TODO
  asset-manufacturer-migration" notes are gone; replaced with the
  full deterministic-or-fallback resolution spec + env knob list.
- **`docs/operaciones/mops/MOP-*.md`** -- no body changes; the audit
  gate now resolves the Eaton rule deterministically for any future
  Eaton-vendored asset.
- Backend `__version__` 0.16.0 → 0.16.1; mirrored in `package.json`,
  `pyproject.toml`, `frontend/assets/js/core/version.js`, and the
  two `<span data-app-version-stamp>` literals in
  `frontend/index.html`.

### Tests + tooling

- pytest **1126 → 1143** (+17 across `TestAuditMOPEatonVendorDeterministicLookup`
  (5 tests covering cache-hit / cache-miss / vendor-None / no-
  asset_id) and `tests/test_mcp_health.py` (12 tests covering
  module state, probe sync wrapper with mocked urlopen, and audit
  integration including compound advisories)).
- ruff: 0 violations in `backend/`.
- vitest: 313 passed (unchanged; this release is backend-only).
- GraphRAG: 10 knowledge documents indexed at boot (unchanged).
- Architect library: 23 catalog MOP entries pre-seeded with
  `audit_verdict=approve` (unchanged).
- Skills registry: **24** explicit skills (unchanged from v0.16.0;
  both S-VENDOR-EATON-01 and S-MCP-HEALTH-01 already existed,
  this release replaces their TODO notes with shipped functionality).

### Environment knobs added (all optional, sane defaults)

- `DC_EPMS_MCP_PROBE` -- master switch for option (ii) (default `false`)
- `DC_EPMS_MCP_PROBE_URL` -- URL to probe (default LM Studio /v1/models)
- `DC_EPMS_MCP_PROBE_INTERVAL_S` -- background poll cadence (default 60)
- `DC_EPMS_MCP_PROBE_TIMEOUT_S` -- per-probe timeout (default 5)

## [v0.16.0] "Procedure Architect Universal" — 2026-05-24

> **Theme:** Epic 6 catalog integration + operator-supplied richer
> system prompt fully adopted. 23 canonical MOP bodies, all
> verdict=APPROVE under the Universal 5-Point + multi-vector risk
> taxonomy + MCP agent health check + parameterized abort triggers
> (HARD_STOP) contract.

### Added

- **Procedure Architect agent** (`backend/agents/procedure_architect.py`):
  LLM-authored SOP/MOP/EOP/EMP with deterministic Safety Officer audit
  pipeline. Hermetic prompt envelope (H17) + deterministic-skeleton
  fallback when no LLM is wired. Authoring is LLM-driven; the audit
  verdict is pure-Python pattern matching (S-DET-01 / ADR-006).
- **Operator-supplied "Generador Universal de MOPs" system prompt**
  (Commit 11) -- MOP template body explicitly demands Identificador
  (Tag) + Estado Final Esperado in §1, six risk Vectors (Eléctrico /
  Mecánico-Térmico / Life Safety / Combustible / Lógico /
  Aguas Arriba-Abajo) in §2, MCP Agent Health Check in §3, formal
  step syntax + `[HOLD POINT]` markers in §4, and parameterized
  abort triggers (number + unit, NEVER vague) in §5.
- **Hardened audit gate** -- 10 deterministic rules total across two
  phases. Phase 1 (legacy): per-template required terms. Phase 2
  (Epic 6 hardening + Commit 11 richer-template): Universal 5
  sections, voltage-verification-or-approach-limit, PDU/RPP/STS
  pre-transfer alarm + SCR check, Eaton SOW R-48 (caution),
  Identificador (caution), Estado Final (caution), Vector
  classification (caution), MCP Health Check (caution), `[HOLD
  POINT]` markers (caution), parameterized abort triggers
  (HARD_STOP -- vague back-out criteria block signing).
- **23 canonical MOP bodies** in `docs/operaciones/mops/`:
  infrastructure (UPS bypass / Transformer dry inspection / ATS
  commutation) + distribution (STS load transfer / PDU PM /
  PDU breaker replacement / RPP load balancing / RPP whip
  installation / RPP EPO reset / Busway tap-off install /
  Busway joint maintenance / Busway thermographic scan) +
  mechanical (Chiller staging / Chiller trip response / Chiller
  ride-through recovery / CRAH hot-swappable filters / CRAH
  VFD-valve calibration / CRAH psychrometric control / Tower
  chemical dosing / Tower pan cleaning / Tower free-cooling
  transition) + global (IST full-load test / DBB main-ring
  isolation). Every body satisfies the full richer-template
  contract -- audit=APPROVE.
- **Library pre-seed at boot** -- `_seed_architect_library_from_catalog`
  parses every `MOP-*.md` and appends to the Architect library
  with `source="catalog"` + category tag. Boot log:
  `[BOOT] Architect library pre-seeded with 23 catalog MOP(s)`.
- **GraphRAG corpus expansion 6 → 10 documents**:
  `electrical-mop-catalog.md` + `distribution-mop-catalog.md` +
  `eaton-sow-r48-mp-checklist.md` + `cooling-thermodynamics-references.md`
  (ASHRAE TC 9.9 + Uptime Tier IV + OCP + CTI ATC-105 + physics
  equations).
- **HMI MOP chip categorías 4 → 10** with 32 chip starter templates
  (UPS / Transformer / Utility / PDU-STS / RPP / Busway / Chiller /
  CRAH / Cooling Tower / Global). Each chip embeds the full safety
  contract (LOTO + PPE + CSA Z462 + voltage-or-approach + back-out +
  {asset} substitution).
- **Maker-Checker witness gate** (Sprint 3 Phase 4 alignment):
  MOPs require two distinct `operator_id`s to seal into the
  Forensic Ledger. Self-witnessing → HTTP 403. Content drift
  between signs → HTTP 409. Documented in
  `docs/architecture/maker-checker-cuatro-ojos.md`.
- **6 new skills** in Category I "Procedure Authoring Safety" --
  `S-SAFETY-01` (Universal 5-Point + voltage verification),
  `S-DISTRIBUTION-01` (PDU/RPP/STS pre-transfer alarm + SCR),
  `S-VENDOR-EATON-01` (Eaton SOW R-48 caution),
  `S-VECTOR-01` (vector classification),
  `S-MCP-HEALTH-01` (MCP / agent health check string-match),
  `S-HOLD-POINT-01` (`[HOLD POINT]` markers). Registry 18 → 24.
- **Save-to-library endpoint** + `source` filter -- operator can
  pin approved Architect drafts into the in-memory library;
  `GET /api/procedures/architect/library?source=catalog|signed`
  filters by origin.
- **Option A consolidation** -- legacy `POST /api/mops/generate`
  retired with HTTP 410 Gone + migration pointer. MOPs view cross-
  links to the Procedure Architect for new procedure authoring.

### Changed

- `PROCEDURE_ARCHITECT_SYSTEM_PROMPT` MOP template body replaced
  with the operator-supplied "Generador Universal" structure (the
  prior Universal 5-Point with extra sub-fields).
- `MOP_PARAMETERIZED_ABORT_PATTERN` promoted from CAUTION to
  HARD_STOP (Commit 12) -- vague abort criteria are safety-critical.
- HMI MOP chip categorías: previously a single flat list of 4
  generic templates; now 10 categorías with 32 specialized chips,
  each pre-seeding the safety vocabulary the audit gate enforces.
- Backend `__version__` 0.15.0 → 0.16.0; mirrored in `package.json`,
  `pyproject.toml`, `frontend/assets/js/core/version.js`, and the
  two `<span data-app-version-stamp>` literals in
  `frontend/index.html`.

### Fixed

- `DC-EPMS-MSD-006` (HIGH, resolved earlier in cycle): asyncpg
  UUID → str coercion in `forensic_ledger.PostgresPersistence`
  `_row_to_entry`. `/api/ledger/verify` no longer 500s against
  Postgres-backed deployments. +4 integration tests in
  `test_forensic_ledger_postgres.py`.

### Tests + tooling

- pytest **875 → 1126** (+251 cumulative across Epic 4 + DC-EPMS-MSD-005
  + Epic 3 Capacity Planner + Epic 6 catalog integration + Epic 6
  richer-template adoption).
- vitest **193 → 313** (+120 across optimizer view, Hermes stream,
  MOP categorías, chip filter, safety-contract assertions).
- ruff: 0 violations in `backend/`.
- GraphRAG: 10 knowledge documents indexed at boot.
- Architect library: 23 catalog MOP entries pre-seeded at boot, all
  verdict=APPROVE.

## [v0.10.13-modal-fix] - 2026-05-10

### Fixed

- DC-EPMS-MAINT-003: closure modal "zombie" — `app.css .m-modal-overlay`
  used `display: flex`, overriding the UA `[hidden]` rule on specificity.
  Fix plus inline validation UX (shake/hint replacing silent `alert()`)
  plus force-close on success. Plus 3 hardening directives.

## [v0.10.12-maint-fix] - 2026-05-10

### Fixed

- DC-EPMS-MAINT-001/002: Maintenance nav-routing flicker (`maintenance` key
  absent from the legacy `MODULES` dict) and dead asset-panel to Maintenance
  focus handoff (`sessionStorage.cmms_focus_asset_id` was never consumed).

## [v0.10.11-ddu-busway] - 2026-05-10

### Added

- DDU / busway expansion in the Power SLD — 12 GB200 NVL72 rack drops.

## [v0.10.10-aesthetic-polish] - 2026-05-10

### Changed

- PBR brushed-metal isometric blocks; JetBrains Mono global typography.

## [v0.10.9-asset-panel] - 2026-05-10

### Added

- Phase 4 contextual SCADA asset panel with Chart.js sparkline.

## [v0.10.8-power-cam] - 2026-05-10

### Added

- Bounded isometric camera controls (zoom/pan/pitch/yaw/flat) for the Power & UPS SLD.

## [v0.10.7-dag-engine] - 2026-05-10

### Added

- DAG-driven electrical propagation engine with universal fault injection.

## [v0.10.6-iso-sld] - 2026-05-10

### Added

- 2.5D isometric "living-organism" Power & UPS single-line diagram.

## [v0.10.5-power-sld-v2] - 2026-05-10

### Added

- Power & UPS SLD "Lead Engineer Mode".
- `docs/ROADMAP-V11.md` committed — the V11 backlog (Tier 1/2/3 + Hermes).

## [v0.10.4-b1-production] - 2026-05-10

### Added

- B1 Mission Control — Tesla Megapack glass-panel: glassmorphism overlay cards
  (live PUE / MW / Racks / Anomalies), animated InstancedMesh particle flow
  Yard to A/B, Raycaster drill-down with 600 ms eased zoom into rack-heatmap /
  site-topology / tech-assist.

## [v0.10.3-b1-spike] - 2026-05-10

### Added

- B1 gray-box three.js spike — 4 BoxGeometry buildings, isometric ortho camera,
  Raycaster, FPS HUD. Validates 4 B1 acceptance criteria. Not production.

## [v0.10.2-tier-b-anomaly-heatmap] - 2026-05-10

### Added

- Tier B: 50-rack anomaly heatmap (Tesla Megapack aesthetic); Tier A+ polish
  (search box, Path A/B coloring, per-rack heat dots). 1019 LOC.

## [v0.10.1-tier-a-topology] - 2026-05-10

### Added

- Tier A: force-directed topology graph (`/api/site/graph` + SVG sim),
  path-coded SLD power flow, thermal heat overlay on the cooling P&ID. 1133 LOC.

## [v0.10.0-tier-c-polish] - 2026-05-10

### Added

- Tier C: WebAudio sound design, boot splash, keyboard shortcuts. Marks the
  v0.10.x feature-set milestone.

## [v0.9.16-asset-enrichment] - 2026-05-10

### Added

- `PATCH /api/cmms/assets/{id}` and a Tech Assist enrich modal — closes the
  nameplate matcher loop end-to-end (seed_new_asset to link_to_existing 0.95+).

## [v0.9.15-voice-closure-modal] - 2026-05-10

### Added

- Voice closure modal in the Maintenance view (closes the API-only gap from v0.9.7).

## [v0.9.14-pue-physics] - 2026-05-10

### Added

- PUE physics widget with first-law cross-check; ADR-004 (Phase 1 480 VAC live,
  Phase 2 800 VDC design).

## [v0.9.13-demo-veto-sample] - 2026-05-09

### Added

- Pre-seeded VETO sample work order so the Multi-Agent demo Act 3 is 100% UI.

## [v0.9.12-multi-agent-facade] - 2026-05-09

### Added

- Sprint 10.1: Multi-Agent facade — 4 agents plus Safety Officer veto,
  deterministic consensus.

## [v0.9.11-consolidation-2026-05-09] - 2026-05-09

### Added

- Pre-demo consolidation: replay script, work-order drill-down, DEMO_SCRIPT.md v2.

### Fixed

- DC-EPMS-040: audit-trail fix.

## [v0.9.10-demo-snapshot-2026-05-09] - 2026-05-09

### Added

- Demo snapshot: 3 predictive_kalman P1 LOTO work orders (cooling / UPS / power
  distribution), all CET-signed — the demo walkthrough state.

## [v0.9.9-tech-assist-view] - 2026-05-09

### Added

- Sprint 7.1 frontend: 3-panel Tech Assist view (nameplate / troubleshoot / library).

## [v0.9.8-tech-assist-71d] - 2026-05-09

### Added

- Sprint 7.1d: nameplate OCR and asset fuzzy matcher (29 tests).

## [v0.9.7-tech-assist-71c] - 2026-05-09

### Added

- Sprint 7.1c: voice/dictation closure pipeline (text mode) — informal notes to
  LLM-normalized professional report plus auto-detected follow-up WOs in
  `pending_approval`.

## [v0.9.6-tech-assist-71b] - 2026-05-09

### Added

- Sprint 7.1b: PDF ingestion pipeline — a field tech uploads a vendor manual and
  the chunks integrate into troubleshoot QA on the next query.

## [v0.9.5-tech-assist-71a] - 2026-05-09

### Added

- Sprint 7.1a: real-time troubleshoot QA combining RAG + CMMS + LLM, 3-section
  cited answers, safety-keyword detection.

## [v0.9.0-cmms-predictive] - 2026-05-09

### Added

- Sprint 9.1: predictive WO trigger end-to-end — simulator to Kalman to auto-WO
  P1 with telemetry forensic snapshot.

## [v0.8.5-cmms-core-v1] - 2026-05-09

### Added

- Sprint 6: CMMS Core v1.0 — persistent asset registry, work-order lifecycle,
  REST router. Vision deck (Wilmer #1..#7) persisted as a CLAUDE.md appendix.

## [v0.8.0-sprint5-kalman] - 2026-05-09

### Added

- Sprint 5 closure: telemetry simulator + Kalman pipeline + per-channel YAML
  calibration (`config/telemetry_channels.yml`).

## [v0.7.6-kalman-pipeline] - 2026-05-09

### Added

- Sprint 5 C2: Kalman + Send-on-Delta pipeline wired.

## [v0.7.5-telemetry-stream] - 2026-05-09

### Added

- Sprint 5 C1: synthetic telemetry simulator wired into the SSE endpoint.

## [v0.7.4-frontend-pivot] - 2026-05-09

### Added

- Sprint 5.5 hybrid frontend pivot milestone (local Chart.js, telemetry
  activity strip, SHI trend sparkline).

## [v0.7.3-sprint5-patches] - 2026-05-08

### Fixed

- Sprint 5 patches: 4 of 5 bugs closed plus UTF-8 BOM strip.

## [v0.7.2-camino1] - 2026-05-08

### Added

- Camino 1 closure: Path C2 drift sync (40 to 67 MW) and the LOTO Auditor HMI view.

## [v0.7.0-batch4] - 2026-05-08

### Added

- **Batch 4.D**: LOTO Auditor closure (REST endpoint + persistence + rendering).
  - `backend/loto_auditor_repository.py` (267 lines): asyncpg-backed
    PostgreSQL persistence with idempotent INSERT ON CONFLICT save,
    AuditNotFoundError exception for explicit FastAPI 404 mapping,
    MockLotoAuditRepository for tests.
  - `backend/loto_auditor_report_renderer.py` (347 lines): pure-function
    markdown renderer producing per-pillar sections, citations table,
    provenance trace, ADR-006 PENDING APPROVAL banner.
  - `backend/loto_auditor_routes.py` (332 lines): FastAPI router with
    4 endpoints. Exports `register_loto_auditor()` for 1-line wiring.
  - `backend/loto_auditor_agent.py` (PATCH +149 lines): final
    NotImplementedError stub replaced with full LM Studio LLM summary
    implementation. Optional `cmms_service` constructor parameter.
  - `tests/test_loto_auditor_e2e.py` (NEW, 7 integration tests).

- **Batch 4.C** (commit `bb4a26b`): Pillars 4+5+6 implementation.
  Witness Gate, Hybrid Sequential Order, PPE Category. +14 unit tests.

- **Batch 4.B** (commit `f0d373e`): Pillars 1+2+3 implementation.
  Topology Impact Radius, 2N Redundancy Survival, Capacitor Discharge.
  +18 unit tests.

- **Batch 4.A** (commit `d4a5ac8`): LOTO Auditor skeleton + models +
  PostgreSQL schema. +21 unit tests. Added ADR-009.

### Changed

- `backend/loto_auditor_agent.py` constructor accepts optional
  `cmms_service` parameter for Pillar 2 overlapping_maintenance check.
  All Batch 4.B/4.C tests remain GREEN with default None.
- `git config --local i18n.commitencoding utf-8` and
  `i18n.logoutputencoding utf-8` set on repo (DC-EPMS-024 mitigation).

### Fixed

- **DC-EPMS-024**: mojibake in commit messages when apply_batch*.ps1
  orchestrators contained Unicode characters. Mitigations:
  1. Phase 0 of `apply_batch4d.ps1` sets git's UTF-8 commitencoding.
  2. All future apply_batch*.ps1 commit messages are ASCII-only.
  3. Historical commit `bb4a26b` not amended (cosmetic only).



<!-- Batch 3 closure addendum 2026-05-06 -->
### Batch 3 closure addendum (2026-05-06)

#### Added
- 6 ADRs in MADR format under `docs/adr/`: ADR-001 dual-RAG architecture,
  ADR-002 NetworkX in-memory rationale, ADR-003 FAISS IndexFlatIP rationale,
  ADR-006 Deterministic Sandbox foundational principle,
  ADR-007 Sprint 6 simulator killed (DPO orphan reuse),
  ADR-008 GO-OPTION-C image size 1.54 GB Phase 1.
- `docs/architecture/sre_layers.md`: 5-layer SRE mapping (Predictive,
  Management, Safety, Post-Incident, Commissioning) for the
  architecture narrative; explicit gap declaration for V10 candidates
  (RCA agent, IST runner, Arc Flash boundary calculator).
- `01_INSTRUCTIONS.md` regenerated as master instructions: Path C2
  baseline (67 MW, 368 racks), Hyperscale Override Protocol preserved,
  Batches 1+2 closure status, 11 bugs registered, LOTO Auditor
  scheduled for Batch 4.
- Pre-commit hooks installed (`.git/hooks/pre-commit` + `commit-msg`)
  and ran on all files for the first time.
- `pre_batch3_cleanup_20260506_211234.tar.gz` (88.4 KB) preserved
  outside git as forensic record of pre-cleanup state (5 duplicates
  + 33 iteration scripts + stray chroma_db).
- `scripts/_archive/pre_batch3/` directory containing 33 archived
  iteration scripts from S1-S2 sprints (B3-2c sub-decision: archive
  AND version, do not delete forensic history).
- `logs/.gitkeep` skeleton directory for runtime diagnostic logs
  (gitignored content but tracked directory).

#### Fixed
- **DC-EPMS-002 RESOLVED**: `backend/graphrag_service.py` import path
  corrected from `from knowledge_graph` to `from backend.knowledge_graph`.
  AST-validated and backed up as `graphrag_service.py.bak_pre_dc002_20260506_211234`.
- **DC-EPMS-004 RESOLVED**: 5 MD5-identical duplicates deleted from
  `backend/physics/`: `physics_it_thermal.py`, `physics_heat_rejection.py`,
  `physics_electrical.py`, `physics__init__.py`, plus the orphan
  `backend/physics__init__.py` outside the package. Combined ~1280 LOC
  removed without functional impact (canonicals preserved at expected
  paths, MD5 verified before deletion).
- **DC-EPMS-005 RESOLVED**: 33 iteration scripts moved from project
  root to `scripts/_archive/pre_batch3/`: 23 `.py` files (apply_lucide,
  patch_main_metrics, setup_graphrag_*, sprint*_e2e_test, etc.) and
  10 `.ps1` files (add_bom, edit3_apply, sprint3_demo, etc.).
- **DC-EPMS-006 RESOLVED**: Stray `chroma_db/` (164 KB) at project root
  removed. Operational `data/chroma_db/` (5,677 KB, 2 collections, 20-doc
  corpus) preserved untouched.

#### Pending Tech Debt (opened for Batch 3.5)

##### DC-EPMS-012 (HIGH severity, opened 2026-05-06)
**File**: `backend/cyber_physical_tools.py`
**Issue**: Orphan file (Decision D1 vote 1A target for S5 integration)
contains 248 lines of Kalman + Send-on-Delta + Numba `@njit` code but is
**missing all required imports**. Ruff reports F821 errors for `np`,
`njit` across 17 sites (lines 37, 39, 40, 42, 64, 102, 104-106, 134,
205-211, 233).
**Runtime impact**: NONE — file has zero references in `main.py`, never
imported, never executed (orphan confirmed during 2026-05-03 audit).
**CI impact**: pre-commit ruff hook fails. Cannot integrate file into
S5 sprint until fixed.
**Resolution path** (Batch 3.5): add header imports
`import numpy as np`, `from numba import njit`. AST-validate.
Estimated effort: 30 minutes including unit smoke test.

##### DC-EPMS-013 (HIGH severity, opened 2026-05-06)
**File**: `backend/dpo_edge_healing.py`
**Issue**: Orphan file (Decision D1 vote 2B target for S6 integration)
contains 352 lines of DPO + LoRA + bitsandbytes code but is
**missing all required imports**. Ruff reports F821 errors for `json`,
`time`, `torch`, `LoraConfig`, `TaskType`, `TrainingArguments` across
6+ sites (lines 147, 221, 239, 246, 259, 286, 359, 409).
**Runtime impact**: NONE — orphan never imported.
**CI impact**: pre-commit ruff hook fails. Cannot integrate file into
S6 sprint until fixed.
**Resolution path** (Batch 3.5): add header imports
`import json`, `import time`, `import torch`,
`from peft import LoraConfig, TaskType`,
`from transformers import TrainingArguments`. AST-validate.
Note: deferred runtime verification of `peft` and `bitsandbytes`
import chain happens in S6 Hour 1 per ADR-007 entry criteria, NOT
in Batch 3.5.
Estimated effort: 30 minutes for import fix + AST validation.

##### DC-EPMS-014 (MEDIUM severity, opened 2026-05-06)
**File**: `backend/hal/cummins_adapter.py` line 41
**Issue**: mypy strict reports `error: invalid syntax` at line 41.
Hypothesis: BOM corruption or mojibake unicode confusing mypy parser
(but NOT Python interpreter — `sys.path.insert` plus runtime import
chain works, evidenced by 39 HAL adapter tests passing within the
352-test aggregate).
**Runtime impact**: NONE — module imports fine via Python interpreter,
HAL adapters tested clean.
**CI impact**: mypy strict pre-commit hook hard-fails on this file.
**Resolution path** (Batch 3.5): inspect line 41 for non-ASCII bytes,
re-encode file as pure UTF-8 without BOM, replace any mojibake with
ASCII equivalents. Verify mypy passes.
Estimated effort: 15 minutes.

##### DC-EPMS-015 (MEDIUM severity, opened 2026-05-06)
**Files**: `backend/agent_copilot.py`, `backend/cyber_physical_tools.py`,
`backend/dpo_edge_healing.py`, `backend/main.py`,
`backend/metrics_router.py`, `backend/physics/electrical.py`,
`backend/physics/heat_rejection.py`, `backend/physics/it_thermal.py`,
`backend/physics/mechanical.py`, `backend/shift_report.py`,
`scripts/simulator.py` (12 files total).
**Issue**: Mojibake unicode characters in strings, comments, and
docstrings. Examples: `├ù` (should be `×` or `x`),
`ΓÇô` (should be `-`), `ΓÇÖ` (should be `'`), `╬öP` (should be `dP`),
`╧ä` (should be `tau`), `╬µ` (should be `epsilon`).
Source: copy-paste from earlier Claude conversations where Spanish
prose used Spanish quotation marks and mathematical symbols that got
encoded as cp1252-flavored UTF-8 then re-saved as UTF-8.
**Runtime impact**: NONE — Python reads UTF-8 fine.
**CI impact**: ruff hard-fails on RUF001/RUF002/RUF003 ambiguous
characters (~50 occurrences across files). Without `--unsafe-fixes`
flag, these cannot be auto-resolved.
**Resolution path** (Batch 3.5): mass find-replace via Python script
mapping mojibake to ASCII or proper unicode. Run `ruff check
--unsafe-fixes --fix` after to catch any residual.
Estimated effort: 60-90 minutes including manual review of
substitutions in physics formulas (do not break math notation).

##### DC-EPMS-016 (LOW severity, opened 2026-05-06)
**File**: `config/site_model.yml` (and possibly other config YAMLs)
**Issue**: yamllint pre-commit hook crashes with
`UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d in position
13221: character maps to undefined`. Root cause: yamllint reads files
using Python's default codec which on Windows is cp1252; the YAML file
contains UTF-8 bytes (probably from mojibake or accented characters
in component descriptions) that cp1252 cannot decode.
**Runtime impact**: NONE — `site_model.py` reads with explicit
`encoding="utf-8"`, parses fine.
**CI impact**: yamllint hook crashes (not just fails); blocks
pre-commit pipeline.
**Resolution path** (Batch 3.5): patch `.pre-commit-config.yaml`
yamllint hook to set `PYTHONUTF8=1` env var, OR rewrite affected
YAML files as pure ASCII (replace any accented characters in
descriptions).
Estimated effort: 15 minutes.

##### DC-EPMS-017 (LOW severity, opened 2026-05-06)
**Files**: All 6 ADRs under `docs/adr/`
**Issue**: markdownlint pre-commit hook fires:
- MD034 "no-bare-urls" on `https://adr.github.io/madr/` reference line
  in each ADR header (cosmetic, but cited URL is intentional reference
  to MADR template authority).
- MD004 "ul-style: expected asterisk, actual dash" on every list bullet.
Project style preference (dash bullets) conflicts with markdownlint
default (asterisk).
**Runtime impact**: NONE — markdown renders fine on GitHub, in IDE
preview, in mkdocs.
**CI impact**: markdownlint hook fails; blocks pre-commit.
**Resolution path** (Batch 3.5): either (a) patch
`.markdownlint.json` to set `"MD004": { "style": "dash" }` plus
disable MD034 for ADR header lines, or (b) bulk find-replace `- ` to
`* ` at line start in ADRs. Option (a) is better — preserves project
style choice and documents it.
Estimated effort: 15 minutes.

#### Decisions

- **GO-OPCION-C** (Batch 3 closure strategy, 2026-05-06): accepted
  Atomic Batches discipline; auto-fixes from pre-commit captured in
  one clean commit; 6 new bugs (DC-EPMS-012 through DC-EPMS-017)
  registered as documented tech debt; surgical resolution deferred
  to Batch 3.5 (estimated 3-4h dedicated session). Rationale: mixing
  these fixes into Batch 3 violates V9 Atomic Batches principle and
  introduces risk of capturing partial mojibake fixes that re-break
  the encoding state.

#### Notes

- pytest aggregate after Batch 3 closure: **352 passed, 5 deselected**
  (the 5 deselected are FAISS-touching tests marked `slow` per
  DC-EPMS-001 hardware bug). NO regression vs Batch 2 baseline.
- Container image `dc-epms-pro:latest` 1.54 GB still healthy in 10 s.
- Two-commit strategy was approved (B3-1 vote C) but collapsed in
  practice because commit 1 captured ALL files including ADRs and
  SRE layers placed in Phase 3 of `apply_batch3.ps1`. The "commit 2
  failed because nothing to commit" message was the correct git
  behaviour (working tree clean), not a real failure. The auto-fixes
  commit captured by `close_batch3.ps1` becomes the de facto commit 2.
- Tags after closure: `v0.5.0` (Batches 1+2 milestone) +
  `v0.6.0-batch3` (Batch 3 closure including auto-fixes).

<!-- end Batch 3 closure addendum -->


> Active development frontier post-audit 2026-05-03.
> Phase V9 in progress (12-week roadmap, Option A confirmed).

### Added — Documentation baseline (post-archaeological audit 2026-05-03)
- Replaced obsolete `02_STATUS_SUMMARY.md` with evidence-verified `02_STATUS_SUMMARY_REAL.md`
  (873 lines, every claim cross-referenced against codebase and filesystem).
- New `S5_5_BRIEFING_SPEC.md` — technical spec for Pre-Operational Briefing sprint
  (split S5.5a W6.5 orchestrator + S5.5b W7 PUE logic with architecture-aware thresholds).

### Decisions RESOLVED (2026-05-03 to 2026-05-06)
- **Decision 1** *(votes 1A + 2B + D-B, 2026-05-03)*: integrate `cyber_physical_tools.py`
  in S5; integrate `dpo_edge_healing.py` capture-only with manual trigger in S6;
  DPO compute on CPU bitsandbytes.
- **Decision 2** *(Path C2, 2026-05-05)*: facility scale set to **67 MW AI factory hyperscale**.
  118× GB200 NVL72 + 250× GB300 NVL144. Rubin Ultra excluded.
- **Decision 3** *(vote 3B, 2026-05-03)*: keep `agent_engine.py` as dual-AI fallback
  coexisting with `agent_copilot.py`.
- **Decision 4** *(Option 4-B, 2026-05-05)*: convert `T4-MOP-CHI-001` and `T4-MOP-UPS-001`
  markdown to executable YAML in S5.
- **Decision GO-OPTION-C** *(2026-05-06)*: accept ~2 GB Docker image size for Phase 1
  (CPU-only torch, RAG stack in-container, edge-first autonomy preserved).
  Migration to Distroless or Alpine deferred to Phase 3.
- ADR-004 *(scheduled S5.5b H6)*: `agent_engine.py` dual-AI coexistence rationale.
- ADR-005 *(scheduled S6 H6)*: DPO compute strategy.

---

### DevOps Quick Wins — Batch 1 *(✅ COMPLETED 2026-05-05)*

#### Added
- **Unified `pyproject.toml`** (PEP 621, ~13 KB): consolidates dependencies and
  tool configs. 10 optional-dependency extras: `db`, `rag`, `obs`, `ai`, `phys`,
  `dpo`, `mcp`, `dev`, `full`, `all`. Critical pins exact-matched to installed
  venv. ZERO runtime downgrades.
- **`.pre-commit-config.yaml`** (177 lines, 17 hooks). Installation deferred to
  Batch 3 (requires git repo).
- **`validate_environment.ps1`** (292 lines, 8 checks).
- Tooling installed: `ruff` 0.9.10, `mypy` 1.15.0, `black` 25.12.0, `pre-commit`
  4.6.0, `pytest-cov` 6.3.0, `pytest-mock` 3.15.1, `pytest-timeout` 2.4.0.

#### Changed
- `pytest.ini` permissive bug fixed via `testpaths = ["tests"]` in pyproject.toml.
- `pytest.ini` file deleted; configuration migrated entirely to pyproject.toml.

#### Test verification
- 91 tests pass in 5.56s (`test_procedure_engine.py` + `test_site_model.py` + `test_graphrag.py`)
- 5 tests deselected by default (FAISS slow tests, see DC-EPMS-001)
- EXIT CODE: 0

---

### DevOps Quick Wins — Batch 2 *(✅ COMPLETED 2026-05-06)*

> **Theme**: Containerization + observability. AI-Factory Speed mode under
> Protocol Override (V9 Rules 1-5).

#### Added
- **`.dockerignore`** (159 lines, ~3 GB excluded): aggressive exclusion list
  preventing dev artifacts (.venv, _legacy_backup, data/chroma_db, scripts root)
  from being copied into Docker build context.
- **`Dockerfile`** v2 (137 lines): multi-stage builder + runtime. Targets:
  - amd64 only
  - non-root user `epms` (uid 10001, gid 10001) per IEC 62443 segregation
  - tini as PID 1 (zombie process protection, signal handling)
  - `--mount=type=cache,target=/root/.cache/pip` for build cache reuse
  - Build-time arg `EXTRAS=db,rag,obs` parametrizable
  - HEALTHCHECK aligned with Tier IV monitoring: 30s interval, 5s timeout, 3
    retries, 60s start_period (FastAPI lifespan grace)
  - Aggressive cleanup post-install: remove `__pycache__/`, `.pyc`, `tests/`,
    strip `.so` debug symbols, prune pip cache (~150-300 MB savings)
  - **Critical**: torch installed FIRST from PyTorch CPU index
    (`https://download.pytorch.org/whl/cpu`) preventing CUDA toolkit
    auto-pull (~3.5 GB savings). See DC-EPMS-009.
- **`docker-compose.yml`** (143 lines): healthcheck-first design fixing the
  long-standing `epms-backend` auto-restart bug:
  - `restart: unless-stopped` (was: `always`, causing port-8080 restart storms)
  - `stop_grace_period: 30s` (DB) and `20s` (backend) for fsync/lifespan cleanup
  - Network isolation: `epms-internal` + `epms-egress` bridges
  - `depends_on: { epms-db: condition: service_healthy }` ensures ordered startup
  - Volumes: `epms-db-data` (Postgres), `epms-chroma-data` (preserves 2.4 MB
    operational corpus across container recreates)
  - `host.docker.internal:host-gateway` so container can reach LM Studio on
    Windows host
- **`backend/metrics_router.py`** (236 lines): Prometheus instrumentation with
  curated SLO buckets and normative grounding in docstrings:
  - SLO 1: Pre-Op Briefing latency p95 < 8s (S5_5_BRIEFING_SPEC §6.2 + ISO 11064-7)
  - SLO 2: EOP abort decision p99 < 100ms (NFPA 70E §130 + IEC 62443-3-3 SR 3.4/7.6)
  - SLO 3: SSCB software decision p99 < 5ms (OCP-LVDC §4 + IEC 60947-2 + IEC TR 63282 §5.2)
  - SLO 4: Telemetry ingestion sustained > 1000 req/s (ASHRAE TC 9.9 Class A2 sample rate)
  - SLO 5: DB pool saturation < 80% (Uptime Institute 2024 incident review)
  - Histogram buckets explicit: 5ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s, 8s, 15s, 30s, 60s
  - Excluded paths: `/metrics`, `/favicon.ico`, `/static`, `/lm/`
  - Graceful degradation if `prometheus-fastapi-instrumentator` not installed
    (returns False with warning, app continues to start)
  - `ENABLE_METRICS=true|false` env var for runtime toggle
- **`tests/test_metrics.py`** (212 lines): 12 unit tests across 4 categories
  (configuration, endpoint exposure, instrumentation behavior, env var control).
  Includes `clear_prometheus_registry` autouse fixture preventing global REGISTRY
  pollution between tests.
- **`patch_main_metrics_v3.py`**: BOM-aware, paren-balanced parser for inserting
  `setup_metrics(app)` after `FastAPI(...)` instantiation. Validates AST before
  writing. Handles strings with parentheses correctly (v1 and v2 had regex bugs).
- **`apply_batch2.ps1`** v2 (295 lines): orchestrator script. Backup, copy,
  patch, install, validate. Idempotent. Logs to `batch2_apply_<ts>.log`.
- **`validate_batch2.ps1`** v2 (410 lines): 8-layer CI/CD validator producing
  paste-to-Claude diagnostic log on failures. Layers: files, imports, pytest
  test_metrics, pytest aggregate, docker build, compose config, container
  healthcheck (max 90s), `/metrics` HTTP+Prometheus format.
- **`rebuild_batch2.ps1`** (254 lines): full rebuild orchestrator for size fix
  (Decision GO-OPTION-C). Backup → patch → image cleanup → rebuild → re-validate.
- **`patch_pyproject_torch_cpu.py`**: pyproject patcher (idempotent, BOM-aware,
  TOML-validating).
- **`patch_pyproject_obs.py`**: adds `prometheus-fastapi-instrumentator>=7.0.0,<8.0.0`
  to `[obs]` extra. Resolves DC-EPMS-011.

#### Changed
- `backend/main.py` patched: `from backend.metrics_router import setup_metrics`
  added near other backend imports; `setup_metrics(app)` called after FastAPI
  instantiation. BOM preserved. AST-validated.
- `pyproject.toml` `[obs]` extra updated: now includes
  `prometheus-fastapi-instrumentator>=7.0.0,<8.0.0` (was missing, see DC-EPMS-011).
- Old bloated image `dc-epms-pro:batch2-validate` removed during cleanup.
  Final tag: `dc-epms-pro:latest` (matches `docker-compose.yml` reference).

#### Test verification (2026-05-06 cierre)
- 12 tests pass for `test_metrics.py` in 0.92s
- 103 tests pass in aggregate (`test_procedure_engine.py` + `test_site_model.py`
  + `test_graphrag.py` + `test_metrics.py`) in 6.67s
- 5 tests deselected by default (FAISS slow tests, see DC-EPMS-001)
- 8/8 validation layers PASS
- Container healthy in 10 seconds (6× faster than 60s start_period budget)
- `/metrics` endpoint returns HTTP 200 with valid Prometheus exposition format
  including `dc_epms_*` namespace, `# HELP` and `# TYPE` comments

#### Final image metrics
- Disk usage: **1.54 GB** (was 8.85 GB — **83% reduction**)
- Content size (compressed): 338 MB
- Build time cold (--no-cache): ~5-7 min
- Build time warm: ~30s
- CPU-only torch from PyTorch official index: `torch==2.5.1+cpu`,
  `torchvision==0.20.1+cpu`

#### Backups defensively created (Batch 2)
- `pyproject.toml.bak_pre_batch2_20260506_*`
- `pyproject.toml.bak_pre_torch_cpu_20260506_*`
- `pyproject.toml.bak_pre_obs_fix_20260506_*`
- `Dockerfile.bak_pre_batch2_20260506_*`
- `Dockerfile.bak_pre_v2_20260506_*`
- `docker-compose.yml.bak_pre_batch2_20260506_*`
- `backend/main.py.bak_pre_batch2_20260506_*`
- `backend/main.py.bak_pre_metrics_*` (3 attempts: v1, v2, v3 — only v3 succeeded)

---

### Bugs discovered during Batches 1+2 (technical debt — registered for future cleanup)

#### DC-EPMS-001 — FAISS AVX2 access violation on AMD Ryzen + Windows
**Severity**: Hardware-specific (Wilmer's ASUS Zephyrus G14 + AMD Ryzen + Windows 11)
**Status**: 🟡 Mitigated via `-m "not slow"` in addopts. 5 tests skip on this hardware.
**Root cause**: FAISS C++ runtime caches CPU detection at first load, ignoring
`FAISS_NO_AVX2=1` env var on subsequent allocations. Bug exists across faiss-cpu
1.7.x to 1.13.x on AMD+Windows specifically; Linux and Intel hardware unaffected.
**Future fix**: Linux CI runner (Batch 3) or migrate to hnswlib/annoy (S5+).

#### DC-EPMS-002 — Broken import path in `graphrag_service.py`
**Severity**: 🟡 Latent (works in pytest context, fragile elsewhere)
**Status**: Pending fix in Batch 3
**Description**: `backend/graphrag_service.py` line 26 should use
`from backend.knowledge_graph` instead of `from knowledge_graph`.

#### DC-EPMS-003 — Encoding mojibake in legacy text files
**Severity**: 🟢 Cosmetic
**Status**: Pending automatic fix in Batch 3 (first pre-commit run after `git init`)

#### DC-EPMS-004 — Duplicate physics modules (MD5-identical)
**Severity**: 🟢 Low (excluded from linting via pyproject.toml)
**Status**: Pending deletion in Batch 3

#### DC-EPMS-005 — Iteration scripts cluttering project root (23 files)
**Severity**: 🟢 Low (excluded from linting)
**Status**: Pending archive in Batch 3

#### DC-EPMS-006 — Two ChromaDB directories (root + data/)
**Severity**: 🟡 Medium (storage waste)
**Status**: Pending investigation in Batch 3

#### DC-EPMS-007 — UTF-8 BOM in `backend/main.py`
**Severity**: 🟢 Cosmetic
**Status**: Mitigated. Patch script `patch_main_metrics_v3.py` is BOM-aware
(decodes with `utf-8-sig`, validates AST after stripping BOM, writes back
preserving BOM).
**Description**: `backend/main.py` ships with UTF-8 BOM (3 bytes `EF BB BF`
at file start). Python 3.12 imports it transparently, but `ast.parse()` on
raw bytes rejects it as "invalid non-printable character U+FEFF" in line 1.
Same root cause as DC-EPMS-003 — encoding inconsistencies in Windows authoring.
**Future fix**: pre-commit hook `fix-byte-order-marker` from pre-commit-hooks
(activated in Batch 3 after `git init`).

#### DC-EPMS-008 — Prometheus REGISTRY pollution between pytest tests
**Severity**: 🟡 Medium (resolved in v2)
**Status**: ✅ Resolved by `clear_prometheus_registry` autouse fixture in
`tests/test_metrics.py`.
**Description**: `prometheus_client.REGISTRY` is a process-global singleton.
Tests creating multiple `FastAPI` apps in the same session collide with
`ValueError: Duplicated timeseries in CollectorRegistry: {'dc_epms_inprogress_requests'}`.
**Lesson**: future Prometheus tests must use the same cleanup fixture. Will
apply to S5.5 PUE tests and S5 telemetry tests.

#### DC-EPMS-009 — Container image size 1.54 GB exceeds original target <1.2 GB
**Severity**: 🟡 Medium (operational, not blocking)
**Status**: Documented as Phase 1 acceptable per Decision GO-OPTION-C (2026-05-06).
Plan: address in Phase 3.
**Description**: Container image after Batch 2 v2 rebuild: 1.54 GB disk / 338 MB
compressed. Original target was <1.2 GB but breakdown reveals ML stack
(torch CPU + sentence-transformers + chromadb + faiss + transformers) consumes
~1.3 GB of the venv inherently. Compressing further would require sacrificing
edge-first autonomy (RAG out of container) or migrating to Alpine base
(musl libc compatibility risk for cuda-bindings even in CPU mode) or distroless
final stage (debugging difficulty).
**Decision**: accept ~1.54 GB as Phase 1 pragmatic. Edge-first autonomy preserved.
Plan Distroless or Alpine migration for Phase 3 if image distribution bandwidth
becomes a constraint.
**Future fix candidates**: Phase 3 Batch X — Alpine base + statically linked
deps; Distroless final stage; multi-arch (amd64 + arm64) for Graviton edge deploy.

#### DC-EPMS-010 — `rebuild_batch2.ps1` falsely fails on Docker stderr noise
**Severity**: 🟢 Low (cosmetic, build actually succeeds)
**Status**: Recognized 2026-05-06, fix deferred to Batch 3.
**Description**: PowerShell `& docker build ... 2>&1 | Out-String` aborts with
`$ErrorActionPreference='Stop'` even when Docker writes informational output
to stderr (`#0 building with desktop-linux instance using docker driver`).
Builds complete correctly but the wrapper script reports false failure.
The user can verify success via `docker images dc-epms-pro` (image is built).
**Future fix (Batch 3)**: use cmd.exe wrapper for native commands or explicitly
set `$ErrorActionPreference='Continue'` around docker invocations.

#### DC-EPMS-011 — `prometheus-fastapi-instrumentator` missing from `[obs]` extra
**Severity**: 🟡 Medium (silent feature degradation)
**Status**: ✅ Resolved 2026-05-06. Now pinned at
`prometheus-fastapi-instrumentator>=7.0.0,<8.0.0` in `[obs]` extra.
**Description**: During Batch 2 development, prometheus-fastapi-instrumentator
was installed manually via `pip install` into local venv but not added to
pyproject.toml's `[obs]` extra. Container builds via `pip install -e ".[obs]"`
therefore did NOT include it, leaving `/metrics` endpoint absent from runtime.
The graceful degradation in `metrics_router.py` masked this — app continued
to start cleanly, only logging a WARNING. Healthcheck passed (Layer 7),
but `/metrics` was 404 (Layer 8).
**Lesson**: graceful degradation with logging is correct V9 design, but
discovery of the gap requires production-grade validation (which is exactly
what `validate_batch2.ps1` Layer 8 caught). Future protocol: when running
`pip install` manually, always verify the package is also pinned in
pyproject.toml. Better: only install via extras mechanism.

---

### Pending — DevOps Quick Wins remainder

#### Batch 3 *(next session, ~3 hours)*
- `git init` + `.gitignore` (covers `.venv/`, `__pycache__/`, `data/chroma_db/`,
  `chroma_db/`, `_legacy_backup/`, `*.bak_pre_*`, `htmlcov/`, `.pytest_cache/`,
  `pytest_*.log`, `*.bak`, all the iteration scripts and orchestrator scripts)
- First commit phases (formatting baseline, then config addition)
- `pre-commit install` + `pre-commit install --hook-type commit-msg`
- First `pre-commit run --all-files` (auto-fixes DC-EPMS-003 mojibake +
  DC-EPMS-007 BOM)
- `.github/workflows/test.yml` — disabled (per V9 Rule 5: ZERO GitHub).
  Replaced by local `watch_tests.ps1` + `pre-commit hook`.
- `docs/adr/` initial set: ADR-001 through ADR-009 (last 5 created during
  Batch 2 decisions)
- Cleanup of DC-EPMS-002 through DC-EPMS-006 (cumulative ~1.5h)
- Fix DC-EPMS-010 (PowerShell wrapper for native commands)

#### Backlog for Phase 3 / V10
- DC-EPMS-009 follow-up: Alpine or Distroless base image migration
- Multi-arch builds (amd64 + arm64) for Graviton edge deploy
- Replace faiss-cpu with hnswlib/annoy to retire DC-EPMS-001

---

## [0.4.0] — TBD (Sprint S2 GraphRAG completion, ~2026-04 mid)

### Added
- **GraphRAG service** (`backend/graphrag_service.py`, 166 lines) with NetworkX
  `MultiDiGraph` + FAISS `IndexFlatIP` + sentence-transformers `all-MiniLM-L6-v2`.
- **GraphRAG router** (`backend/graphrag_routes.py`, 62 lines): 6 endpoints `/api/graph/*`.
- **Knowledge corpus** under `config/knowledge/`: 5 markdown documents.
- **Agent tool** `query_graph_rag` registered, total Copilot tools = 6.
- 20 unit tests (`tests/test_graphrag.py`).

### Architecture
- Established **Dual-RAG topology**: ChromaDB primary + GraphRAG secondary.

---

## [0.3.0] — TBD (Sprint S1b Site Model + Lucide UI Polish, ~2026-04 early)

### Added
- **Declarative site model** (`backend/site_model.py`, 462 lines).
- **Site routes** (`backend/site_routes.py`, 186 lines): 9 endpoints `/api/site/*`.
- **LOTO impact analysis**: walks power_chains and cooling_chains DAGs.
- 44 unit tests + 41 integration tests = 85 tests total.

### Architecture
- YAML as single source of truth for facility topology.

---

## [0.3.0-physics] — TBD (Physics Engine, ~2026-04 early)

### Added
- 4 physics modules: `it_thermal.py`, `heat_rejection.py`, `electrical.py`,
  `mechanical.py` (~3500 lines, 85 tests total).
- `physics_engine.py` facade aggregating Site Health Index.

---

## [0.2.0] — TBD (Sprint S1a Procedure Engine, ~2026-04 early)

### Added
- **Procedure orchestration engine** with 8-state machine.
- **Witness engine** for multi-signature draft approval.
- **First MOP YAML executable**: `MOP-ATS-MONTHLY-001.yml`.
- **HAL** (Cummins, ASCO, Russelectric adapters): 39 tests.
- **CMMS work-order drafting**: deterministic LOR scoring, 51 tests.

### Decided (foundational)
- **Deterministic Sandbox**: zero write-action authority for AI per IEC 62443.

---

## [0.1.0] — TBD (Initial baseline, ~2026-03)

### Added
- FastAPI backend skeleton.
- TimescaleDB persistence layer.
- BMS connector stub (BACnet/Modbus).
- Initial agent engine (Gemma + Claude Sonnet + NeMo Guardrails).
- Initial frontend HMI.
- Shift report PDF generator.
- MCP server (3 tools + 4 resources).

---

## Format conventions

- `[Unreleased]` always at the top.
- Versioned releases below in reverse chronological order.
- Categories: **Added**, **Changed**, **Deprecated**, **Removed**, **Fixed**,
  **Security**, **Architecture**, **Decisions RESOLVED**, **Bugs discovered**.
- Date format: `YYYY-MM-DD`. `TBD` indicates date to be reconstructed from journal.
- Sprint references: `S{N}` for sprints, `W{N}` for weeks of 12-week roadmap.
- Bug IDs: `DC-EPMS-NNN`, sequential, registered in `[Unreleased]` until resolution.

## [v0.7.2-camino1] - 2026-05-09 (Frontend Path C2 sync + LOTO Auditor view)

### Added
- Frontend view-loto-auditor with form + 6 pillar cards renderer (commits 2a04d03, a90869c)
- Path C2 drift sync: 10 strings updated in frontend/index.html (commit 7ec55b2)
- nav-item LOTO Auditor with Lucide shield-alert icon
- Real-world demo: MOP-ATS-MONTHLY-001 + ups_a target catches NEC 460.6 violation in 12ms

### Fixed
- DC-EPMS-FE-001 MED: Path C2 drift in frontend (40 MW to 67 MW total, v4.0 to v8.1.0 footer)
- DC-EPMS-FE-002 LOW: LOTO Auditor view ausente in HMI

### Tech debt
- Phase B v1 bug discovered + remediated: [regex]::Replace breaks on $N patterns in replacement strings
- Multi-variant tolerance for middle-dot encoding (U+00B7 / and-middot / numeric entities)

### Demo capability
- Production-grade HMI now demonstrates 6-pillar LOTO Auditor end-to-end
- ADR-006 Deterministic Sandbox visible: status=pending_approval enforced
- Decision time 4-12ms in browser
- WARN vs HARD_FAIL color coding visible

## [v0.7.3-sprint5-patches] - 2026-05-09 (LOTO Auditor 6-pillar fixes + smoke verification)

### Fixed
- **DC-EPMS-033** (MED, commit 00caff1): voltage_v fallback in get_voltage_nominal.
  config/site_model.yml uses voltage_v field for switchgear/transformer canonical
  components; helper now reads voltage_v with graceful fallback to legacy keys.
- **DC-EPMS-030** (MED, commit da995e1): cooling_chain_for() called by Pillar 5 did
  not exist in site_model.py. Replaced call with impact_set(component_id,
  chain="cooling") which returns the equivalent downstream cooling DAG.
- **DC-EPMS-031** (MED, commit 324d87f): query_topology() called by Pillar 1 did
  not exist in graphrag_service.py. Replaced with loto_with_knowledge(target_id)
  returning {edges, evidence_chunks} payload Pillar 1 already expected.
- **DC-EPMS-032** (LOW, commit d853907): inline comment block clarifying walk
  direction polarity (downstream from disconnect to load) in Pillar 1 helper.
  No code change.

### Verified (browser smoke 2026-05-09 03:00)
- LOTO Auditor end-to-end on `MOP-ATS-MONTHLY-001` + `ups_a` target.
- 16 sources_consulted: 14 OK + 1 ADR-009 deferral + 1 DC-EPMS-034 warning.
- decision_time_ms ~12 ms maintained.
- Pillars 1, 2, 3, 5, 6 report OK; Pillar 4 reports the DC-EPMS-034 warning.
- Real-world demo capability: NEC 460.6 capacitor discharge violation surfaced
  in 12 ms on `MOP-ATS-MONTHLY-001` against `ups_a` target.

### Tech debt opened
- **DC-EPMS-034** (LOW, opened 2026-05-09): Pillar 4 reports
  `witness_engine_protection: "engine present but interface unknown"`. Witness
  engine is injected via dependency, but the helper cannot determine the call
  interface. Estimated effort: 30 min reading `backend/witness_engine.py` and
  fixing call site. Target: Sprint 5.5a or V10.

### Tech debt deferred
- **DC-EPMS-029b** (MED, deferred to Sprint 5 Telemetry):
  `simulate_loto_measurements` produces `shi_pre == shi_post` (no SHI delta).
  Hypothesis: `physics_engine.validate_site()` reads thermal fields
  (`hall_inlet_temp_c`, `chiller_supply_temp_c`, `cdu_pressure_bar`) that
  `simulate_loto` does not modify. Will resolve naturally during Kalman /
  telemetry stream integration in Sprint 5 (`v0.8.0-sprint5-kalman` target).

### Documentation
- CLAUDE.md endpoint listing for LOTO Auditor corrected to match runtime
  OpenAPI: `POST /api/loto/audit`, `GET /api/loto/audit/{id}`,
  `GET /api/loto/audit/{id}/markdown`, `GET /api/loto/audits/recent`.
  Previous listing erroneously included `/api/loto/procedures` and
  `/api/loto/health` (never registered).

### Session helpers archived
- 15 PowerShell orchestrators (`apply_*.ps1`, `diagnose_encoding.ps1`),
  `diagnose_output.txt`, and `frontend_pre_camino1_20260508_215625.zip` moved
  to `scripts/_archive/sesion_sprint5/` per Atomic Batches discipline
  (B3-2c precedent).
