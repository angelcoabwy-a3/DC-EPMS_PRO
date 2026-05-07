# 5-Layer SRE Architecture Mapping — DC-EPMS PRO

**Purpose**: This document maps the five Site Reliability Engineering operational layers that Microsoft Cloud Operations + Innovation (CO+I) and analogous hyperscale operators rely on, against the specific code, sprints, and standards in DC-EPMS PRO. The intent is to make defensible, evidence-grounded statements during interviews and architecture reviews — not marketing slides.

**Maintainer**: Wilmer Y. Angel Beltran, Lead Architect, a3semi
**Last updated**: 2026-05-06 (Batch 3 DevOps Quick Wins closure)
**Scope**: A3-Alpha Toronto Area, 67 MW Path C2 (118x GB200 NVL72 Phase 1 + 250x GB300 NVL144 Phase 2)

---

## Layer 1 — Predictive (Physics and Telemetry)

### What hyperscale operators expect at this layer

Detect deviation from steady-state before alarms latch. The discipline here is closer to control engineering than to traditional IT monitoring: read first-principles physics (thermodynamics, electrical balance, fluid dynamics), apply state estimation (Kalman, particle filter), forecast trajectories of critical metrics, and surface predicted boundary violations with enough lead time for the CET to take corrective action.

### What DC-EPMS PRO does at this layer

| Component | Implementation |
|---|---|
| First-principles physics | `backend/physics/` package: 4 sub-modules (`it_thermal`, `mechanical`, `heat_rejection`, `electrical`) implementing Darcy-Weisbach pressure drop, Magnus-Tetens psychrometric saturation, ANSI C57.12 transformer loss model, ODE integration via `scipy.solve_ivp` for transient air temperature evolution |
| Aggregated facility health | `backend/physics_engine.py` facade computes Site Health Index (SHI) from per-module health states, weighted by redundancy state (2N power, N+1 cooling) |
| Telemetry stream | `backend/database.py` (asyncpg + TimescaleDB hypertables) ingests synthetic telemetry; `/api/telemetry/stream` Server-Sent Events publishes live updates |
| Sensor fusion (planned S5) | `backend/cyber_physical_tools.py` (orphan to be integrated): Kalman innovation residual flagging anomalies; Numba `@njit` JIT compilation for hot path; Send-on-Delta protocol to suppress redundant sensor publishes |
| PUE forecast (planned S5.5b) | `physics_engine.compute_pue()` aggregates 4 modules with first-law cross-check; threshold classification per `config/pue_targets.yml` (Phase 1: <1.30 green / <1.45 yellow; Phase 2: <1.15 / <1.25) |

### Sprints contributing to this layer

- **S1a-physics**: 4 modules + facade, 85 unit tests (`tests/physics/`)
- **S5 W5-6**: integrate `cyber_physical_tools.py` per Decision D1 vote 1A
- **S5.5b W7**: PUE compute + first-law cross-check
- **S7 W9-10** (Alarm Storm): topological correlation of co-occurring alarms

### Standards grounding

- ASHRAE TC 9.9 Class A2 thermal envelope (telemetry sample cadence and limits)
- ANSI C57.12 transformer iron + copper loss model
- IEC TR 63282 Section 5.2 (LVDC voltage band U2-U5)
- ISO 11064-7 ergonomic requirements for control center monitoring (latency budgets)

---

## Layer 2 — Management (CMMS and Work Orders)

### What hyperscale operators expect at this layer

Every detected deviation must produce a *workable artifact* — a CMMS work order that names the responsible technician, the impacted asset, the parts required from inventory, the level-of-risk score, the standards cited, and the entry/exit pre-conditions. The work order is the operational currency. AI assistance must integrate into the existing CMMS workflow, not replace it.

### What DC-EPMS PRO does at this layer

