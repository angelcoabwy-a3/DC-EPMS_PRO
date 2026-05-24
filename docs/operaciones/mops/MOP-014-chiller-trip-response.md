# MOP-014 — Chiller: Respuesta y Aislamiento por Disparo Térmico (Chiller Trip)

**Asset Category:** Chiller · **Work Mode:** Emergency response —
conmutación rápida a bypass + chiller de respaldo. **Compliance:**
CSA Z462-24, NFPA 70E, ASHRAE TC 9.9, Uptime Tier IV.

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** Chiller primario (en trip) + Chiller de respaldo
* **Estado Final Esperado:** Carga absorbida por Chiller de respaldo + ATD restaurado + temperatura de suministro < 8 °C + Chiller fallido con LOTO completo

Secuencia de emergencia automatizada / manual para conmutar las
válvulas de derivación (`bypass`) hacia una enfriadora de respaldo
tras un fallo repentino del compresor del Chiller primario, **antes
que la inercia térmica del bucle de agua helada se agote** y la
sala IT cruce el límite ASHRAE.

**Equipo objetivo:** Chiller primario en trip + bypass valves +
Chiller de respaldo (`chiller_2`). **Ubicación:** Planta Mecánica.

---

## 2. Evaluación de Impacto y Riesgos Térmicos


- **Vector Mecánico/Térmico (Tiempo de Inercia ~2 min ASHRAE A2 breach -- emergencia)**

- **Impacto en carga IT:** durante el trip, la carga térmica
  (`Q_load`) deja de ser rechazada; la inercia del bucle de agua
  helada amortigua brevemente, pero el `dT` del aire en CRAHs
  comienza a subir inmediatamente.
- **Tiempo de Tolerancia Térmica crítico:** la sala IT cruza el
  límite ASHRAE A2 (`T_inlet = 35 °C`) en **≈ 2 min** al 100% carga
  Phase 1 si no hay rechazo de calor (peor caso entre todos los
  MOPs). La conmutación al respaldo DEBE completarse en < 90 s.
- **Nivel de energía incidente:** Arc Flash Categoría 3 en el panel
  del Chiller fallido; **NO se intenta diagnosticar el trip durante
  la emergencia** — esa fase es post-restauración.
- **Cascada potencial:** si la conmutación falla y el respaldo no
  arranca, el siguiente backstop es el shutdown controlado de IT
  loads (EOP separado).

---

## 3. Parámetros Físicos de Referencia (Prerrequisitos)

- **Bypass valves pre-configuradas** y verificadas mensualmente en
  estado "ready to commute".
- **Chiller de respaldo en modo Auto** con bombas en standby + GPM
  alcanzable en < 30 s.
- **ATD baseline** documentado para el respaldo (debe coincidir con
  el primario ± 1 °C).
- **PPE Cat 3** disponible en sala mecánica per **CSA Z462-24**.
- **Motor LOTO eléctrico** del compresor fallido para safety post-
  trip + **Vivo-Muerto-Vivo** antes de cualquier inspección.
- Personal: técnico de turno + supervisor remoto via HMI
  (Maker + Checker — **Cuatro Ojos**); el técnico es el ejecutor
  físico, el supervisor monitorea HMI + cronometra.

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).
> El cronómetro arranca con el disparo del Chiller primario.

1. Confirmar el trip en HMI (alarma del compresor + caída de COP) +
   notificar al NOC el evento + iniciar cronómetro.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Verificar estado del Chiller de respaldo: modo Auto + sin
   alarmas + bombas listas.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Ejecutar comando de **conmutación de bypass valves** desde HMI
   (automático) o manual en sala mecánica.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Arrancar el Chiller de respaldo + verificar absorción de carga
   en < 60 s desde el trip; monitorear gradiente de temperatura
   en el anillo primario.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Confirmar restauración: temperatura de suministro vuelve dentro
   del rango (< 8 °C nominal) dentro de los 90 s del cronómetro.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > [HOLD POINT] Confirmar absorción de carga por el respaldo + T_suministro < 8 °C antes de aplicar LOTO al Chiller fallido.

6. Una vez estabilizado: aplicar **Motor LOTO eléctrico** al
   compresor fallido + **Vivo-Muerto-Vivo** en motor disconnect +
   **LOTO mecánico** en válvulas del Chiller fallido + alivio de
   presión.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Documentar el incidente: hora del trip, tiempo de restauración,
   alarmas precedentes + abrir WO de diagnóstico para el compresor
   fallido. Notificar al NOC la conclusión.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (escalamiento a EOP separado):**

- Si el Chiller de respaldo **no arranca** o **no absorbe carga en
  90 s** → escalar al **EOP de IT Load Shedding**; aislar IT no
  crítica para reducir `Q_load` por debajo de la capacidad del
  rechazo residual.
- Si **ambos Chillers fallaron** (escenario doble trip) → escalar
  inmediatamente al Manager on Duty + activar EMP de pérdida total
  de enfriamiento.
- Si durante el paso 6 la prueba **Vivo-Muerto-Vivo detecta tensión
  residual** en el compresor fallido → no intentar inspección;
  mantener LOTO mecánico hasta intervención eléctrica especializada.

**Secuencia de Reversión:**

1. Si el respaldo no asume: ejecutar IT Load Shedding (procedimiento
   EOP separado).
2. Mantener bypass valves abiertas a free cooling temporal si el
   bulbo húmedo exterior lo permite (MOP-021).
3. Notificar al cliente / stakeholder según matriz de escalamiento
   Tier IV.

**Ventana de reversión bounded by:** el Tiempo de Tolerancia Térmica
crítico (≈ 2 min); cualquier acción posterior es daño contenido,
no prevención.
