# MOP-016 — CRAH: Reemplazo de Filtros en Caliente (Hot-Swappable)

**Asset Category:** CRAH · **Work Mode:** En vivo (ventiladores
operativos durante el reemplazo). **Compliance:** CSA Z462-24,
NFPA 70E, ASHRAE TC 9.9, OCP Cooling Environments.

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** CRAH-XX (per Data Hall)
* **Estado Final Esperado:** Bancos de filtros nuevos instalados + sellado perimetral validado + dP y presión estática vueltos a baseline ± 10%

Sustituir los bancos de filtros internos de una CRAH operativa **sin
apagar los ventiladores**, monitoreando la presión diferencial (`dP`)
de la manejadora para evitar la pérdida de presión estática en el
piso falso (lo que provocaría bypass de aire caliente hacia los
racks adyacentes).

**Equipo objetivo:** CRAH específica (`crah_a1`, etc.) + bancos de
filtros. **Ubicación:** Data Hall / pasillo caliente.

---

## 2. Evaluación de Impacto y Riesgos Térmicos


- **Vector Mecánico/Térmico (Tiempo de Inercia ~10 min breach ASHRAE A1; bypass de aire caliente si presión estática cae)**

- **Impacto en carga IT:** durante el reemplazo, el caudal volumétrico
  (`V_dot`) cae transitoriamente; el `dT` del aire sube por
  `Q_s = rho * V_dot * Cp * dT` — el caudal reducido fuerza un
  `dT` mayor para mover la misma carga sensible.
- **Tiempo de Tolerancia Térmica:** si la CRAH se restringe sin
  redundancia, la sala excede el rango ASHRAE A1 (`T_inlet > 27 °C`)
  en **≈ 10 min** al 100% carga. Las CRAHs vecinas absorben durante
  la maniobra.
- **Riesgo de bypass de aire caliente:** si la presión estática del
  piso falso cae, los racks adyacentes succionan aire de retorno
  caliente — efecto cascada.
- **Nivel de energía incidente:** **Arc Flash Categoría 1** (CRAH
  enclosure low-voltage; el motor de ventilador es típicamente VFD
  240V o 480V trifásico). No se abre el gabinete del motor durante
  esta maniobra.

---

## 3. Parámetros Físicos de Referencia (Prerrequisitos)

- **Caudal nominal de la CRAH** y `V_dot_min` aceptable durante el
  reemplazo (típicamente ≥ 70% nominal).
- **`dP` baseline a través de los filtros** documentado pre-reemplazo
  + `dP_max` aceptable (umbral del fabricante).
- **Presión estática del piso falso** baseline; degradación máxima
  aceptable: ± 10%.
- **CRAHs vecinas con margen de capacidad** para absorber
  temporalmente; verificar antes de iniciar.
- **Mechanical LOTO** en el latch / portezuela del banco de filtros
  con alivio de presión interna previo.
- **Motor LOTO eléctrico disponible** para abort emergency en el
  ventilador (sin aplicar durante la operación normal); **CSA
  Z462-24**, **PPE Cat 1**. Si llegara a aplicarse el LOTO eléctrico:
  **Vivo-Muerto-Vivo** en bornes del motor disconnect.
- Durante el reemplazo en caliente, respetar **límite de aproximación
  restringida** al gabinete del VFD (no abrirlo durante esta
  maniobra; está bajo tensión).
- **Herramientas:** filtros nuevos certificados (MERV / EPA según
  spec del DC), manómetro diferencial, equipo de protección
  respiratoria (los filtros viejos contienen polvo + partículas).
- **PTW** firmado por el Manager on Duty.
- Personal: técnico ejecutante + supervisor (Maker + Checker —
  **Cuatro Ojos**).

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + verificar margen de capacidad en CRAHs
   vecinas + documentar `dP` baseline + presión estática del piso
   falso baseline.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > `[HOLD POINT]` Confirmar dP y presión estática del piso falso dentro de ± 10 % baseline antes de iniciar el reemplazo.

2. Verificar que el VFD del ventilador está en modo Auto (sin
   intervenir; la CRAH compensará el `dP` creciente subiendo RPM).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Aplicar **Mechanical LOTO** en latch del banco de filtros +
   alivio de presión interna previo a la apertura.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Abrir portezuela; retirar bancos de filtros viejos con EPP
   respiratorio (los filtros tienen carga de polvo).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Inspeccionar visualmente el interior de la CRAH; documentar
   cualquier signo de degradación o partículas anómalas.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Insertar bancos nuevos certificados; verificar sellado
   perimetral (un sellado pobre causa bypass de aire sin filtrar).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Cerrar portezuela + retirar **Mechanical LOTO** + medir `dP`
   nuevo + presión estática del piso falso; verificar que ambos
   vuelven a baseline ± 10%.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (disparadores térmicos automáticos):**

- Si durante la maniobra la **temperatura de inlet de los racks
  vecinos sube por encima de los 27 °C** (límite ASHRAE A1) por
  más de 60 s → abortar; reinstalar los filtros viejos
  temporalmente.
- Si la **presión estática del piso falso cae > 15%** → abortar;
  los racks adyacentes están succionando aire caliente.
- Si en el paso 5 la inspección revela daño interno (corrosión,
  partículas metálicas, evidencia de impacto) → no continuar;
  escalar a Engineering para evaluación completa.

**Secuencia de Reversión:**

1. Reinstalar bancos de filtros viejos (aún viables temporalmente);
   verificar sellado.
2. Cerrar portezuela + monitorear `dT` y presión estática hasta
   normalizar.
3. Documentar el aborto + causa raíz + reprogramar la maniobra con
   mayor margen (más CRAHs vecinas disponibles, o reducir carga IT
   temporalmente).

**Ventana de reversión bounded by:** el Tiempo de Tolerancia Térmica
(≈ 10 min para breach ASHRAE A1); la reversión debe iniciarse en
< 50% de esa ventana si los disparadores se activan.
