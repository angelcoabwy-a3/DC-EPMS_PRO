# DC-EPMS PRO — Canonical Demo Script v6.1 (2026-05-24, v0.16.0 "Procedure Architect Universal")

**Audience:** Microsoft CO+I — Critical Environment Technician (CET)
managers + infrastructure recruiters. Assume deep data-center fluency,
low patience for hand-waving. Every claim is cited or shown.

**Duration:** **6:30 walkthrough** (+ unlimited Q&A buffer).

**Mode:** **All-live** — all 6 beats are presented live on this laptop,
browser at `http://127.0.0.1:8080/`, terminal in second window. OBS
recording is **descoped** per the 2026-05-17 decision; this script
treats every beat as a live performance with explicit `[FALLBACK]`
flows for any HMI/network hiccup.

**Anchor narrative:** the **deterministic audit gate** as the
architectural moat. Competitors ship LLM dashboards. DC-EPMS PRO
ships an LLM author + a Tier-IV-grade Safety Officer who can refuse.

**Maintainer:** Wilmer Y. Angel Beltran · a3semi.

**Supersedes:** DEMO_SCRIPT v6 (2026-05-24, hybrid pre-recorded
intro). v6.1 honors the OBS-descope by going fully live. v5 (the
pre-Epic-6 14-15 min B1 Mission Control variant) remains archived
in git history.

---

## How to read this while presenting

- `[ACTION]` — do this with the mouse / keyboard. Do it, **then** speak.
- `[SAY]` — speak this. Conversational, not read-aloud-stiff. Bold is
  the load-bearing claim you must land.
- `[HOLD]` — pause 1-2 seconds for the panel to absorb the screen.
- `[FALLBACK]` — what to say/do if the live path misbehaves.
- `~m:ss` — cumulative clock; keep pace.
- Anything not in a beat is **out of scope for the live demo** — Q&A.

---

## PRE-FLIGHT (15 minutes before the panel)

Run the verifier script from a clean PowerShell prompt:

```powershell
cd C:\dev\DC-EPMS_PRO
.\scripts\preflight_demo.ps1
```

The script:
1. Verifies `epms-db` docker container is **healthy**.
2. Kills any orphan python on `:8080`.
3. Starts `backend\main.py` in a tracked process.
4. **Tails the boot log until** `[BUILD] DC-EPMS_PRO=v0.16.0` + `[BOOT]
   Architect library pre-seeded with 23 catalog MOP(s)` + `[graphrag]
   loaded 10 knowledge documents` all appear.
5. Curls `/api/health` and `GET /api/procedures/architect/library?source=catalog`
   to confirm `version=0.16.0`, `pg=up`, library `total=23`, every
   entry `audit_verdict=approve`.
6. Reports **GREEN/RED** summary per check. Refuses to declare ready if
   any check fails.

If GREEN → proceed. If RED → fix root cause before continuing; **do
NOT demo against a degraded stack**.

### Browser pre-checks (operator does manually after `preflight_demo.ps1` is GREEN)

- **Hard reload**: `Ctrl+Shift+R` (defeats `?v=` static cache).
- Open in this order, leave each tab pinned:
  - Tab 1: `http://127.0.0.1:8080/` (Overview — landing for Beat 0)
  - Tab 2: `http://127.0.0.1:8080/#mission-control` (Beat 1)
  - Tab 3: `http://127.0.0.1:8080/#procedures-architect` (Beats 2-4)
  - Tab 4: `http://127.0.0.1:8080/#mops` (Beat 5 close)
- DevTools console open in a Z-order behind (Cmd+Shift+I on Mac, F12
  on Windows). Footer must read `DC-EPMS PRO v0.16.0`. Console banner
  must show `%c DC-EPMS PRO v0.16.0`.

### Terminal pre-staged

Second PowerShell window, side-by-side with browser:

```powershell
cd C:\dev\DC-EPMS_PRO
.\.venv\Scripts\Activate.ps1
# Stage the verify-chain command -- you press ENTER live in Beat 4.
# The panel sees the staged command before you execute, which builds
# anticipation. Do NOT execute now -- only during Beat 4.
$cmd = 'curl -s http://127.0.0.1:8080/api/ledger/verify | python -m json.tool'
```

### Display config (all-live)

- Browser: full-screen mode (F11) on the presentation monitor.
- Mouse cursor: **enlarged + click-highlight** so the panel can
  follow your clicks (Windows: Settings → Accessibility → Mouse
  pointer → enable Mouse pointer trails + larger size).
