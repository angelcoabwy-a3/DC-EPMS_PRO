# 🎬 DEMO RUNBOOK — BMO · Critical Facilities Operations

**Fecha entrevista:** 2026-05-29 (mañana) · **Audiencia:** Hiring Manager, Critical Facilities Operations
**Plataforma:** DC-EPMS PRO (A3-Alpha Toronto Area simulator, Path C2) · **Duración objetivo:** ~8-9 min los 2 features

> **Estrategia:** esta audiencia juzga *seguridad operativa y disciplina de procedimientos*, no lo flashy.
> Los 2 features elegidos hablan ese idioma: **LOTO 6-pilares** (seguridad + estándares) y
> **Maker-Checker en firma de MOP** (control de cambios / Cuatro Ojos). Todo el flujo fue
> verificado en vivo contra el backend el 2026-05-28.

---

## Pre-flight (5 min antes)

Si el backend no está corriendo (arranque en frío):

```powershell
docker start epms-db          # esperar a que quede "healthy"
# docker inspect --format "{{.State.Health.Status}}" epms-db   # -> healthy
python backend\main.py        # esperar "Application startup complete" + /api/health
```

Abrir **http://127.0.0.1:8080/** → pantalla de login (gate de Epic 10).

**Verificación rápida de salud:** `curl http://127.0.0.1:8080/api/health` debe reportar
`postgres: up`, `rag: up`, `gemma: up`.

---

## Paso 0 — Login (~15 s)

| Campo | Valor |
|---|---|
| Usuario | `manager` |
| Password | `manager-demo` |

Rol **FACILITY_MANAGER** = acceso total. El banner superior muestra usuario + rol.

> Otros usuarios demo (por si querés mostrar roles): `operator/operator-demo` (L1, solo lectura),
> `technician/technician-demo` (L2), `safety_a/safety-demo` y `safety_b/safety-demo-b` (SAFETY_OFFICER).

---

## 🔵 DEMO A — LOTO Auditor (el catch de seguridad) · ~3 min

**Sidebar → "LOTO Auditor"** (icono escudo). Campos pre-cargados: target `ups_a`, CET `demo_cet`.

### A.1 — El sistema ATRAPA una violación (arrancar con el procedimiento malo)
1. *Procedure ID* → **`DEMO-UPS-MISSING-DISCHARGE`**.
2. Click **"Audit Procedure"**.
3. **Verificado:** badge **HARD_FAIL** (2 hard-fails). Señalar **Pilar 3 (Capacitor Discharge) = HARD_FAIL, found = NO**.
   > *"Este MOP omite el paso de descarga de capacitores. Energía almacenada letal. El auditor
   > hace HARD-STOP citando NEC 460.6 — no deja ejecutar."*

### A.2 — El mismo procedimiento, bien hecho
4. *Procedure ID* → **`DEMO-UPS-COMPLIANT`** → **"Audit Procedure"**.
5. **Verificado:** ahora **Pilar 3 = PASS** (descarga presente, NEC 460.6); Pilares 4 (Witness/CSA Z462),
   5 (Sequential), 6 (PPE/NFPA 70E) en PASS.
   > *"Mismo equipo, procedimiento correcto: pasa la cadena de seguridad."*

### ⚠️ Honestidad (decirlo vos antes de que lo noten)
Este escenario **igual marca HARD_FAIL en Pilar 2 (Redundancia 2N)** — el SHI cae **0.54 → 0.42** al
aislar UPS-A. Convertirlo en feature:
> *"Y miren: independientemente detecta que aislar esta UPS degrada la redundancia 2N bajo umbral.
> Defensa en profundidad — no solo valida el papel, valida el impacto en el sistema vivo."*

### Los 6 pilares (para responder preguntas)
| Pilar | Valida | Estándar |
|---|---|---|
| 1 | Radio de impacto topológico (GraphRAG) | — |
| 2 | Redundancia 2N (delta SHI) | — |
| 3 | Descarga de capacitores | NEC 460.6 |
| 4 | Witness Gate | CSA Z462 |
| 5 | Orden secuencial (eléctrico→hidráulico→purga) | — |
| 6 | Matriz PPE | NFPA 70E |

---

## 🟢 DEMO B — Maker-Checker en firma de MOP (control de cambios) · ~3 min

**Sidebar → "Procedure Architect"**.

1. *Document type* → **MOP**. Aparece *MOP category* → dejar **UPS**.
2. Chips de contexto → click **"Reemplazo de baterías"** (pre-llena el textarea con LOTO + PPE Cat 2 +
   CSA Z462-24 + Vivo-Muerto-Vivo + Back-out).
3. *(Opcional)* *Asset id* → **UPS A**.
4. **Operator id** → escribir **`safety_a`**.
5. Click **Generate** → verdict **APPROVE** (verificado, determinístico). Aparece **"Sign & Save to Ledger"**.
6. Click **Sign** → banner **"AWAITING SECOND SIGNATURE"** (maker: safety_a + sha256).
   > *"Un MOP no se sella con una sola firma — four-eyes / Cuatro Ojos, práctica Tier IV."*
7. *(Opcional, impacta)* Click **Sign** de nuevo sin cambiar nada → **bloqueo 403**
   *"el mismo operador no puede ser maker y checker"*.
8. **Operator id** → cambiar a **`safety_b`** → click **Sign** → **SEALED**: entry de ledger + seq# +
   maker=safety_a / checker=safety_b.
   > *"Segregación de funciones forzada por el sistema, con evidencia criptográfica en el ledger inmutable."*

---

## 🛡️ Guardrails de honestidad (críticos con esta audiencia)

- **Vocabulario:** si surge Fase 2 / bus DC → **"800 VDC unipolar TN-S"**, NUNCA "trifásico".
  "Trifásico" aplica SOLO al AC upstream del MV Rectifier. Un facilities engineer lo caza al vuelo.
- **Escala:** es simulador sobre laptop RTX 3060 → *"plataforma edge-first de operación / entrenamiento"*,
  sin overselling de telemetría de planta real.
- **Quantum (BB84):** si lo mostrás (sidebar "Quantum (BB84 sim)"), es **educativo** — enmarcalo como
  *awareness post-quantum*, jamás como producción. Si preguntan "¿es cuántico real?", la respuesta honesta
  es "no, es un simulador BB84 didáctico".

---

## Apertura sugerida
Arrancar 30 s en **Overview / Site Topology** (contexto del site: 2N, power chains) antes de entrar a LOTO.

## Cierre (una línea)
> *"Lo que ven es disciplina de operación de infraestructura crítica codificada en software: seguridad
> validada contra estándares, control de cambios forzado y auditoría inmutable — operada desde el edge."*
