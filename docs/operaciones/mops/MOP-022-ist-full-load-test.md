# MOP-022 — Sistema Completo: Pruebas de Sistemas Integrados a Plena Carga (IST)

**Asset Category:** Global (full site) · **Work Mode:** Simulación
controlada de pérdida de acometida con bancos de carga al 100% de
carga térmica + monitoreo coordinado. **Compliance:** CSA Z462-24,
NFPA 70E, NFPA 110, Uptime Tier IV (annual IST mandate), ASHRAE TC 9.9.

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** Sitio completo (utility intake + generadores + UPS + Chillers + CRAHs + bancos de carga)
* **Estado Final Esperado:** IST validado + tiempos cronometrados documentados + utility restaurada + generadores apagados + sistema en operación normal

Protocolo macro para **simular la pérdida catastrófica de la
acometida principal** con el centro de datos operando al **100% de
su carga térmica simulada** (bancos de carga). Valida la respuesta
coordinada de Chillers + arranque de plantas de emergencia +
secuenciación de bombas + mantenimiento de la envolvente ASHRAE en
los pasillos fríos.

**Equipo objetivo:** sitio completo (utility intake + generadores +
UPS + Chillers + CRAHs + torres + bancos de carga simulando IT).
**Ubicación:** todo el Data Hall + Planta Mecánica + sala de
generadores + cuarto de control.

---

## 2. Evaluación de Impacto y Riesgos Térmicos


- **Vector Eléctrico:** Arc Flash Categoría 4 en todos los paneles principales durante la transición; ningún operador debe acercarse a switchgear durante la maniobra.
- **Vector Mecánico/Térmico:** Tiempo de Inercia ≈ 4 min antes de breach ASHRAE A2 al 100 % carga sin rechazo activo; UPS proporcionan ride-through eléctrico ≈ 10 min pero el rechazo térmico es el hard limit.
- **Vector Lógico/Controles:** los controladores deben entrar en fail-safe coordinado si la simulación falla; reinicio masivo de PLCs aumenta el riesgo de pérdida de visibilidad sistémica.

- **Impacto en carga IT:** **CRÍTICO** — durante el IST, los
  bancos de carga simulan IT al 100%. Si la prueba falla, el sitio
  experimenta una pérdida de enfriamiento + potencia REAL.
- **Tiempo de Tolerancia Térmica:** ≈ 4 min antes de breach ASHRAE
  A2 si Chillers no se restablecen post-transición; los UPS
  proporcionan ride-through eléctrico ≈ 10 min, pero el rechazo
  térmico es el limit hard.
- **Nivel de energía incidente:** **Arc Flash Categoría 4 (peor
  caso)** en todos los paneles principales durante la transición;
  ningún operador debe acercarse a switchgear durante la maniobra.
- **Riesgo cascada sistémica:** si los generadores no arrancan en
  15 s + los Chillers no recuperan en 90 s → el sitio entra en
  modo IT Load Shedding forzado.
- **Riesgo de daño térmico a IT real:** si los bancos de carga
  comparten infraestructura con IT real (no recomendado), un IST
  fallido daña equipo de producción.

---

## 3. Parámetros Físicos de Referencia (Prerrequisitos)

- **Bancos de carga validados** y conectados con sus disconnects
  propios (separados de IT real cuando sea posible).
- **Generadores con combustible ≥ 95%** + baterías de arranque
  cargadas + último mantenimiento dentro del trimestre.
- **UPS con SoC ≥ 90%** y `battery_runtime_min` ≥ 12 min al 100%
  carga.
- **Chillers en N+1** + todas las bombas operativas + bulbo húmedo
  exterior favorable.
- **Mechanical LOTO** preparado en válvulas críticas para evitar
  deriva inadvertida durante la prueba.
- **Motor LOTO eléctrico disponible** para abort emergency en
  cualquier subsystem + **Vivo-Muerto-Vivo** capability;
  **CSA Z462-24**, **PPE Cat 4** para el equipo on-call.
- Si hay equipo **Eaton** (SOW R-48) en el path crítico: verificar
  BCMS + fibra óptica + estado caja SCR + FSBs + firmware reciente.
