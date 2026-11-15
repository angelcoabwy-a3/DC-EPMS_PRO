# DC-EPMS-068: migration of the site model to the closed power design

Status: **IN PROGRESS** (2026-11-14). Steps 1, 2, 4 (specification) and
5 of the operator plan are done, plus the runtime switch (lote A);
steps 3, 4 (runtime), 6 and 7 are not.

## What exists now

| Item | File | State |
|---|---|---|
| Closed design (single source) | `config/power_plant.yml` | 8 x Trinergy 2500 + 9 x 2.75 MW at 13.8 kV per path |
| Model builder and validator | `backend/site_model_v2.py` | done, pure, tested |
| CLI (write / `--check`) | `scripts/build_site_model_v2.py` | done |
| Generated model | `config/site_model_v2.yml` | GENERATED, 177 components, loads in `SiteModel` |
| Generated telemetry spec | `config/telemetry_mapping_v2.yml` | GENERATED, 516 points, symmetric A and B |
| Power Controls roster | `backend/device_control.py` | ids identical to v2 (test fence) |

`config/site_model.yml` is NOT renamed to `site_model_legacy.yml`.
Renaming it would break every consumer below at once; git history
already freezes it. It is renamed when the last consumer moves.

## Phase 1 topology in v2 (per path)

```
utility_feed_p 27.5 kV -> mv_xfmr_p 27.5/13.8 kV -> mvtc_p (52-U)
genset_p_01..09 13.8 kV -> gen_bus_p -> mvtc_p (52-GM)
mvtc_p -> mv_swgr_p 13.8 kV -> unit_sub_p_NN 13.8 kV/480 V -> lv_swbd_p_NN
       -> ups_p_NN -> ups_out_bus_p -> rpp_p_01/02 -> busways -> racks
```

Sizing assumptions (not vendor data, stated in the model): unit
substation 3500 kVA, UPS input switchboard 5000 A frame, utility
transformer 25 MVA.

## What the validator proves

- Every chain endpoint exists; every new component has a room.
- Counts and ratings match `power_plant.yml`.
- Generation N+1 is at least the design total (ADR-013).
- No AC voltage mismatch along Phase 1 chains. The same check on the
  legacy model reports `utility_feed_a (27.5 kV) -> ats_a (0.48 kV)`,
  which is DC-EPMS-058; v2 does not have it.
- Every Phase 1 rack is fed through both MV transfer controllers (2N).
- A LOTO on one UPS block or on a whole transfer controller leaves no
  rack without a path.

## Consumers still on the legacy ids (step 7)

Retired ids: `ups_a/b`, `ats_a/b`, `xfmr_a/b`, `switchgear_a/b`.
Generator ids `genset_a_01`, `genset_b_02`, etc. are kept in v2.
Counted 2026-11-14 with a word-boundary grep:

| Area | Files | References |
|---|---|---|
| backend | 13 | 59 |
| frontend | 10 | 148 |
| config (procedures) | 5 | 14 |
| tests | 39 | 475 |
| BMS tags (`config/bms_tags.yml`) | 1 | 22 power tags, all mapped in `telemetry_mapping_v2.yml` |

Per file (backend, frontend, config):

| File | References |
|---|---|
| `backend/agent_copilot.py` | 21 |
| `backend/agent_site_tool.py` | 1 |
| `backend/cmms_mcp.py` | 1 |
| `backend/cmms_repository.py` | 1 |
| `backend/hal/asco_adapter.py` | 2 |
| `backend/loto_auditor_models.py` | 1 |
| `backend/loto_auditor_pillar_helpers.py` | 1 |
| `backend/main.py` | 17 |
| `backend/multi_agent.py` | 1 |
| `backend/site_model.py` | 7 |
| `backend/site_routes.py` | 3 |
| `backend/tech_assist/troubleshoot.py` | 1 |
| `backend/telemetry_proto_adapter.py` | 2 |
| `config/procedures/DEMO-UPS-COMPLIANT.yml` | 1 |
| `config/procedures/DEMO-UPS-MISSING-DISCHARGE.yml` | 1 |
| `config/procedures/MOP-ATS-MONTHLY-001.yml` | 4 |
| `config/procedures/SOP-DAILY-ROUNDS-001.yml` | 1 |
| `config/procedures/T4-MOP-UPS-001.yml` | 7 |
| `frontend/assets/js/core/asset_metadata.js` | 6 |
| `frontend/assets/js/core/node_registry.js` | 27 |
| `frontend/assets/js/core/power_grid.js` | 36 |
| `frontend/assets/js/core/power_sld.js` | 36 |
| `frontend/assets/js/core/state.js` | 2 |
| `frontend/assets/js/views/cooling.js` | 4 |
| `frontend/assets/js/views/mission_control.js` | 2 |
| `frontend/assets/js/views/power.js` | 16 |
| `frontend/assets/js/views/procedures.js` | 4 |
| `frontend/assets/js/views/topology.js` | 15 |

## Order of the remaining work (estimates, not commitments)

1. **Runtime switch behind a flag**: DONE (lote A, 2026-11-14).
   `DC_EPMS_SITE_MODEL` = unset / `legacy` (default) or `v2`; any other
   value fails closed. v2 loads only if rebuilding it from
   `site_model.yml` + `power_plant.yml` gives the committed file and
   the validator is clean. `GET /api/site/model` reports the variant.
   Under v2 the process boots (177 components) and the main routes
   answer 200; consumers on retired ids are still unported.
2. **Backend consumers**: DONE (lote B, 2026-11-14). Role resolution in
   `backend/site_roles.py`; ported `power_chain_for`, LOTO pillar 2
   (block-level UPS LOTO), boot warmup, copilot HLD mapping, CMMS
   seeder, tool texts. The HLD display keys in `get_topology_state`
   stay with the frontend. ASCO HAL is legacy-only (no 480 V ATS in
   v2; binding a vendor to the MV transfer controller is a separate
   decision). Under v2, 5 tests fail on legacy-id fixtures.
3. **Frontend**: DONE (lotes C1 + C2 + SLD vida 1 / 2, 2026-11-14).
   Power SLD and What-If DAG on the closed design (MV transfer
   controller, 13.8 kV switchgear, unit substations, generator bus,
   UPS bank with per-block detail, animated flow, status strip and
   sequence of events); topology HLD labels; Procedure Architect
   presets from `/api/site/model` roles. The HLD keys stay an
   aggregate namespace (`site_roles.hld_key`).
4. **Procedures** (5 MOP / SOP files): rewrite the targets; the ATS
   monthly MOP becomes an MV transfer controller MOP. 3-5 h, plus
   operator review of the procedure text.
5. **Tests**: DONE for the runtime switch: the full backend suite passes
   with `DC_EPMS_SITE_MODEL` unset (1886) and with `v2` (1886).
   Fixtures that build their own legacy SiteModel still exercise the
   legacy file on purpose.
6. **Telemetry simulator** producing the v2 points (step 4 runtime).
7. Rename `site_model.yml` to `site_model_legacy.yml`, make v2 the
   default, close DC-EPMS-057..061 and -068.

Remaining (2026-11-14): step 4 (procedure YAMLs, 5 files, needs
operator review of the procedure text), step 6 (simulator check of the
v2 points against telemetry_mapping_v2.yml) and step 7 (make v2 the
default; then close DC-EPMS-057..061 and -068). DC-EPMS-072 (40 of 50
Phase 1 racks without a power chain) should be settled before step 7.
Estimated 8-14 h.
