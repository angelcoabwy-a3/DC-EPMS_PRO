# B1 — 3D Mission Control: Design Brief & Visual Contract

- **Status**: BRIEF (locked 2026-05-10) · GRAY-BOX SPIKE IN PROGRESS · B1 PRODUCTION IMPLEMENTATION DEFERRED
- **Decision-maker**: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
- **Scope**: Pre-implementation design contract for B1 (Tier B mission-control view)
- **Purpose**: De-risk the highest-effort highest-risk frontend item before any production three.js code is written. Captures the three contract decisions made on 2026-05-10.

## Why this brief exists

B1 was originally scoped at 25-30 hours of three.js work. Without an explicit visual + interaction contract codified before code, the failure modes are:

1. **Kitsch drift** — B1 ends up looking like a video game UI (rotating cubes, neon trails, lens flares) and the CO+I panel discounts the entire platform's credibility.
2. **Vacant scene** — B1 ends up as four white boxes with no information, *worse* than the existing 2D dashboard.
3. **Performance trap** — B1 renders all 91 components with shaders and drops to 30 FPS on the demo laptop's RTX 3060 6 GB.
4. **Scope creep** — "while I'm in three.js…" adds particle systems, custom shaders, post-processing, and the 25-hour budget becomes 60.

This brief is the contract that makes those failure modes detectable in code review.

---

## Contract decision 1 — **Aesthetic anchor: Tesla Megapack Grid Operations**

### What this means

