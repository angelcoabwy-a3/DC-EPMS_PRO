# three.js r166 addons (vendored)

Copied from the npm package `three@0.166.0` (`examples/jsm/`), the same
release as `../three.module.min.js` (SHA-256 prefix 40e5358d17078439).
MIT licence, see LICENSE.

Only change: the bare `from 'three'` import is rewritten to the relative
`from '../../three.module.min.js'`, so the browser needs no import map
and every addon shares the single vendored three.js instance.

Used by the 3D Hall view (ADR-021 track): OrbitControls, EffectComposer,
RenderPass, UnrealBloomPass, OutputPass, RoomEnvironment.
