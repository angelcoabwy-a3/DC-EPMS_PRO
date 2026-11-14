# ADR-013: Phase 1 generation sized and withdrawn against TOTAL path load

- Status: ACCEPTED
- Date: 2026-11-14
- Decision-maker: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
- Resolves: DC-EPMS-066, DC-EPMS-067
- Source: `docs/design/operator/Estructura_Repositorio_y_Resolucion_DC-EPMS_066_067_068.md`
- MADR template: https://adr.github.io/madr/

## Context

The closed design of 2026-11-13 (`config/power_plant.yml`) gave each
2N path 9 x 2.5 MW generators at 13.8 kV. The R3-B model showed that
with one set out (8 x 2.5 = 20.0 MW) the path cannot carry its full
demand of about 21.5 MW (16.76 MW IT + 25 percent cooling and
auxiliaries + UPS losses). The rule used to permit taking a set out
("residual generation at least 16.76 MW") counted IT load only, so it
allowed isolations that left the path short.

## Decision

1. **Generators: 9 x 2.75 MW per path at 13.8 kV** (option B of the
   operator document). N = 24.75 MW, N+1 = 22.0 MW. 18 sets in total.
2. **Withdrawal rule:** a generator bay may be taken out of service
   only if the generation still available on the path is at least the
   generation floor:

   `floor = max(current total path load, computed full-path demand, 21.5 MW design total)`

   where total load = IT + cooling + auxiliaries + UPS losses.
3. Generation N and N+1 on the capacity panel use the same floor. The
   IT-only figure stays visible for comparison, labelled "not used".

## Options considered

| Option | Per path | N+1 (one out) | Against 21.5 MW |
|---|---|---|---|
| A | 10 x 2.5 MW | 22.5 MW | covers, one more machine per path |
| **B (chosen)** | **9 x 2.75 MW** | **22.0 MW** | **covers, same machine count** |
| C | 9 x 2.5 MW, cooling on generators capped | 20.0 MW | only with an operating restriction |

## Consequences

- Only ONE generator per path can be out at a time (8 x 2.75 = 22.0 MW
  passes, 7 x 2.75 = 19.25 MW does not). Under the superseded IT-only
  rule three could have gone out. Maintenance planning must account
  for this.
- The 0.5 MW margin of N+1 over the design total is thin (about 2.3
  percent). Any growth in the cooling share above 25 percent breaks
  N+1; the model then reports it (`generation_floor_kw` follows the
  computed demand when that is larger).
- Normal 2N transfer needs 4 sets synchronised per path (11.0 MW
  against about 10.7 MW drawn).

## Not decided here

- Generator vendor and model (`not selected` in the model).
- Whether the 2.75 MW rating is a data-center continuous or a prime
  rating: the operator document does not say, and the margin above
  depends on it.

## Enforcement

- `backend/device_control.py::_generation_floor_kw` and
  `_bay_context` (rule R10 of `backend/mv_switching.py`).
- `tests/test_device_control.py::TestClosedDesign` and
  `::TestMvProcedures::test_capacity_rule_uses_total_load`.
- Scenario `config/power_scenarios/GEN-N1-001.json`.
- `backend/site_model_v2.py::validate` refuses a model whose
  generation N+1 is below the design total.
