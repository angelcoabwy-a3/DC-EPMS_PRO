# MOP-024 — VESDA: Zone Functional Test (Annual Calibration)

**Asset Category:** VESDA (Very Early Smoke Detection Apparatus) ·
**Work Mode:** Live (panel operativo) con zona específica en
**Maintenance Mode** (solenoides Novec/FM-200 aislados durante la
prueba). **Compliance:** NFPA 75 (Fire Protection for Information
Technology Equipment), NFPA 72 (National Fire Alarm Code),
CSA Z462-24, FM 7745 (VESDA system requirements).

---

## 1. Alcance y Objetivo

* **Identificador (Tag):** VESDA-Z3 (zona específica per Data Hall)
* **Estado Final Esperado:** zona VESDA re-armada + sensitivity
  ≤ 15% de drift vs baseline + panel fuera de Maintenance Mode +
  solenoides Novec re-conectados + cero alarmas residuales

Verificación funcional anual de una zona VESDA: introducción
controlada de humo de prueba (cigar smoke pen / FM-200 test
aerosol) en el punto de muestreo más lejano, medición del tiempo
de detección, y validación de que la sensitivity está dentro del
band de tolerancia per FM 7745.

**Equipo objetivo:** VESDA panel (Xtralis VLP-400 o equivalente) +
red de tubería de aspiración + zona específica del Data Hall.
**Ubicación:** sala de incidentes / panel principal de detección.

---

## 2. Evaluación de Impacto y Riesgos

- **Vector Life Safety:** riesgo PRINCIPAL es descarga accidental
  del agente de supresión (Novec 1230 / FM-200) si la zona no se
  aísla correctamente antes de generar humo de prueba. Una descarga
  accidental causa evacuación inmediata + cilindro recargable
  (~$15k USD) + downtime de la zona afectada.
- **Impacto en carga IT:** ninguno directo si la zona se mantiene
  en Maintenance Mode. Riesgo INDIRECTO: si el panel queda mal
  reseteado, futuros eventos reales podrían no disparar supresión.
- **Tiempo de Inercia:** N/A (no es maniobra térmica). PERO si
  ocurre incendio REAL durante la prueba con zona en Maintenance,
  la supresión NO se activa → operador debe estar listo para
  evacuar manualmente.
- **Nivel de energía incidente:** Arc Flash Categoría 1 en el
  panel VESDA (24 VDC + 120 VAC service). Riesgo eléctrico bajo.
- **Riesgos químicos:** humo de prueba (cigar smoke pen) NO es
  tóxico pero requiere ventilación post-prueba para limpiar
  partículas residuales del Data Hall.

---

## 3. Prerrequisitos (Gatekeeper Universal)

- **Panel VESDA en Maintenance Mode** confirmado en HMI ANTES de
  generar humo. Modo Maintenance silencia beacons + aísla
  solenoides + inhibe descarga + mantiene logging.
- **Cigar smoke pen** o **FM-200 test aerosol calibrado** dentro de
  fecha de vigencia.
- **Cronómetro calibrado** para medir tiempo de detección.
- **LOTO en panel VESDA upstream power** (24 VDC service) +
  **LOTO eléctrico en solenoide de descarga del clean agent** +
  **Vivo-Muerto-Vivo** en bornes del solenoide; **PPE Cat 1** per
  **CSA Z462-24**.
- **Confirmación al NOC + fire department del sitio** que la zona
  está en prueba (en caso de respuesta automática externa).
- **Operabilidad de Agentes (Health Check):** Checker + HVAC AI
  (para validar que ventilación post-prueba funciona) están
  `ONLINE` vía **MCP**.
- **PTW especial Life Safety** firmado por Manager on Duty +
  Safety Officer.
- Personal: técnico Life Safety certificado + supervisor (Maker +
  Checker — **Cuatro Ojos**) + observador junto al cilindro de
  supresión para evitar descarga.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + fire department + verificar historial de
   alarmas del panel VESDA (últimos 30 días).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Capturar baseline de sensitivity de la zona objetivo + tiempo
   de detección histórico (referencia annual previa).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Aplicar **Maintenance Mode** en el panel VESDA para la zona
   objetivo + verificar en HMI que beacons + solenoides están
   inhibidos.

   > `[HOLD POINT]` **CONFIRMAR EN PANEL HMI** que la zona muestra
   > "Maintenance Mode — Discharge Inhibited" antes de continuar.
   > Sin esta confirmación, NO se procede con la generación de humo.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Aplicar **LOTO eléctrico** al solenoide de descarga del clean
   agent + ejecutar **Vivo-Muerto-Vivo** en bornes para confirmar
   ausencia de tensión que pueda activar la válvula.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Identificar el punto de muestreo más lejano de la zona
   (típicamente el de mayor latencia, según design diagram).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Generar humo de prueba en el punto de muestreo identificado +
   iniciar cronómetro simultáneamente.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Cronometrar tiempo hasta cada nivel de alarma (Alert / Action /
   Fire 1 / Fire 2) en el HMI del panel. Comparar contra spec del
   fabricante (típicamente Fire 2 en < 120 s para zona
   correctamente configurada).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Detener humo de prueba + esperar a que la sensitivity vuelva al
   baseline ± 15% antes de retirar **LOTO** del solenoide.

   > `[HOLD POINT]` **CONFIRMAR EN HMI** sensitivity dentro del band
   > antes de retirar LOTO. Si el panel reporta drift sostenido,
   > NO se retira LOTO — escalar a fabricante.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Retirar Maintenance Mode + retirar **LOTO** del panel + verificar
   re-armado completo en HMI + documentar resultados (tiempos por
   nivel + sensitivity drift + recommended next inspection date).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (parameterized triggers):**

- Si en el paso 3 el panel **NO confirma Maintenance Mode en 30 s**
  tras el comando → abortar; NO generar humo de prueba.
- Si en el paso 7 el tiempo hasta **Fire 2 excede 180 s** (50% peor
  que spec) → el sistema requiere recalibración antes de declararse
  operativo; mantener Maintenance Mode hasta intervención del
  fabricante.
- Si en el paso 8 la **sensitivity drift excede 25%** del baseline
  por más de 60 s → el sensor está derivado; reemplazar la cabeza
  de detección antes de re-armar.
- Si durante cualquier momento se observa **partícula visible
  saliendo de boquilla de Novec** (descarga incipiente) → evacuar
  el área + cerrar válvula de cilindro manualmente + activar
  emergency response.

**Secuencia de Restauración:**

1. Cerrar válvula de cigar smoke / aerosol de prueba.
2. Verificar **Vivo-Muerto-Vivo** en bornes del solenoide ANTES de
   retirar **LOTO**.
3. Retirar **LOTO** del solenoide + retirar Maintenance Mode en
   el orden inverso (primero panel, luego beacons).
4. Confirmar zona muestra "Normal — Armed" en HMI durante 15 min
   antes de declarar mantenimiento cerrado.
5. Documentar el aborto + causa raíz + escalar a fabricante con
   evidencia (HMI screenshots + drift logs + cronometraje).
6. Notificar al NOC + fire department la conclusión + estado final.

**Ventana de reversión bounded by:** si la zona queda en
Maintenance Mode más de **4 horas** sin supervisión, el panel
genera trouble alarm y debe re-armarse manualmente — restauración
debe completarse en < 50% de esa ventana.
