# ADR-010: Dual-Graph Asset Taxonomy — Flow DAG vs Containment Tree

- Status: accepted
- Date: 2026-05-17
- Deciders: Wilmer Y. Angel Beltran
- Context: ProcedureGenerator sprint, Bite G1. See `docs/architecture/C0-Procedure-Generator.md`.

> Placed in `docs/adr/` alongside ADR-001..009 for ADR-series consistency
> (the directive named `docs/architecture/`; flagged in the G1 delta report).

## Context and Problem Statement

The ProcedureGenerator must author a micro-LOTO procedure for a sub-component
(one CDU coolant filter, one branch breaker) that isolates *only that branch*
without de-energizing the macro-equipment's still-active IT load. This needs
two distinct facts about every node:

1. *What feeds it* — to walk upstream and find the nearest isolation point.
2. *What it is physically inside* — to know the macro-equipment to preserve and
   the procedure scope (System/Equipment -> SOP/MOP; Component/Sensor -> EMP).

These are different relationships. Coolant *flows* pump -> filter -> injectors,
but the filter is physically *contained in* the pump assembly. `site_model.yml`
today models only flow (`power_chains` / `cooling_chains`); there is no
containment hierarchy for sub-equipment nodes.

## Decision Drivers

- Recursive micro-LOTO isolation-point search must be correct.
- Must stay non-breaking and within the flat-file convention.
- Must not corrupt the existing flow-graph semantics (`impact_set`, LOTO audit).

## Considered Options

1. **Single graph, typed edges** — one graph with `edge_type` of `feeds` vs
   `contains`. Rejected: conflates two semantics on one structure; every
   existing traversal (`impact_set`, `power_chain_for`) would have to filter
   edge types, and a containment edge accidentally walked as a flow edge is a
   silent safety bug.
2. **Containment tree only** — replace flow chains with a parent tree.
   Rejected: destroys isolation-point search (which is inherently a flow
   question) and breaks the LOTO auditor.
3. **Dual graph** — keep the flow DAG, add an orthogonal containment tree.
   **Chosen.**

## Decision

Maintain **two orthogonal graphs**, never merged:

- **Flow DAG** (unchanged) — `power_chains` / `cooling_chains`, directed
  `from -> to` = energy/coolant source -> load. Consumed by `site_model.py`
  (`power_chain_for`, `impact_set`). Used by the generator for upstream
  isolation-point search.
- **Containment Tree** (new) — each `components:` entry gains an optional
  `parent` pointer and an `asset_level` tier (System -> Equipment ->
  Sub-assembly -> Component -> Sensor). Used for scope classification.

System-tier roots are modelled as ordinary `components:` entries with
`type: system`, `asset_level: system` — **not** a separate top-level block.
This keeps every taxonomy tier queryable through the existing
`get_component()` API with **zero parser changes** (the C0 floated a separate
`systems:` block; this refinement avoids touching `site_model._build_*`).

`parent` / `asset_level` are captured automatically into
`ComponentInfo.metadata` by the existing lenient parser, so the schema
addition is non-breaking.

## Consequences

- Positive: recursive micro-LOTO is expressible — flow graph for the isolation
  search, containment tree for scope. Additive, non-breaking. No parser change.
- Negative: two structures to keep mutually consistent (a filter's `parent`
  and its flow edges must agree). Mitigated by a G3 validation check.
- Negative: System nodes counted as `kind="component"` in the GraphRAG graph
  (they live in the `components:` map). `test_graphrag` component count is
  updated accordingly.
- The DB-mirror gap stands: new `Asset` columns (`asset_level`,
  `parent_asset_id`, arc-flash fields) and the `procedure_class` CHECK
  (needs `EMP`) require a SQL migration — tracked as the standing follow-up.
