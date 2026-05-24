# MOP-020 — Cooling Tower: Mantenimiento + Limpieza de Piletas y Rociadores (Celda Aislada)

**Asset Category:** Cooling Tower · **Work Mode:** Live (celdas
remanentes operativas) + de-energizado en la celda intervenida con
Mechanical + Motor LOTO. **Compliance:** CSA Z462-24, NFPA 70E,
CTI ATC-105, ANSI/ASSE A10.32 (fall protection).

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** Cooling Tower Cell ID (e.g. Tower-1 Cell-A)
* **Estado Final Esperado:** Pileta limpia + rociadores funcionales + fill sin daño + celda re-conectada + ventilador en soft-start + T_retorno baseline restaurado

Aislar hidráulicamente **una celda** de la torre de enfriamiento
para la remoción de sedimentos de la pileta + limpieza de rociadores
+ inspección del fill, **manteniendo las celdas remanentes
operativas a máxima velocidad** para sostener el rechazo de calor
del sitio durante la intervención.

**Equipo objetivo:** una celda específica de la torre (`tower_1_cell_A`,
etc.). **Ubicación:** techo / nivel exterior de la torre.

---

## 2. Evaluación de Impacto y Riesgos Térmicos


- **Vector Mecánico/Térmico (Tiempo de Inercia ~6 min; biofilm Legionella en sedimentos)**

- **Impacto en carga IT:** durante la intervención, las celdas
  remanentes (típicamente 2 o 3 de 3 o 4 en N+1) absorben el
  rechazo de calor a mayor velocidad; el `Q_rej` total se mantiene
  pero con margen reducido.
- **Tiempo de Tolerancia Térmica:** ≈ 6 min antes de breach
  ASHRAE A2 si la torre completa falla; con una celda aislada y
  el resto operativas, el margen es suficiente para una limpieza
  ordenada (no es maniobra de emergencia).
- **Riesgos físicos:** trabajo en altura (techo); resbalones por
  agua / lodo; exposición a químicos del fill (algicidas residuales).
- **Riesgos biológicos:** los sedimentos pueden contener biofilm
  con Legionella (CTI ATC-105 microbiological quality); EPP
  respiratorio obligatorio durante la remoción.
- **Nivel de energía incidente:** Arc Flash Categoría 2 en el panel
  del motor del ventilador de la celda aislada.

---

## 3. Parámetros Físicos de Referencia (Prerrequisitos)

- **N+1 confirmado:** al menos 1 celda redundante operativa antes
  de aislar.
- **Aprobación de ventana de mantenimiento** con bulbo húmedo
  exterior favorable (T_wb < umbral del fabricante para las celdas
  remanentes a máx velocidad).
- **Caudal mínimo por celda remanente:** verificar que cada celda
  remanente puede sostener su porción de carga incrementada.
- **Mechanical LOTO** en válvulas de entrada / salida de agua + en
  válvulas del rociador + alivio de presión + drenaje completo de
  la pileta antes de cualquier ingreso.
- **Motor LOTO eléctrico** del ventilador de la celda aislada +
  **Vivo-Muerto-Vivo** en bornes del motor disconnect; **CSA
  Z462-24**, **PPE Cat 2**.
- **EPP físico:** arnés de seguridad + casco + guantes anti-corte +
  botas anti-deslizantes + respirador N95 (sedimentos biológicos)
  + traje impermeable.
- **Herramientas:** aspiradora industrial, mangueras de limpieza
  a presión, productos químicos de limpieza compatibles (per CTI
  ATC-105), candados + tarjetas LOTO mecánicos y eléctricos.
- **PTW** + **Permiso de Trabajo en Altura** firmado por el
  Manager on Duty.
- Personal: técnico mecánico calificado en altura + supervisor
  (Maker + Checker — **Cuatro Ojos**) + observador de safety.

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + verificar bulbo húmedo exterior favorable +
   confirmar N+1 + caudal por celda remanente.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Cerrar válvulas de entrada y salida de agua de la celda objetivo
   + aplicar **Mechanical LOTO** en ambas + alivio de presión.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Aumentar velocidad de las celdas remanentes en HMI para absorber
   la carga (ajustar VFDs si aplica); verificar que `T_retorno` se
   mantiene dentro del rango.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > [HOLD POINT] Confirmar T_retorno se mantiene dentro del rango con celdas remanentes a max velocidad antes de aislar la celda objetivo.

4. Apagar el ventilador de la celda objetivo + aplicar **Motor
   LOTO eléctrico** + **Vivo-Muerto-Vivo** en bornes del motor
   disconnect.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Drenar completamente la pileta a contenedor de neutralización
   (los sedimentos pueden tener residuos químicos + biofilm).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Ingresar a la celda con **EPP completo** (arnés + respirador +
   traje); aspirar sedimentos + limpiar rociadores + inspeccionar
   fill por daño.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Enjuagar la pileta + aplicar producto químico de limpieza
   (compatible con sistema químico — coordinar con MOP-019); drenar
   + enjuagar nuevamente.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Retirar **LOTOs** (eléctrico + mecánico); arrancar ventilador
   en soft-start; abrir válvulas lentamente + verificar `T_retorno`
   + ajustar velocidad de celdas remanentes a baseline.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (disparadores térmicos automáticos):**

- Si durante la maniobra la **`T_retorno` del agua sube > 3 °C
  sobre baseline** → re-conectar la celda inmediatamente
  (retirar LOTO, abrir válvulas).
- Si el **bulbo húmedo exterior se degrada** (sube por encima del
  umbral de diseño) durante la maniobra → completar limpieza con
  prisa o abortar; las celdas remanentes pueden no sostener.
- Si en el paso 6 se detecta **daño estructural del fill** (grietas,
  desprendimientos) → no re-energizar hasta inspección de
  Engineering.
- Si hay **derrame químico o evidencia de contaminación
  significativa** durante el drenaje: activar protocolo HAZMAT.

**Secuencia de Reversión (re-conexión de la celda):**

1. Drenar agua de limpieza si no se completó el enjuague.
2. Retirar **Motor LOTO** + verificar bornes con **Vivo-Muerto-
   Vivo**.
3. Retirar **Mechanical LOTO** + abrir válvulas lentamente +
   arrancar ventilador en soft-start.
4. Verificar `T_retorno` vuelve a baseline + restaurar velocidad de
   las celdas remanentes a baseline.
5. Documentar el aborto + causa raíz + reprogramar la limpieza
   con mayor margen de bulbo húmedo o más celdas redundantes.

**Ventana de reversión bounded by:** el Tiempo de Tolerancia
Térmica de la torre (≈ 6 min para breach); con celdas remanentes
operativas el margen es suficiente para reversión ordenada en
< 5 min.
