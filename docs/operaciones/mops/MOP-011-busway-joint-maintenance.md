# MOP-011 — Busway: Mantenimiento de Juntas Mecánicas + Tapas

**Asset Category:** Busway · **Work Mode:** De-energizado por sector
con LOTO. **Compliance:** CSA Z462-24, NFPA 70E, IEC 61439-6,
IEEE 1584 (Arc Flash hazard calculations).

---

## 1. Alcance y Objetivo

Mantenimiento mecánico de un sector del busway: reapriete de uniones,
medición de resistencia de contacto, limpieza de polvo acumulado, y
verificación del estado de las tapas. Operación preventiva para
detectar degradación temprana de los puntos de contacto antes de
generar hot-spots termográficos.

**Equipo objetivo:** sector específico del busway (entre breakers de
seccionamiento) + sus juntas mecánicas + tapas. **Ubicación:**
pasillo del Data Hall.

---

## 2. Evaluación de Impacto y Riesgos

- **Impacto en carga IT:** los racks alimentados por tap-off boxes en
  el sector aislado pierden ese cordón; deben estar servidos por el
  path redundante (sitio en N degradado durante la maniobra).
- **Nivel de energía incidente:** Arc Flash Categoría 3 durante la
  apertura de tapas (busway de-energizado pero residual de capacitancia
  posible).
- **Dependencias aguas arriba:** breakers de seccionamiento del sector
  (puntos de LOTO).
- **Dependencias aguas abajo:** tap-off boxes activas en el sector +
  racks que servían.
- **Riesgos primarios:** contacto deteriorado por par flojo (alta
  resistencia → hot-spot futuro); ingreso de polvo conductor;
  daño mecánico en empaques de las tapas.

---

## 3. Requisitos Previos (Prerrequisitos)

- Ventana de mantenimiento aprobada + tap-off boxes activas en el
  sector confirmadas como respaldadas por path redundante.
- **LOTO** en breakers de seccionamiento aguas arriba y aguas abajo
  del sector + **PPE Cat 3** per **CSA Z462-24**.
- **Herramientas:** torquímetro aislado, micro-ohmímetro
  (medidor de resistencia de contacto, típicamente 4-wire / Kelvin
  bridge), aspiradora HEPA, paños antiestáticos, pintura de torque
  (Torque Seal), candados + tarjetas LOTO.
- **PTW** firmado por el Manager on Duty.
- Personal: técnico ejecutante + supervisor (Maker + Checker —
  **Cuatro Ojos**).

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + confirmar redundancia de las tap-off boxes
   activas en el sector.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Abrir breakers de seccionamiento aguas arriba y aguas abajo del
   sector + aplicar **LOTO** en ambos (candados + tarjetas
   personalizados).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Posicionarse con **PPE Cat 3** + retirar la primera tapa del
   sector con herramientas aisladas.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Ejecutar **Vivo-Muerto-Vivo** en las barras del sector con
   multímetro calibrado para confirmar ausencia de tensión (incluye
   residual capacitivo).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Inspección visual de las juntas mecánicas: buscar decoloración,
   corrosión, acumulación de polvo o evidencia de hot-spot histórico
   (colores azulados / negros).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Limpiar polvo acumulado con aspiradora HEPA + paños antiestáticos
   (**prohibido aire comprimido no filtrado**).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Reapretar conexiones con torquímetro aislado al **torque
   especificado por el fabricante** + marcar tornillería con pintura
   de torque (Torque Seal).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Medir **resistencia de contacto** de cada junta con
   micro-ohmímetro (4-wire); comparar contra umbral del fabricante.
   Repetir pasos 3-8 para cada junta del sector.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Reinstalar tapas + retirar **LOTO** + energizar breakers de
   seccionamiento + verificar estabilidad del sector.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto:**

- Si en el paso 4 la prueba **Vivo-Muerto-Vivo detecta tensión
  residual** después de descarga capacitiva normal → no continuar;
  investigar retornos de energía o fallo de LOTO.
- Si en el paso 5 la inspección revela **evidencia de hot-spot
  histórico severo** (decoloración azul/negra avanzada) → no
  re-energizar; escalar a Engineering para reemplazo de la sección.
- Si en el paso 8 la **resistencia de contacto post-reapriete excede
  el umbral del fabricante** → no re-energizar el sector; reemplazar
  la junta afectada antes del cierre.

**Secuencia de Reversión (estado seguro):**

1. Reinstalar todas las tapas del sector.
2. Mantener **LOTO** en breakers de seccionamiento.
3. Documentar el WO con resultados de micro-ohmímetro + evidencia
   fotográfica + próxima acción (reemplazo de junta, dictamen de
   Engineering).
4. Notificar al NOC + Manager on Duty del aborto + causa preliminar.

**Ventana de reversión bounded by:** las tap-off boxes activas en el
sector dependen del path redundante; coordinar con CET para no
exceder 6 h en single-path por sector.
