# Epic 2 — The Optimizer (proactive edge-agent for PUE / WUE)

> **Status:** DESIGN (defined 2026-05-19). Implementation gated post-CO+I demo.
> **Anchor:** ADR-006 Deterministic Sandbox + the Epic 1 multi-agent consensus chain.
> **Companion:** `docs/engram/main-context.md` §13 (Epic 2 line); `docs/skills/skill-registry.md` (`S-DET-01`, `S-DET-02`, `S-SEC-02`).
>
> **Harness skills applied to author this brief:** `S-DET-01` (verdict before LLM), `S-DET-02` (Safety Officer veto uncrossable), `S-SEC-02` (claim-based RBAC), `S-DOC-01` (doc-sync separate).

---

## 1. Premise

A Tier IV AI factory's PUE and WUE depend on continuously-tuned setpoints
(chiller LWT, cooling-tower fan VFD, pump speed, CDU temperature, free-cooling
mode). Today these setpoints move on slow human cycles — shift handover,
monthly reviews. The platform's reactive AI fleet (Epic 1) responds to
operator queries but does not initiate.

The Optimizer is **the proactive complement to Epic 1**: a continuous edge-
agent that watches live Hermes telemetry and *proposes* setpoint adjustments
to drive PUE toward the architecture-aware target in `config/pue_targets.yml`,
while respecting ASHRAE A2 envelopes, hardware limits, redundancy invariants,
and operator constraints. It never actuates on its own.

## 2. Architectural decision — the Proposer Pattern (ADR-006 anchored)

**The Optimizer is a proposer, not an actuator.** This is the load-bearing
architectural invariant of Epic 2:

1. **Deterministic proposal value.** The setpoint adjustment is computed by a
   pure-Python control law (§4). The LLM is consulted *after* the value is
   fixed and writes only an advisory narrative (`S-DET-01`).
2. **No direct BMS write.** The Optimizer has no `actor_role` and cannot call
   `/api/bms/write` even if it tried. Proposals are written to a queue
   (`optimizer_proposals` table) — never to the live BMS path.
3. **Mandatory multi-agent validation.** Every proposal is routed through
   `MultiAgentOrchestrator.consult()`. The Safety Officer's `HARD_STOP` veto
   discards the proposal, full stop (`S-DET-02`). The Architect verifies
   redundancy impact; the Diagnostician checks recurrence patterns on the
   affected asset; the Analyst frames the kWh / OpEx delta.
4. **Pre-flight What-If simulation.** Each proposal carries an attached
   sandbox outcome (delta-PUE, delta-ECWT, ASHRAE distance, redundancy
   post-state). The sandbox engines (`core/power_grid.js` for power,
   the Cooling L3 sandbox for thermal) are the **validation gate** before
   consensus is even requested.
5. **Operator approval issues the write.** A separate endpoint
   `POST /api/optimizer/approve/{proposal_id}` is gated at `actor_role >=
   SME_L6` (`S-SEC-02`). On approval, the *backend* issues `/api/bms/write`
   attaching the operator's claim — the Optimizer is still not in the call
   chain. NIST SP 800-82 audit covers the whole proposal → consensus →
   approval → BMS write chain by UUID.

This pattern preserves ADR-006 (no LLM in critical decision path), CSA Z462
+ NFPA 70E (no unattended actuation on critical systems), and the platform's
existing RBAC discipline.

## 3. Bounded scope (V11 cut)

**In scope (V11):**
- **Chiller LWT setpoint** — the master cooling lever; biggest PUE swing.
- **Cooling-tower fan VFD modulation** — second-largest lever via ECWT.
- Single-step proposals only.
- Reactive trigger: PUE drift above `pue_targets.yml` target sustained for
  ≥ 5 minutes (per Toronto baseline — see `engram §11`).
- Pacing: ≤ 1 proposal per surface per 15 minutes (oscillation guard).

**Deferred (Epic 2.1+):**
- Pump VFD optimisation (CHW + condenser-water).
- CDU supply temperature tuning.
- Free-cooling mode switching.
- Predictive multi-step horizon control.
- Direct GPU clock / power-cap tuning.
- BESS dispatch (utility peak-shaving).
- WUE optimisation — needs makeup-water sensor coverage we do not yet model.

## 4. Control loop & deterministic core

`backend/optimizer.py` — a single-instance asyncio task started in the FastAPI
lifespan, gated by `DC_EPMS_OPTIMIZER_ENABLED` (default `false` for V11 — opt-in
per deployment).

