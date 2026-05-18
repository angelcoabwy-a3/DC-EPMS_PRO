# DC-EPMS PRO — Canonical Demo Script (v5, ~14-15 min)

**Audience**: Microsoft CO+I — Critical Environment (CET) managers and
infrastructure recruiters. Assume deep data-center fluency, low patience
for hand-waving. Every claim is cited or shown.
**Duration**: ~14-15 min walkthrough (+ Q&A buffer)
**Mode**: Live, this laptop, browser at `http://127.0.0.1:8080/`
**Maintainer**: Wilmer Y. Angel Beltran · a3semi
**Locked**: 2026-05-16 — v5 supersedes v4. Changes: opens on the B1
Mission Control 3D scene (not the KPI grid); adds the floating HUD, the
3D drill-down, and a 15-second SRE chaos-testing pitch; whole script
re-cut into beat blocks with synced screen choreography for OBS.

## How to read this while recording

- `[ACTION]` — do this with the mouse / keyboard. Do it, *then* speak.
- `[SAY]`    — speak this. Conversational, not read-aloud-stiff.
- `~m:ss`    — cumulative clock; use it to keep pace.
- Anything not in a beat is **out of scope** for the live demo — Q&A only.

---

## PRE-FLIGHT  (15 min before recording)

```powershell
# Idempotent state reset to the known demo baseline (~2 s)
.\scripts\_demo\replay_demo.ps1
```

Injects four `pending_approval` LOTO work orders:

| Asset | Trigger | LOR / Pri | LOTO | MOP | Used in |
|---|---|---|---|---|---|
| `rpp_a_01` | predictive_kalman (THDi z=12.8) | 20 / **P1** | YES | yes | Beat 6 + Beat 7A |
| `cdu_a_01` | predictive_kalman (flow z=15.6) | 20 / **P1** | YES | yes | Beat 6 |
| `genset_a_01` | predictive_kalman (oil z=19.2) | 20 / **P1** | YES | yes | Beat 6 |
| `genset_b_01` | manual (shift handover) | 12 / P2 | YES | **NO** | Beat 7B — VETO target |

**Browser pre-checks** — `Ctrl+Shift+R` hard reload FIRST (defeats the
static `?v=` cache):
- `/api/health` → `postgres=up`, `gemma=up`
- `/#mission-control` → 3D scene renders; 4 floating panels in the
  corners; Building A panel reads **CAUTION (amber)**, Building B
  **HEALTHY**; SVG connector lines visible; `⟳ Reset Panel Layout`
  button bottom-right
- `/#maintenance` → 3 predictive P1 + 1 manual P2 + historical rows
- `/#tech-assist`, `/#multi-agent` → render clean

**Terminal pre-staged** (second window, for Beat 4 + Beat 10):
`cd C:\dev\DC-EPMS_PRO` · venv activated.

---

━━ BEAT 1 · Cold open — Mission Control ━━   ~0:00-1:15

[ACTION]  Open already on `http://127.0.0.1:8080/#mission-control`.
          The isometric 3D campus is the first thing on screen. Let it
          breathe 2 s before speaking — the cyan power-flow particles
          should be moving.

[SAY]  "I'm Wilmer Angel Beltran, a Critical Environment Technician.
        This is DC-EPMS PRO — an AI-native edge operations platform I
        built to run a Tier IV AI factory at hyperscale. What you're
        looking at is the command surface: A3-Alpha Toronto Area,
        Path C2 — 67 megawatts, 368 racks."

[ACTION]  Brief mouse circle over Buildings A and B, then the Yard
          fixtures, then the dim Building D.

[SAY]  "Phase 1 is deployed — Buildings A and B: 118 NVIDIA GB200
        NVL72 racks at 142 kilowatts, on 480 VAC trifásico, 2N. Phase 2,
        Building D, target Q2 2026 — the dim one: 250 GB300 NVL144 racks
        at 200 kilowatts, on an 800 VDC unipolar TN-S bus. Unipolar —
        the DC bus has no phases; 'trifásico' only applies to the AC
        upstream of the rectifier. That distinction is not pedantry, it
        is the difference between a correct and a dangerous mental model."

[ACTION]  Hands off the mouse — let the 3D scene idle while these words land.