| Component | Implementation |
|---|---|
| Deterministic LOR scoring | `backend/cmms_mcp.py` (`draft_cmms_work_order` tool, ~492 lines, 51 unit tests) computes Level-of-Risk based on component criticality, redundancy state, voltage level, and active maintenance windows |
| Site context injection | `backend/cmms_site_enrichment.py` adds topology context (rack, row, room, building, redundancy state) to every draft |
| Procedure orchestration | `backend/procedure_engine.py` (8-state machine, ~641 lines, 32 unit tests) runs MOPs from YAML with pre-condition gates that read live telemetry |
| Witness signing | `backend/witness_engine.py` (~290 lines, 26 unit tests) implements multi-signature approvals — high-LOR procedures require multiple CET signatures before transitioning to executing state |
| Paperclip approval queue | All AI drafts persist with status `pending_approval`; only CET-authenticated `/api/cmms/approve` transitions them to `approved` |
| HAL adapters | `backend/hal/` package: Cummins genset, ASCO ATS, Russelectric switchgear adapters (~1000 lines, 39 unit tests) — vendor-specific control surfaces under unified facade |

### Sprints contributing to this layer

- **S1a procedures**: state machine, witness, CMMS drafting, HAL adapters
- **S5 W5-6**: integrate Kalman residual into pre-condition gates
- **S6 W7-8**: DPO capture loop on rejected drafts (per ADR-007)
- **Batch 4 (post-Batch 3)**: LOTO Auditor Agent — paranoid validator that checks if a proposed LOTO breaks 2N redundancy before approving

### Standards grounding

- IEC 62443-3-3 SR 6.1, 6.2 (audit log requirements)
- CSA Z462-24 (Ontario jurisdiction electrical safety) for LOTO procedures
- NFPA 70E (PPE category determination)

---

## Layer 3 — Safety (THA and JHA — Task Hazard Analysis)

### What hyperscale operators expect at this layer

Before any human enters a high-energy zone, a Task Hazard Analysis must compute the arc flash incident energy at the working distance, determine the PPE category required (NFPA 70E Tables 130.5(C) and 130.7(C)(15)(c)), document the boundary distances, and gate the procedure on PPE confirmation. This cannot be skipped, even for routine work.

### What DC-EPMS PRO does at this layer

| Component | Implementation |
|---|---|
| LOTO procedure citations | All procedure YAMLs cite NEC 460.6 (capacitor discharge), CSA Z462-24, NFPA 70E in their `_provenance` block |
| LOTO Level escalation | When `voltage_nominal >= 800` (Building D 800 VDC), the EHS Auditor (S4) auto-escalates to LOTO Level 4 with mandatory capacitor discharge wait of 60 seconds |
| Pre-condition gates | `procedure_engine.py` checks live telemetry before proceeding (e.g., bus voltage < 50 V before declaring zero-energy) |
| Topology-aware impact | `backend/site_model.py` `compute_impact_set()` walks power_chains DAG to identify all downstream loads that lose power if the target is de-energized |
| **Planned (Batch 4)** | LOTO Auditor Agent: `loto_auditor_agent.py` — paranoid validation that proposed LOTO does not break 2N redundancy; cross-checks GraphRAG (which standards apply) + Physics Engine (will the surviving path hold the load) + topology (downstream impact) |

### Sprints contributing to this layer

- **S4 W3-4 EHS Auditor**: DSPy-based rules engine encoding the LOTO escalation policy
- **Batch 4**: LOTO Auditor Agent (Pillar 4 implementation, ~12-16 hours)

### Future Work (V10 candidate)

- **Arc Flash Boundary calculator** per NFPA 70E Annex H formula (incident energy as function of bolted fault current, working distance, arc gap). Requires integration with the electrical sub-module and short-circuit current data from upstream sources.

### Standards grounding

- NFPA 70E Article 130 (Safety-Related Work Practices)
- NFPA 70E Annex H (Arc flash boundary calculations)
- CSA Z462-24 (Ontario equivalent and update)
- NEC 460.6 (capacitor discharge waiting period)
- OSHA 29 CFR 1910.147 (LOTO general standard, US baseline)