- Mic: USB if available, laptop built-in acceptable in a quiet room.
- Notifications: silenced (Slack, Teams, email). The panel sees
  desktop notifications too.

---

## BEAT 0 — Hook (0:00 – 0:30) · [LIVE]

`[ACTION]` Open browser to `http://127.0.0.1:8080/` (Overview view).
The footer reads `DC-EPMS PRO v0.16.0`.

`[SAY]` (~0:00-0:10) "Good morning. This is **DC-EPMS PRO** —
an AI-native edge operations platform for Tier IV AI factories. The
simulator runs A3-Alpha Toronto, **67 MW Path C2**: Phase 1 with **118
NVIDIA GB200 racks at 142 kW each**, Phase 2 with **250 GB300 racks at
200 kW upstream 800 VDC unipolar TN-S** with **SSCB** clearing in the
**1 to 100 microsecond** band per IEC 60947-2."

`[HOLD]` 1 second. Let the spec land.

`[SAY]` (~0:10-0:30) "What makes this platform different from every
AI ops dashboard you've seen is this: **every LLM-authored procedure
crosses a deterministic Safety Officer audit before it can be signed
into a forensic ledger**. The LLM is the author. The Safety Officer is
pure Python pattern matching. The Forensic Ledger is HMAC-SHA256
chained per IEC 62443-3-3. **Let me show you why that matters.**"

`[ACTION]` (transition) Click Mission Control nav-item → fade.

---

## BEAT 1 — Mission Control + Multi-Agent Fleet (0:30 – 2:00) · [LIVE]

`[ACTION]` (~0:30) Tab 2 active. `#mission-control` renders the
3D scene with floating telemetry panels.

`[SAY]` (~0:30-0:50) "Mission Control. The 3D scene is **three.js
WebGL** — runs on this RTX 3060 laptop. The four floating panels are
the live KPI surface: Path A, Path B, environmental envelope, and the
6-agent verdict ribbon at the bottom."

`[ACTION]` Hover over the Path A panel. Pulse animation fires.

`[SAY]` (~0:50-1:15) "Below the visualization, **238 telemetry
channels** are streaming through a **Kalman pipeline**. Only the
**innovation residuals** propagate upstream — ODE-explained behavior
is filtered locally. **Send-on-delta compresses by 12x** at steady
state. Same discipline you'd use on an orbital telemetry uplink. On
this machine, the per-step Kalman is **4.3 microseconds** — well under
the SSCB protection-coordination target."

`[ACTION]` (~1:15) Click an asset on the scene to expand the asset
panel.

`[SAY]` (~1:15-1:45) "Six AI agents are reasoning concurrently —
**Architect, Safety Officer, Diagnostician, Analyst, Capacity Planner,
Carbon-Grid**. They vote deterministically. The **Safety Officer
holds the only veto** — uncrossable, no other agent can override.
That's skill `S-DET-02`, binding test in the suite. Carbon-Grid uses
**live Ontario IESO carbon intensity** with **time-of-use**
perspective to keep us aligned with the CO+I 2030 carbon-negative
commitment, but it has no veto authority — it surfaces as
`HARD_STOP` through the standard rank-2 path, never the rank-1 VETO
branch."

`[ACTION]` (~1:45) Transition out — navigate to Tab 3 / `#procedures-architect`.

`[SAY]` (~1:45-2:00) "All that is the **reactive plane**. Now let me
show you the **authoring plane** — the Procedure Architect — and the
deterministic gate that prevents it from shipping an unsafe procedure.
**This is the moat.**"

`[ACTION]` Click sidebar nav-item "Procedure Architect" OR
`Cmd-3` / `Ctrl-3` to switch to Tab 3.

---

## BEAT 2 — Procedure Architect Authoring (2:00 – 4:00) · [LIVE]

`[ACTION]` (~2:00) Confirm view header reads "Procedure Architect ·
SOP / MOP / EOP / EMP".

`[SAY]` (~2:00-2:15) "This is the Procedure Architect view. Operator
picks document type, asset, and a context starter. **Every starter is
engineered to seed the LLM with the safety vocabulary the audit gate
requires.**"

`[ACTION]` In Document type dropdown → select **MOP**.

`[ACTION]` **Wait** for the form to reveal the new **MOP category**
dropdown (Commit 9 feature). Should appear above the chip row.

