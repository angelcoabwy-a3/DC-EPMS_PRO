# DC-EPMS PRO — Canonical Demo Script (v2, 12 min)

**Audience**: Microsoft CO+I CET Lead Architect panel (or Equinix equivalent)
**Duration**: 12 minutes (10 min demo + 2 min Q&A buffer)
**Mode**: Live walkthrough on this laptop, browser at `http://127.0.0.1:8080/`
**Maintainer**: Wilmer Y. Angel Beltran · a3semi
**Locked**: 2026-05-09 — supersedes the LOTO-only v1 script.

This script is the canonical 12-min walkthrough. Anything outside this list of acts is **out of scope** for the live demo — discuss in Q&A only.

---

## 0. Pre-flight (15 min before recording / panel)

```powershell
# State reset to a known baseline (idempotent, ~2s)
.\scripts\_demo\replay_demo.ps1
```

The script wipes work_orders, replays the postgres snapshot, then injects three fresh predictive_kalman P1 LOTO targets in `pending_approval`:

| Subsystem | Asset | Channel | Kalman z | Standard reference |
|---|---|---|---|---|
| Power Distribution | `rpp_a_01` | `thd_i_pct` | 12.8 | IEEE 519-2014 §5.1 |
| DLC Cooling | `cdu_a_01` | `loop_flow_lpm` | 15.6 | ASHRAE TC 9.9 W17 |
| Backup Power | `genset_a_01` | `oil_pressure_psi` | 19.2 | NFPA 110-2022 §8.4 |

**Browser pre-checks** (Ctrl+Shift+R hard reload first):
- `http://127.0.0.1:8080/api/health` returns `postgres=up`, `gemma=up`
- `http://127.0.0.1:8080/#maintenance` shows 6 open WOs (3 pending P1 + 3 approved P2/P3 historical)
- `http://127.0.0.1:8080/#tech-assist` renders with all 3 panels

---

## Act 1 — Context (1:00)

> *"I'm Wilmer Angel Beltran, a CET. What you're about to see is DC-EPMS PRO — an AI-native edge operations platform I built to simulate Tier IV at hyperscale. The site model is **A3-Alpha Toronto Area, Path C2: 67 MW, 368 racks** total. Phase 1 deployed: 118 GB200 NVL72 racks at 142 kW on 480 VAC trifásico 2N. Phase 2 target Q2 2026: 250 GB300 NVL144 racks at 200 kW, downstream 800 VDC unipolar TN-S — the bus is unipolar, not three-phase. SSCB clearing window is 1–100 µs per IEC 60947-2."*
>
> *"The platform runs entirely on this laptop — RTX 3060, 6 GB VRAM, no cloud dependency. That's deliberate, per ADR-006 Deterministic Sandbox. AI drafts, CET approves; the LLM is never on the critical path."*

**Visual**: terminal showing `git log --oneline --decorate -n 4` (most recent tags visible).

---

## Act 2 — The 3-subsystem predictive arc (3:30) — *the demo killer*

> *"The platform's job is to predict failures before they cascade. Watch the Maintenance backlog."*

**Click** Maintenance in the sidebar. Three pending P1 LOTO work orders, each from a different subsystem.

> *"Three predictive_kalman work orders. None of these were created by a human. They were emitted by the Kalman pipeline — synthetic Send-on-Delta filter watching 238 channels of telemetry — when the innovation residual on a specific channel exceeded 3-sigma sustained over 3 windows. Let me drill into each."*

### Drill-down sequence (click the chevron `▶` on each row)

**rpp_a_01** — Power Distribution
> *"Total Harmonic Distortion of Current at 18.4% — IEEE 519-2014 Section 5.1 caps that at 8% for V<69kV. Sustained over 3 windows. Suggested action is in the row: PQ analyzer scan plus capacitor bank verification on the upstream UPS rectifier. The telemetry snapshot panel below shows the captured per-phase currents — 412 / 398 / 421 amps, 2.8% imbalance — that's the moment-of-anomaly state, frozen in the work order JSON for forensics."*

**cdu_a_01** — DLC Cooling
> *"Coolant Distribution Unit, loop flow drift. Rated 180 LPM, last emission 142 LPM — that's a 22% deficit. ASHRAE TC 9.9 W17 spec. The risk is GPU junction temperature excursion at the next training step burst — a GB200 in turbo will push 1.4 kW into a manifold that can't carry the heat away. The Kalman z-score is 15.6, flagged before any thermal alarm fired."*

