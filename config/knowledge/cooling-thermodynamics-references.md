---
id: cooling-thermodynamics-references
title: Cooling & Thermodynamics Operational References (Tier IV)
source: Operator catalog 2026-05-23 (ASHRAE TC 9.9 + Uptime + OCP + CTI compendium)
source_type: operational_standard
applies_to:
  - chiller
  - crah
  - cooling_tower
  - cdu
  - dlc_secondary_loop
  - pump
  - valve
  - heat_exchanger
  - free_cooling
tags: [cooling, ashrae, tc-9.9, uptime, ocp, cti-atc-105, lsi, coc, affinity-laws, lift, free-cooling, legionella, psychrometric, ist]
jurisdiction: international
version: "2026.1"
voltage_class: "ALL"
---

# Manual de Ingeniería Inversa y Operaciones para Infraestructura de Enfriamiento en Centros de Datos (Tier IV / Mission Critical)

**Status:** Operational reference — indexed by GraphRAG. Surfaced to the
Procedure Architect when authoring SOP / MOP / EOP / EMP for mechanical
cooling assets (chillers, CRAHs, cooling towers, CDUs, free-cooling).

**Driver:** Operator directive 2026-05-23 — fundamentos científicos,
matemáticos y operacionales para Métodos de Procedimiento (MOPs) en la
planta de agua helada e infraestructura de enfriamiento, bajo la
directiva estricta de **cero incidentes**.

**Companion files:** the 9 mechanical + 2 global canonical MOP bodies
live under `docs/operaciones/mops/MOP-013-...` through `MOP-023-...`
(library pre-seed picks them up at boot).

---

## 1. Catálogo de White Papers y Estándares de Referencia

Para asegurar el cumplimiento normativo global y justificar los umbrales
de control lógico en el DC-EPMS, todo procedimiento operativo generado
debe referenciar y validar los siguientes estándares:

- **ASHRAE TC 9.9 (Equipment Thermal Guidelines for Data Processing
  Environments — 5th Ed.):** define las envolventes psicrométricas
  operativas y recomendadas para el aire de entrada a los servidores
  (Clases A1 a A4). Regula los límites de humedad relativa (40% – 55%)
  y temperatura de bulbo seco para evitar fallas por choque térmico o
  corrosión por alta humedad.
- **Uptime Institute (Tier Standard: Operational Sustainability):**
  establece los criterios de resiliencia y el concepto de
  *Mantenibilidad Concurrente*. Justifica la obligatoriedad de contar
  con topologías redundantes activas en válvulas, tuberías y lazos de
  control para realizar aislamientos sin detener la operación de TI.
- **OCP (Open Compute Project — Cooling Environments):** metodologías
  de prueba para la interfaz entre las facilidades de la instalación
  (`FWS` — Facility Water System) y los bucles secundarios /
  refrigeración directa a chip (`TCS` — Technology Cooling System);
  norma la temperatura de aproximación (`ATD` — Approach Temperature
  Difference) y las curvas de impedancia de flujo (`PQ`).
- **CTI ATC-105 (Cooling Technology Institute):** código estándar para
  la evaluación y pruebas de rendimiento térmico de torres de
  enfriamiento de tiro forzado e inducido, así como la gestión estricta
  de la calidad microbiológica del agua (Legionella).

---

## 2. Fundamentos Físicos, Matemáticos y Químicos (Ingeniería Inversa)

Las acciones operativas dentro de un MOP no deben basarse en empirismo,
sino en el comportamiento termodinámico real del sistema. Las
siguientes ecuaciones rigen la lógica de control y los criterios de
seguridad:

### A. Chillers (Ciclos de Compresión de Vapor y Transitorios Eléctricos)

- **Balance Térmico del Condensador.** El calor total rechazado por el
  condensador hacia las torres (`Q_rej`) es la suma de la carga
  térmica del centro de datos (`Q_load`) más el trabajo mecánico de
  compresión (`W_comp`):

  ```
  Q_rej = Q_load + W_comp
  ```

- **Coeficiente de Rendimiento (COP).** La eficiencia de la enfriadora
  está dictada por:

  ```
  COP = Q_evap / W_in
  ```

- **El Efecto "Lift" en Transitorios Eléctricos.** Durante una
  transferencia a generadores (`ride-through`), si el flujo del
  condensador disminuye, la temperatura y la presión de condensación
  aumentan súbitamente. Esto eleva la relación de presiones (`Lift`).
  El MOP de secuenciación debe prever que un `Lift` elevado
  incrementa drásticamente el trabajo del compresor (`W_in`), lo que
  puede causar un disparo por sobre-corriente en los interruptores
  principales del Chiller antes de que se estabilice el sistema.