`[FALLBACK]` If MOP category dropdown does not appear: hard refresh
`Ctrl+Shift+R`, repeat. Console-check `MOP_CATEGORY_KEYS` is
defined.

`[ACTION]` (~2:20) In MOP category dropdown → select **Chiller**.

`[SAY]` (~2:20-2:35) "32 chip starter templates across **10
categorías** — UPS, Transformer, Utility, PDU/STS, RPP, Busway,
Chiller, CRAH, Cooling Tower, Global. Pick Chiller for this demo."

`[HOLD]` Chips re-render. Verify 3 chips appear: "Staging / rotación
secuencial", "Trip response (emergencia)", "Ride-through recovery".

`[ACTION]` (~2:35) In Asset id picker → select **Chiller 1 (York YZ)**.

`[ACTION]` Click chip **"Staging / rotación secuencial"**.

`[HOLD]` Textarea fills with full chip text — verify visible: `LOTO`,
`PPE Cat 3`, `CSA Z462-24`, `Vivo-Muerto-Vivo`, `battery_runtime_min`,
`Back-out`, `chiller_1`.

`[SAY]` (~2:50-3:10) "The chip pre-fills with the full safety
vocabulary the audit gate enforces — **Mechanical LOTO on motorized
valves, Motor LOTO on the compressor disconnect, PPE Cat 3 per CSA
Z462-24, Vivo-Muerto-Vivo verification, and a back-out bounded by the
Tiempo de Tolerancia Térmica of approximately 5 minutes** before
ASHRAE A2 breach. **The LLM author starts already inside the safety
envelope.**"

`[ACTION]` (~3:10) Confirm Operator id input reads `wilmer.angel`.

`[ACTION]` Click the **Generate** button.

`[HOLD]` **2-3 seconds** for the LLM to respond (or skeleton fallback
if LM Studio is not reachable).

`[FALLBACK]` If LM Studio is unreachable: the skeleton MOP renders
with `_TBD_` placeholders. The audit will correctly hard-stop
because the skeleton lacks LOTO. **Pivot the narrative**: "We see
the deterministic skeleton fallback when no LLM is wired. Notice the
audit gate still acts — it would refuse this draft because the
required terms are absent. This is the gate operating as designed."
Then jump directly to Beat 3 (the moat is the same story).

`[HOLD]` Draft renders with the full body. **Verify the verdict pill
reads APPROVE (green)** + the Sign button is **enabled**.

`[ACTION]` (~3:30) **Scroll the rendered draft body slowly** so the
panel sees the structure: §1 Alcance with **Identificador: chiller_1**
+ **Estado Final Esperado**, §2 with **Vector Mecánico/Térmico**, §3
with **MCP Agentes Health Check**, §4 with **`[HOLD POINT]` markers**
+ Cuatro Ojos checkboxes, §5 with **parameterized abort triggers**.

`[SAY]` (~3:30-3:55) "**That is the Universal 5-Point Structure**
the operator mandated on May 23rd. **Six explicit risk vectors —
Eléctrico, Mecánico-Térmico, Life Safety, Combustible, Lógico,
Aguas Arriba-Abajo. MCP agent health check as a precondition. Hold
points before commands. Parameterized abort triggers — every
trigger has a number and a unit, never `if something goes wrong`.**
The deterministic audit just verified all of it. Verdict: APPROVE.
Operator can sign."

`[HOLD]` Pause for visual confirmation. **Do not click Sign yet** —
that's Beat 4.

---

## BEAT 3 — ★ THE MOAT: Audit Refuses (4:00 – 5:00) · [LIVE]

`[ACTION]` (~4:00) Position cursor in the Operator context textarea.

`[SAY]` (~4:00-4:10) "Now let me show you what happens when an
operator drifts off the contract."

`[ACTION]` **Edit the context textarea**:
1. Find the line containing `Vivo-Muerto-Vivo` and **delete the
   entire phrase** (leave the surrounding text intact).
2. Find the line containing the back-out trigger `T_suministro > 12
   °C por más de 45 segundos` and **replace it with** `revertir si
   algo sale mal` (the textbook vague trigger).

`[ACTION]` Click **Generate** again.

`[HOLD]` **2-3 seconds**. Draft re-renders. **Verdict pill flips from
APPROVE (green) to HARD_STOP / SAFETY HARD_STOP (red)**. The Sign
button **disappears**. A findings list renders.

