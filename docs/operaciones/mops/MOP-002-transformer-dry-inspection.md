# MOP-002 — Transformadores: Inspección Interna y Limpieza de Transformador de Tipo Seco

**Asset Category:** Transformer (dry-type) · **Work Mode:** De-energizado
con LOTO aplicado. **Compliance:** CSA Z462-24, NFPA 70E,
IEEE C57.94 (dry-type maintenance practices).

---

## 1. Alcance y Objetivo

Desenergizar, aislar y realizar el mantenimiento preventivo anual
(limpieza en seco y reapriete de conexiones) en un transformador de
distribución (ej. 480V a 208/120V) minimizando el riesgo de relámpago
de arco y fallas térmicas.

**Equipo objetivo:** transformador de tipo seco identificado
(p. ej. `xfmr_a` o `xfmr_b`). **Ubicación:** sala eléctrica del
Building correspondiente.

---

## 2. Evaluación de Impacto y Riesgos

- **Impacto en carga IT:** el transformador alimenta los tableros de
  distribución aguas abajo (PDUs/RPPs); su desenergización corta esa
  rama. Verificar que los racks alimentados por la rama están
  servidos por el Path redundante antes de iniciar (el sitio queda
  en N degradado durante la maniobra).
- **Nivel de energía incidente:** medio (Arc Flash Category 3-4 en
  los paneles primario/secundario expuestos durante el retiro de
  cubiertas frontales); usar la etiqueta del equipo como fuente de
  verdad.
- **Dependencias aguas arriba:** breaker principal aguas arriba (que
  será el punto de bloqueo LOTO) + el bus del switchgear.
- **Dependencias aguas abajo:** PDUs y RPPs alimentados por el
  secundario; verificar el diagrama unifilar antes de iniciar.
- **Riesgos térmicos secundarios:** acumulación de polvo en los
  conductos de ventilación puede degradar el aislamiento de las
  bobinas → la inspección visual es load-bearing para el RUL del
  equipo.

---

## 3. Requisitos Previos (Prerrequisitos)

- Aprobación de ventana de mantenimiento para desenergizar el bus
  correspondiente.
- Aplicación estricta de protocolo de **Bloqueo y Etiquetado (LOTO)**.
- Cumplimiento de **CSA Z462-24** + uso de **PPE contra Arc Flash**
  correspondiente al nivel de energía incidente etiquetado en el
  equipo.
- **Herramientas requeridas:**
  - Multímetro calibrado (certificado vigente)
  - Torquímetro aislado
  - Aspiradora con filtro HEPA
  - Paños antiestáticos (**prohibido el uso de aire comprimido no
    filtrado**)
  - Pintura de torque (Torque Seal) para marcar conexiones verificadas
  - Candados y tarjetas LOTO personalizados
- **PTW (Permiso de Trabajo)** firmado por el Manager on Duty.
- Personal mínimo: técnico ejecutante + supervisor (Maker + Checker —
  Cuatro Ojos).

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Identificar y abrir los interruptores de los tableros de
   distribución aguas abajo alimentados por el transformador para
   eliminar la carga.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Abrir el interruptor principal (Breaker Aguas Arriba) que alimenta
   el primario del transformador.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Instalar candados y tarjetas **LOTO** en el interruptor principal.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Retirar los paneles de inspección frontales del gabinete del
   transformador utilizando **EPP contra Arc Flash** correspondiente
   al nivel de energía incidente etiquetado en el equipo.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Realizar la prueba **"Vivo-Muerto-Vivo"** en los terminales del
   primario y secundario para confirmar la **ausencia total de
   tensión**.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Inspeccionar visualmente las bobinas, soportes aislantes y
   terminales buscando signos de decoloración, agrietamiento o
   acumulación de polvo excesiva.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Aspirar cuidadosamente los conductos de ventilación entre las
   bobinas y limpiar las superficies aislantes con paños
   antiestáticos.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Verificar con el torquímetro que todas las conexiones de cables de
   media/baja tensión y las barras de tierra cumplan con la
   especificación de fábrica. Marcar con pintura de torque (Torque
   Seal) las tuercas verificadas.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Instalar nuevamente los paneles frontales, retirar LOTO y energizar
   el equipo validando la ausencia de ruidos anormales.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto:**

- Si durante el paso 5 el multímetro registra **cualquier nivel de
  tensión residual**, detener inmediatamente el trabajo, alejarse del
  equipo y verificar el diagrama unifilar buscando posibles retornos
  de energía o fallos en el bloqueo.
- Si durante el paso 6 se detectan signos de **agrietamiento severo
  o decoloración indicativa de sobre-temperatura sostenida**, no
  energizar el transformador al final del procedimiento — escalar
  al equipo de Engineering para evaluación de RUL y posible
  reemplazo. La rama queda bloqueada hasta el dictamen.
- Si el torque de cualquier conexión está fuera de especificación y
  no se puede corregir en sitio (perno deformado, hilo de rosca
  dañado), no reinstalar los paneles — escalar y dejar el equipo
  con LOTO aplicado.

**Secuencia de Reversión (estado seguro):**

1. Reinstalar los paneles frontales del gabinete del transformador.
2. Mantener el LOTO en el interruptor principal aguas arriba.
3. Notificar al NOC + Manager on Duty del aborto + causa.
4. Documentar en el WO el estado del equipo y la próxima acción
   requerida (re-inspección, reemplazo, escalamiento a fabricante).