**genset_a_01** — Backup Power
> *"Backup genset. Oil pressure dropped to 38 psi during the weekly load-bank exercise — rated band is 45–65 at 1800 RPM. NFPA 110-2022 Section 8.4, Level 1 EPSS. The narrative writes itself: oil pump inspection plus filter change before the genset is ever called for a real utility outage. Kalman z=19.2 — highest of the three."*

### CET signature flow

> *"Here's the audit-trail discipline. I click Approve on rpp_a_01."*

**Click** ✓ on rpp_a_01 → CET prompt → confirm dialog → row flips to `approved` with timestamp + CET id.

> *"`pending_approval → approved`. CET signature locked. ADR-006 satisfied."*

**Then attempt to re-approve the same WO via curl** (have a terminal pre-staged):
```powershell
curl -X POST http://127.0.0.1:8080/api/cmms/work-orders/<the-wo-id>/approve `
  -H "Content-Type: application/json" -d '{\"cet_id\":\"mallory.attacker\"}'
```

> *"HTTP 409 Conflict. State machine refuses the second approval. The original signature can never be silently overwritten — that's the audit-trail integrity guarantee. We caught this in our own session two days ago and shipped the fix as DC-EPMS-040."*

---

## Act 3 — LOTO Auditor (3:00) — *the safety-critical agent*

> *"Predictive maintenance is half the picture. The other half is making sure the work itself is safe. The LOTO Auditor validates Method-of-Procedure documents against six engineering pillars before any CET ever locks out a breaker."*

**Visual**: navigate to `http://127.0.0.1:8080/#loto`.

```bash
curl -X POST http://127.0.0.1:8080/api/loto/audit \
  -H "Content-Type: application/json" \
  -d '{"procedure_id":"MOP-ATS-MONTHLY-001","target_component_id":"ups_a","cet_on_duty":"wilmer"}'
```

> *"`MOP-ATS-MONTHLY-001` against `ups_a`. Twelve milliseconds end-to-end. Sixteen sources consulted. The verdict cites NEC 460.6 by section because the procedure forgot capacitor discharge. Six hundred volt DC link, hundreds of joules in the bus capacitors, breaker open, lockout on — and a CET reaching in could still die. The auditor catches that in 12ms."*

> *"Six pillars, each grounded in a specific standard:"*
> - *"Pillar 1 — Topology + GraphRAG impact radius"*
> - *"Pillar 2 — 2N redundancy survival via SHI delta"*
> - *"Pillar 3 — Capacitor discharge per NEC 460.6"*
> - *"Pillar 4 — Witness gate per CSA Z462-24"*
> - *"Pillar 5 — Cooling chain integrity"*
> - *"Pillar 6 — PPE matrix per NFPA 70E §130"*

> *"All six are pure Python — no LLM in the critical path. The agent classifies, scans, and rules. The LLM only writes the human-readable summary, and only if asked."*

---

## Act 4 — Tech Assist field surface (2:00) — *the operator-facing layer*

> *"Operators don't speak in JSON. The Tech Assist view gives them three tools."*

**Navigate** `http://127.0.0.1:8080/#tech-assist`.

### Nameplate OCR (45s)
**Click** "Load sample" → textarea fills with Schneider Galaxy VX text → **Click** "Extract + match".

> *"Six milliseconds. Vendor canonicalized — `Square D` would normalize to `Schneider Electric`. Model, serial, kVA, voltage, mfg date all extracted via regex first. If regex confidence drops below 0.4 — say a vendor we've never seen — it falls back to gemma with a strict JSON schema prompt. The asset matcher uses stdlib `difflib`, no new dependencies. Suggested action: link, confirm, or seed new asset, scored by serial-exact, vendor, model fuzzy, capacity ±5%, voltage ±5%."*

### Troubleshoot QA (45s)
> *"Type a question. The agent retrieves the top-k chunks from the 4-tier corpus — Safety, Vendor, Standards, MOPs — pulls asset failure history from CMMS, and feeds gemma a tier-aware prompt. Citations come back ranked. Safety keywords trigger a banner at the top — if you mention 'arc flash' the answer always reminds you of the PPE category."*

### Knowledge Library (30s)
> *"Operators upload PDFs. Manuals, OEM docs, shift handover notes. Chunked with sentence-aware overlap, indexed in ChromaDB, instantly searchable through Troubleshoot. Tier-coded, asset-linked, vendor-tagged. Per-row delete with confirm."*

---

## Act 5 — Defensive engineering + audit trail (1:30)

