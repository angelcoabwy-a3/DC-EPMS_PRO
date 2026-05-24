# MOP-028 — Day Tank: Water Removal / Fuel Polishing

**Asset Category:** Day Tank + Polishing Skid · **Work Mode:** Live
(generator en standby; polishing operativo en circuit cerrado);
LOTO mecánico en válvulas de transfer + LOTO eléctrico en bomba
de polishing si se interviene. **Compliance:** ASTM D2276 (fuel
cleanliness particulate), ASTM D6304 (water content Karl Fischer),
NFPA 110, NFPA 30, IEC 60079.

---

## 1. Alcance y Objetivo

* **Identificador (Tag):** DAY-TANK-A + POLISH-SKID-1 (carro
  móvil de polishing o estación fija) + sample port S1-A (toma
  para análisis de pre-polishing) + sample port S2-A (post-polishing)
* **Estado Final Esperado:** water-cut del day tank < 200 ppm per
  ASTM D6304 + sediment bottom drained + filtros del polishing
  skid reemplazados + sample post-polishing documentado en
  laboratory + system operativo

Eliminación de agua libre + agua emulsionada + sediment del
combustible del day tank. Diesel envejecido > 6 meses acumula
agua por condensación (efecto temperatura ambiente diurna) y
biofilm en la interfaz fuel/water — ambos causan **daño
catastrófico al injector del motor diésel del generador** si no
se remedian periódicamente.

**Equipo objetivo:** day tank + polishing skid + filtros (10 μm
particulate + water-coalescing + 1 μm final) + sample ports.
**Ubicación:** sala de generadores.

---

## 2. Evaluación de Impacto y Riesgos

- **Vector Combustible:** PRIMARIO. Diesel contaminado >  500 ppm
  agua causa daño irreversible al injector del generador en
  arranque súbito (overhaul cost ~$80k+ USD). Biofilm en
  fuel/water interface es bio-corrosivo del tanque.
- **Vector Eléctrico:** Arc Flash Categoría 2 si se interviene
  motor de la bomba del polishing skid (480 VAC trifásico
  típico).
- **Impacto en carga IT:** ninguno directo. Riesgo INDIRECTO: si
  el polishing falla y el day tank queda contaminado, próximo
  outage el generador puede no arrancar / fallar in flight —
  cascada total.
- **Riesgo de derrame:** drenaje del bottom puede liberar sediment
  + agua + diesel; spill containment obligatorio.
- **Riesgo químico:** vapores de hidrocarburos + bio-aerosoles
  (Pseudomonas, hongos) si el biofilm es severo.

---

## 3. Prerrequisitos (Gatekeeper Universal)

- **Sample pre-polishing** del bottom del tank vía sample port S1
  enviado a laboratorio certificado **ANTES** de iniciar polishing
  (baseline ASTM D6304 + ASTM D2276 + biological count).
- **Polishing skid certificado** + filtros nuevos en stock (10 μm
  particulate, water-coalescing, 1 μm final).
- **Spill containment** alrededor del polishing skid + bermas
  perimetrales + sorbentes desplegados.
- **Bonding cable** entre day tank + polishing skid (continuidad
  < 1 Ω) — previene ignición por descarga estática.
- **PPE químico** + **respirador con filtro orgánico** (vapores
  hidrocarburos + bio-aerosoles); **PPE Cat 2** per **CSA Z462-24**
  si se interviene motor de bomba + **Vivo-Muerto-Vivo** en bornes.
- **LOTO mecánico** en válvulas de transfer fuel-line (bulk-to-day
  y day-to-engine) durante el polishing en circuit cerrado +
  **LOTO eléctrico** en bomba de polishing si manipulación de
  cableado.
- **Operabilidad de Agentes (Health Check):** Checker + HVAC AI
  (ventilación + monitoreo de O2/LEL en la sala) + Electrical AI
  (alternative power source confirmation si el generador queda
  comprometido durante el polishing) `ONLINE` vía **MCP**.
- **PTW combustible-handling + bio-hazard** firmado por Manager
  on Duty + Safety Officer.
- **Herramientas:** Karl Fischer titrator portátil (verificación
  water-cut en sitio antes de enviar a lab) + multímetro +
  flowmeter + bonding tester + kit de muestreo certificado +
  contenedores HAZMAT etiquetados para sedimento.
