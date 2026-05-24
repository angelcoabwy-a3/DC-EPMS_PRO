# MOP-027 — Day Tank: Transferencia de Combustible desde Bulk a Day Tank

**Asset Category:** Day Tank (combustible) + Bomba de Transferencia
· **Work Mode:** Live (transferencia en operación normal); LOTO
mecánico en válvulas + LOTO eléctrico en motor de bomba si se
interviene físicamente. **Compliance:** NFPA 110 (Standard for
Emergency and Standby Power Systems), NFPA 30 (Flammable and
Combustible Liquids Code), IEC 60079 (Hazardous Areas), ASTM
D2276 (fuel cleanliness), ANSI/AIHA Z9.5 (laboratory ventilation
guidance for fume handling).

---

## 1. Alcance y Objetivo

* **Identificador (Tag):** DAY-TANK-A (tanque diario primario del
  Genset A) + BULK-TANK-1 (tanque bulk principal) + XFER-PUMP-A
  (bomba de transferencia)
* **Estado Final Esperado:** day tank al nivel target (típicamente
  90-95% capacity, no 100% para permitir expansion thermal) +
  transfer pump apagada + válvulas en posición normal-flow +
  spill containment retirado + autonomía del generador validada
  para el load proyectado de las próximas 24 h

Reabastecimiento programado del day tank desde el bulk tank. Se
ejecuta cuando el nivel del day tank cae bajo 30% (low threshold)
O cuando hay forecast de runtime extendido (storm / planned
outage). NFPA 110 requiere autonomía mínima 24 h.

**Equipo objetivo:** day tank + manhole + transfer pump + manifold
de válvulas + bulk tank. **Ubicación:** sala de generadores +
yard exterior (bulk tank).

---

## 2. Evaluación de Impacto y Riesgos

- **Vector Combustible:** PRIORIDAD MÁXIMA. Diesel #2 flash point
  ≥ 52 °C; en condiciones normales no se inflama, PERO vapores
  acumulados en zona confinada Y un arc/spark = incendio. IEC
  60079 zona 1 cuando el manhole está abierto.
- **Vector Eléctrico:** Arc Flash Categoría 2 en motor de la
  bomba de transferencia si se interviene; static discharge
  durante transferencia es el riesgo dominante (de ahí bonding
  cable obligatorio).
- **Impacto en carga IT:** ninguno directo. Riesgo INDIRECTO: si
  el day tank no se reabastece a tiempo y el generador agota
  combustible durante un outage, el sitio cae catastróficamente
  a IT load shedding cuando los UPS agotan baterías.
- **Tiempo de Inercia:** N/A térmico. PERO el day tank a 30%
  representa ~6-8 h autonomía al 100% load — coordinar transfer
  ANTES de que caiga bajo 20%.
- **Riesgo de derrame:** spill de diesel requiere notificación
  ambiental jurisdiccional (Ontario MOECC en este sitio); kit de
  containment + bandeja de bermas + sorbentes obligatorios pre-
  transfer.
- **Riesgos químicos:** vapores de diesel en zona confinada pueden
  causar náusea + irritación respiratoria; ventilación adecuada
  obligatoria.

---

## 3. Prerrequisitos (Gatekeeper Universal)

- **Lectura precisa del nivel actual** del day tank + del bulk
  tank vía HMI + verificación física con varilla de medición.
- **Cálculo del target fill volume** = (target_level_pct -
  current_level_pct) × tank_capacity_gallons. NO transferir más
  del calculado para evitar overflow.
- **Kit de spill containment** (bandeja, sorbentes, bermas) +
  inspección visual de bermas existentes alrededor de bulk +
  day tanks.
- **Bonding cable** entre bulk tank + transfer pump + day tank
  (verificar continuidad < 1 Ω antes de iniciar — previene
  ignición por descarga estática).
- **PPE químico** (gafas selladas, guantes nitrilo, traje
  resistente a hidrocarburos, botas anti-derrame) + **PPE Cat 2**
  per **CSA Z462-24** si se interviene motor de bomba (LOTO
  eléctrico + **Vivo-Muerto-Vivo**).
- **LOTO mecánico** en válvula de bulk tank durante apertura del
  manhole del day tank + **LOTO eléctrico** en bomba de
  transferencia durante manipulación de cableado (sólo si aplica).
- **Operabilidad de Agentes (Health Check):** Checker + HVAC AI
  (ventilación de la sala de generadores) + Electrical AI
  (validar que generador remains en standby con autonomía
  suficiente durante el transfer) `ONLINE` vía **MCP**.
