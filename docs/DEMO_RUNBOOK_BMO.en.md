# 🎬 DEMO RUNBOOK — BMO · Critical Facilities Operations

**Interview date:** 2026-05-29 · **Audience:** Hiring Manager, Critical Facilities Operations
**Platform:** DC-EPMS PRO (A3-Alpha Toronto Area simulator, Path C2) · **Target duration:** ~8-9 min for both features

> **Strategy:** this audience judges *operational safety and procedure discipline*, not flash.
> The two chosen features speak that language: **6-pillar LOTO audit** (safety + standards) and
> **Maker-Checker on MOP signing** (change control / four-eyes). The full flow was verified live
> against the backend on 2026-05-28.

---

## Pre-flight (5 min before)

If the backend is not running (cold start):

```powershell
docker start epms-db          # wait until "healthy"
# docker inspect --format "{{.State.Health.Status}}" epms-db   # -> healthy
python backend\main.py        # wait for "Application startup complete" + /api/health
```

Open **http://127.0.0.1:8080/** → login screen (Epic 10 auth gate).

**Quick health check:** `curl http://127.0.0.1:8080/api/health` should report
`postgres: up`, `rag: up`, `gemma: up`.

---

## Step 0 — Login (~15 s)

| Field | Value |
|---|---|
| Username | `manager` |
| Password | `manager-demo` |

Role **FACILITY_MANAGER** = full access. The top banner shows user + role.

> Other demo users (if you want to show roles): `operator/operator-demo` (L1, read-only),
> `technician/technician-demo` (L2), `safety_a/safety-demo` and `safety_b/safety-demo-b` (SAFETY_OFFICER).

---

## 🔵 DEMO A — LOTO Auditor (the safety catch) · ~3 min

**Sidebar → "LOTO Auditor"** (shield icon). Fields are pre-filled: target `ups_a`, CET `demo_cet`.

### A.1 — The system CATCHES a violation (start with the bad procedure)
1. *Procedure ID* → **`DEMO-UPS-MISSING-DISCHARGE`**.
2. Click **"Audit Procedure"**.
3. **Verified:** badge **HARD_FAIL** (2 hard fails). Point to **Pillar 3 (Capacitor Discharge) = HARD_FAIL, found = NO**.
   > *"This MOP skips the capacitor discharge step. Lethal stored energy. The auditor HARD-STOPs it,
   > citing NEC 460.6 — it will not let the work proceed."*

### A.2 — The same procedure, done right
4. *Procedure ID* → **`DEMO-UPS-COMPLIANT`** → **"Audit Procedure"**.
5. **Verified:** now **Pillar 3 = PASS** (discharge present, NEC 460.6); Pillars 4 (Witness/CSA Z462),
   5 (Sequential), 6 (PPE/NFPA 70E) all PASS.
   > *"Same equipment, correct procedure: it clears the safety chain."*

### ⚠️ Honesty (say it yourself before they spot it)
This scenario **still flags HARD_FAIL on Pillar 2 (2N redundancy)** — the SHI drops **0.54 → 0.42** when
isolating UPS-A. Turn it into a feature:
> *"And notice — independently, it detects that isolating this UPS degrades 2N redundancy below threshold.
> Defense in depth: it doesn't just validate the paperwork, it validates the impact on the live system."*

### The 6 pillars (for follow-up questions)
| Pillar | Validates | Standard |
|---|---|---|
| 1 | Topology impact radius (GraphRAG) | — |
| 2 | 2N redundancy (SHI delta) | — |
| 3 | Capacitor discharge | NEC 460.6 |
| 4 | Witness Gate | CSA Z462 |
| 5 | Sequential order (electrical→hydraulic→purge) | — |
| 6 | PPE matrix | NFPA 70E |

---

## 🟢 DEMO B — Maker-Checker on MOP signing (change control) · ~3 min

**Sidebar → "Procedure Architect"**.

1. *Document type* → **MOP**. *MOP category* appears → leave it on **UPS**.
2. Context chips → click **"Reemplazo de baterías"** (battery replacement — pre-fills the textarea with
   LOTO + PPE Cat 2 + CSA Z462-24 + live-dead-live + back-out).
3. *(Optional)* *Asset id* → **UPS A**.
4. **Operator id** → type **`safety_a`**.
5. Click **Generate** → verdict **APPROVE** (verified, deterministic). The **"Sign & Save to Ledger"** button appears.
6. Click **Sign** → banner **"AWAITING SECOND SIGNATURE"** (maker: safety_a + sha256).
   > *"A MOP cannot be sealed on a single signature — four-eyes principle, Tier IV practice."*
7. *(Optional, high-impact)* Click **Sign** again without changing anything → **403 block**
   *"the same operator cannot be maker and checker"*.
8. **Operator id** → change to **`safety_b`** → click **Sign** → **SEALED**: ledger entry + seq# +
   maker=safety_a / checker=safety_b.
   > *"Segregation of duties enforced by the system, with cryptographic evidence in the immutable ledger."*

---

## 🛡️ Honesty guardrails (critical with this audience)

- **Vocabulary:** if Phase 2 / the DC bus comes up → **"800 VDC unipolar TN-S"**, NEVER "three-phase".
  "Three-phase" applies ONLY to the AC upstream of the MV Rectifier. A facilities engineer will catch it instantly.
- **Scale:** it's a simulator on an RTX 3060 laptop → *"edge-first operations / training platform"*,
  no overselling of real plant telemetry.
- **Quantum (BB84):** if you show it (sidebar "Quantum (BB84 sim)"), it is **educational** — frame it as
  *post-quantum awareness*, never as production. If asked "is this real quantum?", the honest answer is
  "no, it's a didactic BB84 simulator".

---

## Suggested opening
Spend 30 s in **Overview / Site Topology** (site context: 2N, power chains) before entering LOTO.

## Closing line
> *"What you're seeing is critical-infrastructure operations discipline encoded in software: safety
> validated against standards, change control enforced, and an immutable audit trail — operated from the edge."*