`[ACTION]` **Point at the findings panel** so the panel can read it.

`[SAY]` (~4:30-5:00) "**HARD_STOP.** Look at the findings: `missing
safety verification: include either Vivo-Muerto-Vivo or límite de
aproximación restringida` and `richer-template REFUSAL: §5 must
include at least one parameterized abort trigger (number + unit) —
vague abort criteria are safety-critical and block signing`.

**The Sign button is gone.** Not disabled — gone. The HMI doesn't
hide the option from the operator; the deterministic gate prevents
it from existing. **No matter how confident the LLM was in its
prose, this MOP cannot reach the Forensic Ledger until it satisfies
the contract.** That is the architectural moat. The audit is **pure
Python pattern matching** — `audit_procedure_safety` in
`backend/agents/procedure_architect.py`. **Zero LLM calls in the
verdict path.** It runs in microseconds and is deterministic by
construction. **S-DET-01.**"

`[HOLD]` Let the panel read the findings. This is the demo's emotional
peak. **Do not rush.**

---

## BEAT 4 — Fix + Maker-Checker + Forensic Ledger (5:00 – 6:00) · [LIVE]

`[ACTION]` (~5:00) Edit the textarea — **restore** both lines you
deleted in Beat 3 (paste from clipboard if you staged it; otherwise
re-type approximately).

`[ACTION]` Click **Generate**. **Verdict pill returns to APPROVE.**
**Sign button reappears.**

`[SAY]` (~5:10-5:20) "Operator fixes the body. Re-generate. Audit
approves. Sign button is back."

`[ACTION]` (~5:20) Change Operator id input from `wilmer.angel` to
**`maker.alice`**. Click **Sign**.

`[HOLD]` Response renders. **Verify an orange/red badge appears
reading "AWAITING SECOND SIGNATURE — Maker: maker.alice"**.

`[SAY]` (~5:30-5:40) "HTTP 202 — awaiting second signature. **MOPs
require two distinct operators to seal.** This is the **Maker-Checker
witness gate**, the digital encoding of the **Cuatro Ojos** principle
that Tier IV mechanical operations have used on paper for decades."

`[ACTION]` (~5:40) Change Operator id input from `maker.alice` to
**`checker.bob`**. Click **Sign**.

`[HOLD]` Response renders. **Verify the success banner** reads
something like "Signed to ledger · entry &lt;id&gt; · seq #N" +
"Maker: maker.alice · Checker: checker.bob".

`[ACTION]` (~5:50) **Switch focus to the terminal window**. Press
ENTER on the staged command:

```
curl -s http://127.0.0.1:8080/api/ledger/verify | python -m json.tool
```

Response renders. **Point at `"divergence_index": null`**.

`[SAY]` (~5:55-6:00) "Sealed. The Forensic Ledger ran a full HMAC
chain verification — **`divergence_index: null`** means **the entire
audit trail is cryptographically intact** from genesis to this seal.
IEC 62443-3-3 SR 6.1 and 6.2 compliant. NIST SP 800-53r5 AU-9 and
AU-10. **Append-only**, **TimescaleDB-backed**, **DB-side
immutability triggers**."

`[FALLBACK]` If the ledger is on InMemoryPersistence (migration not
applied): the verify still works but say: "in production this is
backed by TimescaleDB hypertable with BEFORE-UPDATE-DELETE-TRUNCATE
triggers raising exceptions — DB-side immutability." Then continue.

---

## BEAT 5 — Close: Library + GraphRAG + Skills (6:00 – 6:30) · [LIVE]

`[ACTION]` (~6:00) Tab 4 → `#mops`. **Or** switch back to terminal
and run:

```
curl -s "http://127.0.0.1:8080/api/procedures/architect/library?source=catalog&limit=5" | python -m json.tool
```

`[HOLD]` Output shows 5 catalog MOP entries with `audit_verdict:
"approve"` each.

`[SAY]` (~6:00-6:30) "Closing the loop. The library pre-seeds **23
canonical MOPs** at boot — UPS bypass, transformer DGA, ATS
commutation, chiller staging, free cooling, IST full-load test,
double-block-and-bleed ring isolation. **All audit equals approve**
under the full contract. **10 GraphRAG knowledge documents**
indexed — ASHRAE TC 9.9, Uptime Tier IV, OCP cooling environments,
CTI ATC-105, Eaton SOW R-48, CSA Z462-24, OESC Ontario, the
NVIDIA 800 VDC architecture whitepaper. **24 explicit skills** in
the deterministic harness, **9 categories** — routing, AI
determinism, testing, security, ledger, proposer, commit, runtime,
**procedure authoring safety**. This is what AI-native edge
operations looks like when safety is **enforced architecturally**,
not narrated. **I'm happy to take questions.**"