- **PTW especial IST** firmado por **CIO + Manager on Duty + Safety
  Officer**.
- Personal: equipo coordinado de ≥ 8 personas distribuidas (sala
  de generadores, Planta Mecánica, Data Hall, sala de control,
  exterior); cada par opera Maker + Checker (**Cuatro Ojos**) +
  un Incident Commander supervisando todo.

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).
> El cronómetro arranca con la simulación de pérdida de utility.

1. Briefing pre-prueba: rolesconfirmados, comunicación radio
   operativa, abort criteria revisados, equipo de bomberos en
   standby. Notificar al NOC + cliente + stakeholders.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > `[HOLD POINT]` Confirmar briefing pre-prueba completo + roles asignados + equipo de bomberos en standby antes de simular pérdida de utility.

2. Cargar bancos de carga al 100% de carga térmica simulada del
   sitio; verificar `T_inlet` racks dentro de ASHRAE A2 baseline.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. **Simular pérdida de utility** abriendo el breaker principal
   (físico o vía controlador del ATS, según diseño de la prueba).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Cronometrar arranque de generadores: deben asumir carga en
   **≤ 10 s** + V/Hz nominales en **≤ 15 s** + ATS conmutado
   completamente en **≤ 30 s** total.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > [HOLD POINT] Confirmar generadores asumen carga en ≤ 15 s + V/Hz nominales antes de continuar.

5. Monitorear UPS: deben absorber el transitorio sin descarga
   excesiva (`battery_runtime_min` no debe caer > 30% en los
   primeros 60 s).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Cronometrar recuperación de Chillers (MOP-015 ride-through
   sequence aplica): primer compresor arranca en **≤ 60 s**, todos
   en línea en **≤ 4 min**.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Verificar envolvente ASHRAE en pasillos fríos durante toda la
   prueba: `T_inlet` racks NO debe exceder 35 °C (ASHRAE A2).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Mantener operación en generador por **mínimo 30 min** para
   validar estabilidad sostenida + monitorear consumo de
   combustible vs proyección.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. **Simular restauración de utility**: cerrar breaker principal +
   verificar re-transferencia ordenada del ATS (transición
   cerrada o abierta según diseño) + apagado de generadores tras
   ciclo de enfriamiento.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

10. Documentar el IST completo: tiempos cronometrados de cada
    transición, SoC mínimo de UPS, ATD mínimo / máximo de Chillers,
    `T_inlet` máxima de racks, combustible consumido. Notificar al
    NOC + cliente la conclusión.
    `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (escalamiento inmediato):**

- Si los generadores **NO arrancan o NO asumen carga en 15 s** →
  ABORTAR la simulación: cerrar manualmente breaker principal de
  utility ANTES que los UPS se descarguen significativamente.
- Si los Chillers **NO recuperan en 90 s** → ejecutar **IT Load
  Shedding** sobre los bancos de carga + considerar la prueba
  fallida; documentar todos los timing para análisis.
- Si la **`T_inlet` de racks excede 30 °C** (margen vs ASHRAE A2 =
  35 °C) durante la prueba → ABORTAR + restaurar utility +
  investigar.
- Si los **UPS reportan baja autonomía** (`battery_runtime_min`
  < 4 min) durante operación en generador → ABORTAR; el ride-
  through real sería insuficiente.

**Secuencia de Reversión (R1 — restauración inmediata):**

1. Cerrar breaker principal de utility (manual o controlador).
2. Verificar re-transferencia del ATS a utility.
3. Reducir gradualmente los bancos de carga al 50% para reducir
   stress del sistema durante recovery.
4. Apagar generadores con ciclo de enfriamiento ordenado.
5. Documentar el aborto + análisis de causa raíz preliminar +
   escalar a Engineering + cliente / stakeholders.
6. Programar IST de re-test después de corregir las causas
   identificadas.

**Ventana de reversión bounded by:** la autonomía de UPS al 100%
carga (~10-12 min); el aborto debe ejecutarse en < 50% de esa
ventana si los disparadores se activan.
