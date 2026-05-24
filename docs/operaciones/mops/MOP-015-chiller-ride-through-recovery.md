# MOP-015 — Chiller: Recuperación Eléctrica en Generador (Ride-Through)

**Asset Category:** Chiller · **Work Mode:** Live coordination (la
transición ya ocurrió; este MOP gestiona el reinicio escalonado de
compresores tras pasar a energía de respaldo). **Compliance:** CSA
Z462-24, NFPA 70E, NFPA 110, ASHRAE TC 9.9.

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** Chiller-1 .. Chiller-N (N+1) post ride-through
* **Estado Final Esperado:** N+1 Chillers en línea + ATD restaurado al baseline + T_suministro < 8 °C + frecuencia del generador estable

Programar el reinicio escalonado de los compresores de los Chillers
tras una transición a energía de respaldo (`ride-through`), limitando
la rampa de carga para evitar variaciones críticas de frecuencia en
el alternador del generador y previniendo el disparo por **Lift
elevado** del compresor antes que se estabilice el sistema.

**Equipo objetivo:** Chillers (1, 2, 3, 4 según N+1) + ATS + planta
de emergencia. **Ubicación:** Planta Mecánica + sala de generadores.

---

## 2. Evaluación de Impacto y Riesgos Térmicos


- **Vector Mecánico/Térmico (Tiempo de Inercia ~4 min; Lift effect risk durante reinicio de compresores)**

- **Impacto en carga IT:** durante la transición sin chiller (~15-30 s
  típico hasta arranque del primer compresor), la inercia del agua
  helada en el bucle absorbe; el `dT` del aire CRAH sube
  gradualmente.
- **Tiempo de Tolerancia Térmica:** ≈ 4 min antes de breach ASHRAE
  A2 al 100% carga Phase 1 sin rechazo activo de calor; el reinicio
  escalonado debe completarse dentro de esa ventana.
- **Efecto Lift (riesgo primario):** si el flujo del condensador
  disminuye durante la transición, `T_cond` y `P_cond` suben → la
  relación de presiones (`Lift`) aumenta → `W_comp` crece
  drásticamente → riesgo de disparo del compresor por sobre-
  corriente ANTES de que el sistema se estabilice.
- **Nivel de energía incidente:** Arc Flash Cat 3 en los paneles de
  control de Chillers durante el monitoreo.

---

## 3. Parámetros Físicos de Referencia (Prerrequisitos)

- **Rampa de carga máxima permitida:** definida por el fabricante
  del generador (típicamente 25% de la potencia nominal cada
  10-15 s).
- **Walk-in del rectificador** de los UPS verificado (limita la
  corriente de recarga simultánea para no sobrecargar el alternador).
- **Lift máximo permitido** del compresor: típicamente
  `Lift_max ≤ 1.5 × Lift_baseline`; si se excede, abortar reinicio.
- **PPE Cat 3** disponible + **CSA Z462-24** compliance.
- **Motor LOTO** disponible para abort emergency de cualquier
  compresor (sin aplicar durante la operación normal).
- Personal: técnico de turno + supervisor remoto via HMI
  (Maker + Checker — **Cuatro Ojos**).

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Confirmar transición a generador completada en HMI (ATS muestra
   fuente alterna activa + V/Hz nominales).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > `[HOLD POINT]` Confirmar Lift < 1.5 × baseline + frecuencia del generador estable (± 0.5 Hz) antes del siguiente arranque escalonado.

2. Verificar bombas de condensador + evaporador de los Chillers
   arrancadas o arrancando primero (deben asentar flujo antes que
   los compresores).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Esperar **ecualización del condensador** (`T_cond` + `P_cond`
   estables) antes de arrancar el primer compresor.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Arrancar **Chiller 1** en modo soft-start; monitorear `Lift` +
   corriente del motor durante 30 s; verificar que `Lift <
   Lift_max`.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Esperar 30-45 s + verificar frecuencia del generador estable
   (± 0.5 Hz) antes del siguiente arranque.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Arrancar **Chiller 2**; repetir monitoreo de `Lift` + frecuencia
   + corriente.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Continuar la cadena hasta tener N+1 Chillers en línea + verificar
   ATD restaurado al baseline + `T_suministro` vuelve a < 8 °C.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Notificar al NOC la recuperación completa + documentar tiempos:
   transición → primer compresor → restauración total. Si en
   cualquier paso se aplicó **Vivo-Muerto-Vivo + LOTO** por abort,
   documentar también.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (disparadores automáticos):**

- Si en el paso 4 o 6 el `Lift` excede `1.5 × Lift_baseline` →
  **abortar el arranque** del compresor; aplicar **LOTO eléctrico**
  + **Vivo-Muerto-Vivo** + diagnosticar el flujo del condensador
  antes de re-intentar.
- Si la **frecuencia del generador cae > 1 Hz** durante un arranque
  → abortar el siguiente arranque hasta estabilización.
- Si la **temperatura del agua de suministro supera los 12 °C por
  más de 45 segundos** durante la recuperación → escalar a IT Load
  Shedding (EOP separado).

**Secuencia de Reversión:**

1. Si Lift excedido: dejar el compresor afectado fuera + continuar
   con los demás (operación con menor N).
2. Si frecuencia inestable: pausar arranques + estabilizar generador
   antes de continuar.
3. Documentar el incidente + abrir WO de diagnóstico para los
   compresores que abortaron.
4. Si la sala IT exhibe degradación térmica sostenida: escalar a
   Manager on Duty.

**Ventana de reversión bounded by:** el Tiempo de Tolerancia Térmica
(≈ 4 min en este escenario, mejor que el trip puro porque la rampa
es ordenada); cualquier acción posterior es daño contenido.
