# DC-EPMS PRO v6 — Multimodal ML & Predictive HMI

## Architectural Whitepaper · 6-Week MVP Roadmap

**Author**: Wilmer Angel — CTO, A-Cubed Semiconductor Systems Inc.
**Document classification**: Internal · Stakeholder distribution
**Document version**: 6.0-MVP-roadmap (April 2026)
**Companion document**: `TRANSFORMER_ANALYSIS.md` (April 2026, v5.0)
**Target deployment**: A3-Alpha Toronto Area · 40 MW · 118 × NVIDIA GB200 NVL72

---

## 0. Position statement and continuity with prior architecture

This document extends the architecture described in `TRANSFORMER_ANALYSIS.md`
without contradicting it. Restated for stakeholder clarity:

> The first-principles ODE engine (`scipy.solve_ivp`, deployed in v3.0) remains
> the authoritative source of truth for **forward-trajectory forecasting** of
> failure scenarios on the safety-critical path. It is auditable per NFPA 70B,
> ISO 22301, and IEC 62443. It is sample-efficient and extrapolates correctly
> outside the training distribution. It is not being replaced.
>
> What v6 introduces is a **separate inference layer** dedicated to a
> different problem: **multivariate anomaly detection on observed telemetry
> residuals and on slow-developing component degradation** that lumped-parameter
> physics is structurally incapable of detecting.

The two layers cooperate:

| Decision class | Engine | Latency budget | Auditability |
|---|---|---|---|
| "Will this failure cascade in the next 15 min?" | **ODE** (existing) | < 100 ms | Equation-level |
| "Is the joint state of 200+ sensors anomalous _now_?" | **Transformer/STGNN** (new) | < 500 ms | Attention-attribution |
| "Which component is silently degrading?" | **STGNN + survival head** (new) | minutes-class | RUL with confidence band |
| "What EOP applies to this anomaly?" | **Tier-aware RAG** (existing) | < 1 s | Source-doc citation |

The thesis of this roadmap is that **multivariate attention is the right tool
for the second and third rows** — not the first.

---

## 1. Problem framing: what is being detected

The ODE engine cannot, by construction, detect:

1. **Sensor drift** — when a transducer slowly biases its reading, the ODE
   accepts the biased value as ground truth and produces a coherent (but
   wrong) prediction.
2. **Mechanical degradation below alarm thresholds** — bearing wear, valve
   actuator stiction, capacitor ESR drift, contactor pitting. These produce
   no instantaneous physics-rule violation; they manifest as
   **distributional shifts** in jointly-observed signals.
3. **Cross-system anomalies** — when a UPS harmonics signature predicts a
   downstream pump cavitation event 4 hours in advance because the
   upstream VFD is feeding distorted current. The causal link is not in
   any single equation; it is in the joint statistics.
4. **Asynchronous control-loop misbehavior** — when an ATS settles in
   18 ms instead of 12 ms (still within spec), it does not trigger an
   alarm. But its monotonic drift over 90 days predicts contactor
   replacement.

These four classes of failure are responsible for the majority of unscheduled
hyperscale facility events that survive a Tier IV redundancy envelope. The
literature is consistent: the failure modes that take down 2N sites are
correlated cross-system anomalies, not single-component breakdowns.

This is the inference problem v6 addresses.

---

## 2. Telemetry scope and asynchrony

### 2.1 The full sensor universe at A3-Alpha