[SAY]  "The whole platform runs on this laptop — RTX 3060, 6 gigs of
        VRAM, zero cloud dependency. Deliberate, per ADR-006: the AI
        drafts, the CET approves, the LLM is never on the critical path."

---

━━ BEAT 2 · The living HUD ━━   ~1:15-2:50

[ACTION]  Hover slowly over Building A. Hold 2 s — its floating glass
          panel brightens (backdrop-blur up) and the connector line
          lights cyan. As you say "three anomalies", rest the cursor on
          that panel's Anom counter.

[SAY]  "Every building carries a floating telemetry panel — live PUE,
        IT load, rack count, anomaly count — anchored in 3D space by
        a connector line. Building A is amber: CAUTION. Three anomalies
        queued on Path A right now. Hold that thought."

[ACTION]  Hover Building B — its panel is green, HEALTHY. Then hover
          the Yard panel (NOMINAL) and Building D (DESIGN).

[SAY]  "Building B, healthy. Yard nominal. Building D still in design.
        In a real NOC an operator scans flat dashboards and mentally
        maps numbers onto physical locations. This collapses that step
        — the data lives where the asset physically is. Under an
        incident, locate-time is downtime. Spatial visibility is a
        direct cut to mean-time-to-locate."

[ACTION]  Click-drag the Building A panel a few inches, release. Drag
          the Yard panel too. The connector lines follow in real time.

[SAY]  "The panels are a heads-up display — drag any of them, the
        operator owns the layout, and it persists across reloads."

[ACTION]  Click the `⟳ Reset Panel Layout` button (bottom-right).
          The 4 panels snap back to the corners.

[SAY]  "And one click restores the default layout. Small thing — but
        operator-grade affordances are what separate a dashboard from
        a tool someone trusts at 3 a.m."

---

━━ BEAT 3 · 3D drill-down ━━   ~2:50-3:50

[ACTION]  Single-click Building A. The view drills straight into the
          Rack Heatmap.

[SAY]  "One click — from the 67-megawatt campus view down to the
        rack-level thermal heatmap of that building. No menu, no
        breadcrumb hunt. Same spatial model at a different zoom:
        campus, building, rack — one continuous drill."

[ACTION]  Hover 1-2 of the warmer cells so the per-rack detail shows.

[SAY]  "Each cell is a real rack — live junction temperature and load.
        This is the thermal layer. The three infrastructure anomalies
        behind Building A's CAUTION state — power, cooling, genset —
        are not racks; they live one layer up, in the Maintenance
        backlog. Let me show you that."

---

━━ BEAT 4 · SRE — the drill-down is chaos-armored ━━   ~3:50-4:15

[ACTION]  MANDATORY. The pre-staged terminal already shows the output of
          `npx vitest run --reporter=verbose`. As you say "...stubs out
          requestAnimationFrame...", rest the cursor exactly on the line
          `✓ TC2 — the watchdog self-heals _transitioning even if the
          rAF chain breaks` — that line is the visual proof of the claim.

[SAY]  "Fifteen seconds on engineering discipline. That drill-down you
        just watched? It used to deadlock — a camera-animation flag
        could get stuck and silently freeze every click and hover on
        the view. I found it, decoupled navigation from the animation,
        and added a self-healing watchdog. Then I armored it: a Vitest
        suite where one test stubs out requestAnimationFrame to
        simulate a broken execution chain — and proves the watchdog
        still recovers the state. That's chaos engineering applied to
        a UI. I don't just fix the bug; I prove it stays fixed."

---

━━ BEAT 5 · PUE physics — the audit-grade answer ━━   ~4:15-5:15

[ACTION]  Navigate to `/#overview`. Point at the two-card PUE widget.

[SAY]  "The question every infrastructure panel asks first. Phase 1,
        480 VAC trifásico — PUE 1.32 live, target 1.30. Phase 2,
        800 VDC unipolar TN-S — design forecast 1.16 at full load."

[ACTION]  Point at the first-law cross-check residual card.

[SAY]  "The 16-point delta is what eliminating per-rack rectification
        buys you — one MV rectifier upstream at 97% efficiency replaces
        the whole AC conversion chain. And this number is not a guess:
        the bottom card shows a first-law energy-balance cross-check,
        residual 0.4% — audit-grade. ADR-004 documents the math. Pure
        deterministic Python, no LLM on the critical path."