| Visual lever | Direction |
|---|---|
| Background | Pure black or very dark navy (#0B0D10 baseline). NO starfields, NO grid pattern overlays. |
| Buildings | Glass-panel meshes — translucent fill (~10-15% alpha cyan) with sharp cyan edges (0.85 alpha). NO solid fill, NO textures. |
| Edges | Crisp cyan stroke, 1.5-2 px equivalent width. Thicker on selected/hovered buildings. |
| Labels | Glassmorphism cards floating above each building: `backdrop-filter: blur(8px)`, 1px subtle border, semi-transparent background. Tabular monospace for all numerics. |
| Power flow | Animated dashed lines from Yard → Building A and Yard → Building B. Cyan particles flowing in the direction of energy delivery. Speed proportional to live MW (faster = more current). |
| Color discipline | Cyan = healthy / active. Amber = warn. Red = crit. Purple = redundancy (2N path). NO neon pinks/greens/lime. NO glow on healthy items. |
| Typography | JetBrains Mono everywhere. Uppercase letterspacing for category labels. Tabular numerics for metrics. |
| Animation | Sub-1Hz pulse on alarms only. NO continuous decoration. NO bouncing, NO pop-in. Smooth 0.3-0.6s easing on transitions. |

### Reference materials (concrete, public)

These are the inspiration anchors. If any element of the spike deviates from these references, it deviates **on purpose** with a documented rationale:

1. **Tesla Megapack Owner Portal** (live ops dashboard for utility-scale BESS installations) — glass-panel cards with floating metrics, fixed isometric camera, cyan-on-dark, click-to-drill flow.
2. **Vestas wind farm operations console** (turbine fleet view) — building-level aggregation with hover-to-inspect, animated power flow between assets.
3. **Equinix Smart Hands console** (data center customer portal) — facility plan view with status badges per cabinet, severity-coded only.

### Failure modes to refuse (panel test)

If during review someone says "let's add…" any of the following, the answer is **no**:

- Particle systems beyond the power flow lines (e.g., sparkles, stardust, embers)
- Lens flare, bloom post-processing, chromatic aberration
- Free-floating "data orbs" with no semantic meaning
- Music or ambient sound effects beyond what `core/sound.js` already does
- Anime-style speed lines or cyber-noir scan lines
- Anything labeled "neon" or "futuristic" in the description

These are kitsch markers. They subtract credibility from a CO+I evaluation.

---

## Contract decision 2 — **Information density: Mid-level (building-as-block + drill-down)**

### Default view (no click)

Four buildings rendered as isometric glass-panel objects with floating KPI cards:

```
[Building A — Phase 1]               [Building B — Phase 1]
 480 VAC trifásico 2N                 480 VAC trifásico 2N
 ┌─────────────────┐                  ┌─────────────────┐
 │ PUE   1.34      │                  │ PUE   1.32      │
 │ IT    16.2 MW   │                  │ IT    16.5 MW   │
 │ Racks 30        │                  │ Racks 20        │
 │ Anom  1         │ ← amber chip     │ Anom  0         │
 │ State HEALTHY   │                  │ State HEALTHY   │
 └─────────────────┘                  └─────────────────┘

[Yard]                                [Building D — design Q2 2026]
 Utility 27.5 kV                      800 VDC unipolar TN-S
 ┌─────────────────┐                  ┌─────────────────┐  ← dim, dashed
 │ Util  27.5 kV   │                  │ PUE   1.15 tgt  │
 │ ATS   2x        │                  │ IT    50 MW tgt │
 │ Gens  4x 2 MW   │                  │ Racks 250 tgt   │
 │ Cool  3 chiller │                  │ Available Q2 26 │
 │ State NOMINAL   │                  └─────────────────┘
 └─────────────────┘
```

Animated cyan power flow lines: Yard → Building A, Yard → Building B. A second dashed line Yard ⇢ Building D (design only, no flow).

### Drill-down (on click)

Click a building → 0.6s zoom-and-fade transition to an existing detail view:

| Click target | Goes to |
|---|---|
| Building A | `#rack-heatmap?path=A` (filtered to 30 racks) |
| Building B | `#rack-heatmap?path=B` (filtered to 20 racks) |
| Yard | `#site_topology?cluster=yard` (force-directed graph centered on yard) |
| Building D | `#tech-assist` (design narrative — Phase 2 800 VDC info card) |

Each detail view has a "← back to mission control" affordance.

### Why mid-level

Re-uses existing rack-heatmap and site-topology views. Does NOT duplicate functionality. Each click action goes somewhere meaningful, not into another layer of the same scene. Tesla Megapack Portal does this exactly — high-level → drill → detail, never recursive 3D.

### Live data sources for the floating KPIs

| Field | Endpoint |
|---|---|
| PUE per phase | `GET /api/physics/pue` (Sprint 5.5b) |
| Rack count per path | `GET /api/cmms/assets?asset_type=it_rack` filtered by `path` |
| IT MW per phase | Computed from rack count × rack_kw (P1: 142 kW, P2: 200 kW) |
| Anomaly count | Open WOs with `trigger_source=predictive_kalman` per building |

---

## Contract decision 3 — **Camera & interactivity: Fixed isometric + click-to-drill**

### Camera spec

- **Projection**: orthographic camera positioned at isometric angle — 30° azimuth from +Z, 30° elevation. No perspective foreshortening. Standard architectural / video-game iso.
- **Position**: locked. NO orbit, NO scroll-zoom, NO pan. The only camera motion is the 0.6s zoom-and-fade transition on drill-down.
- **Why locked**: predictable framing for screenshots, no possibility of a panelist rotating to a weird angle that breaks the visual story, 60 FPS guaranteed on RTX 3060.

### Interaction model

| Input | Effect |
|---|---|
| Mouse hover building | Edge thickens to 2.5 px equivalent, tooltip pops with breadcrumb (e.g. "Building A · A3-Alpha · Path C2") |
| Mouse click building | Smooth 0.6s zoom-and-fade transition to the appropriate drill-down view |
| Mouse click empty space | No-op |
| `Esc` | If on drill-down, returns to mission control. Reuses existing keyboard module. |
| Right-click | No-op (reserve for browser context menu) |

### Animation budget

- **Power flow**: continuous cyan particle drift @ 60 fps. ~12 particles per line × 2 lines = 24 animated objects max.
- **Alarm pulse**: 1 Hz blink on amber/crit chips only. NO continuous animation on healthy state.
- **Transition**: 0.6s eased zoom on drill-down. ONE transition at a time, no chaining.
- **Total simultaneous animations**: < 30 objects. Trivially within 60 FPS budget on RTX 3060.

---

## Component inventory (for B1 production implementation, post-spike)

If B1 ships to production after the gray-box spike, these are the only meshes needed:

| Mesh | Count | Geometry | Material | Notes |
|---|---|---|---|---|
| Building A | 1 | BoxGeometry 60×30×40 (W×D×H) | MeshStandardMaterial cyan tint, 0.12 alpha, 0.85 metalness | + EdgesGeometry overlay 1.5 px cyan |
| Building B | 1 | same | same | mirror of A |
| Building D | 1 | BoxGeometry 100×50×60 (larger, Phase 2) | same but 0.06 alpha + dashed edge shader | dim treatment |
| Yard plate | 1 | PlaneGeometry 200×100 | dark navy, low-alpha grid texture | optional |
| Yard fixtures | 5-6 | small cylinders/boxes | cyan stroke | utility, ATS, gensets, cooling towers, BMS |
| Power flow line A | 1 | TubeGeometry along curve Yard→A | shader with animated UV offset | cyan particles |
| Power flow line B | 1 | same Yard→B | same | cyan particles |
| Power flow line D | 1 | same Yard→D | dashed, dim, no animation | "design" |

Total geometry budget: **~15 meshes**. RTX 3060 6 GB does this without breathing hard.

---

## Performance budget

| Target | Threshold | Action if violated |
|---|---|---|
| FPS @ idle | 60 | Reduce edge geometry resolution |
| FPS @ hover | 60 | Cap glow intensity |
| FPS @ transition | 30+ acceptable mid-transition | Use `requestAnimationFrame` throttling |
| First paint | < 200 ms after three.js bundle parses | Lazy-load three.js bundle |
| Memory | < 80 MB additional (three.js + scene meshes) | Dispose textures on unmount |

Three.js minified module build typically lands at 600-700 KB. We're already vendoring chart.js (~250 KB). Adding three.js takes the static budget to ~1 MB. Acceptable for a single-laptop demo; would matter more if we were shipping to mobile.

---

## Phase 2 — Gray-box three.js spike (the de-risk artifact)

The spike (`view-mission-control` + `views/mission_control.js`) is a **bare-geometry three.js scene** with primitive boxes only. NO textures, NO custom shaders, NO post-processing. Its job is exactly four things:

### What the spike must prove

1. **Three.js bundle loads + the canvas mounts** in this hybrid (no-bundler, ES-module) repo. We vendor `three.module.min.js` to `frontend/assets/vendor/` matching the chart.js convention. ESM `import` from the local path works in the browser without a build step.
2. **60 FPS holds** on RTX 3060 6 GB with the four building primitives + animated camera + power-flow line. Prove it with an on-canvas FPS HUD.
3. **The state.js bus integrates cleanly** with the three.js render loop. Subscribe to `latestTelemetry` / PUE channels and update label sprites or HTML overlays in the requestAnimationFrame tick. NO blocking + NO double-update + state changes propagate within 1 frame.
4. **Click-to-drill via Raycaster** dispatches the existing nav system (`#rack-heatmap`, `#site_topology`, etc.). Reuses the LOTO-pattern click delegation already in place.

### Spike scope (gray-box only)

| In scope | Out of scope (deferred to production B1) |
|---|---|
| 4 BoxGeometry buildings (A, B, D, Yard plate) — flat cyan wireframe | Glass-panel translucent material, EdgesGeometry overlays |
| OrthographicCamera at fixed iso angle (30° / 30°) | Smooth zoom-and-fade transitions |
| Hardcoded grayish positions; no live data binding yet | Live PUE / rack count / anomaly chips |
| Single Line for each power flow (no animation) | Animated tube particles, shader UV offset |
| Raycaster click → console.log(building.id) | Drill-down navigation to existing views |
| HTML overlay FPS counter | Floating glassmorphism KPI cards |
| state.js subscribe stub that logs telemetry receipts | Real label sprite updates per tick |

### Spike acceptance criteria

The spike ships when ALL FOUR are true on the demo laptop:

- [ ] `npm`-free local import: `import * as THREE from '/assets/vendor/three.module.min.js'` resolves with no console errors
- [ ] FPS HUD shows ≥ 58 FPS sustained at idle on RTX 3060
- [ ] The state.js subscribe callback fires when telemetry arrives, no exception, no leak
- [ ] Clicking on each of the 4 building meshes prints the correct asset id to the console

### What we DON'T need to prove in the spike

- That it looks pretty (it won't — gray boxes only)
- That the click goes anywhere useful (just a console log is enough)
- That label cards exist (deferred)
- That power flow particles animate (deferred — just a static line)

If the four acceptance criteria pass, B1 production work is technically de-risked and we have explicit permission to invest the remaining 20-25 hours on visual polish + glass-panel materials + live-data integration without fearing a foundational blocker.

If any of the four criteria fail, B1 is rejected for V9 scope and we stop.

---

## Out of scope (explicitly deferred)

- WebXR / VR / AR support
- Free-camera orbit (rejected per contract decision 3)
- Per-rack 3D voxels (rejected per contract decision 2 — drill into existing rack-heatmap)
- Music / ambient SFX
- Multi-facility view (this is single-site A3-Alpha only)
- Real-time animation of every component state (only buildings + power flow)

---

## References

- [Tesla Megapack Owner Portal screenshots](https://www.tesla.com/megapack)
- [Vestas wind farm SCADA case study](https://www.vestas.com/en/products/wind-farm-services)
- [Equinix Smart Hands console docs](https://www.equinix.com/services/equinix-customer-portal/)
- [NASA JPL Deep Space Network operations](https://eyes.nasa.gov/dsn/dsn.html) — for the discipline contrast
- ADR-006 Deterministic Sandbox (this repo) — visual layer is advisory only
- `frontend/assets/js/views/site_topology.js` (this repo, Tier A) — the existing graph is the closest precedent
- `frontend/assets/js/views/rack_heatmap.js` (this repo, Tier B) — drill-down target

---

**Locked: 2026-05-10. Any deviation from this brief during B1 implementation requires either (a) updating the brief first, or (b) explicit acceptance noted in the implementation PR.**