```text
loop every 30 s:
    point        = hermes.latest_telemetry()
    kalman       = hermes.latest_kalman_channels()
    if pue_drift_sustained(point, sustain_ticks=10):           # ≥ 5 min
        for surface in [chiller_lwt, ct_fan_vfd]:
            proposal = compute_proposal(surface, point, kalman)
            if proposal is None or proposal_paced(surface):
                continue
            sandbox = simulate_in_whatif(proposal)
            if sandbox.violates_ashrae or sandbox.drops_redundancy:
                audit('rejected_pre_consensus', proposal, sandbox)
                continue
            ctx = build_consult_context(proposal)
            consensus = await multi_agent.consult(ctx)
            if consensus.consensus == 'hard_stop':
                audit('safety_veto', proposal, consensus)
                continue
            narrative = await gemma_synthesize(proposal, sandbox, consensus)
            await proposal_queue.enqueue(
                proposal, sandbox, consensus, narrative,
            )
            hermes.publish('optimizer-proposal', {...})
```

`compute_proposal(surface, point, kalman)` is rule-based for ADR-006
transparency. Initial heuristics:

- **Chiller LWT:** `if pue_drift > 0 AND chiller_lwt > 6.0 °C` → propose
  `lwt -= 0.5 °C`. Bounded by ASHRAE A2 envelope on hall inlet (≤ 27 °C
  recommended ceiling per `physics/it_thermal`).
- **CT fan VFD:** `if pue_drift > 0 AND (ecwt - wet_bulb) > 5.0 K` →
  propose `vfd += 5 %` (capacity headroom available). `if approach < 2.0 K`
  → tower already saturated, no proposal.

A future revision may swap in a learned PUE-surrogate model + gradient
descent, but the V11 cut is rule-based and inspectable.

## 5. Multi-agent validation gate

Every proposal becomes a `ConsultContext` and routes through Epic 1:

| Agent | What it validates for an Optimizer proposal |
|---|---|
| **Safety Officer** | LOTO + PPE scope. A setpoint change is not LOTO; verdict normally `caution` or `approve`. `hard_stop` if proposal would energise / de-energise a downstream asset that lacks an MOP. |
| **Architect** | Redundancy invariant. A chiller LWT drop that *forces* a chiller staging change (N+1 → N) becomes `caution`. |
| **Diagnostician** | Recurrence. A known-degrading chiller (3+ WOs in 18 months) should not be pushed harder — verdict `caution`. |
| **Analyst** | CapEx vs OpEx framing — kWh saved by the proposal vs. mechanical wear cost. |

Each agent attaches its Gemma narrative (Epic 1 T3.3 / T3.3b / T3.3c / T3.3d).
The Optimizer's own narrative explains *the proposal value* and *the expected
delta*; it is grounded in the sandbox outcome + the live Kalman block via the
same `_synthesize_narrative` pattern (`S-DET-03`).

Consensus is treated verbatim: `hard_stop` → discard; `caution` or `approve`
→ enqueue.

## 6. RBAC + actuation path (`S-SEC-02`)

- The Optimizer service runs **with no claim token**. Backend RBAC middleware
  rejects any direct `/api/bms/write` invocation it might somehow generate.
- New endpoint `POST /api/optimizer/approve/{proposal_id}` enforces
  `actor_role >= SME_L6` (same gate as direct BMS write) and additionally
  requires the operator to confirm the sandbox-projected ASHRAE distance is
  within tolerance.
- On approval, the *route handler* — not the Optimizer — issues
  `/api/bms/write` with the operator's `actor_role`. The audit log records
  three linked rows: proposal, approval, BMS write. Single UUID joins them.
- Endpoint `POST /api/optimizer/reject/{proposal_id}` records the reason; the
  rejection list is read by V11 in a future feedback loop (Epic 2.2 deferred).

## 7. HMI surface

New view `views/optimizer.js` (route `optimizer`). Per `S-ROUTE-01` it
registers on `core/router.js` via `registerRoute('optimizer', …)`. Lists the
live proposal queue with, per proposal:

- Surface name + proposed value + delta vs. current value.
- Multi-agent consensus chip (Epic 1 UI parts reused).
- The 4 Epic-1 narratives + the Optimizer's own narrative.
- The What-If sandbox outcome: projected delta-PUE, delta-ECWT, ASHRAE
  distance, redundancy mode post-actuation.