---

━━ BEAT 6 · The 3-subsystem predictive arc ━━   ~5:15-8:15   *the demo killer*

[ACTION]  Click `Maintenance` in the sidebar. Three pending P1 LOTO
          work orders, three different subsystems.

[SAY]  "Those three anomalies on Building A — here they are. Three
        predictive_kalman work orders. None created by a human. The
        Kalman pipeline — a Send-on-Delta filter watching 238 telemetry
        channels — emitted them when the innovation residual on a
        channel broke 3-sigma, sustained over 3 windows."

[ACTION]  Click the chevron `▶` on `rpp_a_01`.

[SAY]  "Power distribution. Total Harmonic Distortion of current at
        18.4% — IEEE 519-2014 Section 5.1 caps that at 8%. The
        telemetry snapshot below froze the per-phase currents at the
        moment of anomaly — 412 / 398 / 421 amps, 2.8% imbalance —
        in the work-order JSON, for forensics."

[ACTION]  Click the chevron `▶` on `cdu_a_01`.

[SAY]  "Coolant Distribution Unit, loop-flow drift. Rated 180 LPM,
        last emission 142 — a 22% deficit. The risk is GPU junction
        temperature excursion at the next training-step burst. Kalman
        z-score 15.6 — flagged before any thermal alarm fired."

[ACTION]  Click the chevron `▶` on `genset_a_01`.

[SAY]  "Backup genset. Oil pressure down to 38 psi during the weekly
        load-bank exercise — rated band is 45 to 65. NFPA 110-2022
        Section 8.4, Level 1 EPSS. Inspect the pump and change the
        filter before this genset is ever called for a real outage."

[ACTION]  Click `✓` (Approve) on `rpp_a_01` → enter CET id → confirm.
          Row flips to `approved` with timestamp + CET id.

[SAY]  "Pending-approval to approved. CET signature locked. ADR-006
        satisfied — the human made the call."

[ACTION]  Switch to the pre-staged terminal. Run the re-approve curl
          on the SAME work-order id (a `mallory.attacker` cet_id). When
          it returns, rest the cursor on the `409` in the output.

[SAY]  "Watch the second approval attempt. HTTP 409 Conflict. The
        state machine refuses it — the original CET signature can
        never be silently overwritten. That's the audit-trail
        integrity guarantee. We caught this gap in our own session
        and shipped the fix as DC-EPMS-040."

---

━━ BEAT 7 · Multi-Agent consultation + VETO ━━   ~8:15-10:00

[SAY]  "Before approving predictive work, an experienced CET consults
        colleagues — architect, safety officer, diagnostician, analyst.
        The platform formalizes that."

### Part A — 4-perspective consultation

[ACTION]  Navigate `/#multi-agent`. Click `Load RPP scenario` → click
          `Consult all 4 agents`.

[SAY]  "Eight to fourteen milliseconds. Four agents in parallel via
        asyncio.gather. Architect: Path A drops from 2N to 1N for the
        LOTO duration — approve only if Path B is healthy.
        Diagnostician: five prior work orders on this asset — that's
        accelerated wear, investigate the root cause, don't just fix
        it again. Analyst: OpEx repair 3,200 dollars versus CapEx
        replace 42,000. Consensus: caution. Structured reasoning an
        auditor can follow."

### Part B — The VETO

[ACTION]  Switch to `/#maintenance`. Point at the `genset_b_01` row —
          P2, manual, `loto=YES`, `mop=null`. Click its WO id → Ctrl+C.

[SAY]  "Fourth row. Genset B-01 — manual draft, requires LOTO, but the
        MOP column is empty. Someone drafted a lockout without
        attaching the procedure. Watch the Multi-Agent."

[ACTION]  Back to `/#multi-agent`. Clear the textarea, type
          `Approve this work order? Found during shift handover, no MOP
          linked.` Paste the WO id into `work_order_id`. Leave
          `asset_id` / `procedure_id` empty. Click `Consult all 4 agents`.

[ACTION]  As the result paints, move the cursor ONE element per spoken
          phrase: the red HARD STOP banner -> the Safety Officer card's
          red border -> the rationale line at the bottom of that card.

