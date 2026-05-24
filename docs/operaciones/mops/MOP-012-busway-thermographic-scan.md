# MOP-012 — Busway: Escaneo Termográfico Operativo bajo Carga (No Invasivo)

**Asset Category:** Busway · **Work Mode:** LIVE (inspección no
invasiva con busway energizado). **Compliance:** CSA Z462-24,
NFPA 70B (Recommended Practice for Electrical Equipment Maintenance),
ASTM E1934 (IR thermography of electrical systems).

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** Busway sector + tap-off boxes activas
* **Estado Final Esperado:** Escaneo termográfico completo + todos los puntos documentados con ΔT + cualquier hot-spot flagged para WO de seguimiento

Escaneo termográfico operativo del busway bajo carga real para
identificar gradientes térmicos inusuales en puntos de contacto con
las tap-off boxes y en juntas mecánicas. Indicador anticipado de
degradación que NO requiere desenergizar.

**Equipo objetivo:** un sector completo del busway + sus tap-off
boxes activas. **Ubicación:** pasillo del Data Hall / techo del
white space.

---

## 2. Evaluación de Impacto y Riesgos


- **Vector Eléctrico (Arc Flash Cat 3 durante proximidad al busway energizado; inspección no invasiva)**

- **Impacto en carga IT:** ninguno (inspección no invasiva — el
  busway sigue alimentando la carga sin interrupción).
- **Nivel de energía incidente:** Arc Flash Categoría 3 al
  acercarse al busway energizado; toda la inspección se realiza
  DESDE FUERA del límite de aproximación restringida + sólo se
  abren puertos de inspección IR donde el diseño los permite.
- **Dependencias aguas arriba:** ninguna (la inspección no toca el
  upstream).
- **Dependencias aguas abajo:** ninguna directa.
- **Riesgos:** quemaduras térmicas por contacto accidental con la
  carcasa del busway si la superficie excede 60 °C; deslumbre del
  IR camera si se enfoca arc visible.

---

## 3. Requisitos Previos (Prerrequisitos)

- **LOTO NO aplica** (inspección no invasiva); en su lugar:
  - Respetar **límite de aproximación restringida** per
    **CSA Z462-24**
  - **PPE Cat 3** + guantes anti-térmicos para proximidad al busway
- **Herramientas:** cámara termográfica calibrada (emisividad
  configurable; típicamente 0.95 para superficies pintadas), trípode
  (para estabilidad en ángulos difíciles), termómetro IR puntual
  (verificación cruzada), tablet o laptop para anotaciones en sitio.
- Carga del busway al **≥ 70% de la nominal** durante la inspección
  (gradientes anómalos son más detectables bajo carga real;
  inspeccionar en carga baja produce falsos negativos).
- **PTW** firmado por el Manager on Duty.
- Personal: técnico certificado en termografía (Nivel I mínimo per
  ASNT/ISO 18436) + supervisor (Maker + Checker —
  **Cuatro Ojos**).

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Verificar carga del busway en el HMI: debe ser **≥ 70% nominal**;
   si está por debajo, programar la inspección en una ventana de
   mayor carga.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Notificar al NOC el inicio del escaneo + revisar historial de
   alarmas térmicas del busway de los últimos 30 días.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Capturar baseline de temperatura ambiente del pasillo
   (con termómetro IR puntual + cámara termográfica); documentar.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Posicionarse DESDE FUERA del **límite de aproximación
   restringida** con **PPE Cat 3** + guantes anti-térmicos.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > [HOLD POINT] Confirmar carga del busway ≥ 70% nominal antes de iniciar escaneo (carga baja produce falsos negativos).

5. Escanear cada junta mecánica del sector con la cámara
   termográfica; capturar imagen + temperatura puntual de cada junta.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Escanear cada punto de contacto entre busway y garras de las
   tap-off boxes activas; capturar imagen + temperatura.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Calcular gradiente (`ΔT = T_punto - T_ambiente`) para cada
   medición; comparar contra umbral del fabricante (típicamente
   **30 °C sobre vecindario / ambiente** como umbral de atención;
   60 °C como umbral crítico).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Documentar todos los puntos con sus imágenes termográficas + ΔT
   en el WO; flag cualquier gradiente > 30 °C para seguimiento.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (acciones inmediatas):**

- Si se detecta un **hot-spot con ΔT > 30 °C sobre vecindario** en
  un punto de contacto de tap-off box:
  - **REDUCIR LA CARGA** sobre esa tap-off box transfiriendo el
    rack downstream al path redundante
  - Abrir **WO de inspección mecánica** para esa tap-off antes que
    el ΔT escale a categoría crítica
- Si se detecta un **hot-spot con ΔT > 60 °C** en cualquier punto:
  - **EVACUAR PERSONAL DEL ÁREA** + notificar a Engineering
  - Considerar desenergización de emergencia del sector (consultar
    MOP-011 + Engineering)
- Si la inspección visual revela deformación o decoloración severa
  de la carcasa: no continuar el escaneo en ese sector; escalar.

**Secuencia de Reversión:**

1. Si se actuó por hot-spot: documentar foto + ΔT + acción tomada
   (reducción de carga, WO abierto).
2. Notificar al NOC + Manager on Duty + Engineering.
3. La tap-off box afectada o el sector queda en seguimiento
   prioritario hasta confirmar normalización térmica o reemplazo.

**Ventana de acción para hot-spots:** un hot-spot con ΔT > 30 °C
puede escalar a daño irreversible en horas si la carga se mantiene;
la acción correctiva debe iniciarse dentro de las **4 h** siguientes
a la detección.
