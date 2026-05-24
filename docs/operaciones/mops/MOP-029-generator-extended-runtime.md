# MOP-029 — Generador: Operación de Runtime Extendido (> 12 h continuas)

**Asset Category:** Generator (Cummins QSK95 o equivalente) +
Day Tank monitoring + Bulk transfer scheduling · **Work Mode:**
Live (generador asumiendo carga crítica del sitio); LOTO
mecánico/eléctrico solo en bulk transfer windows si aplica.
**Compliance:** NFPA 110 (Standard for Emergency and Standby
Power Systems §8.4 Maintenance + §A.5.6.4 extended runtime),
NFPA 30, IEEE 446, CSA Z462-24, OEM service manual (Cummins QSK95
extended-run procedure).

---

## 1. Alcance y Objetivo

* **Identificador (Tag):** GENSET-A-01 (Cummins QSK95, 2750 kW) +
  DAY-TANK-A + BULK-TANK-1 + ATS-A + cooling auxiliary skid
* **Estado Final Esperado:** generador continúa estable bajo
  carga IT del sitio + alternator winding temp < 110 °C +
  oil pressure dentro del band del fabricante + day tank
  refilled per schedule + cooling system holding + monitoreo
  continuo activo hasta restauración de utility

Operación coordinada del generador cuando el outage de utility
excede 12 horas continuas — escenario típico: storm regional,
falla equipo distribución, prueba IST extendida. NFPA 110
requiere protocolos específicos para runtime extendido por
estrés acumulativo en motor + alternador + oil aging acelerado.

**Equipo objetivo:** generador principal + day tank + bulk tank
+ transfer scheduling + monitoring instrumentation. **Ubicación:**
sala de generadores + monitoring desde sala de control.

---

## 2. Evaluación de Impacto y Riesgos

- **Vector Combustible:** consumo de fuel en runtime extendido
  típico Cummins QSK95 = ~150 GPH al 75% load. Day tank de 500
  galones agota en ~3-4 horas → bulk transfer cada 3 h durante
  extended runtime. ASTM D2276 cleanliness compromised tras
  manipulación frecuente del fuel.
- **Vector Eléctrico:** Arc Flash Categoría 3 en switchgear del
  alternador durante monitoreo + verificación. Riesgo principal:
  **temperatura de winding del alternador** > 110 °C indica
  insulation breakdown imminent (insulation lifetime se reduce
  50% por cada 10 °C sobre rated).
- **Vector Mecánico/Térmico:** oil aging acelerado en runtime
  > 250 h continuas; OEM recomienda oil sample analysis cada
  100 h + filtro de aceite reemplazo cada 250 h en extended
  runtime. Cooling system stress por convection ambiental.
- **Vector Lógico/Controles:** ATS + BMS deben mantener
  monitoreo continuo del generador; pérdida de telemetría
  durante extended runtime = ceguera operacional, escalar a
  fail-safe.
- **Impacto en carga IT:** load del sitio servido al 100% por
  el generador. Cualquier trip = pérdida total (UPS absorbe ~
  10 min, then catastrophic).
- **Tiempo de Inercia:** N/A térmico del Data Hall (los Chillers
  siguen operando). PERO si generador falla con UPS < 100% SoC,
  ventana hasta breach es ~10 min.

---

## 3. Prerrequisitos (Gatekeeper Universal)

- **Generador en standby** con verificación pre-startup completa
  (oil + coolant + fuel + battery) en últimas 24 h.
- **Day tank al 95%+ capacity** + bulk tank con autonomía
  proyectada > 48 h al load actual + cisterna móvil contratada
  for top-up si outage proyectado > 72 h.
- **Cooling auxiliary** (radiador del generador o intercambiador
  externo) en mantenimiento current + N+1 si aplica.
- **PPE Cat 3** contra Arc Flash en sala de generadores per
  **CSA Z462-24** + **PPE térmico** (winding temp inspections
  cercanos a 110 °C) + protección auditiva (sala generador =
  85-95 dB sostenido).
- **LOTO mecánico** en válvulas de fuel disponible para abort
  emergency + **LOTO eléctrico** en motor disconnect del
  alternador disponible (no aplicado durante operación normal);
  **Vivo-Muerto-Vivo** capacity confirmed.
- **Operabilidad de Agentes (Health Check):** Checker + HVAC AI
  (mantenimiento sala generador) + Electrical AI (alternator
  winding temp monitoring) + Discipline AI de fuel quality
  `ONLINE` vía **MCP** durante TODA la operación extended.
- **PTW extended runtime** firmado por Manager on Duty + Safety
  Officer + Cummins service partner contactable on-call.
- **Herramientas:** termopares para winding temp directa
  (validación cruzada del sensor BMS), oil sample bottles + Karl
  Fischer + ASTM kit para fuel sampling, fire extinguisher clase B
  + clase C accesibles, vibration analyzer portátil.
- Personal: técnico generator certificado on-shift continuo
  (shift relief cada 8 h) + supervisor remoto en HMI (Maker +
  Checker — **Cuatro Ojos**) + fire watcher.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).
