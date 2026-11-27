# ADR-022: 3D Hall view (Building D) in WebGL

- Status: accepted
- Date: 2026-11-26
- Deciders: Wilmer Y. Angel Beltran (operator: GO on the 3D hall track,
  reference video as the quality bar), Claude (implementation)

## Context and problem statement

The operator wants a 3D view of the AI hall at the visual level of an
800 VDC reference video (dark racks, glowing busway, blue / red liquid
cooling, cutaway rack), with every number coming from the design model
or the simulator. The video looks offline-rendered; the target here is
a real-time browser view on a mid-range laptop GPU.

## Decision

1. Renderer: the three.js r166 already vendored for Mission Control.
   Addons (OrbitControls, EffectComposer, RenderPass, UnrealBloomPass,
   OutputPass, CSS2DRenderer, RoomEnvironment) are vendored from
   `three@0.166.0`, the same release (hash checked). Only change: the
   bare `'three'` import becomes a relative path, so no import map and a
   single three.js instance. No CDN.
2. Data: the scene reads only `GET /api/design/building-d` and
   `/racks` (ADR-021). `core/hall3d_model.js` is a pure function from
   that payload to geometry in metres, unit-tested without WebGL. A
   backend contract test fences the fields the view reads.
3. Drawing: every repeated part is an `InstancedMesh` (racks, doors,
   tap-offs, drops, CDUs); one rack is a cutaway. The 800 VDC busways
   carry an emissive flow texture animated in the direction of supply,
   with bloom at half resolution. Pixel ratio capped at 1.5. The render
   loop stops when the view is hidden. The room is one back-faced box,
   so orbiting never puts a wall between the camera and the hall.
4. Honesty: the view says DESIGN, simulated facility. Rack internals
   (tray count), tap-off boxes and pipe sizes are drawn SCHEMATIC.
5. Vendored third-party code is excluded from the pre-commit hooks so it
   stays byte-identical to upstream.

## Consequences

- Lote 3 adds live telemetry, rack selection, callouts with leader lines
  (CSS2DRenderer is already vendored), the scripted fly-through and a
  quality governor (bloom off / lower pixel ratio below 30 fps).
- Frame rate must be measured on the operator's GPU; the headless check
  here runs SwiftShader (software) at about 5 fps, which says nothing
  about a real GPU.
- Not photoreal: no ray tracing, no baked lighting, no real shadows yet.
