# Catálogo de MOPs — Infraestructura Eléctrica Crítica

**Status:** Living catalog. Each `MOP-NNN-*.md` file is a fully-canonical
Method of Procedure that complies with the **Universal 5-Point Structure**
defined below. The Procedure Architect (`backend/agents/procedure_architect.py`)
audits every generated draft against the same structure and refuses to seal
any MOP that omits a section, the voltage-absence verification, or the
back-out plan.

**Source of authority:** Operator-supplied catalog (2026-05-23) refined under
Tier IV operational practice and aligned with the multi-agent fleet's
deterministic safety gate (S-DET-02 — Safety Officer is the sole vetoer).

---

## Universal 5-Point Structure (mandatory for every MOP)

Per the operator directive, every MOP autogenerado debe validar
obligatoriamente esta estructura de 5 puntos antes de darse por completado:

1. **Alcance y Objetivo** — definición exacta del equipo, ubicación
   (Site / Data Hall) y propósito de la intervención.
2. **Evaluación de Impacto y Riesgos** — identificación de posibles
   interrupciones en la carga IT, nivel de energía incidente
   (cal/cm²), dependencias aguas arriba/abajo.
3. **Requisitos Previos (Prerrequisitos)** — listado innegociable de
   herramientas aisladas, Categoría de EPP (CSA Z462-24 / NFPA 70E)
   y Permisos de Trabajo (PTW) aprobados.
4. **Lista de Pasos Secuenciales** — instrucciones directas, no
   ambiguas, con casillas de verificación para la firma del técnico
   ejecutante y el supervisor (**Principio de los Cuatro Ojos**,
   alineado con el Maker-Checker witness gate del Sprint 3 Phase 4).
5. **Plan de Reversión (Rollback / Backout Plan)** — criterios de
   aborto claros y pasos precisos para deshacer la maniobra y
   devolver el sistema a su estado original, seguro y funcional.

Every MOP additionally must mention, in the body:

- **CSA Z462-24** (or NFPA 70E) electrical-safety standard reference
- **PPE** category (1 / 2 / 3 / 4) per Arc Flash labelling
- **LOTO** (Lockout/Tagout) protocol — when the maneuver de-energizes
- **Vivo-Muerto-Vivo** (voltage absence verification) — for de-energized
  work, OR **límite de aproximación restringida** for live work

Missing any of the above → audit returns `hard_stop` (see
`audit_procedure_safety` in `backend/agents/procedure_architect.py`).

---

## Current Catalog

### Infrastructure layer (UPS / Transformer / Utility)

| ID | Asset Category | Title | Work Mode |
|---|---|---|---|
| [MOP-001](MOP-001-ups-bypass-transfer.md) | UPS | Transferencia a Bypass de Mantenimiento Externo | De-energized (after transfer) |
| [MOP-002](MOP-002-transformer-dry-inspection.md) | Transformer | Inspección Interna y Limpieza de Transformador de Tipo Seco | De-energized |
| [MOP-003](MOP-003-ats-commutation-test.md) | ATS / Utility | Prueba de Conmutación en Vacío y con Carga en ATS | Live (operational test) |

### Distribution layer (PDU / STS / RPP / Busway)

| ID | Asset Category | Title | Work Mode |
|---|---|---|---|
| [MOP-004](MOP-004-sts-load-transfer.md) | STS | Transferencia de Carga (Preferred → Alternate / Bypass) | Live |
| [MOP-005](MOP-005-pdu-pm-thermography.md) | PDU | Mantenimiento Preventivo Anual (Termografía + Lógica de Control) | De-energized |
| [MOP-006](MOP-006-pdu-breaker-replacement.md) | PDU | Reemplazo de Breaker Principal o Sub-Alimentador | De-energized |
| [MOP-007](MOP-007-rpp-load-balancing.md) | RPP | Balanceo de Carga de Fases A/B/C | De-energized (per circuit) |
| [MOP-008](MOP-008-rpp-whip-installation.md) | RPP | Instalación de Látigos (Whips) Bajo Piso Falso / Bandeja Aérea | De-energized |
| [MOP-009](MOP-009-rpp-epo-reset.md) | RPP | Restablecimiento Post-EPO (Humo / Fuego) | De-energized + Inspección |
| [MOP-010](MOP-010-busway-tap-off-install.md) | Busway | Instalación / Retiro de Tap-off Boxes | LIVE (high risk) |
| [MOP-011](MOP-011-busway-joint-maintenance.md) | Busway | Mantenimiento de Juntas Mecánicas + Tapas | De-energized (per sector) |
| [MOP-012](MOP-012-busway-thermographic-scan.md) | Busway | Escaneo Termográfico Operativo bajo Carga | LIVE (no invasivo) |