- Personal: técnico fuel-handling certificado + supervisor (Maker
  + Checker — **Cuatro Ojos**) + fire watcher.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + documentar baseline del day tank: nivel,
   autonomía calculada, último sample lab result, último polishing
   fecha.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Tomar **sample S1 (pre-polishing)** del bottom del tank +
   verificar in-situ con Karl Fischer (preliminary water-cut) +
   enviar a laboratorio certificado para ASTM D6304 + D2276 + bio.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Confirmar que el generador está en **standby** + autonomía
   actual ≥ 12 h al load proyectado (si autonomía < 12 h, abortar
   y completar bulk transfer primero per MOP-027).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Establecer **spill containment** + **bonding cable** entre
   day tank y polishing skid + verificar continuidad < 1 Ω.

   > `[HOLD POINT]` **VERIFICAR FÍSICAMENTE** bonding + spill
   > containment desplegado antes de abrir cualquier válvula.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Aplicar **LOTO mecánico** en válvula day-to-engine
   (aislar el generador del polishing loop durante la operación)
   + verificar que el generador NO arrancará durante polishing
   (modo Manual / Off en HMI).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Conectar polishing skid en circuit cerrado: suction desde
   bottom del day tank, return al top del day tank después de
   filtros. Arrancar bomba del skid en soft-start.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Drenar **bottom sediment** (primero 5 galones del flujo desde
   skid output) directamente a contenedor HAZMAT (NO de retorno al
   tank) + etiquetar contenedor + chain of custody.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Continuar polishing en circuit cerrado **mínimo 4 horas** (un
   ciclo completo de toda la masa del tank), monitoreando dP a
   través de los filtros + flowrate.

   > `[HOLD POINT]` Cada **60 min** tomar **sample intermedio**
   > para Karl Fischer preliminary. Si water-cut no decrece
   > monotónicamente, hay problema (filtro saturado, biofilm
   > severo) — escalar antes de extender el ciclo.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Tomar **sample S2 (post-polishing)** vía sample port S2 +
   verificar in-situ Karl Fischer (target water-cut < 200 ppm)
   + enviar a lab. Apagar polishing skid + retirar **LOTO** +
   re-establecer válvula day-to-engine + retirar bonding cable +
   inspeccionar cero derrame + retirar containment + notificar
   al NOC.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (parameterized triggers):**

- Si en el paso 3 la autonomía del generador es **< 12 h** al load
  proyectado → abortar; el polishing en circuit cerrado aisla el
  día tank temporalmente, riesgo de gen no-arrancar durante
  emergencia es inaceptable.
- Si en el paso 4 el bonding reporta **> 5 Ω** en cualquier par →
  abortar; static discharge en presencia de vapor diesel = riesgo
  de ignición inaceptable.
- Si en el paso 7 el sediment drenado contiene **> 50% agua libre
  visible** (interface clara líquido fuel / líquido agua) → el
  tank tiene contaminación severa; polishing solo no resolverá;
  escalar a **tank cleaning** (full drain + manual cleaning per
  ANSI/AIHA Z9.5 confined space entry protocol).
- Si en el paso 8 el water-cut sample intermedio **no decrece > 10%
  entre samples consecutivos** → filtros saturados o biofilm severo;
  reemplazar filtros o escalar.
- Si en el paso 9 el sample post-polishing reporta **water-cut >
  500 ppm** tras 2 ciclos completos → el day tank requiere
  reemplazo o tank cleaning intensivo; etiquetar OUT OF
  SERVICE FOR REMEDIATION + coordinar generator backup.

**Secuencia de Restauración:**

1. Apagar polishing skid.
2. Cerrar válvulas del polishing loop.
3. Retirar **LOTO** de día-to-engine + verificar válvula 100%
   abierta + verificar generador puede arrancar a comando manual
   (test sin carga).
4. Si hubo derrame: containment + sorbentes + recolección HAZMAT
   + notificación ambiental dentro de **2 horas**.
5. Documentar el aborto + samples enviados a lab + próxima acción
   requerida.
6. Si el generador queda comprometido: coordinar **fuel polishing
   de emergencia con vendor móvil** + considerar rental generator
   temporal.

**Ventana de reversión bounded by:** N/A térmico. Lo crítico es
mantener autonomía del generador > 12 h en todo momento —
restauración debe completarse sin reducir la autonomía bajo ese
threshold.
