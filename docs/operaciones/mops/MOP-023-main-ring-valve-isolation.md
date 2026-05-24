# MOP-023 — Sistema Completo: Aislamiento por Válvulas de Seccionamiento de Anillos Principales (Double Block and Bleed)

**Asset Category:** Global (chilled water main ring) · **Work Mode:**
De-energizado y aislado en el tramo intervenido; el resto del anillo
permanece operativo (Mantenibilidad Concurrente / Uptime Tier IV).
**Compliance:** CSA Z462-24, NFPA 70E, Uptime Tier IV, ASME B31.9
(Building Services Piping), API 6D (Double Block and Bleed valves).

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** Anillo principal de agua helada + 2 válvulas DBB + purga intermedia
* **Estado Final Esperado:** Tramo intervenido + válvulas DBB reabiertas + T_suministro y dP en CRAHs servidas vueltos a baseline + bypass del anillo restaurado

Intervenir tramos específicos de la tubería matriz de agua helada
utilizando configuraciones de **doble bloqueo y purga** (`Double
Block and Bleed` — DBB) para garantizar la **Mantenibilidad
Concurrente** de la instalación sin interrumpir el flujo de agua
helada hacia las CRAHs activas.

**Equipo objetivo:** tramo específico del anillo principal de agua
helada + dos válvulas DBB que lo aíslan + purga intermedia.
**Ubicación:** Planta Mecánica.

---

## 2. Evaluación de Impacto y Riesgos Térmicos


- **Vector Mecánico/Térmico (Tiempo de Inercia ~8 min para CRAHs sin bypass; presión hidrotérmica en bridas)**

- **Impacto en carga IT:** el flujo a las CRAHs servidas por el
  anillo se redirige por el tramo redundante (sitio en N degradado
  durante la intervención); las CRAHs aguas abajo del tramo
  aislado dependen del bypass / by-pass del anillo.
- **Tiempo de Tolerancia Térmica:** ≈ 8 min antes de breach
  ASHRAE A2 si las CRAHs alimentadas dependen exclusivamente del
  tramo aislado y no hay bypass; con bypass del anillo, el margen
  es indefinido (la Mantenibilidad Concurrente es el punto del
  diseño).
- **Riesgo crítico de DBB:** si la purga intermedia falla, agua
  presurizada puede atravesar una de las dos válvulas y exponer al
  personal durante la apertura de bridas → quemaduras
  hidrotérmicas + proyección de fluido caliente.
- **Nivel de energía incidente:** Arc Flash Categoría 3 si se
  interviene motor de bombas asociadas; Cat 2 para válvulas
  motorizadas estándar.

---

## 3. Parámetros Físicos de Referencia (Prerrequisitos)

- **Topología DBB validada:** dos válvulas en serie con purga
  intermedia, ambas con capacidad de bloqueo mecánico (LOTO).
- **Caudal mínimo en el bypass del anillo:** GPM ≥ 100% del
  caudal nominal de las CRAHs servidas (la rama redundante debe
  soportar la carga completa).
- **`dP` aceptable** en el bypass durante la maniobra (degradación
  ≤ 20% baseline).
- **`T_suministro` baseline** en las CRAHs servidas; criterio de
  aborto: `T_suministro > setpoint + 2 °C`.
- **Mechanical LOTO** en AMBAS válvulas DBB + en la válvula de
  purga + alivio de presión interna del tramo + drenaje a
  contenedor antes de abrir cualquier brida.
- **Motor LOTO eléctrico** en bombas asociadas si se intervienen
  + **Vivo-Muerto-Vivo** en bornes del motor disconnect; **CSA
  Z462-24**, **PPE Cat 3**.
- **EPP físico:** guantes anti-térmicos + traje impermeable + cara
  cubierta + zapatos anti-deslizantes (riesgo de derrame).
- **Herramientas:** torquímetro, manómetros, bandeja de drenaje
  con contenedor de neutralización, llaves para bridas, candados +
  tarjetas LOTO mecánicos y eléctricos.
- **PTW** firmado por el Manager on Duty.
- Personal: técnico mecánico calificado en DBB + supervisor (Maker
  + Checker — **Cuatro Ojos**).

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + verificar bypass del anillo activo +
   capacidad de la rama redundante + `T_suministro` baseline en
   CRAHs servidas.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > `[HOLD POINT]` Confirmar bypass del anillo activo + capacidad de la rama redundante antes de cerrar la primera válvula DBB.

2. Cerrar la **primera válvula DBB** (lado upstream) +
   monitorear el redireccionamiento de flujo en el bypass.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Cerrar la **segunda válvula DBB** (lado downstream); el tramo
   queda aislado entre ambas válvulas.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Abrir la **válvula de purga intermedia** (entre las dos DBB) a
   contenedor + drenar el tramo + monitorear que el flujo de
   drenaje se DETIENE (confirmación de que ambas DBB sellan bien).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Aplicar **Mechanical LOTO** en AMBAS válvulas DBB (candado +
   tarjeta en cada una) + en la válvula de purga (en posición
   abierta a contenedor).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Si la intervención involucra bombas eléctricas: apagar + aplicar
   **Motor LOTO eléctrico** + **Vivo-Muerto-Vivo** en bornes del
   motor disconnect.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Verificar **alivio total de presión** del tramo aislado con
   manómetro antes de aflojar cualquier brida (debe ser 0 bar
   relativo).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Ejecutar la intervención (reemplazo de válvula, segmento de
   tubería, sensor, etc.) con **EPP físico completo** + bandeja de
   drenaje bajo el punto de trabajo.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Llenar tramo + presurizar a baseline + retirar **LOTO** de purga
   (cerrarla) + retirar **LOTO** de las DBB + abrir ambas válvulas
   lentamente + verificar `T_suministro` y `dP` vuelven a baseline
   en CRAHs servidas.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (disparadores térmicos automáticos):**

- Si **`T_suministro` en las CRAHs servidas supera setpoint +
  2 °C** por más de 60 s → abrir bypass de emergencia O re-abrir
  válvulas DBB para restaurar flujo directo.
- Si en el paso 4 la **purga intermedia NO detiene su flujo** (una
  de las válvulas DBB no sella bien) → **NO continuar la
  intervención**; restaurar flujo + reprogramar con válvulas
  reemplazadas.
- Si durante el paso 8 se detecta fuga en bridas removidas más
  allá del expected → re-presurizar el tramo + diagnosticar antes
  de continuar.
- Si **derrame químico significativo** (glicol en sistemas con
  anti-congelante): activar protocolo HAZMAT.

**Secuencia de Reversión (R1 — restauración del tramo):**

1. Detener intervención + cerrar accesos.
2. Llenar tramo aislado desde la válvula de make-up; verificar
   ausencia de aire.
3. Cerrar válvula de purga + retirar **Mechanical LOTO** de
   purga.
4. Si hubo Motor LOTO: retirar + **Vivo-Muerto-Vivo** + restaurar
   bombas.
5. Retirar **Mechanical LOTO** de las DBB + abrir ambas válvulas
   lentamente (upstream primero, downstream segundo) para evitar
   golpe de ariete.
6. Verificar `T_suministro` + `dP` vuelven a baseline.
7. Documentar el aborto + análisis de causa raíz + reprogramar la
   intervención cuando las condiciones lo permitan.

**Ventana de reversión bounded by:** el Tiempo de Tolerancia
Térmica de las CRAHs servidas exclusivamente por el tramo aislado
(≈ 8 min). Si el bypass del anillo está sano, la ventana es
indefinida — la **Mantenibilidad Concurrente** de Uptime Tier IV
es exactamente este caso de uso.