[SAY]  "Four milliseconds. Red banner — HARD STOP. The Safety Officer
        card: red border, HARD STOP. One agent, and only one, holds
        veto power. LOTO required, no MOP linked — it does not matter
        what the other three say. The work order is gated until a CET
        attaches the procedure. CSA Z462 Section 4.2, NFPA 70E Section
        130. ADR-006 enforced in Python, not in process."

---

━━ BEAT 8 · LOTO Auditor — the safety-critical agent ━━   ~10:00-12:00

[SAY]  "Predictive maintenance is half the picture. The other half is
        making sure the work itself is safe."

[ACTION]  Navigate `/#loto`. In the pre-staged terminal, run the audit
          curl: `MOP-ATS-MONTHLY-001` against `ups_a`, `cet_on_duty=wilmer`.
          Refresh `/#loto` if it does not auto-update with the result.

[SAY]  "Twelve milliseconds end-to-end. Sixteen sources consulted. The
        verdict cites NEC 460.6 by section — because the procedure
        forgot capacitor discharge. A 600-volt DC link, hundreds of
        joules in the bus capacitors; breaker open, lockout on — and a
        CET reaching in could still die. The auditor catches that in
        twelve milliseconds."

[ACTION]  Point at the 6 pillar results on screen.

[SAY]  "Six pillars, each grounded in a standard. Topology impact
        radius via GraphRAG. 2N redundancy survival. Capacitor
        discharge per NEC 460.6. Witness gate per CSA Z462-24. Cooling
        chain integrity. PPE matrix per NFPA 70E 130. All six are pure
        Python — no LLM in the critical path. The LLM only writes the
        human-readable summary, and only if asked."

---

━━ BEAT 9 · Tech Assist — the operator-facing layer ━━   ~12:00-13:15

[SAY]  "Operators don't speak JSON. Tech Assist gives them three tools."

[ACTION]  Navigate `/#tech-assist`. Click `Load sample` → `Extract + match`.

[SAY]  "Six milliseconds. A nameplate — vendor canonicalized, 'Square D'
        normalizes to 'Schneider Electric'; model, serial, kVA, voltage
        extracted by regex, with a gemma fallback on low confidence.
        The asset matcher scores it against the registry — link,
        confirm, or seed new."

[ACTION]  In Troubleshoot, type a short question (e.g. about arc flash).
          Show the cited answer + the safety banner.

[SAY]  "Troubleshoot retrieves from a 4-tier corpus — Safety, Vendor,
        Standards, MOPs — plus asset failure history, feeds gemma a
        tier-aware prompt, returns ranked citations. Mention 'arc
        flash' and a banner reminds you of the PPE category — every
        time."

[ACTION]  Point at the Knowledge Library panel.

[SAY]  "And operators upload PDFs — manuals, OEM docs — chunked,
        indexed in ChromaDB, instantly searchable through Troubleshoot."

---

━━ BEAT 10 · Engineering discipline ━━   ~13:15-14:15

[ACTION]  In the terminal: `git log --oneline --decorate -n 15`. Cursor to
          the `fix(mission-control)` line and the `test(mission-control)`
          line just above it (newest-first ordering).

[SAY]  "Every commit references an ADR or a bug ID. This one —
        the drill-down deadlock fix — and the one after it, its Vitest
        chaos-test suite. Two atomic commits, feature and test
        separated. We don't ship spaghetti history."

[ACTION]  Run `pytest -m "not slow" -q --tb=short` — show the tail.
          Then `npm test` — show `10 passed`.

[SAY]  "660-plus backend tests, sub-second aggregate — and now a Vitest
        frontend harness on top. Every bug in the registry has a
        status, an effort estimate, and a target sprint. There is no
        'mostly fixed' at Tier IV. And the whole demo is reproducible —
        replay_demo.ps1 resets the postgres state in two seconds; the
        snapshot is in git."

---

━━ BEAT 11 · Wrap ━━   ~14:15-14:45

[ACTION]  Navigate back to `/#mission-control`. Hold on the 3D scene.