> *"Here's the discipline behind it."*

```powershell
git log --oneline --decorate -n 12
```

> *"24 commits this sprint, 18 tags, every one referencing an ADR or a bug ID. Look at this one — `feat(audit): preserve approver signature on re-approve`. That's DC-EPMS-040, surfaced during a smoke test in this same session, fixed in 30 minutes with 4 unit tests. We don't ship un-tested fixes."*

```powershell
.\.venv\Scripts\Activate.ps1
pytest -m "not slow" -q --tb=short 2>&1 | tail -5
```

> *"530+ tests. Sub-second aggregate. The pre-existing 4 mock failures are documented in DC-EPMS-036 and explicitly out of scope for V9. Honest tech debt — every bug in the registry has a status, an effort estimate, and a target sprint. There is no 'mostly fixed' at Tier IV."*

> *"This whole demo is reproducible. `.\\scripts\\_demo\\replay_demo.ps1` resets the postgres state in 2 seconds. The snapshot is in git. Anyone can clone this repo and replay this exact walkthrough on their own laptop."*

---

## Act 6 — Wrap (30 seconds)

> *"To recap. The platform predicts subsystem failures before alarms fire — three subsystems, three Kalman triggers, three CET signatures, eleven minutes. It validates LOTO procedures against six engineering pillars in 12 milliseconds. It gives operators a nameplate-to-asset matcher, a corpus-grounded troubleshooter, and a managed knowledge library. The audit trail is locked — original CET signatures cannot be silently overwritten. ADR-006 enforced. NEC, NFPA, CSA, ASHRAE, IEEE cited by section, not paraphrased."*
>
> *"This is what V9 AI-Factory speed plus Tier IV doctrine looks like in practice on a single laptop. I'd be grateful for the chance to bring this discipline to your team."*

**Final visual**: hold on the Maintenance view with the 6 WO rows visible. 3-second pause. Stop recording.

---

## Fallback scenarios

| Symptom | Fix |
|---|---|
| Maintenance click bounces to Overview | `Ctrl+Shift+R` (stale JS cache) |
| KPI cards show "—" | Backend health: `curl /api/health` — restart uvicorn if postgres=down |
| Empty WO backlog | Replay script wasn't run: `.\scripts\_demo\replay_demo.ps1` |
| Approve button hangs | `sessionStorage.clear(); location.reload()` in DevTools console |
| Troubleshoot QA timeout | LM Studio offline: verify `http://127.0.0.1:1234/v1/models` |
| LOTO audit returns 500 | GraphRAG cache cold: first call takes ~30s, subsequent <50ms |

---

## Talking points to memorize (do NOT read)

1. *"Path C2 — 67 MW, 368 racks. 800 VDC is unipolar, not three-phase."*
2. *"Three predictive triggers, three subsystems, eleven minutes."*
3. *"ADR-006 Deterministic Sandbox: AI drafts, CET approves."*
4. *"Six pillars, each grounded in a specific standard."*
5. *"Pure Python, no LLM in the critical path."*
6. *"Original CET signature can never be silently overwritten — DC-EPMS-040."*
7. *"Honest tech debt registry — every bug has a status, an effort, a sprint."*
8. *"Single laptop, no cloud dependency, fully reproducible."*

---

## What this demo proves

| Skill | Evidence |
|---|---|
| **Architectural thinking** | 7 ADRs with rejected alternatives + rationale |
| **Standards literacy** | NFPA 70E, NEC 460.6, CSA Z462, IEC 62443, IEEE 519-2014, ASHRAE TC 9.9, NFPA 110-2022 cited by section |
| **Operational discipline** | 530+ tests, atomic commits, replay script, ADR-006 audit trail |
| **Safety-critical engineering** | Deterministic LOTO auditor, 12ms decisions, defense in depth, no LLM on critical path |
| **Honest scope reporting** | DC-EPMS bug registry with status precision, in-session catches (DC-EPMS-040) |
| **Tier IV operational mindset** | Single-signature audit trail, pending_approval gating, retention-aware schema |
| **Hyperscale fluency** | 67 MW Path C2, GB200/GB300 specs, 480 VAC vs 800 VDC vocabulary discipline |
| **Edge-first autonomy** | Single-laptop deployment, no cloud CI, deterministic replay |

The panel walks away knowing **this person can be trusted to own a Tier IV problem end-to-end**.

That's the bar.

---

**Locked: 2026-05-09. Tag the recording session as `demo-take-NN` and reference this file's commit hash in your notes.**