`[ACTION]` Stop the visual focus. Hands off the keyboard. Open posture
toward the panel.

---

## Q&A — Anticipated Panel Questions (preview, prep in Phase 4)

The following are the questions the CO+I panel is most likely to
ask. Tight answers ≤ 30s each. Full prep is Phase 4.

1. **"What stops a malicious operator from editing the audit gate
   to remove the hard_stop?"** → The audit constants are byte-stable
   per the test `test_system_prompt_sha256_is_pinned` + the
   skill-registry `S-DET-01`. Any drift surfaces in CI. Production
   deployments use commit-signing + git-tag-pinning at the container
   build layer.
2. **"How do you handle multi-vendor fleets (your Eaton rule is
   string-match)?"** → Today: string-match on context. Next sprint:
   `Asset.manufacturer` schema migration in `cmms_models.py` (TODO
   marker in code). Then deterministic lookup. The string-match is
   why it's CAUTION not HARD_STOP — multi-brand reality.
3. **"What's the latency of the audit gate?"** → Pure Python regex.
   Microseconds. Zero LLM calls in the verdict path. Demo just
   proved this — verdict flip was instant.
4. **"How do you cite GraphRAG in the generated MOPs?"** → The
   knowledge docs carry `cite: NNN` markers; the LLM author quotes
   them back when relevant. Operator sees the source.
5. **"What about Life Safety systems (VESDA, Novec)?"** → Honest
   answer: not in the canonical body library yet. The richer system
   prompt names them as vectors, the audit accepts them, but
   `site_model.yml` doesn't have these assets in the Path C2 spec.
   Next sprint candidate.
6. **"Where does Carbon-Grid get its data?"** → Today: deterministic
   Ontario IESO mock keyed to time-of-day + weekend. `backend/
   grid_provider.py`, function-as-DI-seam pattern for real IESO API
   drop-in replacement.
7. **"How do you scale this to multi-site?"** → Single-laptop today
   (honest: this is the demonstrable surface). Multi-IBX confederation
   is V11 design pattern, not implemented. Equinix-style sovereign
   data + msgpack over private link. Vision Deck #5.
8. **"Why the byte-pinned system prompt instead of a prompt
   library?"** → A library is mutable; a byte-pinned prompt has a
   test gate. Any drift fails CI. Same discipline as configuration
   versioning in production systems.

---

## Reality Checks (the operator's CLAUDE.md discipline)

- This demo runs on a **6 GB RTX 3060 laptop**. Every claim above is
  measurable on this hardware. No cloud sleight-of-hand.
- **Path C2 vocabulary fence**: `trifásico` applies ONLY to AC
  upstream of MV Rectifier (Phase 1 480 VAC, Phase 2 35 kVAC). The
  Phase 2 800 VDC bus is **unipolar TN-S** — saying "800 VDC
  trifásico" is a credibility-destroying error in front of a CO+I
  panel. Stay disciplined.
- **No vaporware**: every screen shown is the live HMI. Every
  endpoint shown returns real bytes. The library pre-seed of 23
  catalog MOPs is verifiable by boot log + `curl
  /api/procedures/architect/library?source=catalog`.

---

## Out-of-scope for this demo (Q&A only)

- LOTO Auditor 6-Pillar (Sprint 5 era — still works but tangential
  to the Architect story)
- B1 Mission Control 3D drill-down details (covered in v5)
- Tech Assist QA + PDF ingest + voice (Sprint 7.1 era)
- Witness Engine 8-state machine internals (tangential — Maker-
  Checker is the visible surface)
- The Optimizer (it's a separate epic; default OFF in this
  deployment per env-gate)
- Hermes WebSocket EDA plane (it's running but not visually
  surfaced in this script)

These are all interesting; they are all out-of-scope for **this
6:30**. If the panel asks, bridge to them ≤ 30s and pivot back.

---

**Locked: 2026-05-24 (v6.1 all-live). Aligned to v0.16.0 "Procedure
Architect Universal". OBS recording descoped per 2026-05-17.
Next revision: post-rehearsal Phase 2 feedback.**
