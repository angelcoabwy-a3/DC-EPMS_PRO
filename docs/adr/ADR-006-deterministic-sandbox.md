# ADR-006: Deterministic Sandbox — AI Has Zero Write-Action Authority

- Status: ACCEPTED
- Date: 2026-03 (foundational decision, retroactively documented 2026-05-06 in Batch 3)
- Decision-maker: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
- Sprint: S0 (foundational, predates V9 phase numbering)
- MADR template: https://adr.github.io/madr/

## Context

DC-EPMS PRO is a simulation of a Tier IV AI factory with critical electrical and mechanical systems: 800 VDC bus, 67 MW IT load, 2N power redundancy, N+1 cooling, hybrid sequential LOTO procedures, dual-path failover. In a real Microsoft CO+I deployment, an LLM agent that could **write** to these systems would be a catastrophic risk:

- A hallucinated CMMS work order that cites the wrong component could trigger a wrong LOTO and crash production workloads.
- A streaming LLM that writes BMS setpoints during a thermal transient could amplify a fault into an outage.
- A tool-calling agent that approves its own draft work orders erases the human-in-the-loop oversight that the IEC 62443 zone-and-conduit segregation model demands.

Industry guidance (NIST AI RMF, ISO/IEC 42001, IEC 62443-3-3 SR 6.1/6.2) all converge on the same principle for safety-critical OT environments: AI is an advisor, not an actor. The implementation must enforce this at the architecture level, not as a policy that depends on prompt discipline.

## Decision

Adopt the **Deterministic Sandbox** as a non-negotiable architectural constraint:

1. **Read-only topological authority**. AI components (Copilot agent, MCP server, future LOTO Auditor agent) may query `site_model.yml`, GraphRAG, ChromaDB, physics_engine state, and TimescaleDB telemetry. They may NOT mutate any of these.

2. **Document drafting only**. AI may draft CMMS work orders, MOPs, THAs, and pre-shift briefings. Every drafted document is created with status `Approval Request` in the Paperclip simulator. **No drafted document transitions to `Approved` or `Executing` without explicit CET signature**.

3. **No BMS write authority**. The BMS connector (`backend/bms_connector.py`) exposes read methods (`read_bms_tag`, `list_bms_tags`) to AI tools. The `write_bms_tag` capability exists in the connector but is **gated by a hardcoded check** that rejects calls originating from the AI tool registry. Only direct CET-signed REST endpoints with audit trail can invoke writes.

4. **Auditable provenance**. Every AI-generated artifact carries a `_provenance` field with the model used (e.g., `gemma-4-e2b-it via LM Studio` or `claude-sonnet-4 via Anthropic API`), the tools called, the standards cited, the LOR score computed, and a deterministic hash of inputs. This enables forensic reconstruction.

5. **Compute the impact, never enact it**. The agent can compute "if this rectifier is taken offline, the 2N redundancy collapses to N because Path B is in maintenance" and surface that conclusion as a warning in the draft. The agent cannot prevent the technician from approving anyway; that judgment is reserved to the human. The agent's job is to make the consequences visible, not to enforce them.

This is enforced by:

- The `agent_copilot.py` tool registry — none of the 6 registered tools writes to facility state.
- The `mcp_server.py` exposed tools — `simulate_failure`, `read_bms_tag`, `list_bms_tags` are all reads or simulations against synthetic state.
- The `cmms_mcp.py` `draft_cmms_work_order` tool produces `WorkOrderDraft` objects with status `pending_approval`; the only path to executable status is through `/api/cmms/approve` which requires an authenticated CET token.
- IEC 62443 zone-and-conduit segregation realized at the network layer in `docker-compose.yml` (per ADR-008 image): AI tools live on `epms-internal` bridge; BMS write paths live on a separate trusted conduit not accessible from AI containers.

## Consequences

### Positive

- **Defense in depth**. Even if a prompt-injection attack convinces the LLM to "write to the BMS", there is no code path that lets it. The capability does not exist in the running tool registry.
- **Regulatory alignment**. The Deterministic Sandbox is what NIST AI RMF and IEC 62443 demand for OT-adjacent AI. The project can pass a paper audit on the architecture diagrams alone.
- **Defensible interview narrative for Microsoft CO+I**. "How do you prevent the LLM from making a wrong decision in a 67 MW facility?" — the answer is structural, not policy.
- **Predictable failure modes**. If LM Studio crashes, the consequence is "no new drafts" — never "a wrong write went out". Graceful degradation.
- **Auditable**. `_provenance` field plus the Paperclip approval queue produces a complete forensic record.

### Negative / Trade-offs

- **Latency in operations**. Every action requires a CET in the loop. Acceptable: this is the entire point in Tier IV. Speed without correctness is a liability in critical environments.
- **Implementation discipline required**. New tools added to the registry must be reviewed for the read-only constraint. Mitigated by the small surface area (6 tools today; future additions like the LOTO Auditor Agent in Batch 4 are gated by ADR review).
- **Edge cases around DPO** (S6 V9). The DPO loop captures CET corrections to AI drafts. The fact that the AI consumes those corrections to update its own LoRA weights might be argued as "the AI updates itself" — but the update is gated by `POST /api/dpo/recompile` which requires CET trigger (not autonomous). See ADR-005 (scheduled S6) for full treatment.

## Alternatives Considered and Rejected

- **AI with conditional write authority** (e.g., low-risk writes auto-approved, high-risk writes gated). Rejected: introduces a classification problem for "what is low risk" that is itself error-prone in a 67 MW facility. The blast radius of any wrong write is too high.
- **AI with simulation-only write authority** (writes apply to a sandbox simulator, not to real facility state). Rejected: simulator/real divergence is itself a category of risk; better to keep AI strictly read-only and have all writes be CET-signed REST calls.
- **Cloud-side AI with stricter audit**. Rejected because the Hyperscale Override Protocol (1.4 GW Federated Fleet) requires edge-local autonomy under degraded uplink. The constraint must hold at the edge, not just in the cloud.

## References

- `backend/agent_copilot.py` — tool registry, all 6 tools read-only
- `backend/cmms_mcp.py` — `draft_cmms_work_order` produces `pending_approval` drafts
- `backend/bms_connector.py` — write paths protected by gating
- `backend/main.py` — `/api/cmms/approve` requires CET-token authentication
- `02_STATUS_SUMMARY_REAL.md` — describes Deterministic Sandbox as foundational
- ADR-001, ADR-002, ADR-003 — Dual-RAG architecture, all read-only retrievers
- ADR-005 (scheduled S6) — DPO compute strategy, manual trigger preserves the principle
- IEC 62443-3-3 SR 6.1 (Audit log) and SR 6.2 (Auditable events)
- NIST AI Risk Management Framework AI RMF 1.0
- ISO/IEC 42001 AI management systems (Annex A controls A.6 and A.7)

## Verification

- The 51 unit tests in `tests/test_cmms_mcp.py` verify that drafted work orders are produced with `pending_approval` status and never auto-transition.
- The 26 unit tests in `tests/test_witness_engine.py` verify multi-signature drafts cannot collapse to executable state without all required signatures.
- Code review constraint: any new entry in the agent tool registry MUST be reviewed against this ADR. New tools that implement writes are rejected by definition until they are restructured as drafts.
