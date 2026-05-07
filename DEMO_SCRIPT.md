# DC-EPMS PRO — Demo Script (Microsoft CO+I)

**Audience:** Microsoft Cloud Operations + Innovation interview panel
**Duration:** 5–7 minutes core demo + 5 minutes Q&A
**Presenter:** Wilmer Angel — CTO, A-Cubed Semiconductor Systems Inc.

---

## What you're demonstrating

A purpose-built **Edge Operations Platform** for an AI-class data center
(40 MW, 118 × NVIDIA GB200 NVL72 racks, Tier IV 2N redundancy)
that combines four capabilities most facilities silo into separate teams:

1. **Physics-validated digital twin** — first-law thermodynamics engine
   replacing rule-based heuristics. The system *knows* when measurements
   violate the laws of physics.
2. **Real-time AI co-pilot** — local Gemma model with NeMo Guardrails,
   grounded in 20 indexed standards (ASHRAE, NFPA, IEC 62443, IEEE)
3. **Industrial connectivity** — BACnet/Modbus tag namespace compatible
   with Niagara N4, Honeywell EBI, Schneider EcoStruxure
4. **Agentic resilience** — physics-driven What-If simulation that
   evaluates redundancy in real time

---

## Pre-flight checklist (run 30 min before demo)

```powershell
cd C:\dev\DC-EPMS_PRO

# Verify infrastructure
docker ps                          # epms-db must be 'healthy'
.\.venv\Scripts\activate
python scripts\diagnose.py         # all 4 components green

# Start LM Studio with Gemma loaded (separate window)
# Verify: curl http://127.0.0.1:1234/v1/models

# Run all tests
python -m pytest tests\ -q         # 93 passed
```

If any of these fails, **don't demo live** — show video recording instead.

---

## Demo flow (5 minutes core)

### Minute 0:00 — Open

Open Chrome to `http://localhost:8080`.

> "This is DC-EPMS PRO running locally. It's the operations platform we
> built for our 40-megawatt AI campus, A3-Alpha. Everything you'll see
> runs on my laptop — no external services."

### Minute 0:30 — Overview view

Point to the **Site Health Index** card (under the KPI grid).

> "This number — 1.00 — isn't a smoothed average. It's the minimum across
> our four physics modules: IT thermal, mechanical, electrical, heat
> rejection. If any one of them violates a physical bound, the SHI drops
> immediately and the weakest module is flagged."

### Minute 1:00 — Topology view

Click **🌐 Topology (HLD/LLD)**.

> "This is the live system-of-systems map. Two utility feeds in true 2N —
> Feed A goes to Transformer A, Feed B to Transformer B. Both UPS A and
> UPS B carry equal load. The atom symbols ⚛ next to hall temperatures and
> chiller COPs mean *physics-verified* — the values pass first-law
> validation: Q = ṁ·Cp·ΔT with residual under 2%."

Hover over an atom symbol to show the tooltip.

### Minute 1:45 — Emergency Simulation (THE moment)

Click **🚨 Emergency Simulation** button.

> "Now the operator-class feature. With this enabled, I can click any
> node to simulate its failure. The physics engine evaluates whether the
> remaining redundancy can carry the load."

Click **Transformer A**.

> "Transformer A failure. SHI drops from 1.00 to 0.40. Redundancy went
> from 2N to N — non-redundant. The physics engine says: *Site CANNOT
> carry full load on remaining components*. Why? Because Transformer B's
> winding would hit 145°C — IEEE C57.12 hottest-spot limit is 110."

Close the banner, click **Cooling Tower**.

> "Different failure type. Cooling tower trip — the wet bulb approaches
> ECWT, which means the chiller condenser can't reject heat. Watch the
> AI Mission Control panel."

Pause for 2 seconds — let panel auto-update.

### Minute 3:00 — AI Mission Control

> "These insights are generated from the physics state, not from a chat
> model — they're deterministic alerts. They reference the actual
> standards: IEEE C57.12 for transformer winding limits, ASHRAE A2 for
> hall envelope, IEEE 1188 for UPS battery checks. The chat model is a
> separate layer."

### Minute 3:30 — BMS Connector

Click **🔌 BMS Connector**.

> "We're not replacing a BMS — we're talking to one. Forty-two BACnet
> and Modbus tags across HVAC, power, IT, fire, security, and
> environment. Compatible with the namespace Niagara N4 and EcoStruxure
> use today."

Click on a writable tag like **HVAC.CHILLER1.CW_SETPOINT**.

> "Operators can issue setpoint changes here. Every write hits an
> immutable audit log per NIST SP 800-82 OT operations standard."

### Minute 4:00 — Scenarios + MOPs (brief)

Click **🧪 Scenarios** → SCN-01-PUMP-CAVITATION → Run.

