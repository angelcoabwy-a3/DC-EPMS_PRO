# Proposed repository structure: mapped, not moved

Date: 2026-11-14. Responds to section 4 of
`docs/design/operator/Estructura_Repositorio_y_Resolucion_DC-EPMS_066_067_068.md`.

## Decision

The proposed tree (`digital-twin-power/` with `models/`, `modules/01_..07_`,
`telemetry/`, `scripts/`) is **adopted as the logical module map** and
**not applied as a physical move**. Reasons:

1. Every backend module is imported as `backend.<name>` or, in tests,
   as a top-level module from `backend/` (the DC-EPMS-008 import
   convention). Moving files into `modules/0N_*` touches the imports
   of 214 Python files (114 of them import `backend.*` explicitly) and
   the 1800-test suite in one commit.
2. Directory names that start with a digit (`01_core_model`) are not
   valid Python package names; they cannot be imported without
   `importlib` tricks.
3. The public deployment starts `uvicorn backend.main:app`
   (`docs/DEPLOY_PUBLIC.md`); the operator workstation path
   `C:\dev\DC-EPMS_PRO` and its scripts assume the current layout.
4. A move of that size would make the DC-EPMS-068 migration (the
   operator's top priority) much harder to review, because every
   diff would mix renames with logic.

## Where each proposed folder lives today

| Proposed | Current location | Note |
|---|---|---|
| `docs/design/` | `docs/design/` | operator documents copied to `docs/design/operator/` |
| `docs/decisions/` | `docs/adr/` | MADR ADRs; the generator decision is ADR-013 |
| `models/site_model_legacy.yml` | `config/site_model.yml` | renamed at the end of DC-EPMS-068 |
| `models/site_model_v2.yml` | `config/site_model_v2.yml` | generated |
| `models/one_line/` | `frontend/assets/js/core/power_sld.js` | the SLD is generated in the browser, not stored as SVG / DXF |
| `models/physics/electrical`, `thermal` | `backend/physics/` | electrical, mechanical, it_thermal, heat_rejection |
| `modules/01_core_model` | `backend/site_model.py`, `backend/site_model_v2.py` | |
| `modules/02_power_system/ups`, `generators` | `backend/device_control.py`, `config/power_plant.yml` | |
| `modules/03_safety_mv_arcflash/interlocks` | `backend/mv_switching.py` | rules R1 to R10 |
| `.../switching_assistant` | `backend/mv_switching.py` (procedures) + `views/device_control.js` | |
| `.../loto` | `backend/loto_auditor_*.py` | not yet linked to MV procedures (R3-F) |
| `.../incident_energy`, `thresholds` | not built | needs a short-circuit and coordination study (R3-E) |
| `modules/04_thermal_model` | `backend/physics/` (equipment level only) | room model not built (R3-D) |
| `modules/05_scenarios_library` | `backend/power_scenarios.py`, `config/power_scenarios/` | 9 scenarios |
| `modules/06_ot_security_usability` | `backend/ot_security.py`, `views/ot_security.js` | DC-EPMS-063..065 open |
| `modules/07_integration_layer/epms_adapters` | `backend/hal/`, `edge/gateway-rs/` | |
| `.../iec61850_prep` | not built | |
| `telemetry/mapping_v2.yaml` | `config/telemetry_mapping_v2.yml` | generated |
| `tests/test_n1_ups.py`, `test_n1_generators.py` | `tests/test_device_control.py` (`TestClosedDesign`, `TestUpsBlocks`, `TestMvProcedures`), `tests/test_site_model_v2.py` | |
| `tests/test_incident_energy_thresholds.py` | not built | depends on R3-E |
| `scripts/validate_site_model_v2.py` | `scripts/build_site_model_v2.py --check` | |

## Documents referenced but not received

`Analisis_Umbrales_Energia_Incidente.md`,
`Seccion_Energia_Incidente_IEEE1584.md` and
`Estructura_Gemelo_Modular_Pendientes_DC-EPMS.md` are listed in the
proposed tree but were not provided. Incident energy stays unbuilt:
IEEE 1584 needs bolted fault current, electrode configuration, gap,
working distance, enclosure size and protective-device clearing time
for each bus, and none of those exist in the repo.
