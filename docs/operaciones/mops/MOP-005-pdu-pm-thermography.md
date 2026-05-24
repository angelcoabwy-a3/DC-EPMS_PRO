# MOP-005 — PDU: Mantenimiento Preventivo Anual (Termografía + Lógica de Control)

**Asset Category:** PDU · **Work Mode:** De-energizado con LOTO.
**Compliance:** CSA Z462-24, NFPA 70E, IEEE 1106, Eaton SOW R-48
preventive maintenance checklist (cuando aplique).

---

## 1. Alcance y Objetivo

Mantenimiento preventivo integral de PDU (Power Distribution Unit):
inspección termográfica bajo Arc Flash, revisión de lógica de control,
calibración de displays, limpieza de filtros de aire de ventilación
forzada, y reapriete de conexiones de barras principales.

**Equipo objetivo:** PDU identificada (`pdu_a` / `pdu_b` / etc.).
**Ubicación:** sala blanca / planta eléctrica del Data Hall.

---

## 2. Evaluación de Impacto y Riesgos

- **Impacto en carga IT:** la PDU alimenta múltiples RPPs aguas abajo;
  su desenergización corta esa rama. Confirmar que la carga IT está
  servida por la PDU redundante (sitio en N degradado durante la
  maniobra).
- **Nivel de energía incidente:** Arc Flash Categoría 3 en los paneles
  expuestos durante la apertura de tapas.
- **Dependencias aguas arriba:** breaker principal aguas arriba + STS
  (si aplica) — punto de bloqueo LOTO.
- **Dependencias aguas abajo:** RPPs alimentados por la PDU y sus
  racks.
- **Riesgos térmicos:** hot-spots en conexiones de barras indican
  par flojo o degradación de tornillería → indicador de RUL.

---

## 3. Requisitos Previos (Prerrequisitos)

- Aprobación de ventana de mantenimiento para desenergizar la PDU.
- **LOTO** en breaker principal aguas arriba + **PPE Cat 3** contra
  Arc Flash per **CSA Z462-24** (verificar etiqueta del equipo).
- **PRE-TRANSFER VALIDATION** (S-DISTRIBUTION-01) si el upstream es
  STS: revisar **historial de alarmas** + estado de la **caja SCR**
  antes de cualquier maniobra de transferencia previa.
- Si la PDU es **Eaton** (SOW R-48), MOP debe incluir verificación
  de **BCMS** + **fibra óptica** de la placa de monitoreo +
  evaluación de **FSBs** + aprobación previa de **firmware** updates.
- **Herramientas:** cámara termográfica calibrada, multímetro
  calibrado, torquímetro aislado, aspiradora HEPA, pintura de torque
  (Torque Seal), candados + tarjetas LOTO personalizados.
- **PTW** firmado por el Manager on Duty.
- Personal: técnico ejecutante + supervisor (Maker + Checker —
  **Cuatro Ojos**).

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + Manager on Duty el inicio de la maniobra.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Revisar + imprimir el historial de alarmas de la PDU
   (últimos 90 días) + estado de la caja SCR del STS aguas arriba.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Confirmar que las RPPs aguas abajo están servidas por la PDU
   redundante; transferir cargas si es necesario antes de
   desenergizar.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Abrir breaker principal aguas arriba + aplicar **LOTO**
   (candados + tarjetas personalizados).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Retirar paneles frontales con **PPE Cat 3** contra Arc Flash.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Ejecutar prueba **Vivo-Muerto-Vivo** en barras principales con
   multímetro calibrado para confirmar ausencia de tensión.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Escaneo termográfico bajo carga preliminar (antes de aplicar LOTO
   completo si la PDU lo permite con paneles laterales abiertos);
   documentar gradientes anómalos.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Reapretar conexiones de barras con torquímetro aislado a la
   especificación del fabricante; marcar con pintura de torque.
   Si la PDU es Eaton: verificar BCMS, conexiones de fibra óptica
   en la placa de monitoreo + evaluación de FSBs vigentes.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Limpiar filtros de aire de ventilación forzada con aspiradora HEPA
   + revisar lógica de control + calibrar displays.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

10. Reinstalar paneles + retirar **LOTO** + energizar + escaneo
    termográfico post-mantenimiento para verificar que no hay
    hot-spots residuales.
    `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto:**

- Si en el paso 6 la prueba Vivo-Muerto-Vivo detecta tensión residual
  → **detener inmediatamente** y revisar diagrama unifilar buscando
  retornos o fallos de LOTO.
- Si la termografía post-mantenimiento revela **hot-spots > 60 °C
  sobre ambiente** en cualquier conexión → no dejar la PDU en
  servicio; reapretar + re-medir antes del cierre.
- Si la inspección visual revela cableado degradado, corrosión o
  daño estructural → no re-energizar; escalar a Engineering.

**Secuencia de Reversión (estado seguro):**

1. Reinstalar paneles frontales de la PDU.
2. Mantener **LOTO** en el breaker principal aguas arriba.
3. Documentar el WO con el estado del equipo + próxima acción
   requerida (re-inspección, reemplazo, escalamiento al fabricante).
4. Notificar al NOC del aborto + causa raíz preliminar.