- **Approve & Actuate** button (`actor_role` selector, defaults to SME_L6).
- **Reject** button (records the operator's reason text).

All LLM-authored narratives route through `core/sanitize.js sanitizeHTML`
per `S-SEC-01` (the Optimizer's narrative IS LLM-authored; the proposal
metadata is structured UI with intentional buttons and uses per-value
`escapeHTML`).

Live updates via the existing Hermes EDA plane — `hermes:optimizer-proposal`
DOM event, picked up by `views/optimizer.js`.

## 8. Testing strategy

| Layer | Coverage |
|---|---|
| Unit (deterministic core) | `compute_proposal` returns expected values for canonical PUE-drift / approach scenarios. Verdict-unchanged-by-LLM (`S-DET-01` test pattern). |
| Integration (proposal pipeline) | FakeGemma + mock `multi_agent.consult` — a proposal lands in queue with consensus + narrative + sandbox. |
| Safety (veto blocks) | Synthetic Safety Officer `hard_stop` → proposal discarded, audit entry written, queue remains empty (`S-DET-02`). |
| RBAC (no autonomous write) | Sub-SME_L6 caller → HTTP 403 on approve endpoint (`S-SEC-02`). |
| No-bypass smoke test | Disable the approve endpoint; let the Optimizer tick for N cycles; assert `bms_write_log` rows do not grow. |
| Frontend | `tests/frontend/optimizer.test.js` — render + XSS escape on narrative + route registration via `isRegistered('optimizer')` (`S-TEST-02`). |

**Floors at Epic 2 close:** pytest ≥ ~740 (∼14 new tests), Vitest ≥ ~184
(∼8 new tests, new view file). Per `S-TEST-01` / `S-TEST-02`.

## 9. Sequencing & dependencies

**Target window:** post-CO+I demo (August 2026). Pre-demo focus stays on
delivery; Epic 2 is the next major architectural sprint.

**Dependencies (status now):**
- ✅ Multi-agent fleet (Epic 1) — full 4-agent narratives live.
- ✅ Hermes EDA + `hermes.latest_kalman_channels()` — `hermes.py:218`.
- ✅ RBAC chain + `/api/bms/write` SME_L6 gate.
- ✅ What-If sandbox (Power) — `core/power_grid.js`.
- ✅ What-If sandbox (Cooling) — Cooling L3 control plane.
- ⚠ `config/pue_targets.yml` — exists (v0.9.14); confirm CT-approach target line is present, add if missing.
- ⚠ Canonical control-law reference set — needs Toronto-baseline calibration runs (per `engram §11`).

**Internal sub-batches (each independently shippable):**

| Batch | Scope | ~Effort |
|---|---|---|
| **2.A** | `backend/optimizer.py` deterministic control law + asyncio task + audit log + unit tests | 3 days |
| **2.B** | Multi-agent consensus integration + proposal queue + Hermes event emission | 2 days |
| **2.C** | `POST /api/optimizer/approve` + `/reject` endpoints + RBAC gate + write-chain audit | 1 day |
| **2.D** | `views/optimizer.js` + Vitest + the proposal queue HMI | 2 days |
| **2.E** | Live smoke test + `S-RUNTIME-01` boot signature verification + release tag `v0.13.0` *"Proactive Edge"* | 1 day |

**Total ~9 days** of focused work; assumes no scope creep into deferred
surfaces.

## 10. Open questions (explicitly deferred decisions)

- Should rejected proposals feed a learning loop? **No for V11** — preserves
  ADR-006 simplicity. Epic 2.2 candidate.
- Should the Optimizer emit a Hermes event on every tick (not just on
  proposal)? **No** — `hermes:optimizer-proposal` only, to avoid telemetry
  noise.
- Predictive multi-step horizon control? **Deferred to V12** — needs a
  validated PUE-surrogate model and a longer test corpus.
- WUE optimisation? **Deferred to Epic 2.1** — requires makeup-water sensor
  coverage not yet modelled.
- Should the Optimizer be allowed to propose actuation outside of operator
  hours (24/7)? **Yes, propose; no, actuate** — the queue persists, the
  operator approves in their shift.

## 11. ADR-006 invariants re-stated (acceptance checklist)

The implementation is "done" only when every line below is verifiable:

- [ ] `compute_proposal()` is pure-Python; no LLM call inside.
- [ ] No code path in `backend/optimizer.py` calls `requests.post(/api/bms/write)` or any equivalent.
- [ ] Every proposal carries a `consensus` field populated by `multi_agent.consult()` before enqueue.
- [ ] A Safety Officer `hard_stop` consensus DISCARDS the proposal; an audit row records the veto.
- [ ] `POST /api/optimizer/approve` enforces `actor_role >= SME_L6` and returns HTTP 403 below it (tested).
- [ ] Operator approval is what issues the BMS write (the Optimizer is not on that call stack).
- [ ] The HMI surface routes every LLM-authored narrative through `sanitizeHTML`.
- [ ] Smoke test verifies the post-restart `[BOOT]` log carries an Optimizer-aware signature, per `S-RUNTIME-01`.

## 12. References

- ADR-006 — `docs/adr/ADR-006-deterministic-sandbox.md` (load-bearing).
- ADR-004 — `docs/adr/ADR-004-pue-physics.md` (PUE target model).
- `docs/engram/main-context.md` §13 — Epic 2 future-roadmap note; §11 Toronto baseline.
- `docs/skills/skill-registry.md` — `S-DET-01` / `S-DET-02` / `S-DET-03` / `S-SEC-01` / `S-SEC-02` / `S-TEST-01` / `S-TEST-02` / `S-COMMIT-01` / `S-RUNTIME-01` / `S-ROUTE-01` cited herein.
- `backend/multi_agent.py` — Epic 1 consensus + Safety Officer veto chain.
- `backend/hermes.py:218` — `latest_kalman_channels()` live Z-score tap.
- `config/pue_targets.yml` — architecture-aware PUE thresholds.