> "Ten pre-defined failure scenarios with ODE-based 15-minute
> projections. The trajectory shows what would happen second-by-second.
> Notice the cascade event at t=59 seconds — secondary loop overtemp
> downstream of the cavitation."

Click **📋 MOPs & EOPs**.

> "Six indexed procedures covering chiller PM, UPS PM, generator
> exercise, VESDA test, PDU thermography, and emergency cooling
> reduction. Each is parsed into 4–7 actionable steps with execution
> checklist and timestamps. The AI can also draft new MOPs from the
> existing template — useful when a new equipment type is commissioned."

### Minute 4:45 — Claude Desktop integration (the kicker)

Switch to **Claude Desktop** (already running with MCP server connected).

In the chat, type:

> "Read the site health from a3semi facility, then simulate
> SCN-05-XFMR-OVERTEMP, and explain whether we'd lose redundancy."

Wait for Claude to respond using the MCP tools.

> "This is the same physics engine, accessed via the Model Context
> Protocol. Claude has live access to the digital twin. It just used
> two MCP tools — `read_resource` for site health, and `simulate_failure`
> for the scenario — and reasoned about the result."

### Minute 5:30 — Closing

> "What I built here is what I think Microsoft CO+I needs at scale: not
> a SCADA replacement, but the *physics-validated reasoning layer* that
> sits between SCADA and the operator. Every claim the AI makes is
> backed by an equation. Every number on the screen has been verified
> against first principles. Every MOP is grounded in standards.
>
> That's the architecture I'd bring to a hyperscale fleet."

---

## Q&A preparation — likely questions

**Q: Why your own physics engine instead of OpenFOAM / EnergyPlus?**

A: Those are full CFD/EMS — heavyweight, hours-long simulations, not
useful at the operations cadence. I built lumped-parameter ODEs that
solve in milliseconds, sufficient for "is the next 15 minutes safe?"
The trade-off is conscious: I lose detailed flow patterns but gain
real-time decision support.

**Q: How did you validate the physics?**

A: 93 unit tests covering bounds, conservation laws, and known-good
operating points. For the wet-bulb solver specifically, I verified
against ASHRAE Fundamentals Chapter 1 examples — Td=30°C, RH=50% gives
Twb=21.93°C. For the chiller COP curve, I used York YZ vendor data.
For UPS efficiency, Schneider Galaxy VX datasheet curves.

**Q: How would you scale this to 1,000 facilities?**

A: This is single-site. For fleet:
- Replace local LM Studio with a centralized inference cluster
- Replace TimescaleDB with sharded Postgres + Citus or partitioned
  ingestion
- The physics engine is stateless — it scales horizontally trivially
- The MCP server pattern is the right abstraction for fleet operations:
  Claude (or any LLM) queries any site through a uniform interface

**Q: Why MCP and not REST?**

A: Both are exposed. REST for the web UI; MCP for AI integration. MCP's
value is in the *typed resource/tool contract* — Claude understands
"read site health" without me having to design custom prompt
engineering. It's the standard way LLMs will integrate with operational
systems.

**Q: Security?**

A: Defense in depth: NeMo Guardrails on the agent (refuses
unauthorized actions), audit log on every BMS write (NIST SP 800-82),
no internet calls from the agent (LM Studio is local), IEC 62443
zone separation (the OT side is isolated from the dashboard via the
BMS connector layer).

**Q: What would you build next?**

A: Three things, in order:
1. Replace mock BMS with actual BACnet/IP client (1 week — I know the
   library: bacpypes3)
2. Add federated learning across facilities for model
   personalization (4 weeks)
3. Integrate with NVIDIA Morpheus for OT anomaly detection on the
   network layer (6 weeks)

---

## Backup slides (if live demo fails)

If anything breaks live, switch to:
- Slide deck `a3semi_CET_Training_Manual.pdf`
- Show physics smoke test output:
  `python scripts\physics_smoke_test.py`
- Show test pass count: `python -m pytest tests\ -q`

The system has a hard fallback: even if the database is offline, the
physics engine returns nominal values and the UI stays functional.
That's a feature — operators don't lose their dashboard during DB
maintenance.

---

## Time budget

- 0:00–0:30 — Open + framing
- 0:30–1:00 — Overview + SHI
- 1:00–1:45 — Topology + Physics-Verified
- 1:45–3:00 — Emergency Simulation (the moment)
- 3:00–3:30 — AI Mission Control
- 3:30–4:00 — BMS Connector
- 4:00–4:45 — Scenarios + MOPs
- 4:45–5:30 — Claude Desktop / MCP
- 5:30–7:00 — Q&A buffer

Stay ruthlessly within these blocks. If any one runs over, skip
Scenarios+MOPs (slot 4:00–4:45). The key beats are SHI, Emergency
Simulation, and MCP.
