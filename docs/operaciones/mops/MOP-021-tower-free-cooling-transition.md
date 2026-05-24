# MOP-021 — Cooling Tower: Transición a Modo Free Cooling (Water-Side Economizer)

**Asset Category:** Cooling Tower + Chiller + Plate HX · **Work Mode:**
Live coordinated transition (apagado controlado de compresores +
redirección de flujo). **Compliance:** CSA Z462-24, NFPA 70E,
ASHRAE TC 9.9, ASHRAE 90.4 (Energy Standard for Data Centers).

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** Cooling Tower + Chillers + Plate HX
* **Estado Final Esperado:** Compresores apagados con LOTO + Free Cooling activo + T_suministro dentro del rango sin compresores + reducción 60-80% en W_comp

Maniobra crítica de **eficiencia energética**: apagar los compresores
de los Chillers y redirigir el agua de las torres directamente a un
**intercambiador de calor de placas** de alta eficiencia cuando las
condiciones termodinámicas externas (temperatura de bulbo húmedo
exterior favorable) lo permitan. Reduce dramáticamente `W_comp`
sustituyendo enfriamiento mecánico por enfriamiento por evaporación
ambiente.

**Equipo objetivo:** Chillers + plate HX (`heat_exchanger_1`) +
válvulas de bypass + bombas. **Ubicación:** Planta Mecánica.

---

## 2. Evaluación de Impacto y Riesgos Térmicos


- **Vector Mecánico/Térmico (Tiempo de Inercia ~5 min; bulbo húmedo crítico T_wb ≤ T_supply - 5 °C)**

- **Impacto en carga IT:** durante la transición, el `Q_rej` debe
  mantenerse continuo; un timing pobre permite que `T_suministro`
  derive fuera del rango.
- **Tiempo de Tolerancia Térmica:** ≈ 5 min ASHRAE A2 al 100%
  carga sin rechazo activo de calor; la transición debe completarse
  en < 90 s.
- **Condición termodinámica obligatoria:** bulbo húmedo exterior
  (`T_wb`) **≤ T_suministro_objetivo - 5 °C** para que el HX de
  placas pueda alcanzar el setpoint sin compresores. Si el `T_wb`
  no es favorable, NO se debe iniciar la transición.
- **Nivel de energía incidente:** Arc Flash Categoría 3 al
  desenergizar motores de compresores.
- **Riesgo de oscilación:** si el `T_wb` está marginal, el sistema
  puede oscilar entre modo Free Cooling y modo Chiller (hunting);
  perdida de eficiencia.

---

## 3. Parámetros Físicos de Referencia (Prerrequisitos)

- **Bulbo húmedo exterior** medido + verificado **≤ T_suministro -
  5 °C** durante la última hora con tendencia estable.
- **Plate HX limpio y validado** (último PM dentro de los 12
  meses); `ATD` baseline < 2 °C.
- **Caudal de torre incrementado** disponible (las bombas de
  condensador deben soportar la operación a HX directo).
- **Mechanical LOTO** en válvulas de bypass de los Chillers cuando
  se aíslan los compresores + alivio de presión.
- **Motor LOTO eléctrico** en los compresores de los Chillers
  apagados + **Vivo-Muerto-Vivo** en bornes; **CSA Z462-24**,
  **PPE Cat 3**.
- **PTW** firmado por el Manager on Duty (maniobra de alta
  visibilidad operacional).
- Personal: técnico mecánico + supervisor (Maker + Checker —
  **Cuatro Ojos**).

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + verificar `T_wb exterior ≤ T_suministro -
   5 °C` con tendencia estable la última hora.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > `[HOLD POINT]` Confirmar T_wb exterior ≤ T_suministro - 5 °C con tendencia estable la última hora antes de iniciar la transición.

2. Verificar plate HX limpio (`ATD < 2 °C`) + bombas de
   condensador con margen de caudal.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Abrir válvulas de derivación hacia el plate HX (válvulas
   motorizadas) en paralelo con los Chillers — operación dual
   temporalmente para no perder rechazo.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Verificar que el plate HX absorbe carga creciente; monitorear
   `T_suministro` durante 60 s.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Cuando el plate HX absorba > 70% del `Q_load`: iniciar shutdown
   controlado de los compresores de Chillers (uno a la vez con
   pausa de 30 s entre cada uno).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Aplicar **Motor LOTO eléctrico** en motores de compresores
   apagados + **Vivo-Muerto-Vivo** en bornes del motor disconnect.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Aplicar **Mechanical LOTO** en válvulas de bypass de los
   Chillers (cierre completo) + alivio de presión interna.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Verificar régimen de Free Cooling estable: `T_suministro` dentro
   del rango durante 10 min sin compresores; documentar consumo
   energético antes / después (reducción típica de 60-80% en
   `W_comp`).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Notificar al NOC la finalización + ajustar control para vigilar
   `T_wb` (si sube por encima del umbral, retorno automático a
   modo Chiller — operación inversa).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (disparadores térmicos automáticos):**

- Si la **`T_suministro` excede el setpoint + 2 °C** durante la
  transición → revertir inmediatamente a modo Chiller (retirar
  LOTOs + arrancar compresores secuencialmente).
- Si el **`T_wb` exterior se degrada** durante la operación de
  Free Cooling (sube por encima del umbral) → ejecutar transición
  inversa (arrancar Chillers + cerrar válvulas de derivación al
  plate HX).
- Si el **plate HX exhibe `ATD > 3 °C`** durante operación → el
  HX está saturado o fouling severo; revertir a Chiller +
  programar limpieza del HX.
- Si **oscilación detectada** (alternancia rápida entre modos):
  forzar modo Chiller hasta análisis de causa raíz.

**Secuencia de Reversión (R1 — retorno a Chiller):**

1. Retirar **Motor LOTO eléctrico** + **Vivo-Muerto-Vivo** en
   bornes; verificar ausencia de tensión residual.
2. Retirar **Mechanical LOTO** en válvulas de bypass + abrir
   lentamente.
3. Arrancar compresores en soft-start uno a la vez (MOP-013 staging
   sequence aplica).
4. Cerrar válvulas hacia plate HX gradualmente cuando los Chillers
   absorban la carga.
5. Verificar `T_suministro` vuelve a setpoint + documentar el
   aborto.

**Ventana de reversión bounded by:** el Tiempo de Tolerancia
Térmica (≈ 5 min); la transición inversa debe iniciarse en < 60 s
de detectar disparador.
