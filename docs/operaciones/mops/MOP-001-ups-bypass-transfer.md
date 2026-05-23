# MOP-001 — UPS: Transferencia a Bypass de Mantenimiento Externo

**Asset Category:** UPS · **Work Mode:** Transferencia (segura `make-before-break`)
seguida de aislamiento total para mantenimiento.
**Compliance:** CSA Z462-24, NFPA 70E, IEEE 1100, lessons from the
Sprint 3 Phase 4 Maker-Checker witness gate.

---

## 1. Alcance y Objetivo

Transferir la carga crítica IT desde la salida del inversor del UPS hacia
el bypass de mantenimiento (Wrap-Around) de forma segura
("make-before-break"), permitiendo el aislamiento eléctrico total del
módulo UPS para su mantenimiento preventivo o correctivo sin afectar la
carga.

**Equipo objetivo:** módulo UPS (Path A o Path B según corresponda),
sus interruptores asociados (RIB / BIB / MIB / MBB) y el banco de
baterías. **Ubicación:** sala UPS del Data Hall correspondiente.

---

## 2. Evaluación de Impacto y Riesgos

- **Impacto en carga IT:** durante la transferencia la carga IT queda
  momentáneamente alimentada por el bypass estático (sin filtrado de
  inversor). Cualquier `sag` o transitorio severo en utility se
  propaga directamente a la carga; verificar previamente que la red
  comercial está estable.
- **Pérdida de redundancia:** durante el aislamiento del módulo UPS,
  el sitio opera con redundancia degradada (N en lugar de 2N en su
  Path); cualquier falla en el Path redundante es ahora un evento de
  pérdida total de respaldo de baterías.
- **Nivel de energía incidente:** en el panel del MBB (bypass de
  mantenimiento externo) la categoría EPP es 2 según etiquetado
  Arc Flash; verificar el sticker de la unidad antes de la maniobra
  por si el cálculo difiere.
- **Dependencias aguas arriba:** Utility commercial, ATS, transformador
  de aislamiento (si aplica).
- **Dependencias aguas abajo:** PDUs, RPPs, regletas, racks, equipo IT.
- **Riesgos eléctricos primarios:** Arc Flash en el panel del MBB
  durante la inserción mecánica, retorno de energía si el banco de
  baterías no se abre antes de la verificación de tensión.

---

## 3. Requisitos Previos (Prerrequisitos)

- Cumplimiento íntegro del estándar **CSA Z462-24** para trabajos
  eléctricos; uso de **PPE Categoría 2** (ropa ignífuga, guantes
  dieléctricos con protector de cuero, pantalla facial y balaclava).
- Verificar que la carga IT no supera la capacidad nominal de la red
  comercial directa.
- Notificar al NOC de las instalaciones el inicio de la maniobra.
- **Permiso de Trabajo (PTW)** firmado por el Manager on Duty.
- **Herramientas:** multímetro calibrado (con certificado vigente),
  candados y tarjetas **LOTO** personalizados, torquímetro aislado,
  lámpara de inspección.
- Personal mínimo: técnico ejecutante + supervisor (Maker + Checker
  para satisfacer el **Principio de los Cuatro Ojos** —
  alineado con el Maker-Checker witness gate del Sprint 3 Phase 4).

---

## 4. Lista de Pasos Secuenciales

> Casillas de verificación: cada paso se firma por el técnico
> ejecutante (Maker) Y por el supervisor (Checker). Mismo operator_id
> en ambas firmas → la firma se rechaza (Maker-Checker enforced
> server-side por `_process_mop_signature`).

1. Verificar en el panel de control HMI del UPS que no existan alarmas
   activas y que la línea de bypass estático esté disponible y
   sincronizada con el inversor.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Desde el HMI, ejecutar el comando para transferir la carga del
   Inversor al **Bypass Estático** (Static Bypass).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Confirmar visualmente en el diagrama unifilar del HMI que el flujo
   de energía pasa exclusivamente por la línea de bypass estático.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Acercarse al tablero del bypass de mantenimiento externo y cerrar
   el interruptor de **Bypass de Mantenimiento (MBB - Maintenance
   Bypass Breaker)**. En este punto, la red comercial alimenta la
   carga en paralelo con el bypass estático.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Abrir inmediatamente el interruptor de salida del UPS (**MIB -
   Module Isolation Breaker**) para aislar la salida del equipo.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Abrir el interruptor de entrada del rectificador (**RIB - Rectifier
   Input Breaker**) y el de la línea de bypass del equipo (**BIB -
   Bypass Input Breaker**).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Abrir el interruptor del banco de baterías.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Verificar en los bornes internos del UPS la **ausencia de tensión**
   utilizando el método **"Vivo-Muerto-Vivo"** con un multímetro
   calibrado antes de iniciar cualquier manipulación física.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto:**

- Si en el paso 1 el HMI indica **"Bypass No Sincronizado"** o
  desfasaje, **abortar el procedimiento**. No forzar la transferencia
  estática bajo ninguna circunstancia. Restablecer el inversor a su
  estado operativo primario.

**Secuencia de Reversión (si la falla ocurre después del paso 4):**

1. Cerrar el interruptor de salida del UPS (MIB).
2. Cerrar el interruptor de entrada del rectificador (RIB) y el de
   bypass (BIB).
3. Cerrar el interruptor del banco de baterías.
4. Desde el HMI, ejecutar el comando para transferir la carga del
   Bypass Estático de vuelta al Inversor.
5. Confirmar en el diagrama unifilar que el flujo de energía pasa por
   el inversor.
6. Abrir el interruptor de bypass de mantenimiento (MBB) para
   restaurar el aislamiento del módulo UPS frente a la red comercial
   directa.
7. Notificar al NOC la reversión + razón de aborto.

**Ventana de reversión bounded by:** la autonomía de baterías a la
carga actual (`battery_runtime_min` reportado por el BMS antes del
paso 7). Si la reversión se inicia con menos del 50% de esa ventana
disponible, escalar al Manager on Duty.