### B. CRAHs (Psicrometría y Leyes de Afinidad)

- **Remoción de Calor Sensible.** Los centros de datos operan
  principalmente eliminando carga sensible. El caudal de aire
  necesario está gobernado por:

  ```
  Q_s = m_dot * Cp * dT = rho * V_dot * Cp * (T_retorno - T_suministro)
  ```

  Donde `rho` es la densidad del aire, `V_dot` es el caudal
  volumétrico y `Cp` el calor específico. Si un MOP de reemplazo de
  filtros restringe el caudal (`V_dot`), el `dT` del aire se
  disparará de inmediato, empujando la temperatura de los servidores
  fuera de la envolvente ASHRAE.

- **Leyes de Afinidad de Ventiladores.** Justifica la calibración de
  los variadores de frecuencia (VFD). La potencia consumida (`P`)
  escala al cubo de la velocidad de rotación (`N`):

  ```
  P1 / P2 = (N1 / N2)^3
  ```

  Reducir un 10% la velocidad mediante el ajuste fino del `Fan Wall`
  disminuye casi un 27% el consumo energético del motor, manteniendo
  estable la presión estática del piso falso.

### C. Torres de Enfriamiento (Transferencia de Masa y Control Químico)

- **Calor Latente de Vaporización.** Las torres disipan calor
  evaporando una fracción del flujo de agua circulante. Este proceso
  absorbe aproximadamente **2260 kJ por cada kilogramo de agua
  evaporada**.

- **Índice de Saturación de Langelier (LSI).** Determina el
  comportamiento del agua (corrosiva o incrustante) mediante el
  balance de pH, temperatura, dureza cálcica y alcalinidad:

  ```
  LSI = pH - pH_s
  ```

  - `LSI < 0` → agua corrosiva (destruye tuberías y empaques).
  - `LSI > 0` → agua incrustante (crea capas de carbonato de calcio
    que aíslan térmicamente los tubos del condensador del Chiller).
  - **Objetivo del MOP químico:** mantener el agua en un rango seguro
    de **0.2 a 0.5**.

- **Ciclos de Concentración (CoC).** Regula el agua de purga
  (`blowdown`) para evitar la saturación de minerales:

  ```
  CoC = Conductividad_agua_de_la_torre / Conductividad_agua_de_reposicion
  ```

---

## 3. Estructura Universal Obligatoria del MOP Mecánico

Todo MOP autogenerado por el sistema (incluidos los mecánicos) debe
estructurarse estrictamente bajo las siguientes 5 secciones dedicadas,
incorporando puntos de validación obligatorios:

1. **Alcance y Objetivo.** Identificación inequívoca del equipo (Tag),
   ubicación física exacta (Data Hall / Planta Mecánica) y la
   justificación técnica de la maniobra.
2. **Evaluación de Impacto y Riesgos Térmicos.** Análisis de la
   inercia térmica del bucle de agua helada. Debe calcular
   explícitamente el **"Tiempo de Tolerancia Térmica"** (cuántos
   minutos tardará la sala IT en alcanzar el límite crítico de
   ASHRAE TC 9.9 si el flujo de agua helada se detiene por completo).
3. **Parámetros Físicos de Referencia.** Especificación innegociable
   de caudales mínimos (GPM / LPM), presiones diferenciales de
   operación (`dP`), temperaturas de aproximación (`ATD`) y límites
   químicos del LSI permitidos durante la maniobra.
4. **Lista de Pasos Secuenciales con Doble Validación (Cuatro Ojos).**
   Pasos de ejecución directa, libres de ambigüedad. Incluye bloqueo
   y etiquetado físico de válvulas (**LOTO mecánico**), alivio de
   presión interna previo a la apertura de bridas, y casillas
   explícitas de firma para el técnico ejecutor y el supervisor
   (`Maker-Checker`).