---

## Layer 4 — Post-Incident (RCA and 5-Whys)

### What hyperscale operators expect at this layer

When an outage or near-miss occurs, a Root Cause Analysis must be produced within hours, not days. The RCA reconstructs the event timeline from logs and telemetry, identifies the proximate cause and the chain of contributing causes (5 Whys methodology), recommends preventive measures, and feeds those recommendations back into the procedure library. AI assistance accelerates this without replacing the human judgment about systemic causes.

### What DC-EPMS PRO does at this layer

| Component | Implementation |
|---|---|
| Telemetry windowed retrieval | `backend/database.py` query supports time-windowed extraction (e.g., last 5 minutes around an incident) from TimescaleDB hypertables |
| Topology reconstruction | `backend/graphrag_service.py` query "what was the redundancy state at time T" via NetworkX + applies_to edges (per ADR-001 and ADR-002) |
| Incident persistence | `incidents` table in TimescaleDB; `/api/incidents` endpoint for write and retrieve |
| MCP server resource | `mcp_server.py` exposes `a3semi://incidents/recent` resource for Claude Desktop subprocess access |

### What is **NOT** yet built (honest gap)

A dedicated **RCA agent** that orchestrates the 5 Whys methodology automatically — pulling telemetry, reconstructing topology, drafting the incident narrative — does not exist in V9. This is a **V10 candidate** rather than a current capability. Honesty about gaps is a defensible position in a panel review; pretending otherwise would crater credibility.

### Sprints contributing to this layer

- **Existing**: telemetry ingest + incidents CRUD + GraphRAG topology query
- **V10 candidate**: `rca_agent.py` — automated 5 Whys orchestrator producing an RCA draft with cited evidence; would consume the same Deterministic Sandbox principle (drafts only, not closures)

### Standards grounding

- ITIL 4 Incident Management
- ASME RP-3 (Root Cause Analysis Recommended Practices, generic engineering)
- IEC 62443-2-1 Annex A.4 (incident response)

---

## Layer 5 — Commissioning (Cx, IST — Integrated Systems Testing)

### What hyperscale operators expect at this layer

When a new piece of infrastructure (rack, MV rectifier, BESS, chiller) is added to the facility, it must pass Levels 1-5 of commissioning before going live: factory acceptance test, on-site verification, point-to-point checkout, functional test, integrated systems test. The IST is the climactic test where the entire chain — utility loss simulation, generator start, ATS transfer, UPS bridge, BMS handoff — must complete in under 10 seconds (the standard for Tier IV).

### What DC-EPMS PRO does at this layer

| Component | Implementation |
|---|---|
| Simulated facility model | `config/site_model.yml` declares the entire facility topology declaratively. Adding a new component (e.g., a Building D MV rectifier) is a YAML edit, not a code change |
| Procedure execution against the model | `procedure_engine.py` runs MOPs against the simulated state; pre-condition gates verify expected initial state, post-condition gates verify final state |
| What-if simulator | `/api/topology/whatif` endpoint accepts a synthetic fault injection (e.g., "what if I de-energize ats_a?") and computes the resulting impact set + redundancy state without applying the change |
| Scenario library | `mcp_server.py` resource `a3semi://scenarios/list` exposes the library of pre-defined commissioning scenarios for Claude Desktop subprocess access |

### Sprints contributing to this layer

- **S1b**: site_model declarative parsing + LOTO impact analysis
- **Existing**: `/api/topology/whatif`, scenario library
- **S5.5a Pre-Operational Briefing** (W6.5) consumes IST-style validations as part of the daily handover pipeline

### Future Work (V10 candidate)

- **Automated IST runner**: `ist_runner.py` would orchestrate a full 10-second sequence (utility loss simulated -> generator start at t+0.5s -> ATS transfer at t+8s -> verify load held throughout) and produce a pass/fail report with timing budget breakdown. Would consume `procedure_engine.py` as the substrate.

