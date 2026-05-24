# MOP-013 — Chiller: Cambio de Operación y Rotación Secuencial (Staging)

**Asset Category:** Chiller · **Work Mode:** En vivo con motor LOTO
disponible (mechanical LOTO en válvulas + electrical LOTO en motor
disconnect del compresor cuando se desenergiza). **Compliance:**
CSA Z462-24, NFPA 70E, ASHRAE TC 9.9, Uptime Tier IV
(Concurrent Maintainability).

---

## 1. Alcance y Objetivo

Arrancar un Chiller secundario (Standby) y sus bombas asociadas
(condensador + evaporador), ecualizando previamente las presiones en
el colector de agua helada antes de abrir las válvulas motorizadas
para **prevenir golpes de ariete**, y rotar la operación al nuevo
Chiller liberando al primario para mantenimiento.

**Equipo objetivo:** Chiller standby (`chiller_2`) + bombas asociadas
+ colector primario de agua helada. **Ubicación:** Planta Mecánica.

---

## 2. Evaluación de Impacto y Riesgos Térmicos

- **Impacto en carga IT:** durante la transición ambos Chillers
  comparten brevemente el rechazo de calor (`Q_rej = Q_load +
  W_comp`); si la ecualización falla, golpe de ariete puede dañar
  empaques de tuberías + sobre-corriente en el compresor.
- **Tiempo de Tolerancia Térmica:** si el flujo de agua helada se
  interrumpe completamente, la sala IT alcanza el límite ASHRAE A2
  (`T_inlet = 35 °C`) en **≈ 5 min** bajo carga nominal del Phase 1
  (118 racks GB200 @ 142 kW). Cualquier paso de esta maniobra debe
  completarse dentro de esa ventana.
- **Nivel de energía incidente:** Arc Flash Categoría 3 en el panel
  de control del Chiller (durante el motor disconnect del compresor).

---

## 3. Parámetros Físicos de Referencia (Prerrequisitos)

- **Caudal mínimo:** GPM ≥ 70% del nominal del Chiller durante la
  transición.
- **`dP` operativo:** diferencia de presión entre suministro y
  retorno dentro del rango del fabricante (típicamente ± 20% del
  baseline).
- **ATD (Approach Temperature Difference):** verificar antes y
  después; si crece > 2 °C, indica fouling o flujo insuficiente.
- **Mechanical LOTO** en válvulas motorizadas que serán manipuladas
  (alivio de presión interna previo a cualquier apertura de bridas).
- **Motor LOTO eléctrico** disponible para abort emergency en el
  compresor del Chiller secundario (CSA Z462-24, **PPE Cat 3**).
- **Herramientas:** manómetros calibrados, sensores de vibración,
  cámara termográfica, candados + tarjetas LOTO mecánicos y
  eléctricos, multímetro calibrado.
- **PTW** firmado por el Manager on Duty.
- Personal: técnico mecánico + supervisor (Maker + Checker —
  **Cuatro Ojos**).

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + verificar estado del Chiller primario + standby
   en el HMI (sin alarmas activas).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Arrancar bombas de condensador + evaporador del Chiller standby
   en modo **soft-start**; verificar caudal alcanzado ≥ 70% nominal.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. **Ecualizar presiones** del colector con válvulas de bypass
   ANTES de abrir las válvulas motorizadas hacia el nuevo Chiller
   (prevención golpe de ariete).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Arrancar Chiller standby; verificar setpoint + ATD + COP en HMI
   durante 60 s antes de continuar.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Abrir lentamente las válvulas motorizadas del nuevo Chiller hacia
   el colector primario; monitorear vibración + ruido.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Verificar transferencia de carga: el nuevo Chiller absorbe carga
   creciente sin disparo del compresor.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Aplicar Motor LOTO eléctrico al compresor del Chiller primario
   (a desconectar) + **Vivo-Muerto-Vivo** en bornes del motor
   disconnect + cerrar válvulas mecánicas + aplicar **LOTO mecánico**
   en válvulas con alivio de presión previo.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Documentar fotográficamente el estado final + rotar etiquetas de
   primario / standby en HMI + notificar al NOC la finalización.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (disparadores térmicos automáticos):**

- Si la **temperatura del agua de suministro supera los 12 °C por
  más de 45 segundos** → abortar inmediatamente; restaurar Chiller
  primario.
- Si en el paso 3 la presión no se ecualiza dentro de ± 10% en 60 s
  → no abrir válvulas motorizadas; investigar bloqueo en bypass.
- Si en el paso 5 se detecta vibración anómala o ruido de cavitación
  → cerrar válvulas + investigar.
- Si en el paso 6 el compresor del nuevo Chiller dispara por sobre-
  corriente → abortar + restaurar primario.

**Secuencia de Reversión (R1 — restauración del primario):**

1. Re-abrir válvulas motorizadas del Chiller primario.
2. Confirmar absorción de carga + estabilidad de ATD.
3. Cerrar válvulas + apagar el Chiller standby.
4. Verificar temperatura de suministro vuelve dentro del rango.
5. Notificar al NOC + Manager on Duty del aborto + causa preliminar.

**Ventana de reversión bounded by:** el Tiempo de Tolerancia Térmica
de la sala IT (≈ 5 min ASHRAE A2 breach al 100% carga); la
restauración del primario debe completarse en < 50% de esa ventana.
