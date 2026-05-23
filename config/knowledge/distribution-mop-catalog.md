---
id: distribution-mop-catalog
title: White-Space Distribution MOP Catalog (PDU, RPP, Busway)
source: Operator-supplied catalog 2026-05-23
source_type: operational_standard
applies_to:
  - pdu
  - sts
  - rpp
  - busway
  - tap_off_box
  - whip
  - regleta
  - rpdu
tags: [mop, distribution, white-space, sts, scr-box, bcms, tap-off, load-balancing, epo, thermography, busway, whip]
jurisdiction: international
version: "2026.1"
voltage_class: "LV"
---

# Catálogo y Evaluación de MOPs: Distribución Eléctrica (White Space)

**Status:** Operational knowledge — indexed by GraphRAG and surfaced
to the Procedure Architect when authoring MOPs for downstream
distribution gear (PDU / STS / RPP / Busway). The Architect's audit
gate enforces vendor-specific checks via cross-reference to
[`eaton-sow-r48-mp-checklist`](./eaton-sow-r48-mp-checklist.md) when
the operator context names Eaton equipment.

**Companion files:** infrastructure-side MOP catalog (UPS / Transformer
/ Utility) at [`electrical-mop-catalog`](./electrical-mop-catalog.md).
Fully-canonical bodies for the most-common MOPs live under
[`docs/operaciones/mops/`](../../docs/operaciones/mops/).

---

## Análisis Integrado: Eaton SOW (PDU, RPP, STS)

Para mantener el objetivo de cero incidentes y asegurar la
confiabilidad, todos los MOPs de mantenimiento preventivo en PDU y
RPP deben incorporar las directrices del fabricante (basado en el
SOW R-48 de Eaton). Además de la revisión de potencia (termografía,
reapriete), **el agente debe exigir la inclusión de:**

- Verificación de funcionamiento de las tarjetas de monitoreo BCMS.
- Comprobación de conexiones de cables de control en la caja lógica y
  caja SCR (para STS).
- Revisión de conexiones de fibra óptica en la placa de monitoreo.
- Impresión y revisión exhaustiva del **historial de alarmas**.
- Evaluación de Field Service Bulletins (FSBs) y actualización de
  firmware (con aprobación previa).

> See `eaton-sow-r48-mp-checklist.md` for the structured checklist
> the audit gate matches against. The gate fires `caution` (not
> `hard_stop`) when the operator's context mentions `eaton` but the
> draft omits the BCMS / fiber / FSB / firmware checks — the verdict
> is advisory because the fleet is multi-brand.

---

## 1. MOPs para PDU (Power Distribution Unit) y STS

La PDU es el núcleo de la distribución secundaria, conteniendo
transformadores de aislamiento e interruptores principales. A menudo
integra un STS (Static Transfer Switch).

- **MOP de Transferencia de Carga (STS/Bypass):** Procedimiento
  crítico para conmutar la carga de la fuente preferida a la fuente
  alterna (o bypass de mantenimiento). *(Nota para integración: debe
  incluir la revisión previa del HMI, **historial de alarmas** y
  **estado de la caja SCR** del STS antes de autorizar la
  transferencia — S-DISTRIBUTION-01.)*
- **MOP de Mantenimiento Preventivo (Termografía y Control):**
  Protocolo integral. Incluye la apertura de paneles bajo normas Arc
  Flash para escaneo infrarrojo de barras/conexiones, combinado con
  la revisión de lógica de control, calibración de displays y
  limpieza de filtros de aire.
- **MOP de Reemplazo de Breakers (Disyuntores):** Procedimiento de
  desenergización estricta. Lockout/Tagout (LOTO) obligatorio, prueba
  `Vivo-Muerto-Vivo` y cambio físico de interruptores principales o
  sub-alimentadores.

---

## 2. MOPs para RPP (Remote Power Panel)

El RPP distribuye la energía final en la sala blanca hacia las
regletas (rPDUs) de los racks.

- **MOP de Balanceo de Carga:** Procedimiento para identificar,
  calcular y equilibrar las fases eléctricas al instalar nuevos
  circuitos. Asegura que ninguna línea (A, B, C) supere el 80% de su
  capacidad nominal, previniendo disparos térmicos.
- **MOP de Cableado e Instalación de Látigos (Whips):** Protocolo
  para el despliegue de cables de potencia bajo piso falso o en
  bandejas aéreas. Garantiza el respeto de radios de curvatura,
  etiquetado normativo e instalación de conectores (ej. IEC 309,
  NEMA).
- **EOP/MOP de Desconexión de Emergencia (EPO):** Procedimiento de
  respuesta rápida. Define las acciones para el corte súbito de
  energía en el panel ante eventos de humo/fuego y los pasos de
  reinicio (reset) de contactores tras la resolución del incidente.

---

## 3. MOPs para BUSWAY (Track Busway)

Sistema de electroducto (barras conductoras) que reemplaza el
cableado tradicional, permitiendo una topología `plug-and-play` en
los pasillos de datos.

- **MOP de Instalación/Retiro de Tap-off Boxes (Cajas de Derivación):**
  Operación de alto riesgo. Procedimiento riguroso para enchufar
  (`plug-in`) o retirar cajas en vivo (energizadas). Define el PPE
  específico y la postura corporal para minimizar el riesgo de
  relámpago de arco durante la inserción mecánica. **Trabajo en vivo
  — usa límite de aproximación restringida, NO LOTO.**
- **MOP de Mantenimiento de Juntas y Tapas:** Pasos para
  desenergizar sectores del busway, reapretar uniones mecánicas (con
  pintura de torque), medir resistencia de contacto y limpiar polvo
  acumulado. **De-energizado — LOTO + Vivo-Muerto-Vivo obligatorios.**
- **MOP de Escaneo Termográfico Operativo:** Protocolo de inspección
  no invasiva bajo carga. Busca identificar gradientes térmicos
  inusuales en los puntos de contacto entre el busway y la garra de
  las tap-off boxes.

---

## Estructura Universal Requerida para Generación de MOPs

*(Directiva para el Procedure Architect: todo documento MOP
autogenerado debe validar obligatoriamente esta estructura de 5
puntos antes de darse por completado.)*

1. **Alcance y Objetivo:** definición exacta del equipo, ubicación
   (Site/Data Hall) y propósito de la intervención.
2. **Evaluación de Impacto y Riesgos:** identificación de posibles
   interrupciones en la carga IT, nivel de energía incidente
   (cal/cm²) y dependencias aguas arriba/abajo.
3. **Requisitos Previos (Prerrequisitos):** listado innegociable de
   herramientas aisladas, Categoría de PPE (CSA Z462-24 / NFPA 70E),
   y Permisos de Trabajo (PTW) aprobados.
4. **Lista de Pasos Secuenciales:** instrucciones directas, no
   ambiguas, con casillas de verificación para la firma del técnico
   ejecutante y el supervisor (**Principio de los Cuatro Ojos**,
   alineado con el Maker-Checker witness gate del Sprint 3 Phase 4).
5. **Plan de Reversión (Rollback/Backout Plan):** criterios de
   aborto claros y pasos precisos para deshacer la maniobra y
   devolver el sistema a su estado original, seguro y funcional.

> El audit gate determinístico
> (`audit_procedure_safety` en `backend/agents/procedure_architect.py`)
> enforcea las 5 secciones para todo MOP. Faltante de cualquiera →
> `hard_stop` y la firma queda bloqueada.