### Standards grounding

- Uptime Institute Tier IV Topology Standard (10-second hold during utility transition)
- ASHRAE Guideline 0 (commissioning process)
- IEEE 3001 series (commercial and industrial power systems)

---

## Cross-cutting concerns

### Deterministic Sandbox (per ADR-006)

All five layers preserve the principle: AI may *read* and *draft*, never *write* to facility state. Predictive findings produce alerts, not auto-actions. CMMS drafts produce approval requests, not approvals. THA drafts produce PPE recommendations, not authorization to enter. RCA drafts propose preventive measures, not closures. IST simulations validate, never apply.

### Audit trail

Every artifact produced at any layer carries a `_provenance` block with: model used, tools called, standards cited, deterministic input hash. Persisted to PostgreSQL (telemetry to TimescaleDB hypertable, drafts to ordinary tables, briefings to `shift_briefings` per S5.5a).

### Edge-first autonomy

All five layers operate without uplink. The full RAG corpus (20 docs ChromaDB + 5 docs GraphRAG), the physics engine, the procedure engine, and the local LLM (gemma-4-e2b-it via LM Studio) are inside the container. Cloud is a fallback (Claude Sonnet via Anthropic API), not a dependency. Aligned with the Hyperscale Override Protocol scenario where uplink may be degraded across the 1.4 GW Federated Fleet.

---

## Sprint-to-Layer Coverage Matrix

| Sprint | L1 Predictive | L2 Management | L3 Safety | L4 Post-Incident | L5 Commissioning |
|---|---|---|---|---|---|
| S0 baseline | --- | --- | --- | --- | --- |
| S1a procedures | --- | YES | YES | --- | YES |
| S1a-physics | YES | --- | --- | --- | --- |
| S1b site model | --- | YES | YES | YES (topology) | YES |
| S2 GraphRAG | --- | YES (citations) | YES (standards) | YES (topology) | YES |
| S3 W1-2 DevOps | --- | --- | --- | --- | --- |
| **Batch 4 LOTO Auditor** | --- | YES | **YES (primary)** | --- | --- |
| S4 EHS Auditor | --- | YES | YES | --- | --- |
| S5 telemetry + Kalman | YES (primary) | YES (gates) | --- | --- | --- |
| S5.5a Briefing | YES | YES | YES (procedure recall) | --- | YES (IST recall) |
| S5.5b PUE | YES | --- | --- | --- | --- |
| S6 DPO | --- | YES (improvement) | --- | --- | --- |
| S7 Alarm Storm | YES | --- | --- | YES | --- |
| S8 EOP Abort | YES | --- | YES | --- | --- |
| **V10 RCA Agent** | --- | --- | --- | **YES (primary)** | --- |
| **V10 IST Runner** | --- | --- | --- | --- | **YES (primary)** |

---

## Defensible interview narrative (for Microsoft CO+I panel)

When asked "how does your platform support the operational lifecycle of a critical environment?", the layered framing above provides a structured answer. The candidate's value proposition:

1. **Predictive** — first-principles physics, not just dashboards. State estimation grounded in published thermal and electrical models, with a defined first-law cross-check on PUE that flags the case where the model and reality diverge by more than 2 percent.
2. **Management** — deterministic LOR scoring, topology-aware impact analysis, every draft mandatory through CET approval per IEC 62443.
3. **Safety** — standards-grounded LOTO escalation logic with explicit jurisdictional binding (CSA Z462-24 for Ontario), arc flash boundary as next gap to close (V10).
4. **Post-Incident** — telemetry plus topology reconstruction is in place; the RCA orchestrator is honestly identified as a V10 gap.
5. **Commissioning** — declarative facility model means new infrastructure is a YAML edit, not a code change; what-if simulator validates impact before commit; IST automation as next gap (V10).

The honesty about the V10 gaps is itself a credibility signal — operators trust contributors who say "this is a gap, here is how I would close it" over those who claim full coverage on slides.