[SAY]  "To recap. A spatial command surface that drills from 67
        megawatts to a single rack in one click. Live PUE per phase
        with a first-law audit-grade cross-check. Failure prediction
        before alarms fire — three Kalman triggers, three subsystems.
        A 4-agent panel reasoning in parallel under 15 milliseconds,
        Safety Officer holding the veto. LOTO validated against six
        engineering pillars in twelve milliseconds. An audit trail
        that cannot be silently overwritten. And a UI armored with
        chaos testing. Standards cited by section — NEC, NFPA, CSA,
        ASHRAE, IEEE — not paraphrased."

[SAY]  "This is what Tier IV doctrine plus AI-factory speed looks like
        on a single laptop. I'd be grateful for the chance to bring
        this discipline to your team."

[ACTION]  3-second hold on the Mission Control scene. Stop recording.

---

## Fallback scenarios

| Symptom | Fix |
|---|---|
| Mission Control canvas black / blank | `Ctrl+Shift+R` (stale JS cache — the `?v=` is static) |
| Drill-down click does nothing | Stale pre-fix JS — hard reload; verify `0d7f2b7` is served |
| HUD panels stacked in the center | Hard reload — pre-HUD-MODE cached build |
| Maintenance click bounces to Overview | `Ctrl+Shift+R` (stale JS cache) |
| KPI / PUE cards show "—" | `curl /api/health` — restart uvicorn if `postgres=down` |
| Empty WO backlog | Replay not run: `.\scripts\_demo\replay_demo.ps1` |
| Approve button hangs | `sessionStorage.clear(); location.reload()` in DevTools |
| Troubleshoot QA timeout | LM Studio offline — check `127.0.0.1:1234/v1/models` |
| LOTO audit returns 500 | GraphRAG cache cold — first call ~30 s, then <50 ms |
| Multi-Agent shows "Path unknown" | CMMS asset row not seeded — re-run replay_demo.ps1 |

---

## Talking points to memorize (do NOT read aloud)

1. "Path C2 — 67 MW, 368 racks. 800 VDC is unipolar, not three-phase."
2. "One click from the 67-megawatt campus to a single rack."
3. "Phase 1 PUE 1.32 live, Phase 2 design 1.16 — first-law cross-check."
4. "Three predictive triggers, three subsystems — flagged before alarms."
5. "Four agents in parallel, sub-15 ms, Safety Officer holds the veto."
6. "ADR-006 Deterministic Sandbox: AI drafts, CET approves."
7. "Six LOTO pillars, each grounded in a specific standard, 12 ms."
8. "Pure Python on every critical path — no LLM."
9. "Original CET signature can never be silently overwritten — DC-EPMS-040."
10. "The drill-down is chaos-tested — watchdog proven under a broken rAF chain."
11. "Single laptop, no cloud dependency, fully reproducible."

---

## What this demo proves

| Skill | Evidence |
|---|---|
| **Spatial / HMI design** | B1 Mission Control — 3D campus, floating HUD, one-click drill-down campus→rack |
| **Architectural thinking** | 8 ADRs with rejected alternatives + rationale |
| **Standards literacy** | NFPA 70E, NEC 460.6, CSA Z462, IEC 62443, IEEE 519-2014, ASHRAE TC 9.9, NFPA 110-2022, OCP 800 VDC — cited by section |
| **SRE mindset** | Drill-down deadlock found, root-caused, fixed (decouple + self-healing watchdog), and chaos-tested (rAF stubbed to simulate a broken chain) |
| **Operational discipline** | 660+ backend tests + Vitest frontend harness, atomic commits, replay script, ADR-006 audit trail |
| **Safety-critical engineering** | Deterministic LOTO auditor, 12 ms decisions, 4-agent consult + Safety Officer veto, no LLM on critical path |
| **Physics literacy** | Live PUE per phase + first-law cross-check; 480 VAC trifásico vs 800 VDC unipolar TN-S discipline |
| **Honest scope reporting** | DC-EPMS bug registry — status, effort, target sprint per bug; in-session catches (DC-EPMS-040, DC-EPMS-MC-001) |
| **Hyperscale fluency** | 67 MW Path C2, GB200 / GB300 specs, vocabulary discipline |

The panel walks away knowing **this person can be trusted to own a Tier IV problem end-to-end.** That's the bar.

---

**Locked: 2026-05-16 (v5). Tag the recording session `demo-take-NN` and
note this file's commit hash. v5 supersedes v4 (commit history).**