- **PTW combustible-handling** firmado por Manager on Duty +
  Safety Officer.
- **Notificación ambiental jurisdiccional** si transfer > 500
  galones (Ontario Environmental Protection Act).
- **Herramientas:** flowmeter calibrado, varilla de medición,
  manguera de transferencia certificada anti-estática, multímetro
  para bonding test, torquímetro aislado, candados LOTO duales.
- Personal: técnico mecánico certificado en combustible + fire
  watcher con extintor clase B + supervisor (Maker + Checker —
  **Cuatro Ojos**).

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + capturar lecturas baseline: nivel day tank
   + nivel bulk + autonomía calculada al load actual + temperatura
   ambiente.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Calcular **target fill volume** + verificar que el bulk tank
   tiene capacidad suficiente. Adjuntar cálculo al WO.

   > `[HOLD POINT]` **CONFIRMAR EN CALCULADORA + DOCUMENTAR** el
   > target fill volume. Sin este número claro, NO se inicia
   > transfer — riesgo de overflow.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Establecer **spill containment**: bandeja bajo conexiones,
   bermas perimetrales, sorbentes desplegados, kit de respuesta
   accesible en < 30 s.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Conectar **bonding cable** entre bulk tank + transfer pump +
   day tank + verificar continuidad **< 1 Ω** con multímetro en
   cada par de conexiones.

   > `[HOLD POINT]` **VERIFICAR FÍSICAMENTE** que el bonding está
   > activo en los 3 puntos. Static discharge en presencia de
   > vapor de diesel = ignición instantánea.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Abrir válvula de salida del bulk tank + válvula de entrada del
   day tank lentamente (cuarto de vuelta, 5 s entre cada
   incremento para evitar pressure surge).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Arrancar transfer pump en soft-start desde HMI + monitorear
   flowmeter para confirmar caudal nominal (típicamente 30-50
   GPM dependiendo del modelo).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Monitorear nivel del day tank en HMI **cada 60 s** hasta
   alcanzar 90% del target. Detener transfer 5% antes del target
   final por overshoot del flowmeter.

   > `[HOLD POINT]` **DETENER TRANSFER AL 95% DEL TARGET** (no al
   > 100%) — el flowmeter tiene latencia + el momentum de la
   > columna líquida añade overshoot.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Apagar transfer pump desde HMI + cerrar válvula de salida bulk
   + cerrar válvula de entrada day tank + verificar lectura final
   del nivel + retirar bonding cable.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Retirar spill containment + inspeccionar visualmente cero
   derrame visible + documentar autonomía actualizada del
   generador + notificar al NOC la finalización.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (parameterized triggers):**

- Si en el paso 4 el bonding cable reporta **> 5 Ω** en cualquier
  par → abortar; sin bonding correcto NO se transfiere.
- Si en el paso 6 el flowmeter reporta **caudal < 15 GPM** o
  **> 70 GPM** del nominal → diagnosticar bomba (cavitation,
  blockage); detener transfer.
- Si en el paso 7 el nivel del day tank **alcanza 98%** antes de
  apagar la bomba → emergencia overflow inminente; apagar bomba
  inmediatamente desde E-stop físico + cerrar válvulas manualmente.
- Si en cualquier paso se detecta **olor severo de diesel** fuera
  de spec normal **O derrame visible > 1 galón** → activar
  protocolo HAZMAT + notificación ambiental jurisdiccional dentro
  de **2 horas** (Ontario EPA requirement).

**Secuencia de Restauración:**

1. Apagar transfer pump desde el E-stop físico + HMI.
2. Cerrar válvulas en orden: día tank entrada PRIMERO, luego bulk
   salida (previene back-flow + golpe de ariete).
3. Retirar bonding cable + cerrar manhole.
4. Si hubo derrame: containment con sorbentes + recolección a
   contenedor HAZMAT + notificación ambiental dentro de 2 h +
   chain-of-custody documentada.
5. Si bomba defectuosa: etiquetar OUT OF SERVICE + escalar a
   maintenance + verificar bomba de respaldo si N+1 aplica.
6. Documentar el aborto + causa raíz + reprogramar transfer.
7. Verificar autonomía del generador con nivel actual del day
   tank — si < 8 h al load proyectado, escalar al Manager on
   Duty para programar load shedding preventivo.

**Ventana de reversión bounded by:** la operación es planificada,
no de emergencia; budget de reversión holgado (~4 h). PERO si el
day tank quedó parcialmente lleno y la transfer pump falló, el
generador opera con autonomía reducida — coordinar refill
manual con cisterna mobile si autonomía calculada < 12 h.
