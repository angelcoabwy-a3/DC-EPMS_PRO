# MOP-018 — CRAH: Control Psicrométrico + Mitigación de Condensación

**Asset Category:** CRAH · **Work Mode:** Live tuning (CRAH operativa
durante el ajuste de setpoints). **Compliance:** CSA Z462-24,
NFPA 70E, ASHRAE TC 9.9 (envolvente psicrométrica A1-A4 + 40-55% RH).

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** CRAH-XX (psychrometric setpoint adjust)
* **Estado Final Esperado:** HR < 55% + T_serpentín ≥ T_punto_de_rocío + 1.5 °C + sin condensación visible en bandejas + curvas T-HR documentadas

Ajustar los setpoints de la CRAH ante alarmas de **alta humedad
relativa** en el Data Hall, regulando la **temperatura de la
superficie del serpentín** para mantenerla siempre **por encima del
punto de rocío** del ambiente — eliminando la formación de agua
libre (condensación) en la sala de servidores y en componentes
eléctricos.

**Equipo objetivo:** CRAH (`crah_a1`, etc.) + sus setpoints + sondas
psicrométricas. **Ubicación:** Data Hall + sala de control.

---

## 2. Evaluación de Impacto y Riesgos Térmicos


- **Vector Mecánico/Térmico + Vector Lógico (riesgo de condensación = corrosión + arc tracking en racks; over-cooling sube W_comp)**

- **Impacto en carga IT:** condensación en componentes eléctricos =
  corrosión + falla por arc tracking + corto en racks; humedad
  excesiva sostenida acelera la corrosión galvánica.
- **Tiempo de Tolerancia Térmica:** la formación de condensación es
  ACUMULATIVA — no hay un timer agudo; pero **HR > 60% sostenida
  por > 30 min** se considera fuera de tolerancia.
- **Riesgo de over-cooling:** si para bajar HR se reduce demasiado
  `T_suministro`, los costos energéticos suben + se baja artificialmente
  el COP del Chiller (Lift aumenta).
- **Nivel de energía incidente:** Arc Flash Categoría 1 (CRAH
  enclosure low-voltage; configuración de setpoints es desde HMI).

---

## 3. Parámetros Físicos de Referencia (Prerrequisitos)

- **Envolvente ASHRAE A1-A2 aplicable:** RH entre **40% y 55%**,
  `T_inlet` rack entre **18 °C y 27 °C** (A1) o **18 °C y 35 °C**
  (A2).
- **Punto de rocío baseline** del Data Hall (calcular desde T +
  HR actuales).
- **Temperatura de superficie del serpentín** debe permanecer
  **≥ 1.5 °C por encima del punto de rocío del ambiente** para
  prevenir condensación.
- **Mechanical LOTO** en la válvula modulante de agua helada si
  se interviene físicamente; **Motor LOTO** del VFD del ventilador
  + **Vivo-Muerto-Vivo** en bornes si se abre panel; **CSA
  Z462-24**, **PPE Cat 1**.
- **Herramientas:** sondas psicrométricas calibradas
  (T + HR + punto de rocío), tablet HMI + acceso al SCADA.
- **PTW** firmado por el Manager on Duty (si se modifican setpoints
  fuera de la banda estándar).
- Personal: técnico de control + supervisor (Maker + Checker —
  **Cuatro Ojos**).

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + capturar baseline psicrométrica:
   `T_suministro`, `T_retorno`, HR, punto de rocío calculado,
   temperatura de superficie del serpentín.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Verificar que las sondas están calibradas (deriva < ± 1% HR;
   recalibrar si supera).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Calcular el setpoint objetivo: `T_serpentín ≥ punto_de_rocío +
   1.5 °C`; ajustar `T_suministro_setpoint` para que el serpentín
   no baje del umbral.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Aplicar el nuevo setpoint en HMI; monitorear durante 10 min
   sin tocar nada (deja que el lazo PID estabilice).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > [HOLD POINT] Confirmar T_serpentín estable ≥ T_punto_de_rocío + 1.5 °C durante 10 min antes de cerrar WO.

5. Verificar HR del Data Hall cae a < 55% + `T_serpentín` se
   mantiene en el umbral seguro + no aparece condensación visible
   en bandejas / serpentín.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Si se requiere ajuste físico (válvula modulante o VFD): aplicar
   **Mechanical LOTO** o **Motor LOTO** + **Vivo-Muerto-Vivo**
   antes de intervenir.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Documentar nuevos setpoints + curvas psicrométricas (gráfico T-HR
   antes/después) + notificar al NOC la finalización.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto:**

- Si tras el cambio la **HR del Data Hall NO cae bajo 55% en
  15 min** → revertir setpoint; investigar carga latente externa
  (infiltración, condensación de building envelope).
- Si aparece **condensación visible en bandejas de drenaje de la
  CRAH o en superficies aledañas** → revertir setpoint
  inmediatamente; el serpentín bajó del punto de rocío.
- Si el `T_inlet` de los racks **excede 27 °C (ASHRAE A1)** por
  más de 60 s → revertir setpoint; over-cooling no debe sacrificar
  la envolvente.

**Secuencia de Reversión:**

1. Restaurar setpoint baseline en HMI.
2. Esperar 10 min de estabilización + verificar HR y `T_inlet`.
3. Documentar el aborto + causa raíz + escalar a Engineering si la
   causa raíz es infiltración o carga latente externa (no
   solucionable desde CRAH sola).

**Ventana de reversión bounded by:** la condensación es acumulativa
(no agudo); pero un setpoint mal aplicado puede generar agua libre
en minutos — la reversión debe iniciarse en < 5 min de detectar
condensación.
