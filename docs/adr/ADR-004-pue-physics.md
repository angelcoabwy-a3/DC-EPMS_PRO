# ADR-004: PUE Physics Computation with Phase 1 / Phase 2 Split + First-Law Cross-Check

- Status: ACCEPTED
- Date: 2026-05-10
- Decision-maker: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
- Sprint: 5.5b
- Tag: `v0.9.14-pue-physics`
- MADR template: https://adr.github.io/madr/

## Context

Power Usage Effectiveness (PUE) is the question hyperscale operations panels ask first — Microsoft CO+I, Equinix, Google, Meta all use it as the lead-off metric in audit conversations. Without a live, defensible PUE number on the operator dashboard, the platform cannot answer that opening question with anything more credible than a slide.

Path C2 has a fundamentally heterogeneous electrical architecture across its two phases:

1. **Phase 1 (Buildings A/B, deployed)** — 480 VAC trifásico 2N with traditional Schneider Galaxy VX online double-conversion UPS. Per-rack rectification stages (480 VAC → 48 VDC PSU → 12 VDC GPU rail) cumulatively dissipate ~6 % of input power. Galaxy VX peak efficiency is ~94 % in the 30–70 % load band per Schneider WP122. Cooling load is partly DLC (retrofitted) and partly residual CRAH for hall ambient.

2. **Phase 2 (Building D, target Q2 2026)** — 800 VDC unipolar TN-S downstream of a single MV rectifier, with BESS 2.5 MWh ride-through and full DLC at the 12 VDC GPU rail. No per-rack rectification; the MV rectifier alone handles AC→DC conversion at ~97 % efficiency per OCP Open Rack 800 V DC reference design + Vertiv 2026 hyperscale DC distribution white paper. Cooling fraction drops to ~10 % because full DLC eliminates most CRAH.

A single-PUE rollup that averages or merges these two architectures is misleading: it would understate the gain Phase 2 delivers and obscure where Phase 1 sits relative to its own target. The panel will recognize this immediately as a credibility issue.

A second concern: any computed PUE without an independent cross-check is asserting a number, not measuring it. ASHRAE TC 9.9 Class W17 metering practice plus Uptime Institute Tier IV audit guidance both require a reconcilable input vs. subsystem decomposition with a residual budget.

## Decision

Compute PUE separately for each phase and surface them as two independent snapshots, with a deterministic first-law cross-check residual on each:

- `backend/physics/pue.py` — `compute_pue_for_phase(phase_name, cfg)` returns a `PUESnapshot` with: `pue`, `target_pue`, `warn_threshold`, `crit_threshold`, `state`, breakdown (`it_load_kw`, `cooling_kw`, `electrical_losses_kw`, `lighting_aux_kw`), and `first_law_residual_pct`.
- `config/pue_targets.yml` — per-phase configuration:
  - Phase 1: target 1.30, warn 1.45, crit 1.60. Subsystem fractions tuned to Schneider Galaxy VX + DLC retrofit + residual CRAH.
  - Phase 2: target 1.15, warn 1.25, crit 1.40. Subsystem fractions tuned to MV rectifier + full DLC.
- `GET /api/physics/pue` — both phases as a single response.
- Phase 2 is marked `is_design_target=true` and rendered with a `design Q2 2026` badge in the UI; the state classifier returns `"design"` regardless of the computed value, communicating to the operator that Phase 2 is a forecasted snapshot, not a measured one.
- First-law cross-check: residual = `|input_total - subsystem_total| / input_total`. Audit-grade <= 2 %, acceptable <= 5 %, > 5 % → `instrumentation_drift`.

For the V9 simulation the IT load is derived from the rack inventory in CMMS (`rack_count * rack_kw`); other subsystem loads are computed via fractions from the rack-architecture model. A small bounded sinusoidal perturbation (amplitude 1.5 % PUE, period 90 s) is added at the snapshot layer so the demo widget visibly oscillates without making the underlying compute stochastic — the underlying physics remain deterministic and reproducible.

## Alternatives considered

1. **Single rolled-up PUE across both phases.**
   *Rejected.* Averaging different architectures violates engineering credibility; a panelist who knows the difference between AC and DC distribution will catch this in the first 30 seconds. The split is also the actual operational reality (the two buildings will be metered independently anyway).

2. **Derive PUE entirely from the live telemetry simulator** (Sprint 5 Send-on-Delta + Kalman pipeline) instead of CMMS aggregates.
   *Deferred to V10.* The simulator integration is the right long-term answer, but it adds a layer of pipeline coupling for marginal demo gain. CMMS aggregates produce identical-looking widget output for the panel walkthrough at a fraction of the implementation cost. The yaml + module are designed so the input source is swappable; the math doesn't change.

3. **Stochastic per-tick PUE with a real RNG.**
   *Rejected.* Reproducibility matters for the demo recording and for tests. A deterministic sinusoidal envelope provides the visual liveness panels expect without breaking determinism.

4. **PUE only, no first-law cross-check.**
   *Rejected.* Asserting PUE without reconciling input vs subsystem decomposition is the kind of shortcut a Tier IV auditor flags. The cross-check is cheap (one subtraction + threshold comparison) and turns the widget from "trust me" to "verify me."

5. **Integrate live PUE into the SHI module rollup.**
   *Deferred.* SHI today is min(H_module) × severity_modifier; adding PUE as a fifth pillar requires careful weight calibration. Standalone widget first; SHI integration in V10 if the demo shows demand for it.

## Consequences

- **Positive**: panel-grade answer to "what is your PUE?" — visible in 100 ms on Overview, target-banded, audit-cross-checked, ADR-grounded.
- **Positive**: vocabulary discipline reinforced — the widget header literally says "480 VAC trifásico" vs "800 VDC unipolar TN-S". A panelist who clicks around the dashboard will see the architectural distinction reinforced visually.
- **Positive**: V10 simulator-integration path is a drop-in: replace the `compute_pue_for_phase` input source with a telemetry-pipeline aggregator; the rest of the stack (route, widget, tests, ADR) is unchanged.
- **Trade-off**: Phase 2 today is a design target, not a live measurement. Operators must distinguish forecast from reality. Mitigation: the `design` state badge + dim card styling + explicit "design Q2 2026" chip on the card.
- **Trade-off**: subsystem fractions in yaml are static — they do not yet model partial-load efficiency curves. Acceptable for V9 (a panel demo at design load); V10 should add load-fraction-aware curves for the cooling and UPS terms.
- **Test debt**: 15 unit tests in `tests/test_pue.py` cover compute paths, first-law thresholds, state classification, demo-noise envelope, and config error paths. No live-telemetry integration tests — those land in V10 alongside the simulator integration.

## References

- Uptime Institute, "2024 Global Data Center Survey" — Tier IV PUE distributions
- ASHRAE TC 9.9, "2021 Thermal Guidelines for Data Processing Environments, 5th edition" — Class W17 + metering guidance
- OCP Open Rack 800 V DC Reference Design v1.0
- Vertiv, "Hyperscale 800 VDC Distribution: Efficiency and Resilience" (2026 white paper)
- Schneider WP122, "Critical Power for AI Factories" (2025)
- IEC 62443-3-3 — instrument network segregation
- `config/pue_targets.yml` — concrete phase parameters
- `backend/physics/pue.py` — implementation
- `tests/test_pue.py` — verification
- `frontend/assets/js/core/pue_widget.js` — operator-facing surface
