---
id: electrical-mop-catalog
title: Electrical Infrastructure MOP Catalog (UPS, Transformers, Utility)
source: Operator-supplied catalog 2026-05-23
source_type: operational_standard
applies_to:
  - ups
  - transformer
  - switchgear
  - ats
  - busway
  - generator
  - utility_intake
  - mv_rectifier
tags: [mop, electrical, infrastructure, loto, csa-z462, arc-flash, bypass, dga, inrush, epo, transfer, sscb]
jurisdiction: international
version: "2026.1"
voltage_class: "ALL"
---

# Catálogo Base para Desarrollo de MOPs: Infraestructura Eléctrica Crítica

**Status:** Operational knowledge — indexed by GraphRAG and surfaced
to the Procedure Architect when authoring MOPs for upstream electrical
infrastructure (UPS, transformers, utility intake / switchgear / ATS).
Mirrors the format of the other `config/knowledge/*.md` documents
(CSA Z462-24, OCP LVDC).

**Companion files:** the 3 fully-canonical bodies for the most-common
MOPs live under [`docs/operaciones/mops/`](../../docs/operaciones/mops/)
(`MOP-001` UPS bypass transfer, `MOP-002` transformer dry inspection,
`MOP-003` ATS commutation test). The Architect library pre-seeds them
on boot.

---

## 1. MOPs para UPS (Uninterruptible Power Supply)

Los UPS son el corazón del respaldo eléctrico a corto plazo. Estos
procedimientos garantizan la transición segura y el aislamiento físico
y lógico del equipo.

- **MOP de Transferencia a Bypass de Mantenimiento:** Procedimiento
  detallado (`make-before-break`) para pasar la carga del inversor al
  bypass estático y luego al bypass mecánico externo sin interrumpir
  los servidores. Incluye verificación de sincronización de fase.
  **Cuerpo canónico:** `docs/operaciones/mops/MOP-001-ups-bypass-transfer.md`.
- **MOP de Mantenimiento y Reemplazo de Baterías:** Secuencia para la
  apertura de interruptores de banco de baterías, medición de voltaje
  de flotación, pruebas de impedancia y reemplazo de celdas (VRLA o
  Litio). Requiere PPE contra riesgo químico y eléctrico.
- **MOP de Prueba de Sincronización con Generador:** Procedimiento
  controlado para simular un corte de red (Utility), observar la
  transferencia al generador y verificar que el rectificador del UPS
  limite la corriente de recarga (`walk-in`) para no sobrecargar el
  alternador.
- **EOP/MOP de Activación de EPO (Emergency Power Off):** Protocolo
  de emergencia pura. Define las condiciones exclusivas (fuego
  irrefrenable, riesgo de muerte inminente) bajo las cuales se
  acciona el EPO, y los pasos para el restablecimiento físico y
  lógico posterior al disparo.

---

## 2. MOPs para Transformadores

Equipos encargados de reducir la media tensión a niveles de
distribución utilizables (ej. 480V/208V). Los procedimientos se
centran en el aislamiento térmico, dieléctrico y la gestión de
transitorios.

- **MOP de Energización (Gestión de Inrush Current):** Pasos paso a
  paso para energizar el transformador de manera segura tras un
  mantenimiento. Incluye la verificación de los ajustes de disparo
  en los interruptores aguas arriba para evitar que la corriente de
  magnetización (`inrush`) dispare la alimentación principal.
- **MOP de Inspección Termográfica y Limpieza:** Para transformadores
  de tipo seco. Incluye remoción de paneles bajo esquema LOTO,
  medición de puntos calientes en conexiones y limpieza de devanados
  con aspiradoras y paños antiestáticos (**cero uso de aire
  comprimido no filtrado**). **Cuerpo canónico:**
  `docs/operaciones/mops/MOP-002-transformer-dry-inspection.md`.
- **MOP de Ajuste de Taps (Tap Changes):** Instrucciones estrictas
  para desenergizar, aplicar LOTO, verificar ausencia de tensión
  (`Vivo-Muerto-Vivo`) y ajustar las derivaciones (taps) mecánicas
  para corregir el voltaje secundario.
- **MOP de Mantenimiento de Líquidos Dieléctricos:** Para
  transformadores inmersos en aceite. Abarca la toma segura de
  muestras para análisis de gases disueltos (DGA), rigidez
  dieléctrica, y el proceso de filtrado/desgasificado mediante
  equipos externos.

---

## 3. MOPs para Utility (Red Eléctrica y Acometida Principal)

Involucran el punto de mayor energía incidente en la instalación
(MV/LV Switchgear). Requieren la máxima disciplina operativa y
rigurosidad en los bloqueos.

- **MOP de Operación y Pruebas de ATS (Conmutación):** Secuencia de
  transferencia manual y automática de la carga desde la red
  comercial hacia la planta de emergencia, verificando el
  enclavamiento mecánico y eléctrico. **Cuerpo canónico:**
  `docs/operaciones/mops/MOP-003-ats-commutation-test.md`.
- **MOP de Mantenimiento Integral de Tableros Principales
  (Switchgear):** Protocolo avanzado de bloqueo y etiquetado (LOTO).
  Define el PPE específico contra Arc Flash, la apertura y extracción
  de interruptores (`racking out`), torqueo de barras colectoras
  (`busbars`) y pruebas de resistencia de aislamiento (Megger).
- **MOP de Restauración de Servicio de Red:** Procedimiento para
  transferir la carga de vuelta a la red comercial de forma segura
  tras un corte. Establece los tiempos de espera para confirmar la
  estabilidad de la red y el proceso de transición (abierta o
  cerrada).
- **MOP de Respuesta a Anomalías de Red (Contingencia):** Protocolo
  de actuación frente a eventos de degradación de energía sostenida
  (`sags` severos, armónicos o fluctuaciones de frecuencia) que
  obligan a aislar la instalación de la red pública preventivamente.

---

## Sección Requerida en Todo MOP

Para que cualquiera de los procedimientos anteriores sea válido para
su ejecución, el documento individual deberá contener obligatoriamente:

- Control de Versiones y Cuadro de Aprobaciones.
- Evaluación de Riesgos y PPE (definiendo categoría y límites de
  aproximación).
- Lista estricta de herramientas y repuestos.
- Plan de Reversión (`Back-out Plan`) con criterios de aborto de
  tarea.

> El audit gate determinístico
> (`audit_procedure_safety` en `backend/agents/procedure_architect.py`)
> enforcea estas secciones; un MOP que omita cualquiera retorna
> `hard_stop` y la firma queda bloqueada (S-DET-02: Safety Officer
> es el único vetoer).
