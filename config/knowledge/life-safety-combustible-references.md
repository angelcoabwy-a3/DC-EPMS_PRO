---
id: life-safety-combustible-references
title: Life Safety + Combustible Operational References (Tier IV)
source: NFPA + ASTM + IEC + ANSI/AIHA + ISO compendium (operator catalog 2026-05-24)
source_type: operational_standard
applies_to:
  - vesda
  - clean_agent_suppression
  - novec
  - fm200
  - day_tank
  - bulk_tank
  - fuel_polishing
  - generator
  - genset
  - alternator
tags: [life-safety, vesda, clean-agent, novec, fm-200, fire-suppression, nfpa-12, nfpa-75, nfpa-110, nfpa-30, combustible, day-tank, fuel-polishing, astm-d2276, astm-d6304, iec-60079, hazardous-area, bonding, scba, sampling]
jurisdiction: international
version: "2026.1"
voltage_class: "ALL"
---

# Life Safety + Combustible — Operational References

**Status:** Operational reference for the v0.17.0 Life Safety +
Combustible canonical MOPs (MOP-024 through MOP-029). Indexed by
GraphRAG and surfaced to the Procedure Architect agent when
authoring procedures touching VESDA / Clean Agent suppression /
Day Tank fuel handling / Generator extended runtime.

**Driver:** Operator directive 2026-05-24 — extending the
electrical + mechanical-cooling catalog (v0.16.x) with Life Safety
and Combustible asset categories per NFPA 75 §11 + NFPA 110
extended-runtime spec.

**Companion files:** the 6 canonical bodies for these MOPs live
under [`docs/operaciones/mops/`](../../docs/operaciones/mops/) —
MOP-024 (VESDA zone test), MOP-025 (Novec cylinder pressure
annual), MOP-026 (clean agent discharge reset), MOP-027 (day tank
bulk transfer), MOP-028 (fuel polishing), MOP-029 (generator
extended runtime).

---

## 1. Catálogo de Estándares de Referencia

### Life Safety

- **NFPA 75 (Fire Protection for Information Technology
  Equipment)** — define los requisitos de protección contra
  incendios para Data Centers + IT rooms; §11 cubre el fire watch
  humano cuando los sistemas de supresión están fuera de servicio
  (cada 30 min si single zone, continuo si full-site disable).
- **NFPA 12 (Standard on Clean Agent Fire Extinguishing
  Systems)** — gobierna Novec 1230, HFC-227ea (FM-200), CO2 y
  otros agentes limpios; §4.7.4 requiere verificación anual de
  presión + masa del cilindro; pérdida > 10% requiere recharge.
- **NFPA 72 (National Fire Alarm and Signaling Code)** — VESDA
  zone configuration + alarm levels (Alert / Action / Fire 1 /
  Fire 2) per §5.7 aspirating smoke detection.
- **FM 7745 (VESDA System Requirements)** — sensitivity drift
  tolerance band para anual calibration; típico ± 15% de baseline
  con drift > 25% = sensor derivado, reemplazar la cabeza.
- **ISO 14520 (Gaseous Fire-Extinguishing Systems)** — equivalente
  internacional a NFPA 12; design concentrations + soak time +
  enclosure integrity test (Door Fan Test).

### Combustible

- **NFPA 30 (Flammable and Combustible Liquids Code)** — gobierna
  storage + handling de diesel #2; bulk tank requirements + spill
  containment + setbacks. Día tank en sala de generadores requiere
  bermas perimetrales calculadas para 110% del volume del tank
  más grande adyacente.
- **NFPA 110 (Standard for Emergency and Standby Power Systems)**
  — §A.5.6.4 Extended Runtime: oil sample analysis cada 100 h,
  filter replacement cada 250 h en operación > 12 h continuas;
  §8.4 weekly maintenance includes fuel cleanliness verification.
- **ASTM D2276 (Particulate Contaminant in Aviation Fuel)** —
  aplicado también a diesel para Data Centers: target cleanliness
  ISO 4406 18/16/13 (partículas por mL).
- **ASTM D6304 (Water in Liquid Petroleum Products by Karl
  Fischer)** — método ASTM gold-standard para water-cut
  measurement. Target < 200 ppm. > 500 ppm = injector damage risk.
- **IEC 60079 (Explosive Atmospheres)** — clasifica zona 0 / 1 / 2
  según probabilidad de presencia de vapor combustible. Manhole
  abierto del day tank = zona 1 temporal → equipo eléctrico
  cercano debe ser Ex-rated O bonding cable + ATEX procedures.
- **ANSI/AIHA Z9.5 (Laboratory Ventilation)** — guía aplicada a
  confined space entry de tanques (full drain + manual cleaning)
  + permit-required confined space protocol.

### Cross-cutting

- **CSA Z462-24 / NFPA 70E** — Arc Flash + LOTO ya cubierto en
  los catálogos eléctricos + mecánicos previos; aplica a panel
  VESDA (Cat 1), panel clean agent (Cat 1-2), bomba de transfer
  (Cat 2), bomba de polishing (Cat 2), alternador del generador
  (Cat 3).

---

## 2. Fundamentos Físicos + Químicos

### A. VESDA Aspirating Smoke Detection

- **Principio**: bomba aspiradora muestrea aire continuamente desde
  una red de tubería con boquillas distribuidas en la zona. Detecta
  partículas de combustión a concentraciones **1000× más bajas**
  que sistemas spot smoke detectors (incipient detection).