| Domain | Subsystem | Channels | Native rate | Protocol |
|---|---|---|---|---|
| Power upstream | Utility metering A/B | 12 (kV, kA, MW, MVAR, PF, THD per phase) | 1 Hz | DNP3 |
| Power upstream | Transformer A/B | 14 (winding T×3, top-oil T, load kVA, tap pos, OLTC counter) | 0.1 Hz | Modbus TCP |
| Power upstream | ATS A/B | 8 (position, transition time, sync angle Δ, retransfer count) | event + 1 Hz | Modbus RTU |
| Power upstream | Genset A/B | 22 (fuel pressure, oil pressure, vibration ×3 axes, exhaust EGT, hours run, starts) | 1 Hz idle, 10 Hz running | CANopen J1939 |
| Power middle | UPS Galaxy VX A/B | 28 (AC-in/out V/I/PF/THD, DC bus V, battery V/I/SOC, eff., cabinet T) | 1 Hz | Modbus TCP |
| Power middle | Battery VRLA bank A/B | 96 (32 cells × 3: V, T, internal R) | 0.1 Hz | proprietary RS-485 |
| Power downstream | RPP A1/A2/B1/B2 | 168 (42 poles × 4 RPPs: I, V_phase, kWh) | 0.5 Hz | Modbus TCP |
| Power downstream | Starline busway A/B | 24 (12 tap-offs × 2: I, V, kWh, T) | 1 Hz | BACnet/IP |
| Power downstream | Rack PDU | 472 (118 racks × 4 outlets: I, V, kWh) | 0.5 Hz | SNMPv3 |
| Cooling primary | Chiller York YZ ×2 | 30 (COP, ECWT, LCWT, EWT, LWT, compressor power, VFD freq, evaporator approach, condenser approach, refrig. P×2) | 0.2 Hz | BACnet/IP |
| Cooling primary | CW pumps ×3 | 18 (suction P, discharge P, motor I, vibration ×3, bearing T) | 1 Hz | Modbus TCP |
| Cooling primary | CHW pumps ×3 | 18 (same set) | 1 Hz | Modbus TCP |
| Cooling primary | Cooling tower fans ×4 | 12 (VFD freq, motor I, vibration) | 1 Hz | BACnet/IP |
| Cooling secondary | CDU A/B | 32 (primary in/out T, secondary in/out T, primary flow, secondary flow, valve position, valve command, propylene glycol concentration, leak detection ×4) | 1 Hz | BACnet/IP |
| Cooling secondary | DLC manifold per row × 6 | 72 (supply T, return T, flow ×4 per row) | 1 Hz | Modbus TCP |
| IT thermal | Rack inlet T | 472 (4 sensors × 118 racks) | 0.5 Hz | IPMI/Redfish |
| IT thermal | GPU Tj | 8496 (72 GPUs × 118 racks) | 0.1 Hz | NVIDIA SMBus |
| Environmental | Ambient T_db, RH, pressure | 6 | 0.1 Hz | BACnet/IP |
| Fire | VESDA aspirating | 8 zones × 4 channels | event + 1 Hz | BACnet/IP |

**Total: ≈ 10,000 raw channels. Effective unique signals after vendor**
**duplications and aggregation: ≈ 2,500 features per timestep.**

### 2.2 The asynchrony problem

The native sampling rates span **four orders of magnitude**:
- ATS transition events: ~10 ms
- High-rate vibration: 100 Hz (when running)
- UPS, RPP, busway: 0.5–1 Hz
- Chiller, battery: 0.1 Hz
- GPU Tj polling: 0.1 Hz (NVIDIA telemetry agent)

A naive resampling-to-1 Hz approach produces three pathologies:
1. **Aliasing** in fast signals (vibration spectra collapse)
2. **Stale-value imputation bias** in slow signals (GPU Tj copied 10× appears as a hold pattern)
3. **Causal leakage** if forward-fill is used carelessly across the rate boundary

The MVP adopts a **multi-rate ingestion architecture** with three time-grain
buffers:

- **Fast grain** (10 ms ↔ 100 Hz): vibration, ATS transition, GPU Tj
  *spike events*. Stored as event streams with millisecond timestamps.
- **Medium grain** (1 Hz): the operational tier. Most telemetry, including
  resampled fast features (RMS / kurtosis / spectral peaks over 1-sec
  windows).
- **Slow grain** (60 s): chiller envelope, battery cells, GPU Tj averages.