### Mechanical / Cooling layer (Chiller / CRAH / Cooling Tower)

| ID | Asset Category | Title | Work Mode |
|---|---|---|---|
| [MOP-013](MOP-013-chiller-staging-rotation.md) | Chiller | Cambio de Operación y Rotación Secuencial (Staging) | Live + LOTO en transferencia |
| [MOP-014](MOP-014-chiller-trip-response.md) | Chiller | Respuesta y Aislamiento por Disparo Térmico | Emergency response |
| [MOP-015](MOP-015-chiller-ride-through-recovery.md) | Chiller | Recuperación Eléctrica en Generador (Ride-Through) | Live coordination |
| [MOP-016](MOP-016-crah-hot-swappable-filters.md) | CRAH | Reemplazo de Filtros en Caliente (Hot-Swappable) | Live |
| [MOP-017](MOP-017-crah-vfd-valve-calibration.md) | CRAH | Calibración Dinámica de VFDs + Válvulas Modulantes | Live tuning |
| [MOP-018](MOP-018-crah-psychrometric-control.md) | CRAH | Control Psicrométrico + Mitigación de Condensación | Live tuning |
| [MOP-019](MOP-019-tower-chemical-dosing.md) | Cooling Tower | Dosificación Química Dinámica + Control de Legionella | Live (química) |
| [MOP-020](MOP-020-tower-pan-cleaning.md) | Cooling Tower | Limpieza de Piletas y Rociadores (Celda Aislada) | LOTO en celda |
| [MOP-021](MOP-021-tower-free-cooling-transition.md) | Cooling Tower | Transición a Free Cooling (Water-Side Economizer) | Live coordinated |

### Global system layer (sitio completo)

| ID | Asset Category | Title | Work Mode |
|---|---|---|---|
| [MOP-022](MOP-022-ist-full-load-test.md) | Global / IST | Pruebas de Sistemas Integrados a Plena Carga | Controlled simulation (peor caso) |
| [MOP-023](MOP-023-main-ring-valve-isolation.md) | Global / Hydraulics | Aislamiento por Válvulas de Anillo (Double Block and Bleed) | LOTO en tramo aislado |

### Companion knowledge (GraphRAG-indexed)

- `config/knowledge/electrical-mop-catalog.md` — infrastructure catalog
  (UPS / Transformer / Utility 12 títulos).
- `config/knowledge/distribution-mop-catalog.md` — distribution catalog
  (PDU/RPP/Busway scope + Universal 5-Point Structure).
- `config/knowledge/eaton-sow-r48-mp-checklist.md` — vendor-specific
  Eaton SOW R-48 PM checklist (BCMS / fibra óptica / FSBs / firmware).
- `config/knowledge/cooling-thermodynamics-references.md` — ASHRAE
  TC 9.9 + Uptime Tier IV + OCP + CTI ATC-105 + physics/chemistry
  equations (chiller `Q_rej`, `COP`, `Lift`; CRAH affinity laws;
  cooling tower `LSI`, `CoC`).
- `docs/architecture/maker-checker-cuatro-ojos.md` — alignment doc:
  the §4 checkboxes paper-trail + the Sprint 3 Phase 4
  Maker-Checker witness gate digital-trail.

---

## How the library uses these files

On backend boot, `_seed_architect_library_from_catalog` (called from the
FastAPI lifespan) parses every `MOP-*.md` in this directory and appends
each one to `_architect_library` with `source="catalog"` and a
`category` tag derived from the asset_category column above. The
operator sees them immediately under the Architect view as
ready-to-use templates that have already passed the audit gate.

Edit policy: edit the canonical bodies here, then restart the backend
to reload the library. Per S-RUNTIME-01 the Python backend does not
hot-reload.
