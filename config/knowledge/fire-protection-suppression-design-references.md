---
id: fire-protection-suppression-design-references
title: Fire Protection + Suppression — Design Specifications & Normative Matrix
source: Operator-supplied whitepaper 2026-05-24 (Especificaciones de Protección y Seguridad contra Incendios - OS Datacenter Confederado)
source_type: design_specification
applies_to:
  - ess
  - battery_lithium_ion
  - ups
  - sprinkler_pre_action
  - sprinkler_wet
  - water_mist
  - clean_agent_suppression
  - novec
  - fm200
  - sapphire_fk_5_1_12
  - inert_gas_suppression
  - dlp_cabinet_protection
  - vesda
  - asd_aspirating_smoke
  - hydrogen_monitor
  - battery_room
tags: [fire-protection, suppression-design, nfpa-855, nfpa-13, nfpa-72, nfpa-75, nfpa-750, nfpa-2001, fm-ds-5-33, fm-hc-2, en-12845, en-14972, en-15004, en-50600, en-54, iso-6182, iso-7240, iso-14520, ess-thermal-runaway, pre-action, water-mist, clean-agent, hypoxic-air-rejected, aerosol-rejected, asd, triple-detection, hydrogen-monitoring, dlp, normative-correspondence]
jurisdiction: international
version: "2026.1"
voltage_class: "ALL"
---

# Especificaciones de Protección y Seguridad contra Incendios — Módulo de Infraestructura Crítica

**Status:** Design reference document — indexed by GraphRAG and
surfaced to the Procedure Architect when authoring procedures or
when the operator queries fire-protection design parameters.
Complements the operational
[`life-safety-combustible-references.md`](./life-safety-combustible-references.md)
which focuses on MOPs for VESDA / Clean Agent cylinders / Day Tanks /
Generator extended runtime.

**This document captures the DESIGN-side specifications**: discharge
densities (gpm/ft², mm/min), sprinkler K-factors, NFPA/FM/ISO/EN
correspondence matrix, technology selection rationale (water mist vs
clean agent vs inert gas), and explicit rejection criteria for
unsuitable approaches (hypoxic air, aerosols in occupied spaces).