> Monitoreo continuo durante toda la operación extended.

1. Confirmar transición a generador completada (per MOP-014 trip
   response o MOP-015 ride-through ya ejecutados) + ATS muestra
   "Generator Active" + load IT 100% servido + UPS en flotación.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Activar **monitoreo extended runtime** en HMI: aumenta cadencia
   de logging de telemetría del generador (oil pressure, winding
   temp, fuel consumption rate, vibration) a 1 Hz.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Cada **hora 1 a 4**: chequeo visual del generador + inspección
   de fugas en fuel/oil/coolant + lectura de oil pressure +
   confirmación de telemetría con BMS.

   > `[HOLD POINT]` Hora 4 -- primer **sample de oil** + envío a
   > laboratorio + monitoreo de wear metals (Fe, Cu, Cr). Si
   > viscosity drift > 10% del baseline, escalar a OEM.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Cada **hora 5 a 8**: monitoreo de **winding temp del
   alternador** con termopar directo cada 2 h (verificación
   cruzada del sensor BMS). Trend chart documentado.

   > `[HOLD POINT]` Si winding temp **> 105 °C trending up**:
   > reducir IT load 10% preventivamente; si winding temp > 110 °C
   > sostenida → abort criteria (ver §5).

   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Cuando day tank cae bajo **40%** (~3 h al consumo nominal):
   ejecutar **MOP-027** (bulk-to-day transfer) durante una
   window cuando el load del generator es estable (no en pico).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Cada **8 h shift change**: cambio de técnico on-shift +
   handover documentado con: lecturas baseline, eventos del
   shift, próximas acciones programadas, alarmas pendientes.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Hora **24**: ejecutar **fuel sample** (ASTM D2276 + D6304)
   del day tank + enviar a lab; coordinar bulk top-up con
   cisterna móvil si proyección de outage > 48 h adicionales.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Hora **48** (si outage persiste): ejecutar **MOP-028** (fuel
   polishing) si fuel sample reporta water-cut > 300 ppm o
   particulate count fuera de ISO 4406 18/16/13 spec.

   > `[HOLD POINT]` Si runtime alcanzará **250 h continuas**:
   > coordinar planned shutdown breve (transfer back to utility
   > si disponible, OR transfer to secondary generator si N+1)
   > para oil change + filter replacement per OEM extended-run
   > schedule.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Cuando utility se restablece + ATS reconmuta a Utility +
   generador entra a cool-down + shutdown: documentar tiempo total
   de runtime, fuel consumido, samples enviados, eventos durante
   operación, recomendaciones para próxima sesión.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (parameterized triggers):**

- Si en cualquier momento **winding temp > 110 °C** por **> 30 s**
  → reducir IT load 25% inmediatamente para reducir current
  del alternador; si trend continúa, reducir 50%; si temp NO
  cae a < 105 °C en 5 min → ejecutar IT Load Shedding (EOP
  separado) para preservar alternator integrity.
- Si en cualquier momento **oil pressure < 80% del nominal** por
  más de 60 s → escalar a **shutdown controlado del generador**
  (NOT abrupt trip); transferir load a UPS + iniciar emergency
  refill o switchover a generador N+1.
- Si **fuel consumption rate > 120% del proyectado** sostenido
  → diagnosticar leak en sistema combustible; escalar urgente.
- Si **vibration analyzer reporta > 7 mm/s RMS** (ISO 10816 zone
  C threshold para alternador large) → indicador de bearing
  failure inminente; escalar a OEM service partner.
- Si **fuel sample reporta water-cut > 1000 ppm** (extreme
  contamination) → riesgo de injector damage en curso; coordinar
  emergency fuel polishing + considerar abort del runtime
  extendido con switchover a generador N+1.

**Secuencia de Restauración (R1 — emergency shutdown controlado):**

1. **Reducir IT load** al 50% del nominal vía coordinated load
   shedding (preserve mission-critical, drop non-essential).
2. **Iniciar cool-down ciclo** del generador desde HMI (NO trip
   manual — daña alternator).
3. **Verificar transfer back to utility OR a N+1 generator** según
   topología.
4. **Aplicar LOTO mecánico** en válvulas de fuel + **LOTO
   eléctrico** en motor disconnect del alternador post-cool-down +
   **Vivo-Muerto-Vivo** en bornes antes de cualquier inspección.
5. Activar protocolo de **emergencia generator restoration**:
   notificación Cummins service partner + ETA on-site, escalar
   a Manager on Duty + cliente, programar inspección completa.
6. Si abort durante el primer 4 h: el generador puede haber
   sufrido daño mínimo, return-to-service rápido posible.
   Si abort tras > 24 h: requiere overhaul check completo +
   OEM-certified inspection antes de re-armar para standby.

**Ventana de reversión bounded by:** los UPS proveen ride-through
~10 min al 100% load. Cualquier abort debe completar transición
a alternativa (utility, N+1, IT load shed) en < 50% de esa
ventana = < 5 min para preservar margen.