Models consume **all three grains via separate input heads**, fused at
the embedding layer (Section 3.3). This is the Time-Series Mixer
pattern (Yi et al. 2023) adapted for OT with explicit causal masking.

### 2.3 Data quality contract

Before any data reaches the ML pipeline, an **OT data quality firewall**
enforces:

| Check | Action on failure |
|---|---|
| Timestamp monotonicity per sensor | Quarantine + ops alert |
| Value within physical bounds (vendor datasheet) | Quarantine + ops alert |
| Per-sensor missingness rate < 1 % over 24 h window | Quarantine + ops alert |
| Cross-sensor consistency (e.g., ΣP_RPP ≈ P_UPS within 2 %) | Flag for ML, do not quarantine |
| Sensor heartbeat (timestamp delta < 3× nominal) | Replace with NaN (let model handle) |

Critically, **cross-sensor consistency violations are not quarantined** —
they are exactly what the model learns to detect. Quarantining would
remove the training signal.

### 2.4 Synthetic degradation injection (controlled experiments)

We cannot wait for real failures to accumulate a labelled training set.
The MVP injects **eight degradation patterns** into the recorded normal-
operation telemetry, producing a labelled dataset:

| Degradation pattern | Target subsystem | Injection method |
|---|---|---|
| Valve actuator stiction | CDU primary control valve | Multiplicative lag on `valve_position - valve_command` (rate-limited response, bias 80 %) |
| Sensor drift | RPP voltage transducer | Linear bias drift, +0.5 V/week |
| Bearing wear | CW pump motor | Vibration spectrum: progressive 1×, 2×, 4× shaft-rate amplitude growth |
| Capacitor ESR drift | UPS DC bus | Ripple voltage variance grows 12 % per simulated month |
| Contactor pitting | ATS | Transition time degrades from 12 ms → 18 ms over 90 days |
| Refrigerant undercharge | Chiller | Approach temperature drift +0.05 K/day, COP -0.04/day |
| Battery cell weakening | UPS battery bank | One cell internal-R rises 8 %/week; SOC trajectory deviates |
| Power harmonic distortion | Upstream VFD | THD increases from 4 % to 9 %; downstream pump cavitation lag-coupled |

Each pattern is parametrised with severity ∈ {0.0 (off), 0.25, 0.5, 0.75,
1.0 (failure)} and duration. We generate 2,000 labelled episodes per
class plus 10,000 normal episodes. Severity 0.25 represents the regime
where the BMS does **not** alarm but the ML model should detect — that is
the value proposition.

---

## 3. Model architecture

### 3.1 Why STGNN + PatchTST and not pure Transformer

Pure Transformers treat the input as a flat token sequence. For our
telemetry that destroys two priors that we know are valid:

1. **The physical topology is a graph**. A vibration anomaly on CW pump 1
   physically affects chiller 1 and the cooling tower above it; it does
   not directly affect RPP-B2 across the facility. The graph structure
   (single-line diagram + cooling P&ID) is **fixed and known** at design time.
2. **The temporal axis has fundamentally different scales** per node
   (Section 2.2).

A **Spatial-Temporal Graph Neural Network** encodes the topology as a
graph adjacency, and a **PatchTST** encoder handles the per-node
multi-scale temporal patterns. This pairing has been validated in grid
operations (Liu et al. 2023, IEEE TPS) and is what we adapt.

### 3.2 Architecture summary

```
Raw telemetry (asynchronous, multi-rate)
    │
    ├── Fast-grain encoder    (vibration, transients) — 1D CNN + spectrogram
    ├── Medium-grain encoder  (1 Hz operational)      — PatchTST per node
    └── Slow-grain encoder    (60 s envelope)         — PatchTST per node
    │
    └─→ Per-node temporal embedding e_v ∈ R^d   (d=128)
        │
        ▼
   ┌─────────────────────────────────────────────┐
   │  STGNN graph encoder                         │
   │  - Node set V = {200+ physical components}   │
   │  - Edge set E = topology (SLD + P&ID)        │
   │  - L=4 graph attention layers (GATv2)        │
   │  - Output: node-context-aware embeddings     │
   └─────────────────────────────────────────────┘
        │
        ├─→ Anomaly score head     (per-node σ(W·h_v))     — binary
        ├─→ Attribution head       (cross-attention map)   — explainability
        └─→ RUL head               (Weibull AFT survival)  — remaining useful life
```