**Driver:** Operator-supplied whitepaper 2026-05-24 ("OS Datacenter
Confederado") — extending the v0.17.0 Life Safety + Combustible
expansion with design-level reference for sprinkler / water mist /
clean agent / ESS suppression system selection + sizing.

---

## 1. Protección de Sistemas de Almacenamiento de Energía (ESS) y Baterías de Iones de Litio

La proliferación de baterías de iones de litio, utilizadas
frecuentemente en sistemas UPS, requiere protocolos rigurosos debido
al riesgo de **desbordamiento térmico (thermal runaway)** causado por
cortocircuitos internos.

### Comportamiento del Fuego y Detección

- El desbordamiento térmico genera una **reacción en cadena que
  propaga el calor entre celdas**, emitiendo vapores altamente
  tóxicos y combustibles.
- **Actualmente no existe tecnología de extinción capaz de detener
  el desbordamiento térmico una vez iniciado** — esto es un hecho
  load-bearing para la doctrina de diseño.
- El objetivo del sistema contra incendios es **evitar la
  propagación** hacia otras baterías o infraestructuras.
- La **detección temprana de los gases emitidos (off-gases)** en las
  fases iniciales de falla es el método más efectivo para una
  intervención preventiva.

### Parámetros de Diseño de Rociadores (FM Global & NFPA)

- **FM Global (FM DS 5-33):** exige que el diseño hidráulico cubra
  el **área total de la sala** (eliminando el límite anterior de
  **2,500 ft²**). La densidad mínima de descarga debe ser de
  **0.3 gpm/ft²** (**12 mm/min**).
- **NFPA 855 (edición 2026):** para unidades ESS de hasta **50 kWh**,
  se requiere una densidad de **0.3 gpm/ft²** sobre el área de la
  sala o un área de diseño de **2,500 ft²**, lo que sea menor.
- **Hardware requerido:** rociadores de respuesta rápida
  (`quick-response`), clasificación de temperatura nominal de
  **165 °F** (**74 °C**) y factor K de **5.6 gpm/psi^(1/2)** o
  superior.
- **Eficiencia operativa:** el uso de rociadores de cobertura
  extendida (EC-11, EC-14, EC-25) puede reducir la cantidad de
  rociadores requeridos entre **50% y 72%**, optimizando los costos
  de instalación.
- **Restricciones:** **NO se recomienda el uso de sistemas secos
  (dry systems) para proteger ESS de iones de litio**, ya que el
  retardo en la entrega de agua aumenta el riesgo durante la
  ventana crítica del thermal runaway.

---

## 2. Tecnologías de Supresión para Salas de Servidores (Data Halls)

La elección de la tecnología dependerá del análisis de riesgo,
considerando: **densidad de potencia**, **tiempo de inactividad
tolerable**, y **daño colateral a los servidores**.

### A. Sistemas de Rociadores (Sprinklers)

- **Configuración:** generalmente sistemas **pre-action**, donde
  las tuberías permanecen secas hasta que un sistema de detección
  primario se activa, mitigando daños por descargas accidentales.
- **Clasificación de riesgo:**
  - Según **EN 12845**: un centro de datos requiere un mínimo
    de **Ordinary Hazard 3 (OH 3)**.
  - **FM Global** es más estricto, clasificándolo como
    **Hazard Classification 2 (HC-2)**.
- **Limitaciones:** los rociadores controlan el fuego **a nivel de
  la estructura pero NO penetran los gabinetes**, y el agua genera
  daños colaterales significativos en el hardware.

### B. Sistemas de Agua Nebulizada (Water Mist)

- **Eficiencia:** operan a baja o alta presión, utilizando **gotas
  muy finas** que absorben el calor rápidamente y desplazan el
  oxígeno mediante la generación de vapor.
- **Ventajas:** requieren mucha menos agua que los rociadores
  tradicionales, lo que reduce el tamaño de las tuberías, las
  bombas y los daños colaterales.
- **Aplicación específica:** son la **única alternativa práctica al
  dióxido de carbono** para la protección localizada de
  **generadores diésel**.

### C. Sistemas de Extinción por Gas (Gaseous Agents)

- **Mecanismo:** diseñados para extinguir completamente el fuego en
  sus fases iniciales (activados por detección de humo), sin dejar
  residuos (**clean agents**).
- **Agentes Halocarbonados:**
  - **FK-5-1-12 (SAPPHIRE / Novec 1230)** — extingue por
    enfriamiento químico.
  - Debido a normativas ambientales (**Regulación F Gas de la UE**),
    los **HFCs están restringidos** (incluido FM-200 / HFC-227ea).
  - El **FK-5-1-12 tiene un potencial de calentamiento global (GWP)
    insignificante y está exento** — preferido en deployments
    nuevos.
- **Gases inertes:** reducen el oxígeno a **menos del 15%**. Los
  sistemas modernos de **flujo regulado a 300 bar** permiten
  tuberías de menor grado y reducen los requisitos de alivio de
  presión.
- **Aislamiento acústico (CRÍTICO):** las unidades de disco duro
  (HDD) modernas son **extremadamente sensibles al ruido de la
  descarga de gas**. Es imperativo implementar **boquillas
  acústicas** para mitigar el impacto sonoro y prevenir la pérdida
  de datos. Operadores que ignoran esta especificación enfrentan
  daño de HDD masivo en cada test de descarga.
- **Dinámica de flujo de aire:** estudios demuestran que **los
  altos flujos de aire en los centros de datos modernos
  (pasillos fríos/calientes) NO impiden la mezcla homogénea del gas
  extintor**, e incluso pueden mejorarla si el aire se recircula —
  refutación del mito de que "el cold-aisle containment necesita ser
  pausado durante la descarga".

### D. Protección Localizada de Gabinetes

- Los sistemas de **baja presión directa (DLP)**, que utilizan un
  **tubo sensor/descargador directamente dentro del rack**, son
  complementos altamente efectivos para fuegos originados en el
  hardware, siempre que se controle la fuga de aire en el gabinete.

### E. Sistemas DESCARTADOS para el OS Datacenter Confederado

- **Reducción de Oxígeno (Hypoxic Air):** mantienen el oxígeno por
  debajo del 15% constantemente. **DESCARTADOS** por:
  - Altos costos operativos continuos de los compresores.
  - Inviabilidad ante las fugas de aire inherentes a la
    presurización de los centros de datos.
- **Aerosoles:** muy eficientes pero generan **residuos
  particulados** que requieren una limpieza exhaustiva y están
  **prohibidos en espacios ocupados por personal debido a la
  toxicidad** de los residuos durante / post-descarga.

---

## 3. Matriz de Telemetría y Detección Temprana (ASD)

La miniaturización y densidad térmica exigen sensores
ultra-sensibles integrados al bus de telemetría del datacenter.

- **Detección de Humo Aspirado (ASD):** esencial para entornos con
  altas tasas de refrigeración mecánica. Estos sistemas toman
  muestras activas de aire a través de redes de tuberías y las
  analizan centralmente, superando los desafíos del flujo de aire
  (cf. VESDA en MOP-024).
- **Tecnología de Triple Detección:** los sensores que combinan
  **óptica de humo + calor + monóxido de carbono (CO)** proporcionan
  **inmunidad contra falsas alarmas** y detección temprana robusta
  al procesar algoritmos cruzados. Recomendado para zonas con
  histórico de false-positive (ej. salas con polvo elevado por
  obras de construcción adyacentes).
- **Monitoreo de Gas Hidrógeno:** **OBLIGATORIO en salas de
  baterías** para prevenir atmósferas explosivas generadas por la
  gasificación natural de las celdas de respaldo. Umbral de alarma
  típico: 1% del LEL (Lower Explosive Limit = 4% v/v en aire).

---

## 4. Tabla de Correspondencia Normativa Global

Para el despliegue del OS Datacenter Confederado a nivel
internacional, los módulos lógicos deben cumplir con los siguientes
marcos normativos:

| Subsistema / Dominio | Estándar Internacional (ISO) | Estándar Europeo (EN) | Norteamérica (NFPA) |
|---|---|---|---|
| **Diseño General de Datacenter** | N/A | EN 50600-2-5 | NFPA 75 |
| **Sistemas de Rociadores** | ISO 6182 (Componentes) | EN 12845 | NFPA 13 |
| **Sistemas de Agua Nebulizada** | N/A | EN 14972 | NFPA 750 |
| **Sistemas Extintores por Gas** | ISO 14520-1 | EN 15004-1 | NFPA 2001 |
| **Sistemas de Detección** | ISO 7240-1 | EN 54 | NFPA 72 |
| **ESS / Lithium-Ion (ediciones recientes)** | (en revisión) | (en revisión) | **NFPA 855** |
| **FM Global Property Loss Prevention** | (privativo FM) | — | **FM DS 5-33** |

> **Nota operativa:** la matriz anterior es referencia jurisdiccional;
> para A3-Alpha Toronto site, la combinación operativa real es
> **NFPA + FM Global** (jurisdicción Ontario / Canada acepta ambas
> como AHJ-approvable). EN se aplica cuando expandimos a deployments
> EU (parte del long-term confederation roadmap).

---

## 5. Cross-references para el Procedure Architect

Cuando el operador autorea procedures que tocan fire protection
design (no operación), el Architect debe surface las secciones
relevantes:

| Doc type | Touchpoint en este knowledge base |
|---|---|
| **Design review / specification** | §1 ESS thermal runaway + §2 technology comparison + §4 normative matrix |
| **EOP — ESS battery fire** | §1 prevent-propagation doctrine + §3 hydrogen monitoring |
| **SOP — Sprinkler test / pre-action drill** | §2.A pre-action configuration + EN 12845 OH 3 / FM HC-2 |
| **MOP — Water mist test on generator room** | §2.B (única alternativa práctica al CO2) |
| **MOP — Clean agent acoustic-nozzle inspection** | §2.C HDD acoustic sensitivity |
| **MOP — DLP cabinet test** | §2.D DLP + air-leak control |
| **Decision artifact — supresion selection** | §2.E REJECTED technologies (hypoxic air, aerosols) con rationale documentado |

The MOP audit gate (Universal 5 + LOTO/PPE/CSA Z462-24 + voltage
+ back-out + Tag + Estado Final + Vector + MCP + HOLD POINT +
parameterized abort) applies to MOPs generated against this design
reference. Vector clasification for ESS work is **Vector Life
Safety + Vector Eléctrico** (combined: lithium battery is both fire
risk and electrical hazard).