5. **Plan de Reversión (Rollback / Back-out Plan) y Criterios de
   Aborto.** Secuencia detallada para devolver el sistema a una
   condición operativa segura si la maniobra falla. Debe incluir
   disparadores térmicos automáticos (ej. *"Si la temperatura del
   agua de suministro supera los 12 °C por más de 45 segundos,
   abortar procedimiento inmediatamente y ejecutar el paso de
   reversión R1"*).

> El audit gate determinístico
> (`audit_procedure_safety` en `backend/agents/procedure_architect.py`)
> enforcea estas 5 secciones para todo MOP — eléctrico O mecánico.
> Los MOPs mecánicos satisfacen la regla de **CSA Z462-24 + LOTO +
> PPE** porque la mayoría de las maniobras involucran motor
> disconnects (compresores de Chiller, ventiladores CRAH, bombas);
> el LOTO eléctrico del motor coexiste con el LOTO mecánico de
> válvulas. La regla de **Vivo-Muerto-Vivo** se aplica al motor
> disconnect cuando el equipo se desenergiza.

---

## 4. Matriz de 9 MOPs Mecánicos por Componente Crítico

### A. Área de Chillers (Enfriadoras)

- **MOP-013-chiller-staging-rotation** — Cambio de operación y
  rotación secuencial (Staging). Arranque de Chiller secundario
  (Standby) + bombas asociadas con ecualización previa de presiones
  para prevenir golpes de ariete.
- **MOP-014-chiller-trip-response** — Respuesta y aislamiento por
  disparo térmico (Chiller Trip). Secuencia de conmutación
  automatizada / manual a bypass + enfriadora de respaldo.
- **MOP-015-chiller-ride-through-recovery** — Recuperación eléctrica
  en generador. Reinicio escalonado de compresores tras transición a
  energía de respaldo, limitando rampa de carga.

### B. Área de CRAHs (Manejadoras de Aire)

- **MOP-016-crah-hot-swappable-filters** — Reemplazo de filtros en
  caliente sin apagar ventiladores; monitoreo de `dP` para preservar
  presión estática del piso falso.
- **MOP-017-crah-vfd-valve-calibration** — Calibración dinámica de
  VFDs + válvulas modulantes (2 o 3 vías) en concordancia con las
  RPM de ventiladores.
- **MOP-018-crah-psychrometric-control** — Control psicrométrico +
  mitigación de condensación; mantener serpentín por encima del
  punto de rocío del Data Hall.

### C. Área de Torres de Enfriamiento

- **MOP-019-tower-chemical-dosing** — Dosificación química dinámica +
  control de Legionella; biocidas (oxidantes / no oxidantes) +
  anti-incrustantes basados en LSI + CoC en tiempo real.
- **MOP-020-tower-pan-cleaning** — Mantenimiento + limpieza de
  piletas + rociadores en vivo; aislamiento hidráulico de una celda
  manteniendo el resto operativas.
- **MOP-021-tower-free-cooling-transition** — Transición operativa a
  modo Free Cooling (economizador del lado del agua); apagado de
  compresores + redirección a intercambiador de placas cuando el
  bulbo húmedo exterior lo permite.

---

## 5. MOPs Globales del Sistema Completo

- **MOP-022-ist-full-load-test** — Pruebas de Sistemas Integrados a
  Plena Carga (`IST` — Integrated System Testing). Simula la pérdida
  catastrófica de la acometida principal con el DC operando al 100%
  de carga térmica simulada (bancos de carga). Valida respuesta
  coordinada Chillers + generadores + bombas + envolvente ASHRAE en
  pasillos fríos.
- **MOP-023-main-ring-valve-isolation** — Aislamiento por válvulas
  de seccionamiento de anillos principales. Intervención de tramos
  específicos de la tubería matriz de agua helada usando
  configuraciones de doble bloqueo y purga
  (`Double Block and Bleed`) para garantizar la *Mantenibilidad
  Concurrente* (Uptime Tier IV).

---

## Cross-references for the Procedure Architect

When generating cooling-related procedures, the Architect should
surface the relevant section verbatim:

| Doc type | Touchpoint in this knowledge base |
|---|---|
| **SOP** | §1 standards (ASHRAE A1-A4 envelopes), §2.B affinity laws (VFD baseline) |
| **MOP — Chiller** | §2.A (COP, Lift, ride-through), §3.2 thermal tolerance time, §4.A canonical bodies |
| **MOP — CRAH** | §2.B (psicrometry, affinity), §3.3 physical reference params, §4.B canonical bodies |
| **MOP — Tower** | §2.C (LSI, CoC, latent heat), §3.3 chemical limits, §4.C canonical bodies |
| **EOP / EMP** | §2.A Lift + transient (ride-through failure), §5 global IST + ring isolation |

The MOP audit gate (universal 5 sections + LOTO + PPE + CSA Z462-24 +
voltage verification + back-out) applies to mechanical MOPs identically
to electrical MOPs — the bodies in `docs/operaciones/mops/` include
electrical disconnect language for compressor / fan / pump motors so
the contract is satisfied.
