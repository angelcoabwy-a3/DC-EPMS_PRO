# ADR-021: Building D 800 VDC design model, sized end to end

- Status: accepted (design values open for operator review)
- Date: 2026-11-26
- Deciders: Wilmer Y. Angel Beltran (operator: GO, "scale every element
  for 800 V"), Claude (sizing and implementation)

## Context and problem statement

The operator asked for a 3D hall view at the quality bar of an 800 VDC
reference video, with every number from the simulator or the design
data. Building D as modelled in `config/site_model.yml` could not carry
that:

- one path only (Phase 1 is 2N);
- one 55 MW MV rectifier, one SSCB, one DC bus;
- 2 x 2 MW RPPs for 250 racks x 200 kW = 50 MW;
- one 60 MW utility feed and a 2.5 MWh BESS (3 min at 50 MW);
- the project spec `03_TECHNICAL_SPECS_800VDC.md` describes yet another
  plant (2 x 5 MW rectifiers, 12 racks).

A 3D view drawn on that data would show a plant that does not close.

## Decision

1. `config/design/building_d.yml` holds the design INPUTS only.
   `backend/design_model.py` computes every derived figure and runs the
   checks. Values carry a tag: DESIGN (input), MODEL (computed); LIVE is
   attached by callers.
2. Topology 2N (paths A and B, each carries 100 percent of IT). Each
   path has 2 DC bus sections to bound bus current.
3. Rules: conductors and overcurrent devices loaded to at most 80
   percent of rating (125 percent continuous-load rule). Transformers,
   rectifiers, converters, generators at 100 percent with the stated
   redundancy. Ratings snap to a standard series.
4. Read-only routes (ADR-006): `GET /api/design/building-d`,
   `/api/design/building-d/racks`, `/api/design/building-d/racks/{id}`.
5. Vocabulary fence (S-VOCAB-01): DC elements carry
   `polarity: unipolar` and no phase count; AC elements carry
   `phases: 3`; only the MV rectifier has both (`phases_in`,
   `polarity_out`). Tested.

## Result (computed, per path unless stated)

| Element | Sizing |
|---|---|
| IT | 250 x 200 kW = 50 MW; rows 10 x 25 racks, 5 MW per row |
| Rack feed | 250 A full (125 A normal), SSCB 315 A, A and B feeds |
| Busway (half row, 13 racks) | 3,250 A, rated 5,000 A; 20 per path |
| DC bus section | 25 MW, 31,250 A, rated 40,000 A; 2 per path |
| MV rectifiers 5 MW | 5 + 1 per section, 12 per path, 24 total |
| Rectifier input | 5,371 kVA, 88.6 A at 35 kV |
| Row capacitor bank | 1 MJ, 8.68 F (200 ms, 800 to 640 V) |
| BESS | 4.17 MWh usable needed, 3 x 2.5 MWh = 7.5 MWh, 5.8 min; 21 x 2.5 MW DC/DC |
| Mechanical | 25 percent of IT = 12.5 MW; 5 x 3,750 kVA unit subs (4+1) |
| Critical mechanical UPS | 1 MW (CDU pumps, controls), 3 x 500 kW (2+1) |
| Path demand | 51.0 MW rectifier input + 12.5 MW = 63.5 MW, 66.9 MVA |
| Utility feed | 83.6 MVA required at 35 kV; 35 kV bus 1,600 A |
| Generators 3.2 MW at 13.8 kV | 20 + 1 per path, 42 total; 13.8 kV bus 4,000 A |
| Step-up 13.8 / 35 kV | 80 MVA, 1+1 per path |
| CDUs 2.5 MW | 2 + 1 per row, 30 total; 111.7 L/min per rack at 27 K |

All checks PASS. The model also cross-checks the Phase 1 README: 142 kW
at 40 L/min implies a 53.5 K rise, outside 18 to 45 C (DC-EPMS-075).

## Consequences and open items

- Generator margin with one set out is 0.75 percent (64.0 vs 63.5 MW).
  BESS recharge after an outage is not in the path demand. Operator
  decision: accept, add a set per path, or a larger unit.
- The DC bus fault level is not computed (no short-circuit study); the
  50 kA / 31 cal figures in `site_model.yml` are not derived from this
  plant.
- Voltage bands (640 / 840 V) come from the project spec, quoted there
  as IEC TR 63282; not re-verified against the standard text.
- Rack footprint, aisle widths, CDU, BESS converter and unit-substation
  ratings are assumptions, not vendor data. Rack internals (trays) are
  not modelled.
- `config/site_model.yml` still holds the old Building D (DC-EPMS-076).
  The SLD, What-If and simulator keep reading it until it is migrated.
- Supersedes the component inventory of `03_TECHNICAL_SPECS_800VDC.md`.

## Revision 2 (2026-11-26): sized upward

Operator direction: "always adjust upward to the best, structured to
reality". The two open decisions of the first version are closed that
way:

- BESS ride-through 10 min (same as the Phase 1 battery spec) instead of
  5 min: 8.33 MWh usable per path, 6 x 2.5 MWh = 15 MWh installed per
  path, 11.5 min.
- BESS recharge is now a load: usable energy back in 2 h (assumption) =
  4.17 MW per path, carried by the rectifiers (DC bus) and, in recovery,
  by the generators.
- New rule `min_unit_margin: 0.05`: every unit rated at 100 percent
  (rectifiers, generators, BESS converters, mechanical unit subs,
  critical mechanical UPS, CDUs) keeps at least 5 percent over its load
  with the redundant unit counted out.

| Element | Revision 1 | Revision 2 |
|---|---|---|
| MV rectifiers 5 MW per section | 5+1 (24 total), 0 % margin | 6+1 (28 total), 10.8 % margin |
| Generators 3.2 MW per path | 20+1 (42 total), 0.75 % margin | 23+1 (48 total), 8.6 % margin |
| Path demand | 63.5 MW | 67.8 MW (recharge included) |
| Utility feed required | 83.6 MVA | 89.2 MVA |
| 35 kV bus | 1,600 A | 1,600 A (1,471 A required) |
| 13.8 kV generator bus | 4,000 A (3,497 A req.) | 4,000 A (3,731 A req.) |
| BESS per path | 7.5 MWh, 21 converters | 15 MWh, 22 converters |
| Mechanical unit subs / critical UPS per path | 5 / 3 | 5 / 4 |
| CDUs | 3 per row (30) | 4 per row (40) |
| Step-up 80 MVA 1+1 | 66.9 MVA | 71.3 MVA |

New checks D-RECT-MARGIN and D-GEN-MARGIN. All checks PASS.

Still open: the 13.8 kV generator bus runs at 93 percent of 4,000 A
(next step would be splitting it into two sections); DC fault level not
computed; DC-EPMS-076.
