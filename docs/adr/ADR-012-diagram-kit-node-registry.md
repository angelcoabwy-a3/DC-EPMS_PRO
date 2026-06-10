# ADR-012: Shared Diagram Kit + Canonical Node Registry for all HMI engineering diagrams

- Status: ACCEPTED
- Date: 2026-06-10
- Decision-maker: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
- Sprint: Diagram Rebuild (Batches 0-5, post-Epic 10)
- Supersedes: nothing (extends the T2.1 "programmatic SLD" direction to ALL diagram views)
- MADR template: https://adr.github.io/madr/

## Context

The HMI carried five engineering-diagram views built in five different eras:

- **Power & UPS**: programmatic orthogonal SLD (T2.1 reinvention).
- **Cooling (DLC)**: programmatic orthogonal P&ID, private copies of the
  Power view's symbol/sparkline/modal code.
- **Topology (HLD/LLD)**: an 18 KB hand-authored static SVG in `index.html`
  (the pre-T2.1 pattern), polled every 8 s by `setInterval`.
- **Site Topology**: force-directed Verlet graph, fetch-once, never updated,
  no severity.
- **Mission Control**: three.js isometric scene.

A 2026-06-10 structural review found the consequences of that divergence:

1. **Four visual languages** for one facility — symbol shapes, severity
   palettes (`#FB8C00` vs `#ffb020`, `#E53935` vs `#ff4d4d`) and legends all
   differed per view.
2. **Three identity vocabularies** for the same physical asset
   (`util_a` / `utility_north` / `utility_feed_a`), each view keeping a
   private mapping table — cross-view linking was structurally impossible.
3. **Three What-If semantics**: a local DAG cascade (Power), a backend
   physics call (Topology), and a cosmetic colour toggle that simulated
   nothing (Cooling).
4. **Triplicated code**: `_sparkPoints` / `_updateSparklines` /
   `_siteMeanZ` existed three times; the RBAC actuation modal twice.
5. **Vocabulary fence violations in pixels**: the static HLD header read
   "27kV -> 480V -> **480VDC**" (Phase 1 has no 480 VDC bus), and the
   Phase 2 800 VDC unipolar TN-S architecture — the project's flagship
   differentiator — was drawn nowhere.
6. **Channel-ownership fragility**: Kalman channels were matched to nodes
   by substring (`channel.includes(nodeId)`), so `ups_a` would swallow a
   hypothetical `ups_a1_*` channel.

## Decision

Introduce two shared `core/` modules that every diagram view MUST consume,
and regenerate the diagram views on top of them:

1. **`core/diagram_kit.js` — one visual language.** Shared symbol library
   (IEEE/ISA-ish, including the Phase 2 set: MV Rectifier with AC/DC
   converter mark, SSCB, 800 VDC bus bar, BESS), orthogonal wire builder
   whose `orthoPath()` **throws on any diagonal segment** (the
   no-spaghetti guarantee is structural, not a review convention), one
   severity model (`severityFromChannels`), one sparkline tracker, one
   legend (`DEFAULT_LEGEND` teaches the AC/DC vocabulary), and one RBAC
   actuation-modal factory. Severity colors are CSS custom properties
   (`--dk-sev-*`) consumed by every view.

2. **`core/node_registry.js` — one identity.** One entry per physical
   asset mapping canonical id <-> `/api/topology/state` key <->
   `/api/site/graph` id(s) <-> explicit Kalman channel prefixes, grounded
   against the live backend. `matchesChannel()` enforces prefix
   discipline (exact id or `prefix_`-anchored). Phase 2 Building D chain
   registered with S-VOCAB-01-fenced labels. The registry is what makes
   cross-view navigation possible ("Open in Power SLD" from the site
   graph).

3. **One What-If semantic for local sandboxes.** `core/cooling_grid.js`
   (availability DAG, the hydraulic sibling of `power_grid.js`) replaces
   the cosmetic cooling toggle. Local DAGs answer "who loses
   power/cooling, instantly, in frontend memory"; the **backend physics
   What-If** (`/api/topology/whatif`, SHI delta) remains the Topology
   view's Emergency Simulation. Both are honest about their scope.

4. **One data-plane pattern.** Fetch `/api/topology/state` once per
   activation; live severity arrives on the Hermes telemetry stream
   resolved through registry channel prefixes. The 8 s `setInterval`
   poll is eradicated.

## Consequences

### Positive

- An operator learns the visual language once; severity reads identically
  on the SLD, the P&ID, the HLD and the site graph.
- Diagonal connectors and identity drift are now **unrepresentable**, not
  merely discouraged (kit throws; registry is the single map; vitest
  asserts the vocabulary fence at markup level).
- Phase 2 is finally drawn: the Power SLD carries the full 35 kV AC ->
  MV Rectifier -> [fence] -> 800 VDC unipolar TN-S -> SSCB/BESS/RPP
  branch, dashed and non-operable (DESIGN, honest scope).
- Frontend test floor rose 368 -> 449 across the rebuild (kit, registry,
  both DAG engines — power_grid had zero tests — engineering sections,
  cross-links).

### Negative / accepted trade-offs

- The kit is a new single point of change: a bad symbol edit propagates to
  every diagram. Mitigated by the kit's own test file and the per-view
  markup assertions.
- Mission Control (three.js) consumes only the severity tokens, not the
  SVG kit — 3D stays out of scope for the kit by design.
- Phase 2 nodes carry no live telemetry (none exists); their panel
  sections are spec sheets with an explicit DESIGN badge.

## Compliance

- New or modified diagram views MUST build symbols/wires via
  `diagram_kit` and resolve identity/channels via `node_registry`
  (see skill `S-DIAGRAM-01`).
- Schema-level vocabulary remains enforced by
  `backend/telemetry_proto/v1/telemetry.proto` (Epic 8); this ADR extends
  the same fence to rendered pixels.
