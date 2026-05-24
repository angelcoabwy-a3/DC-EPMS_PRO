# MOP-017 — CRAH: Calibración Dinámica de VFDs y Válvulas Modulantes

**Asset Category:** CRAH · **Work Mode:** Live tuning (CRAH operativa
durante la calibración; LOTO sólo si se interviene físicamente la
válvula). **Compliance:** CSA Z462-24, NFPA 70E, ASHRAE TC 9.9.

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** CRAH-XX + VFD + válvula modulante asociada
* **Estado Final Esperado:** Setpoints VFD + apertura de válvula calibrados + curvas operativas actualizadas + walk-back baseline registrado

Ajustar la lógica de apertura de las válvulas de agua helada de 2 o
3 vías en concordancia con las RPM del ventilador del CRAH para
**optimizar el `dT` de la sala blanca** y reducir el consumo
energético del motor mediante las **Leyes de Afinidad**
(`P1/P2 = (N1/N2)^3` — reducir 10% RPM disminuye ≈ 27% del consumo).

**Equipo objetivo:** CRAH (`crah_a1`, etc.) + su VFD + válvula
modulante asociada. **Ubicación:** Data Hall + sala de control.

---

## 2. Evaluación de Impacto y Riesgos Térmicos


- **Vector Lógico/Controles + Mecánico (riesgo de hunting en PID; pérdida de coordinación RPM/válvula)**

- **Impacto en carga IT:** la calibración modifica activamente RPM +
  apertura de válvula; si el `dT` resultante sale del rango ASHRAE
  A2, los racks ven inlet > 35 °C.
- **Tiempo de Tolerancia Térmica:** ≈ 8 min antes de breach ASHRAE
  A2 si la CRAH se desconfigura severamente; pero las CRAHs vecinas
  amortiguan.
- **Riesgo de oscilación:** si la sintonía PID se vuelve inestable,
  el sistema oscila (`hunting`) → desgaste mecánico + pérdida de
  precisión térmica.
- **Nivel de energía incidente:** Arc Flash Categoría 2 en el panel
  del VFD si se abre para ajuste manual de parámetros (típico para
  configuración inicial).

---

## 3. Parámetros Físicos de Referencia (Prerrequisitos)

- **RPM baseline** de los ventiladores + **% apertura de válvula
  baseline** documentados antes del cambio.
- **Setpoint de `dT`** objetivo (típicamente `dT = 10-12 °C` para
  Phase 1 Toronto baseline).
- **Caudal mínimo de agua helada** aceptable durante la calibración
  (≥ 70% nominal).
- **Walk-back automático** del VFD configurado (rollback a baseline
  si una variable de proceso sale de rango).
- **Mechanical LOTO** en la válvula modulante si se interviene
  físicamente; **Motor LOTO eléctrico** en el VFD si se abre el
  panel para ajuste de firmware o cableado interno; **CSA Z462-24**,
  **PPE Cat 2**.
- **Vivo-Muerto-Vivo** obligatorio en bornes del VFD antes de
  cualquier intervención eléctrica.
- **PTW** firmado por el Manager on Duty.
- Personal: técnico de control + supervisor en HMI (Maker + Checker —
  **Cuatro Ojos**).

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + capturar baseline: RPM, % válvula, `dT` aire,
   caudal de agua, `dP` filtros.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Definir el plan de cambio: reducción de RPM objetivo (típicamente
   en pasos de 5%) + apertura de válvula asociada (para mantener
   `Q_s` constante a `dT` objetivo).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Si requiere ajuste físico de la válvula: aplicar **Mechanical
   LOTO** + alivio de presión + intervenir.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Si requiere ajuste del VFD interno: aplicar **Motor LOTO
   eléctrico** + **Vivo-Muerto-Vivo** en bornes + abrir panel con
   **PPE Cat 2**.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Aplicar el primer paso de reducción de RPM (5%) + monitorear
   `dT`, presión estática piso falso, ruido / vibración del
   ventilador durante 5 min.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > [HOLD POINT] Confirmar estabilidad de dT + presión estática durante 5 min antes del siguiente paso de reducción de RPM.

6. Si estable: aplicar siguiente paso. Repetir hasta alcanzar
   objetivo o disparar criterio de aborto.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Documentar nuevos setpoints + curvas de operación + actualizar
   walk-back baseline. Retirar LOTOs aplicados.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Notificar al NOC la finalización + adjuntar gráfico
   antes/después del consumo energético del VFD.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (disparadores térmicos automáticos):**

- Si la **temperatura del aire de inlet de los racks supera los
  27 °C** (ASHRAE A1) por más de 60 s → walk-back automático del
  VFD a baseline.
- Si la **presión estática del piso falso cae > 15%** → walk-back +
  diagnosticar coordinación RPM/válvula.
- Si la **válvula muestra hunting** (oscilación > ± 5% del setpoint
  por más de 2 min) → revertir cambio + re-sintonizar PID.
- Si el VFD reporta **alarma de sobre-corriente o
  sobre-temperatura** → aplicar **Motor LOTO** + Vivo-Muerto-Vivo +
  diagnóstico.

**Secuencia de Reversión:**

1. Restaurar setpoints baseline en el VFD (rollback automático o
   manual).
2. Verificar que `dT`, presión estática, caudal vuelven a baseline.
3. Documentar el aborto + causa raíz + reprogramar con un plan más
   conservador (pasos de 2-3% en vez de 5%).

**Ventana de reversión bounded by:** el Tiempo de Tolerancia Térmica
(≈ 8 min); el walk-back automático actúa en segundos, manual en
< 2 min.
