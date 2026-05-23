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

| ID | Asset Category | Title | Work Mode |
|---|---|---|---|
| [MOP-001](MOP-001-ups-bypass-transfer.md) | UPS | Transferencia a Bypass de Mantenimiento Externo | De-energized (after transfer) |
| [MOP-002](MOP-002-transformer-dry-inspection.md) | Transformer | Inspección Interna y Limpieza de Transformador de Tipo Seco | De-energized |
| [MOP-003](MOP-003-ats-commutation-test.md) | ATS / Utility | Prueba de Conmutación en Vacío y con Carga en ATS | Live (operational test) |

---

## Distribution-layer MOPs (catalog only — no full body yet)

The 9 distribution-layer MOPs (PDU/STS, RPP, Busway) live as a catalog in
`config/knowledge/distribution-mop-catalog.md` (GraphRAG-indexed). The
Procedure Architect can author full bodies on demand; until they are
operator-validated the catalog entries stay there, not here.

The Eaton SOW R-48 preventive maintenance checklist (BCMS, fiber-optic
plate, control cable boxes, alarm history, FSBs, firmware) lives at
`config/knowledge/eaton-sow-r48-mp-checklist.md` and is surfaced to the
LLM author whenever the operator's context mentions `eaton`.

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
