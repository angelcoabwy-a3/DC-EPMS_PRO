# R3 - Power controls: evaluation and design basis

Date: 2026-11-13. Inputs: operator documents
`Recomendacion_UPS_2N_16.76MW.md` and
`Recomendacion_Completa_UPS_2N_Ajustable.md`; vendor pages read the
same day (links at the end). Vendor figures below are as published by
each vendor on that date. Verify against the current datasheet before
any procurement decision.

## 1. What was asked

A readings and control panel for each UPS, each transfer switch and
each generator, with manual switching and remote control, informed by
current Eaton and Vertiv products.

## 2. What R3-A delivers

`backend/device_control.py` + `views/device_control.js` ("Power
Controls"). SIMULATED devices; no field equipment is bound.

| Topic | Decision | Basis |
|---|---|---|
| Authority | AUTO / REMOTE / LOCAL per device; remote commands only in REMOTE; LOCAL wins | Same selector found on generator and transfer controllers; keeps a technician at the equipment safe from a remote operation |
| Two-step command | select, then operate inside 30 s; single-use token bound to device and operator; interlocks checked twice | Select-before-operate practice of substation automation (IEC 61850 / DNP3 control models, cited from memory, not re-read for this work) |
| Who may operate | FACILITY_MANAGER from the session token | Epic 10 IAM; stricter than `/api/bms/write`, which trusts a role sent by the client |
| Audit | authority changes and operate attempts chained in the Forensic Ledger | ADR-011 |
| AI | no agent, optimizer or MCP module can reach the control module | ADR-006, enforced by a test |

Interlocks are supervisory permissives only: no transfer to a dead
emergency source, no stopping the only set carrying load, maintenance
bypass only from static bypass. Protection (ANSI 25/27/59/81) is not
modelled.

## 3. Product check (vendor-published, 2026-11-13)

| Product | Published single-block ratings | Fits a 2.5 MW block at 480 V? |
|---|---|---|
| Vertiv Trinergy | 1500 / 2000 / 2500 kW at 480 V, built from 500 kVA cores | Yes |
| Schneider Galaxy VX | 500 to 1500 kW per unit | No. The site model names a "Galaxy VX 2.5 MW" unit, which is not a catalogue rating |
| Schneider Galaxy VXL | 500 to 1250 kW | No |
| Eaton 9395XC | 1500 kW (North America) | No |
| Eaton 9395XR | 1500 / 1800 kVA at 380 to 415 V | No |

No Eaton single block at 2.5 MW was found in this search. That is an
absence in the search, not proof that none exists.

Operating modes worth modelling next, because current large UPS expose
them and the panel today has only three: a high-efficiency line-
interactive mode (Vertiv "Dynamic Online", Schneider "eConversion",
Eaton "ESS"), grid-interactive operation, and input power smoothing
for AI load steps.

## 4. Findings on the operator documents

Arithmetic checked and correct: 16.76 MW at 480 V is about 20.2 kA;
about 701 A at 13.8 kV; about 2326 A at 4.16 kV; 10 min at 16.76 MW is
about 2793 kWh.

Points to resolve before the site model is rebuilt (track R1.2):

1. **Losses.** 450 to 520 kW at 50 percent load does not match the
   stated 96.8 to 97.5 percent efficiency. At 8.38 MW that efficiency
   gives about 215 to 277 kW. About 480 kW corresponds to 100 percent
   load.
2. **No N+1 inside a path.** 7 x 2.5 MW = 17.5 MW covers 16.76 MW, but
   6 x 2.5 MW = 15 MW does not. Removing one block for maintenance
   leaves that path short, so the item "remove one block without
   affecting capacity" holds only while the other path carries the
   load (2N), not within the path. 8 blocks per path would give N+1.
3. **Generators are not sized.** With cooling and losses the facility
   load per path is above the 16.76 MW of IT load (about 22 MW at the
   PUE the platform simulates). Unit rating, count and redundancy are
   open.
4. **Generation voltage is open** (13.8 kV or 4.16 kV). The Phase 2
   farm in the model is 13.8 kV; Phase 1 utility intake is 27.5 kV.
5. **With transfer in medium voltage there is no low-voltage ATS.**
   The "ATS panel" becomes an MV transfer controller acting on the
   utility and generator breakers (52-U / 52-G), and the 480 V ASCO
   switches in the model disappear.
6. **Seven power trains per path.** Each 2.5 MW UPS at 480 V draws
   about 3000 A, so each needs its own transformer of about 3 MVA and
   a 4000 A switchboard.

## 5. Not done, by design

- No HAL binding: the Cummins / ASCO / Russelectric adapters exist but
  were never validated against hardware (stated in `backend/hal`).
- The site model still holds the old Phase 1 design (DC-EPMS-057 to
  061). The panels are keyed by component type, so they follow the
  model when it is rebuilt.
- The 800 VDC side (MV rectifier, SSCB, BESS) has no control panel.

## Sources

- Vertiv Trinergy: https://www.vertiv.com/en-us/products-catalog/critical-power/uninterruptible-power-supplies-ups/vertiv-trinergy
- Vertiv PowerNexus datasheet: https://www.vertiv.com/4a3942/globalassets/shared/vertiv-powernexus---datasheet.pdf
- Schneider Galaxy VXL / VX comparison: https://www.se.com/uk/en/work/products/product-launch/galaxy-vxl
- Eaton 9395XR: https://images.eaton.com/au/en-gb/catalog/backup-power-ups-surge-it-power-distribution/eaton-9395xr-ups.html
- Eaton 9395XC launch note: https://www.achrnews.com/articles/162347-9395xc-uninterruptible-power-supply-eaton
