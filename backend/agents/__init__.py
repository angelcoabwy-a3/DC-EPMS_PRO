"""
backend/agents/
===============
Specialised LLM-authoring agents that compose with the reactive
deterministic fleet in :mod:`backend.multi_agent`. Each agent here is
responsible for producing structured operator-facing artifacts (text
documents, drafts, narratives) — distinct from the multi_agent
fleet, which votes on operator queries.

Members:
  * :mod:`backend.agents.procedure_architect` — Procedure Architect
    (Epic 6). Generates SOP / MOP / EOP / EMP documents using the
    four canonical templates. Output is audited by a deterministic
    Safety Officer pass before reaching the operator.
"""
