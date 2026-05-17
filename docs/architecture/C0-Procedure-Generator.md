# C0 — ProcedureGenerator Sprint: Architecture 1-Pager

**Status**: C0 design record. No code. Drafted 2026-05-17.
**Author**: design pass per Wilmer directive (MACRO-TO-MICRO ASSET TAXONOMY).
**Constraints**: flat-file convention (no new `backend/` subdirs); ASCII; Path C2
67 MW / 368-rack scale unchanged; net-new module (no `procedure_generator.py`
exists today).

## Architectural intent

A net-new `backend/procedure_generator.py` that **auto-authors procedure YAMLs**
into `config/procedures/`, scope-aware from a macro-system (a UPS, a chiller
plant) down to a micro-component (one branch breaker, one CDU filter, one
sensor). Four algorithmic pipelines: SOP Factory, Topological MOP Compiler,
Kalman-triggered EOP Factory, EMP Lifecycle Factory. Output conforms to the
existing procedure schema that `procedure_engine.ProcedureRegistry` already
loads, so generated procedures are immediately executable + LOTO-auditable.

The hard problem this C0 must solve before any code: the data model. Two gaps
block a credible generator — (1) there is no containment hierarchy for
sub-equipment nodes, and (2) there is no Arc Flash data to drive NFPA 70E PPE
selection. Sections 1 and 2 fix those; Section 3 is the traversal that uses
them; Section 4 phases the build.

## 1. Schema Redesign — 5-level hierarchical taxonomy

### The key distinction: two graphs, not one

The platform must hold **two orthogonal relationships**, and conflating them is
the primary design risk:

- **Flow DAG** (already exists) — `site_model.yml` `power_chains` /
  `cooling_chains`, directed `{from, to}` edges = energy/coolant flows
  source -> load. Consumed by `site_model.py` (`_build_power_chains`,
  `power_chain_for`, `impact_set`). Answers *"what feeds what"*.
- **Containment tree** (new) — `parent` pointers = *"what is physically inside
  what"*. A fuel filter is *contained in* the fuel pump, but coolant *flows*
  pump -> filter -> injectors. Different relationship, different graph.

Micro-LOTO needs both: the **flow DAG** to find the isolation point, the
**containment tree** to classify scope (which macro-equipment to preserve,
which procedure class to emit).

### Taxonomy tiers

`System -> Equipment -> Sub-assembly -> Component -> Sensor`

