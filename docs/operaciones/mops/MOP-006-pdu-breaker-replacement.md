# MOP-006 — PDU: Reemplazo de Breaker Principal o Sub-Alimentador

**Asset Category:** PDU · **Work Mode:** De-energizado total con LOTO.
**Compliance:** CSA Z462-24, NFPA 70E §130, IEEE 1015 (coordination
study verification), Eaton SOW R-48 (cuando aplique).

---

## 1. Alcance y Objetivo

Reemplazo físico de interruptor principal o sub-alimentador en una
PDU por falla, fin de vida útil o mejora de capacidad. Incluye
verificación de la curva de coordinación en prueba secundaria antes
de re-energizar.

**Equipo objetivo:** PDU + breaker específico (main o sub-feeder).
**Ubicación:** sala blanca / planta eléctrica.

---

## 2. Evaluación de Impacto y Riesgos

- **Impacto en carga IT:** desenergización completa de la rama servida
  por el breaker; downstream loads MUST estar en el path redundante.
- **Nivel de energía incidente:** Arc Flash Categoría 4 en bornes
  durante la extracción/inserción mecánica (`racking out / racking in`).
- **Dependencias aguas arriba:** STS (si aplica) + breaker principal
  upstream.
- **Dependencias aguas abajo:** RPPs y racks alimentados por el
  breaker en cuestión.
- **Riesgo crítico de coordinación:** el breaker nuevo DEBE operar
  dentro de la curva del fabricante en prueba secundaria; un
  mismatch significa que la coordinación selectiva del sistema se
  degrada (un fault aguas abajo dispararía el upstream también).

---

## 3. Requisitos Previos (Prerrequisitos)

- Ventana de mantenimiento aprobada + breaker repuesto verificado
  contra el part-number original.
- **LOTO** estricto en el breaker upstream + **PPE Cat 4** contra
  Arc Flash per **CSA Z462-24**.
- **PRE-TRANSFER VALIDATION** (S-DISTRIBUTION-01): revisar
  **historial de alarmas** + estado de la **caja SCR** del STS
  aguas arriba para descartar que el breaker viejo falló por
  upstream issue.
- **Eaton** (SOW R-48) si aplica: BCMS + fibra óptica + FSB +
  firmware approval previo.
- **Herramientas:** racking handle aislado, torquímetro aislado,
  multímetro calibrado, equipo de prueba secundaria de breakers
  (curve tester), candados + tarjetas LOTO.
- **PTW** firmado + plan de prueba secundaria adjunto.
- Personal: técnico ejecutante (calificado en racking) + supervisor
  (Maker + Checker — **Cuatro Ojos**).

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + revisar historial de alarmas del breaker +
   caja SCR del STS aguas arriba.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Confirmar que toda la carga aguas abajo está servida por el path
   redundante.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Abrir breaker upstream + aplicar **LOTO** (candado + tarjeta
   personalizados).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Posicionarse con **PPE Cat 4** completo + cara cubierta + guantes
   dieléctricos con protector de cuero antes de abrir gabinete.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Retirar paneles frontales + ejecutar **Vivo-Muerto-Vivo** en
   bornes del breaker (line + load) para confirmar ausencia de
   tensión.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Racking-out del breaker viejo con racking handle aislado;
   posición de prueba primero, luego extracción.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Insertar breaker nuevo (verificado contra part-number) en
   posición de prueba; ejecutar **prueba secundaria** con curve
   tester contra la especificación del fabricante (overload + short-
   circuit + ground-fault si aplica).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Si la prueba secundaria PASA: racking-in a posición conectada;
   reapretar bornes a torque del fabricante con torquímetro aislado;
   marcar con pintura de torque.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Reinstalar paneles + **Vivo-Muerto-Vivo** post-cierre + retirar
   **LOTO** + energizar breaker upstream + cerrar el breaker nuevo
   + verificar que la rama aguas abajo recibe potencia.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto:**

- Si en el paso 7 la **prueba secundaria FALLA** (el breaker nuevo
  no opera dentro de la curva de coordinación del fabricante):
  - NO insertar a posición conectada
  - NO re-energizar la rama
  - Etiquetar el breaker como defectuoso + escalar a Engineering +
    contactar al fabricante por garantía
- Si en el paso 5 la prueba Vivo-Muerto-Vivo detecta tensión residual
  → **detener inmediatamente** + investigar retornos.
- Si durante el racking el breaker no inserta mecánicamente con
  resistencia normal → no forzar; retirar + inspeccionar guías.

**Secuencia de Reversión:**

1. Si el breaker nuevo falló: reinstalar el breaker viejo en
   posición de prueba (no conectada), reinstalar paneles, mantener
   **LOTO** en upstream.
2. Documentar el WO con la falla + part-number + serial del breaker
   nuevo + evidencia de la prueba secundaria.
3. La rama queda fuera de servicio hasta el dictamen de Engineering /
   fabricante.
4. Notificar al NOC + Manager on Duty.

**Ventana de reversión bounded by:** la autonomía de baterías de los
UPS aguas abajo (si esta PDU es parte del path principal); coordinar
con el CET de turno.