- **Sensitivity drift**: el detector laser scatter es sensible a
  contaminación del óptico — la sensitivity nominal puede
  derivarse en 6-12 meses; FM 7745 mandates anual calibration.
- **Alarm levels**:
  - `Alert` (1× sensitivity baseline) — investigate, no auto-action
  - `Action` (3× baseline) — pre-alarm, notify NOC
  - `Fire 1` (5× baseline) — trigger pre-discharge sequence
    (silence beacons, count-down)
  - `Fire 2` (10× baseline) — trigger clean agent discharge

### B. Clean Agent (Novec 1230) — Physics + Chemistry

- **Novec 1230 (FK-5-1-12)**: fluoroketona líquida a 21 °C, vapor
  a temperatura de descarga (~50 °C). Almacena a 25 bar (360 PSI).
- **Mecanismo de extinción**: absorción térmica + ruptura de la
  cadena de combustión (oxígeno NO se desplaza significativamente
  — concentración típica de descarga ~5%, lejos del umbral de
  hipoxia 18%).
- **Toxicidad**: NOAEL (No Observed Adverse Effect Level) > 10%
  exposure por 5 min — segura para occupancy normal.
- **Decomposition risk**: temperatura > 800 °C (fire still
  active) → produce HF + fluoruro de carbonilo (tóxicos).
- **Soak time** requerido per NFPA 12: 10 minutes después de
  alcanzar concentración de diseño — durante este período la
  sala debe permanecer cerrada para evitar dilución prematura.

### C. FM-200 (HFC-227ea) — Variante

- Mismo principio que Novec pero almacenamiento 25 bar nominal.
- Productos de descomposición a temperatura: HF.
- Sensibilidad climática: posibilita efecto invernadero (GWP =
  3220 vs Novec GWP = 1). Por eso muchos sitios nuevos optan
  por Novec 1230.

### D. Diesel #2 — Combustible

- **Flash point**: ≥ 52 °C (Class II liquid per NFPA 30) —
  no se inflama a temperatura ambiente sin spark / arc.
- **Densidad**: 0.85 g/mL a 15 °C.
- **Heat content**: ~36 MJ/L (combustión completa).
- **Water solubility**: < 50 ppm en diesel limpio, pero **agua
  libre** acumula en el bottom del tank por gravedad (separa por
  densidad — agua 1.0 g/mL vs diesel 0.85).
- **Cumming consumo Cummins QSK95** (referencia): ~150 GPH al 75%
  load. Day tank de 500 galones agota en ~3-4 h al load
  proyectado.

### E. Water Contamination — ASTM D6304 Karl Fischer

- **Water-cut measurement** mediante reacción Karl Fischer (yodo
  + dióxido de azufre + alcohol + amina + agua → yodura).
- **Target**: < 200 ppm para fuel diesel destinado a generador
  emergencia.
- **Threshold de acción**: 500 ppm — injector damage probable
  en arranque súbito (water hammer + corrosion en alta presión).
- **Biofilm crítico**: en la interfaz fuel/water, hongos
  (Hormoconis resinae) + bacterias (Pseudomonas) crecen y
  producen biosurfactantes corrosivos. Sample biológico anual
  obligatorio.

### F. Generator Extended Runtime — Stress Profile

- **Winding insulation lifetime**: regla del fabricante
  (Arrhenius) — vida útil se reduce ~50% por cada 10 °C sobre
  rated. Rated típico Class H = 180 °C max, con 110 °C como
  threshold de degradación significativa.
- **Oil aging**: viscosidad se modifica + ácido acumulado +
  metales de desgaste detectables vía AES (Atomic Emission
  Spectroscopy). Cambio oil + filter cada 250 h en extended-run.
- **Vibration**: ISO 10816 zone C threshold para alternadores
  grandes es 7 mm/s RMS — por encima indica bearing failure
  inminente.

---

## 3. Cross-references for the Procedure Architect

When generating Life Safety + Combustible procedures, the
Architect should surface the relevant section verbatim with the
appropriate citation marker:

| Doc type | Touchpoints in this knowledge base |
|---|---|
| **MOP — VESDA** | §1 NFPA 72/75 + FM 7745; §2.A sensitivity drift tolerance; canonical body MOP-024 |
| **MOP — Clean Agent** | §1 NFPA 12/ISO 14520; §2.B Novec / §2.C FM-200; canonical bodies MOP-025 + MOP-026 |
| **MOP — Day Tank** | §1 NFPA 30/110 + IEC 60079 + ANSI/AIHA Z9.5; §2.D diesel properties; canonical bodies MOP-027 + MOP-028 |
| **MOP — Generator Extended Run** | §1 NFPA 110 §A.5.6.4 + ASTM D6304; §2.E water contamination + §2.F generator stress; canonical body MOP-029 |
| **EOP — Discharge / Fuel Spill** | NFPA 12 soak time, NFPA 30 spill response, jurisdictional environmental notification windows |

The MOP audit gate (universal 5 sections + LOTO + PPE + CSA
Z462-24 + voltage verification + back-out + Tag + Estado Final +
Vector + MCP + HOLD POINT + parameterized abort) applies
identically to Life Safety + Combustible MOPs. The Vector
classification for these MOPs is **Vector Life Safety** (VESDA,
clean agent) or **Vector Combustible** (day tank, generator
fuel/oil/cooling). Generator extended-run is multi-vector
(Combustible + Eléctrico + Mecánico/Térmico simultáneamente).