Worked example (the directive's): `sys_backup_power` (System) -> `genset_a_01`
(Equipment) -> `genset_a_01_fuel_pump` (Sub-assembly) -> `genset_a_01_fuel_filter`
(Component) -> `genset_a_01_fuel_pressure_probe` (Sensor).

### Changes — additive, non-breaking

`config/site_model.yml`:

- New top-level `systems:` block declaring the System-tier roots
  (Backup Power, Critical Power Distribution, Primary Cooling, ...).
- Each entry in the existing `components:` map gains two **optional** fields:
  `asset_level` (one of the 5 tiers) and `parent` (canonical_id of the
  container). Components without them default to `asset_level: equipment`,
  `parent: <none>` — every existing component keeps working untouched (the
  file's own comment already guarantees additive entries are non-breaking).

`backend/cmms_models.py`:

- New `AssetLevel(str, Enum)`: `SYSTEM / EQUIPMENT / SUB_ASSEMBLY / COMPONENT /
  SENSOR`, plus an `ASSET_LEVELS` tuple constant for the SQL/UI surface.
- `Asset` model gains `asset_level: str | None` and `parent_asset_id:
  str | None`, both defaulted (non-breaking with `extra="forbid"`).
- Reconcile the procedure-class drift: `PROCEDURE_CLASSES` is currently
  `("SOP","MOP","DMOP","EOP")` while `procedure_engine.ProcedureClass` is
  `SOP/MOP/EOP`. C0 decision: add **`EMP`** (Equipment Maintenance Procedure)
  to both, resolve/retire `DMOP`.

`backend/site_model.py`: extend the parser to read `systems:` + `parent` and
expose `containment_parent(id)`, `containment_children(id)`, and `asset_level(id)`
alongside the existing flow-graph API.

**Honest caveat**: the `Asset` table mirror (`backend/migrations/`) does not
carry the new columns — same DB-mirror gap as the RBAC fields. G1 bundles a SQL
migration. site_model.yml will also need micro-component *data entry* — see
Risks.

## 2. Arc Flash Data Model (NFPA 70E / CSA Z462)

The flagged gap: **voltage alone cannot set the arc-flash PPE category.**

Two distinct safety outputs, two distinct data needs:

- **Shock approach boundaries** (Limited / Restricted) — a function of
  **voltage** (NFPA 70E Table 130.4). The generator *can* derive these from the
  existing `voltage_v` / `voltage_v_dc` fields.
- **Arc-flash boundary + AR PPE category** — a function of **incident energy
  (cal/cm2)**, which derives from available fault current, clearing time and
  geometry per an IEEE 1584 study. Voltage does NOT determine it.

### Changes

Add three **optional** fields to electrical nodes in `site_model.yml`
`components:` (mechanical/sensor nodes leave them null), mirrored on the `Asset`
model:

- `fault_current_ka` — available bolted fault current.
- `incident_energy_cal` — incident energy at working distance (cal/cm2).
- `arc_flash_boundary_m` — arc-flash boundary distance.

**These are engineered inputs, not computed by DC-EPMS.** They are populated
from an IEEE 1584 study / coordination report. The platform *carries and
consumes* them; it does **not** calculate incident energy from first principles
(that requires the full IEEE 1584 model + system impedance — out of scope, and
faking it is a safety-engineering fraud).

### Generator behavior

When generating a micro-level procedure for an electrical node, the engine
injects a mandatory Arc Flash step:

- Reads `incident_energy_cal` of the node (or its parent Equipment), maps it to
  the existing `loto_auditor_models.PPECategory` enum
  (CAT_1 = 4, CAT_2 = 8, CAT_3 = 25, CAT_4 = 40 cal/cm2 per NFPA 70E
  130.7(C)(15)). Emits the AR PPE category + the arc-flash boundary distance.
- If `incident_energy_cal` is **null**: the step is still emitted, but with
  `failure_action: ABORT` and a `DATA_REQUIRED` marker. The generator
  **refuses to guess a PPE category from voltage**. No silent heuristic.

## 3. Recursive Traversal Logic — micro-LOTO isolation point

Problem: a TECH_L4 targets a micro-component (`cdu_a_01_secondary_filter`). Find
the **nearest upstream isolation point** that isolates only that branch, without
de-energizing the macro-equipment's still-active IT load.

Approach: walk the **flow DAG** *against* the flow (`predecessors`), level-order
(BFS, so the first hit is the *nearest*), until an isolation-capable node is
found. Reuse the NetworkX graph already built from `power_chains` /
`cooling_chains` (`site_model.py` / `knowledge_graph.py`).

```text
find_isolation_point(target_id, graph, max_hops = 8):
    # graph: DiGraph of flow edges (from -> to). predecessors() = upstream feeders.
    frontier = [target_id]
    visited  = {target_id}
    for hop in 1 .. max_hops:
        next = []
        for node in frontier:
            for up in graph.predecessors(node):
                if up in visited: continue
                visited.add(up)
                if is_isolation_capable(up):
                    return IsolationPoint(node=up, hops=hop)   # nearest -> stop
                next.append(up)
        frontier = next
    return None        # no local isolation point -> fall back to macro-LOTO + WARN

is_isolation_capable(node):
    return node.type in {breaker, sscb, ats, switchgear, isolation_valve}
           or node.flags.isolation_capable == true
```

Then **validate the scope** before emitting the LOTO step: compute
`impact_set(isolation_point, chain)` (downstream reachable nodes). If that set
excludes the macro-equipment's active IT loads -> valid micro-LOTO. If opening
it would down live racks -> flag, escalate (RBAC), or fall back to macro-LOTO.

Scope-aware output, driven by the target's `asset_level` (containment tree):

- **System / Equipment** target -> holistic **SOP** or **MOP**.
- **Sub-assembly / Component / Sensor** target -> hyper-focused **EMP**:
  localized torque specs, the Arc Flash step from Section 2, localized
  component verification — and the micro-LOTO isolation point above, *not* a
  macro-equipment shutdown.

## 4. Sprint Phasing — 4 atomic bites

| Bite | Output | Validatable by | Tag candidate |
|---|---|---|---|
| **G1 — Taxonomy schema** | `systems:` + `parent`/`asset_level` in site_model.yml (schema + one genset and one CDU fully decomposed as the representative slice); `AssetLevel` enum + `Asset` fields + `EMP` ProcedureClass in cmms_models.py; site_model.py containment API; SQL migration; ADR-010 (dual-graph model); tests. **No generator yet.** | pytest green; containment tree parses | `v0.11.0-asset-taxonomy` |
| **G2 — Generator core + SOP/EMP factories** | `procedure_generator.py` skeleton; SOP Factory (5-step checklist from `telemetry_simulator` baselines); EMP Lifecycle Factory (BESS internal-resistance / UPS rectifier-efficiency thresholds); emits valid YAML; RBAC `DRAFT` / `v1.0-draft` gating; tests. | generated YAML loads in `ProcedureRegistry` | `v0.11.1-gen-sop-emp` |
| **G3 — Topological MOP Compiler + Arc Flash** | recursive isolation traversal (Section 3); `fault_current_ka` / `incident_energy_cal` / `arc_flash_boundary_m` fields; PPE-category mapping + Arc Flash step injection; **the micro-component test** (`tests/test_procedure_generator.py`: secondary-loop filter -> asserts localized isolation valves, not a full CDU shutdown). | micro-LOTO test green | `v0.11.2-micro-loto` |
| **G4 — EOP Factory + RBAC promotion + integration** | Kalman-triggered EOP Factory (anomaly profile -> containment script); RBAC `DRAFT -> ACTIVE` promotion gate (L5/L6 signature -> `v1.0`); full pytest + npm test green. | full suite green | `v0.11.3-gen-eop` |

Each bite is independently validatable; ~4 sessions.

## Risks + countermeasures

- **Arc flash data unavailable** -> generator emits a `DATA_REQUIRED` / `ABORT`
  step, never a voltage-only guess (Section 2).
- **DB-mirror drift** (new `Asset` columns) -> G1 bundles a SQL migration.
- **Containment tree vs flow DAG confusion** -> two explicitly named graphs;
  ADR-010 records the decision.
- **site_model.yml bloat** — fully decomposing every breaker/fuse/sensor is
  hundreds of nodes. Countermeasure: G1 ships the *schema* + a representative
  slice (one genset, one CDU); full-fleet decomposition is data entry, deferred
  and scriptable.
- **Recursion depth / cycles** -> `max_hops` bound + `visited` set (BFS).

## Out of scope

- Computing incident energy from first principles (IEEE 1584) — values are
  carried, not derived.
- Full-fleet micro-component data entry — schema in G1, representative slice
  only.
- Real LOTO hardware actuation.

## Entry conditions (when G1 resumes)

1. HEAD at `8b9aba6` or a descendant; working tree clean.
2. This C0 reread; ADR-010 drafted before G1 code.
3. Explicit GO from Wilmer per bite (approve-then-execute).
