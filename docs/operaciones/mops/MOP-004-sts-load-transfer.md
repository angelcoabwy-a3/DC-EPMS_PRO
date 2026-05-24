# MOP-004 — STS: Transferencia de Carga (Preferred → Alternate / Bypass)

**Asset Category:** STS (Static Transfer Switch) · **Work Mode:** Live
(maniobra operacional en vivo; NO LOTO sobre el STS). **Compliance:**
CSA Z462-24, NFPA 70E §130, Eaton SOW R-48 pre-transfer validation.

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** STS-A or STS-B
* **Estado Final Esperado:** Carga transferida a la fuente alterna (o bypass de mantenimiento); SCR sin alarmas + sincronización confirmada

Conmutar la carga del Static Transfer Switch desde la fuente preferida
hacia la fuente alterna (o hacia el bypass de mantenimiento) sin
interrupción de la carga IT aguas abajo (PDUs / RPPs / racks).

**Equipo objetivo:** STS asociado (`sts_a` / `sts_b`) + sus PDUs
servidas. **Ubicación:** sala eléctrica del Building.

---

## 2. Evaluación de Impacto y Riesgos


- **Vector Eléctrico (Arc Flash Cat 3 en panel STS; SCR temperature risk durante 4ms commutación)**

- **Impacto en carga IT:** la conmutación es sub-ciclo (típicamente
  ≤ 4 ms vía SCR); si la maniobra falla, la pérdida de potencia se
  propaga aguas abajo y los UPS absorben el evento.
- **Nivel de energía incidente:** Arc Flash Categoría 3 en el panel
  STS; toda la maniobra es operada desde el HMI / controlador.
- **Dependencias aguas arriba:** las dos fuentes (preferida + alterna)
  + sus interruptores principales.
- **Dependencias aguas abajo:** PDUs servidas por el STS + sus
  cargas IT.
- **Riesgos primarios:** sobre-temperatura en tiristores SCR durante
  la conmutación; alarma de pre-existencia ignorada llevando a
  conmutación a una fuente degradada.

---

## 3. Requisitos Previos (Prerrequisitos)

- **PRE-TRANSFER OBLIGATORIO** (S-DISTRIBUTION-01):
  1. Revisar e imprimir el **historial de alarmas** del STS de los
     últimos 90 días.
  2. Verificar el **estado de la caja SCR**: LEDs verdes, sin
     alarmas activas de temperatura ni de degradación.
  3. Confirmar **sincronización de fuentes** (V + Hz + fase) en el
     HMI.
- **LOTO no aplica** (maniobra en vivo sobre equipo energizado);
  respetar **límite de aproximación restringida** + **PPE Cat 3** per
  **CSA Z462-24**.
- **PTW (Permiso de Trabajo)** firmado por el Manager on Duty.
- Notificar al NOC el inicio + la finalización.
- Si el equipo es **Eaton** (SOW R-48), verificar BCMS + fibra óptica
  de monitoreo previo (advisory).
- Personal: técnico ejecutante en sala STS + supervisor en el HMI
  (Maker + Checker — **Cuatro Ojos**).

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Confirmar fuente preferida activa + V/Hz/fase nominales en el HMI
   del STS.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Imprimir + adjuntar al WO el historial de alarmas de los últimos
   90 días.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Verificar caja SCR: LEDs verdes, sin alarmas de tiristor, sin
   eventos de sobre-temperatura recientes.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Verificar sincronización de las dos fuentes en el HMI (ángulo
   de fase < 5°, V dentro de ±2%, Hz dentro de ±0.5 Hz).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > [HOLD POINT] Confirmar ángulo de fase < 5°, V ± 2%, Hz ± 0.5 Hz en HMI antes de comando de transferencia.

5. Personal en sala STS se posiciona FUERA del **límite de
   aproximación restringida** + verifica PPE Cat 4.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Supervisor ejecuta el comando de transferencia desde el HMI.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Confirmar en el diagrama unifilar del HMI que la fuente activa
   cambió + no aparecen alarmas nuevas en los 30 s posteriores.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Verificar estabilidad de V/Hz aguas abajo en las PDUs servidas.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto:**

- Si en el paso 3 la caja SCR reporta alarma activa → **abortar**;
  no transferir.
- Si en el paso 4 la sincronización está fuera de los límites →
  **abortar**; no forzar.
- Si durante el paso 6 los SCR reportan alarma de temperatura → forzar
  retorno a la fuente preferida **antes de los 100 ms** de
  transferencia.

**Secuencia de Reversión:**

1. Ejecutar comando manual de retorno desde el HMI a la fuente
   preferida.
2. Confirmar que la carga aguas abajo regresó a la fuente preferida.
3. Notificar al NOC + Manager on Duty del aborto + causa preliminar.
4. La maniobra no se vuelve a intentar sin diagnóstico de los SCR
   por el fabricante.

**Ventana de reversión bounded by:** los UPS aguas abajo absorberían
una transferencia fallida vía baterías (10-15 min típico); la
reversión debe completarse dentro del 25% de esa ventana.
