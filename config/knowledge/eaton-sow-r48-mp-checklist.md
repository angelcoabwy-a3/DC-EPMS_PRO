---
id: eaton-sow-r48-mp-checklist
title: Eaton SOW R-48 Preventive Maintenance Checklist (PDU / STS / RPP)
source: Eaton SOW R-48 vendor documentation (operator-summarized 2026-05-23)
source_type: vendor_specification
applies_to:
  - pdu
  - sts
  - rpp
tags: [eaton, sow-r48, bcms, fiber-optic, scr-box, alarm-history, fsb, firmware, preventive-maintenance, vendor-specific]
jurisdiction: international
version: "R-48"
voltage_class: "LV"
---

# Eaton SOW R-48 — Preventive Maintenance Checklist

**Status:** Vendor-specific operational knowledge — indexed by
GraphRAG. The Procedure Architect surfaces this checklist whenever
the operator's request mentions `eaton` (the audit gate string-matches
the context — see `S-VENDOR-EATON-01` in
`docs/skills/skill-registry.md`).

**Severity:** This document defines a `caution`-level audit signal,
NOT `hard_stop`. Rationale: the operating fleet is multi-brand;
forcing `hard_stop` on Eaton-only checks would refuse legitimate MOPs
on non-Eaton equipment. The agent therefore surfaces the omissions as
a warning so the operator can re-prompt or acknowledge.

**Pending schema migration (next sprint):** today the agent matches
the vendor on a `eaton` substring in the operator-supplied context
string. A future sprint should add an `Asset.manufacturer` field to
the CMMS model so the match becomes deterministic; until then,
operators are responsible for surfacing the vendor in the context
free-text. Tracked as a `TODO` in `backend/agents/procedure_architect.py`.

---

## Mandatory Inclusions in Eaton PDU / STS / RPP Preventive Maintenance MOPs

Además de la revisión de potencia estándar (termografía, reapriete de
conexiones, limpieza), **todo MOP de mantenimiento preventivo sobre
equipo Eaton debe incluir**:

### 1. BCMS — Branch Circuit Monitoring System

- Verificación de funcionamiento de las **tarjetas de monitoreo BCMS**
  (sensores de corriente por circuito).
- Confirmación de comunicación entre las tarjetas BCMS y el
  controlador maestro (Modbus / SNMP, según firmware).
- Calibración de offsets si el firmware lo permite — registrar la
  fecha y el offset aplicado en el WO.

### 2. Caja Lógica y Caja SCR (para STS)

- **Comprobación de conexiones de cables de control en la caja
  lógica** (verifica torque + integridad de los aislamientos de los
  cables de señal).
- **Comprobación de conexiones de cables de control en la caja SCR**
  (Silicon-Controlled Rectifier) — el corazón de la conmutación
  estática del STS. Las terminaciones aquí son load-bearing para la
  velocidad de transferencia (< 4 ms típico).
- Inspección visual de los disipadores de calor de los tiristores
  SCR — buscar decoloración por sobre-temperatura sostenida.

### 3. Fibra Óptica de Monitoreo

- **Revisión de conexiones de fibra óptica en la placa de monitoreo.**
  Verifica la limpieza de los conectores (LC / SC según modelo) y la
  integridad de los latiguillos.
- Confirmar que el LED de link / status está activo en ambos
  extremos.

### 4. Historial de Alarmas

- **Impresión y revisión exhaustiva del historial de alarmas** de los
  últimos 90 días (o el último ciclo de mantenimiento, lo que sea más
  largo).
- Identificar patrones recurrentes (alarmas intermitentes que se
  auto-resuelven son típicamente el primer indicador de degradación).
- Adjuntar la impresión / export al WO de cierre.

### 5. Field Service Bulletins (FSBs) + Firmware

- **Evaluación de Field Service Bulletins (FSBs)** publicados por
  Eaton desde el último mantenimiento. Verificar si alguno aplica al
  modelo + revisión del equipo.
- **Actualización de firmware con aprobación previa** del Manager on
  Duty. El firmware NO se actualiza durante el mismo ventana del PM
  rutinario — abre un MOP separado con PTW dedicado.
- Documentar la versión de firmware pre y post (si aplica) en el WO.

---

## Pre-Transfer Validation (S-DISTRIBUTION-01 alignment)

Para maniobras de transferencia de carga en STS o PDUs con bypass:

- **Historial de alarmas:** revisado + impreso + sin alarmas activas
  bloqueantes.
- **Estado de la caja SCR:** verificado (LEDs verdes, no eventos
  recientes de sobre-temperatura, no alarmas de degradación de
  tiristor).
- **Sincronización de fuentes:** confirmada vía HMI antes de
  autorizar la transferencia.

Estas tres verificaciones son requisito previo de cualquier MOP de
transferencia en equipo Eaton. El audit gate las matchea como
`historial de alarmas` AND (`estado STS` OR `caja SCR`); su ausencia
en un draft de transferencia STS → `hard_stop` (no `caution` — la
omisión aquí es safety-critical, no opcional).

---

## Cross-references

| Doc type | Section in this checklist |
|---|---|
| **MOP preventivo PDU/RPP Eaton** | §1 BCMS, §2 cables de control, §3 fibra óptica, §4 alarmas, §5 FSBs/firmware |
| **MOP transferencia STS Eaton** | Pre-Transfer Validation block (alarmas + caja SCR + sincronización) |
| **EOP fallo STS Eaton** | §4 (alarmas históricas), §2 (caja SCR inspection) |