### 3.3 The mathematics of cross-system correlation

The user's prompt asks specifically how the model correlates a UPS
harmonic anomaly with a downstream CDU pressure drop. This is the core of
the architecture.

In the STGNN graph attention layer, for each node $v$ at time $t$:

$$
\mathbf{h}_v^{(\ell+1)} = \sigma\!\left( \sum_{u \in \mathcal{N}(v)} \alpha_{uv}^{(\ell)} \mathbf{W}^{(\ell)} \mathbf{h}_u^{(\ell)} \right)
$$

where $\alpha_{uv}$ is the learned attention weight from neighbour $u$ to $v$:

$$
\alpha_{uv} = \frac{\exp\!\left(\text{LeakyReLU}\!\left(\mathbf{a}^\top [\mathbf{W}\mathbf{h}_u \,\|\, \mathbf{W}\mathbf{h}_v]\right)\right)}{\sum_{u' \in \mathcal{N}(v)} \exp(\cdot)}
$$

For the UPS-A → CDU-A correlation: the graph adjacency includes the edge
`UPS_A → RPP_A1 → busway_A → tap_off → CDU_A_pump_VFD`. During the
forward pass, the harmonic-distortion signature at the UPS node
($\mathbf{h}_{UPS_A}$ has elevated THD components in the medium-grain
embedding) propagates through the graph attention. The model has learned
during training that this UPS embedding pattern, *combined with* a small
suction-pressure deviation at the CDU pump 30–60 minutes later, is an
anomaly distinct from either signal alone.

Critically, this is **not** the model "predicting" the future — that is
the ODE's job. The model is detecting that **the joint observed state**
is in a region of the joint distribution that historically preceded
failure events. That is exactly what attention-based anomaly detection
is mathematically suited for.

### 3.4 Attention-attribution as explainability

Every anomaly score from the model comes with the attention map that
produced it. For the UPS→CDU correlation example, the attribution head
produces:

```
ANOMALY  cdu_a_pump_suction   score=0.83  RUL_estimate=14d ±3d
  ↑ attribution:
    ups_a (THD harmonic_3rd):     0.41
    busway_a (current_imbalance): 0.22
    cdu_a_valve (response_lag):   0.18
    rpp_a1 (voltage_drift):       0.07
    others:                       0.12
```

This attribution is **not a post-hoc explanation** (like SHAP or LIME).
It is the **actual attention weights** that produced the score. This
distinction matters for IEC 62443 and ISO 22301 audit: the explanation
is the computation, not a separate model trying to rationalise the
computation.

---

## 4. Training and validation protocol

### 4.1 Temporal cross-validation

Standard k-fold CV is **invalid** for time-series data: it leaks future
information into training. We use **expanding-window forward-chaining
cross-validation** with embargo periods to prevent autocorrelation
leakage:

```
Fold 1: train [day  1– 30] → embargo [day 31–32] → test [day 33–37]
Fold 2: train [day  1– 60] → embargo [day 61–62] → test [day 63–67]
Fold 3: train [day  1– 90] → embargo [day 91–92] → test [day 93–97]
Fold 4: train [day  1–120] → embargo [day121–122] → test [day123–127]
Fold 5: train [day  1–150] → embargo [day151–152] → test [day153–157]
```

The 2-day embargo accommodates the longest autocorrelation timescale we
observed in the synthetic-degradation pilot (chiller approach drift
half-life ≈ 18 h, so 48 h is generous).

### 4.2 KPIs and acceptance thresholds

| Metric | Target | Justification |
|---|---|---|
| ROC-AUC (per-class anomaly) | ≥ 0.94 | Below this, the model adds no operational value over rule-based BMS thresholds |
| PR-AUC at severity = 0.25 | ≥ 0.80 | This is the hard regime — sub-alarm degradation. The whole value prop is here. |
| FPR at recall = 0.95 | ≤ 0.005 | At 1 inference per minute, FPR > 0.5 % means >7 false alarms per day → operator alarm fatigue → model gets ignored |
| Precision at recall = 0.95 | ≥ 0.85 | Implied by FPR target, restated for stakeholder clarity |
| Lead time vs BMS alarm | ≥ 4 hours median | Below 4h there is insufficient time to schedule maintenance; the model is then just a faster alarm, not a planning tool |
| RUL MAE (Weibull head) | ≤ 20 % of true TTF | Within the confidence band that operations can act on |
| Inference latency (P99) | ≤ 500 ms on edge GPU | Below the operational refresh cadence of the SLD UI (5 s) |

The False Positive Rate target is the most operationally important. In
a Tier IV facility, a model that produces > 0.5 % FPR will be disabled
within 30 days regardless of its detection performance, because alarm
fatigue is a documented cause of missed real alarms (the Three Mile Island
lesson, restated for the AI era).

### 4.3 Lead-time evaluation

For each labelled failure episode in the held-out fold, we measure:

```
lead_time(episode) = t_BMS_alarm  -  t_model_first_score_above_threshold
```

We accept the model only if **median lead time ≥ 4 hours** across all
eight degradation classes. Below that threshold, the model is not adding
forecasting value over the existing rule-based thresholds.

### 4.4 Adversarial and stress evaluation

Beyond the held-out test set, we evaluate the model on three scenarios
not in any fold:

1. **Sensor-failure injection**: randomly NaN 5 % of channels at
   inference time. Model must degrade gracefully, not produce
   high-confidence false alarms.
2. **Distribution-shift injection**: uniformly bias all temperature
   sensors by +1 K (simulating a calibration error after maintenance).
   Model must flag the systemic shift, not interpret it as 472 separate
   anomalies.
3. **Adversarial concurrent-anomaly injection**: inject two real
   degradation patterns simultaneously and verify the attribution head
   correctly disambiguates them. This is the hyperscale operating
   reality — failures rarely arrive alone.

---

## 5. Edge deployment architecture

### 5.1 Model export and runtime

PyTorch model → ONNX export → TensorRT optimisation → FastAPI inference
endpoint deployed alongside the existing physics engine.

```
Training (cloud, periodic):  PyTorch 2.x · 4× A100 · weekly retrain
Optimisation (one-shot):     ONNX Runtime → TensorRT FP16 plan
Edge inference (continuous): RTX A4000 (single-slot edge GPU,
                              co-located with existing FastAPI)
```

The choice of TensorRT FP16 (not INT8) is deliberate. FP16 retains
enough numerical precision for the attention attribution head to be
trustworthy; INT8 quantisation degrades attribution interpretability in
ways that break the IEC 62443 explainability story we are committing to.
The latency cost (FP16 ~ 320 ms vs INT8 ~ 180 ms on A4000) is acceptable
because the operational cadence is 5 s.

### 5.2 Inference cadence and triggering

The model runs in two modes simultaneously:

- **Continuous**: every 60 s on the medium-grain feature window. Output
  is a per-node anomaly score that updates the SLD/P&ID overlays.
- **Event-triggered**: any ATS transition, UPS mode change, BMS alarm,
  or physics-engine SHI drop > 0.05 triggers an immediate inference
  using the current 5-minute trailing window.

The continuous loop is the predictive RUL channel. The event-triggered
loop is the rapid-investigation channel ("show me what is anomalous
*right now* given this just-fired alarm").

### 5.3 Failure modes of the model itself

The model is not on the safety-critical path. Its outputs are advisory.
Specifically:

- If model latency > 5 s (P99 violation), the UI displays the prior
  inference with a "stale" indicator. The site continues to operate on
  ODE + BMS rules.
- If model availability drops, the SLD/P&ID display reverts to the v5.2
  presentation (severity-only colour). No operational decision is
  blocked.
- If the model produces a high-confidence anomaly that operators
  investigate and find to be a false positive, the incident is logged
  to a feedback table; the next retraining cycle uses these as
  hard-negative examples.

This degraded-mode guarantee is what allows the model to be deployed at
all on a Tier IV site.

---

## 6. Predictive HMI integration

The visualisation layer extends the existing v5.2 SLD and P&ID without
disturbing the validated physics-only views. Three new visual elements:

### 6.1 Anomaly auras

Each node in the SLD/P&ID can carry an **anomaly aura** — a soft,
pulsing radial gradient surrounding the symbol whose:
- **Radius** is proportional to the anomaly score (0 = no aura, 1 = full)
- **Hue** indicates the dominant attribution (electrical / mechanical /
  thermal / vibration), matching the existing severity colour palette
- **Pulse rate** is proportional to the urgency derived from RUL (long
  RUL = slow pulse, short RUL = fast pulse)

The aura is **strictly additive** to the existing severity colouring.
It does not change any existing colour or animation. An operator who
ignores the aura still sees exactly the v5.2 dashboard.

### 6.2 RUL degradation curves

A docked panel (collapsible, default-collapsed) lists components ranked
by lowest predicted RUL. For each entry:

```
Component:       CDU-A primary valve actuator
RUL estimate:    14 days (90 % CI: 8–22 days)
Score:           0.83 (anomalous since 6 days ago)
Top attributions:
    valve response lag       0.42
    associated UPS THD       0.31
Recommended EOP: T4-EOP-MECH-014 (CDU valve actuator inspection)
```

The "Recommended EOP" line is generated by the existing tier-aware RAG
pipeline (no new ML there — that retrieval is already deterministic and
auditable).

### 6.3 Predictive heatmap overlay

A toggleable heatmap layer on top of the rack rows (HLD topology view)
shows the 72-hour-ahead anomaly probability per rack. This is the only
explicit forecast in the system, and it is bounded:
- Forecast horizon: 72 hours, matching the longest synthetic
  degradation half-life that the model was trained on. We do not
  extrapolate beyond it.
- Confidence: every cell carries an opacity proportional to model
  confidence. Low-confidence cells appear nearly transparent — the
  operator is not given false certainty.

### 6.4 What the predictive HMI does NOT do

- It does not auto-generate work orders. Anomaly → operator review →
  optional dispatch. The model is decision support, not the decider.
- It does not modify the existing physics-based What-If simulation.
  That tool remains ODE-driven.
- It does not silently adjust setpoints. All BMS writes still go through
  the human-in-the-loop gate with NIST SP 800-82 audit logging.

---

## 7. Six-week roadmap

The schedule below assumes:
- A3-Alpha is **commissioned and producing real telemetry by week 1**.
  If it is not, weeks 1–2 stretch by however long telemetry availability
  is delayed. This is the dominant schedule risk.
- The team has **two senior ML engineers** plus the existing platform
  team. Scaling down headcount stretches the timeline proportionally.
- **GPU resources** for training are available (≥ 4× A100 or
  equivalent). Without these, weeks 3–4 cannot complete on schedule.

Honest disclosure: this is an ambitious 6-week MVP. A realistic
production-grade deployment with full validation suite typically
requires 12–16 weeks. The MVP here is intended to **demonstrate
viability and capture value early**, not to be the final form.

### Week 1 — Data ingestion plumbing

- Define and version the 2,500-feature schema in a dedicated
  `feature_registry.yml` versioned alongside `bms_tags.yml`
- Implement multi-rate ingestion (fast/medium/slow buffers) into
  TimescaleDB hypertables with 7-day retention for raw, 90-day for
  decimated
- Implement OT data quality firewall (Section 2.3) as a separate
  service; quarantine logs to PostgreSQL audit table
- **Deliverable**: 7 days of clean, versioned, timestamped multi-rate
  telemetry at A3-Alpha. KPI: 99.5 % uptime of ingestion path.

### Week 2 — Synthetic degradation generator

- Implement the eight degradation injection patterns (Section 2.4)
- Generate 80,000-episode labelled training corpus from the week 1
  baseline of normal operation
- Set up the temporal CV splits (Section 4.1) and embargo logic
- **Deliverable**: reproducible synthetic dataset, hashed and logged.
  KPI: regenerable from a single seed, byte-identical across runs.

### Week 3 — Model implementation

- Implement multi-grain encoder (1D-CNN for fast, PatchTST for
  medium/slow)
- Implement STGNN with the A3-Alpha topology graph extracted from the
  v5.2 P&ID and SLD JSON
- Wire the three output heads (anomaly, attribution, Weibull AFT RUL)
- **Deliverable**: model trains end-to-end on a small subset, basic
  PR-AUC > 0.7 on the 0.25-severity class. This is a *gating* check; if
  we miss it, the architecture is wrong and we replan rather than
  pushing through.

### Week 4 — Full training and hyperparameter search

- Complete training across all 5 temporal folds
- Hyperparameter search (graph attention heads, PatchTST patch length,
  dropout) using Bayesian optimisation
- Adversarial evaluation suite (Section 4.4)
- **Deliverable**: model meeting all KPIs in Section 4.2. If it does
  not, the architecture is iterated for week 4.5 and the schedule
  slips. This is acknowledged risk.

### Week 5 — Validation

- Full empirical evaluation: ROC-AUC, PR-AUC, FPR-at-recall, lead time
  per class, RUL MAE
- Generate the validation whitepaper for stakeholder review
- Penetration test the inference endpoint against IEC 62443 SL-2
  threats
- **Deliverable**: signed-off validation report. KPI: at least seven of
  the eight degradation classes meet the lead-time target. We do
  **not** ship if fewer than seven; we iterate.

### Week 6 — Edge deployment

- Export to ONNX, optimise with TensorRT FP16
- Deploy alongside FastAPI on the edge GPU node
- Wire the inference output into the v5.2 dashboard with anomaly
  auras, RUL panel, predictive heatmap
- Commission the feedback-table loop for false-positive curation
- Soft launch with operators in shadow mode (visible but no alerts
  generated for 7 days)
- **Deliverable**: production-shadow inference at A3-Alpha. KPI: P99
  latency < 500 ms, zero impact on existing dashboard latency.

### Post-week-6 — Hardening (out of MVP scope, planning visibility only)

- Weeks 7–8: graduated trust — model output starts contributing to
  operator-facing alerts after a 14-day shadow period with operator
  satisfaction surveys
- Weeks 9–12: federated retraining if the deployment expands beyond
  A3-Alpha to additional facilities
- Weeks 13–16: integration with the maintenance scheduling system, so
  high-confidence RUL predictions can auto-populate the maintenance
  backlog (still operator-approved, not auto-dispatched)

---

## 8. Operational, security, and compliance considerations

### 8.1 OT/IT segregation (IEC 62443)

The model lives on the **IT side of the OT/IT boundary**, consuming
telemetry that crosses the boundary through the existing data diode
configuration. The model does **not** issue any control commands. All
BMS writes continue to go through the existing human-in-the-loop gate
with NIST SP 800-82 audit logging.

This placement is non-negotiable. An ML model on the OT side, with
write access to setpoints, would not pass any Tier IV audit.

### 8.2 Model lifecycle and version control

- Every deployed model carries a unique hash derived from its training
  data, hyperparameters, and code version.
- The hash is logged with every inference, attached to every alert, and
  stored in the audit log.
- The previous model version is retained and can be rolled back within
  60 seconds in case of degraded performance.
- A retraining cadence of 14 days is the baseline; concept drift
  detection (Wasserstein distance between training and observed
  feature distributions) can trigger off-cycle retraining.

### 8.3 What the stakeholder review should evaluate

When this roadmap is reviewed, the questions that should be asked are:

1. *Is the data quality sufficient at A3-Alpha for the schema in §2.1?*
   If telemetry is sparse or noisy, weeks 1–2 stretch. This is the
   single dominant risk.
2. *Is the synthetic degradation library realistic enough?*
   The eight patterns in §2.4 are derived from documented hyperscale
   failure post-mortems. We will publish the parameter justifications
   alongside the dataset.
3. *Does the FPR < 0.005 target survive contact with real operators?*
   It must; if it does not, the model gets unplugged.
4. *What is the second deployment site?*
   Single-site deployments do not test generalisation. Plans for the
   second site should be explicit before committing the MVP.

### 8.4 What this roadmap explicitly does not promise

- It does not promise that the Transformer/STGNN will detect *all*
  failures. Some failure classes are genuinely instantaneous and have
  no precursor signature; the BMS rule-based alarms remain the right
  tool there.
- It does not promise that 4-hour median lead time will hold across
  every degradation pattern. We expect at least one class will miss the
  threshold; that class is then targeted for a focused submodel rather
  than abandoned.
- It does not promise zero alarm fatigue. Operator UX iteration after
  the shadow period is required; we budget for it explicitly in the
  post-week-6 hardening plan.

---

## 9. Summary

This roadmap is the natural extension of the architecture in
`TRANSFORMER_ANALYSIS.md`. The first-principles ODE remains the
authoritative forecast engine on the safety-critical path. The new
multimodal attention-based system is added as a **separate, advisory,
auditable, gracefully-degrading layer** that addresses precisely the
failure modes lumped-parameter physics cannot see.

The architecture is defensible because:

- It does not replace validated physics with statistics
- It uses attention where attention is the right tool (multivariate
  joint-distribution anomaly detection on observed state)
- It preserves auditability through native attention attribution rather
  than post-hoc explanation
- It is gracefully degradable: the site continues to operate at v5.2
  fidelity if the model is offline
- It commits to honest operational thresholds (FPR < 0.005, lead time
  ≥ 4 h) that, if missed, gate deployment rather than deployment
  proceeding regardless

The 6-week MVP timeline is aggressive and depends on data availability
at A3-Alpha. The schedule risks are explicitly named (§7), as are the
classes of failure the system will not address (§8.4). What we are
committing to is not "deploy AI" — what we are committing to is
**deploy the right kind of inference for the problem class that the
existing physics engine cannot solve**, with the operational
guarantees that Tier IV demands.

This is the architecture I would defend in front of a Microsoft CO+I
review board, and it is the architecture I would deploy on a hyperscale
fleet.

---

**Document references**

- `TRANSFORMER_ANALYSIS.md` (April 2026, v5.0) — companion document
  defending the use of ODE for forward-trajectory forecasting
- `scenarios.yml` (10 critical failure scenarios used as ODE-side
  validation set)
- `bms_tags.yml` (42-tag BMS namespace baseline; v6 expands to ≈ 2,500
  features)
- IEC 62443-3-3 SL-2/SL-3 (security baseline for OT/IT boundary)
- NIST SP 800-82 Rev. 3 (industrial control systems security)
- ISO 22301 (business continuity for hyperscale infrastructure)
- IEEE 1184 / 1188 (UPS and battery standards referenced in
  degradation patterns)
- ASHRAE TC 9.9 thermal envelope (referenced in IT-thermal anomaly
  class)
- Liu et al. 2023, "STGNN for Power Grid Anomaly Detection," IEEE TPS
- Yi et al. 2023, "Time-Series Mixer architectures," NeurIPS

---

End of whitepaper.
