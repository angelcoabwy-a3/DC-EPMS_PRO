# S5.5 — Pre-Operational Briefing Logic
## Technical Specification — DC-EPMS PRO Phase V9

**Sprint**: S5.5 (split en S5.5a + S5.5b — insertado entre S5 y S6 del roadmap V9 12 semanas Opción A)
**Calendar Position**: S5.5a en W6.5; S5.5b en W7 (antes de S6 DPO)
**Estimated Effort**: S5.5a 6-8h + S5.5b 5-6h = 11-14h total
**Status**: 🟡 Diseño Lógico Aprobado — Pendiente de Implementación
**Aprobado por**: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
**Aprobación date**: 2026-05-03
**Decision IDs aprobados**: A1+B1+C1+D1+E2 (briefing core) + F2+G1+H1+I1 (PUE addendum)

---

## 1. Propósito

Implementar el componente **"Morning Announcement"** — una interfaz UX/UI con lógica de orquestación que el Critical Environment Technician opera al inicio de su turno para obtener un briefing estructurado del estado de la facility A3-Alpha Toronto Area.

El briefing sintetiza datos de fuentes ya implementadas en el sistema (`physics_engine`, `graphrag_service`, `database`, `rag_service`, LM Studio) sin agregar conectividad nueva ni hardware externo. Incluye PUE como métrica reina, calculada con cross-check first-law sobre los 4 sub-modelos físicos y comparada contra thresholds architecture-aware definidos en config externa.

---

## 2. División Aprobada (Decisión F2)

| Sprint | Calendario | Scope | Esfuerzo |
|---|---|---|---|
| **S5.5a** | W6.5 | **Orchestrator 5-step**: subsystems + topology + incidents + procedures + LLM synthesis. Modelo Pydantic incluye `pue_metrics: Optional[PUEMetrics] = None` como placeholder. | 6-8h |
| **S5.5b** | W7 | **PUE Logic**: `compute_pue()` en physics_engine, `config/pue_targets.yml`, architecture-aware UI thresholds, populación de `pue_metrics` en briefing. | 5-6h |

**Por qué split**:
1. Atomic batches verificables independientemente
2. Cross-check first-law en physics_engine puede revelar bugs latentes — mejor aislarlo
3. Si S5.5a tiene problemas de integración, no atrasa PUE; si PUE tiene complejidad de cálculo, no atrasa briefing
4. PUE merece su propia ADR documentada (ADR-009 propuesta)

---

## 3. User Story Combinada

> Como CET en arranque de turno, presiono el botón "Generate Pre-Shift Briefing" en la HMI y obtengo un documento markdown estructurado con:
> - **(a)** Handover sintetizado de las últimas 12h por LLM local
> - **(b)** Estado verificado de los 4 subsistemas físicos vía `physics_engine.validate_site()`
> - **(c)** Insight topológico de redundancia 2N vía GraphRAG
> - **(d)** Procedimientos relevantes precargados vía ChromaDB tier-aware
> - **(e)** PUE actual con threshold visual architecture-aware (verde/amarillo/rojo según baseline 480VAC trifásico Phase 1 o 800VDC Phase 2 Building D)
>
> El briefing es exportable a PDF y queda registrado como evento auditable en la tabla `shift_briefings` (Tier IV audit trail innegociable).

---

## 4. Honest Scope

### 4.1 Lo que SÍ se construye

✅ Botón HTML "Generate Pre-Shift Briefing" en HMI existente (Vanilla JS)
✅ Endpoint `POST /api/shift/briefing` (orquestador 5-step)
✅ Módulo nuevo `backend/shift_briefing.py` (~250 líneas estimadas, S5.5a)
✅ Failsafe mode si LM Studio falla o timeout >10s
✅ Audit trail completo en tabla nueva `shift_briefings` (PostgreSQL, schema con `pue_json` opcional desde S5.5a)
✅ Markdown render + opción PDF export (reuse `shift_report.py`)
✅ NetworkX progressive overlay durante el chequeo (visualización honesta, no PLC ping en vivo)
✅ Tests: S5.5a 15 tests + S5.5b 9 tests = 24 tests (8+6 unit, 4+2 integration, 3+1 smoke)
✅ Provenance trace (qué fuentes consultadas, decision_time_ms)
✅ **PUE calculation con cross-check first-law (S5.5b, ~3-4h en physics_engine)**
✅ **`config/pue_targets.yml` config-driven (S5.5b, decisión I1)**
✅ **Architecture-aware UI thresholds dinámicos (S5.5b)**

### 4.2 Lo que NO se construye (Future Enhancements)

❌ Botón industrial físico + microcontrolador → Future Enhancement Q3 2026
❌ Webhook desde hardware externo → trivial agregar después si llega el botón
❌ Monitor OLED 39" físico → Future Enhancement (depende de hardware)
❌ Conectividad PLC real (BACnet/Modbus open) → fuera del scope IEC 62443 read-only authority
❌ Multi-agent consensus (voting/debate/arbitration) → no viable en 11-14h
❌ Auto-trigger por cron en cambio de turno → Future Enhancement
❌ 800VDC subsystem en briefing → solo aparece SI Building D está deployed (S3 V9 W1-2)
❌ **PUE 1.10 marketing claim** → defendemos targets reales: 1.30 Phase 1, 1.15 Phase 2

### 4.3 Restricciones Arquitectónicas Heredadas

- **IEC 62443 zone-and-conduit segregation**: el briefing es read-only, no escribe BMS, solo agrega/sintetiza
- **Human-in-the-Loop**: el briefing es información para el CET, no decisión automatizada
- **Deterministic Sandbox preservado**: cero capacidad de write-action por LLM o orquestador

---

## 5. Aclaración Eléctrica Crítica (Vocabulario Defendible)

A3-Alpha tiene dos arquitecturas eléctricas distintas según fase de deployment. La precisión del vocabulario es crítica para defendibilidad ante panel Microsoft CO+I:

### 5.1 Phase 1 — Buildings A/B Actual (deployed)

```
Utility (medium voltage AC trifásico)
  → Transformadores xfmr_a, xfmr_b
  → 480 VAC trifásico distribución (busways trifásicos)
  → UPS Galaxy VX 2N
  → RPP/PDU
  → Racks (50 racks modelados, 142 kW c/u)
```

**Vocabulary defendible**: "480 VAC trifásico, distribución estándar Tier IV 2N con UPS Galaxy VX y chillers York YZ N+1".

### 5.2 Phase 2 — Building D Target Q2 2026

```
Utility (35 kVAC trifásico) ← upstream AC trifásico
  → MV Rectifier (rectificación balanceada de 3 fases)
  → 800 VDC unipolar TN-S downstream ← bus DC, sin fases
  → SSCBs (1-100 µs clearing)
  → Side Car Power Racks (white space retrofit)
  → GB300 NVL144 racks (200 kW c/u, 800VDC → 12VDC at GPU)
```

**Vocabulary defendible**: "Upstream 3-phase AC (35 kVAC trifásico) → MV Rectifier → 800 VDC unipolar TN-S downstream. Ventaja operativa: rectificación balanceada de las 3 fases, reducción del ripple en el rectificador, mitigación de armónicos reflejados a la red. La palabra 'trifásico' aplica al AC upstream, no al bus DC (que es DC unipolar, sin fases)".

**Anti-pattern a evitar**: NO decir "800VDC trifásico" — el bus DC no tiene fases. Decir esto en panel es señal inmediata de imprecisión técnica. La trifasidad vive en el AC upstream del MV Rectifier exclusivamente.

---

## 6. Arquitectura del Sistema

### 6.1 Diagrama de Flujo

```
┌──────────────────────────────────────────────────┐
│  HMI Frontend (Vanilla JS)                       │
│  [Button: "Generate Pre-Shift Briefing"]         │
└──────────────────┬───────────────────────────────┘
                   │ POST /api/shift/briefing
                   ▼
┌──────────────────────────────────────────────────┐
│  main.py — endpoint handler                      │
│  validate request → call BriefingGenerator       │
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│  backend/shift_briefing.py (S5.5a)               │
│  Orchestrator class: BriefingGenerator           │
│  ├── Step 1: subsystem_status()                  │
│  ├── Step 2: topology_awareness()                │
│  ├── Step 3: incidents_last_12h()                │
│  ├── Step 4: relevant_procedures()               │
│  ├── Step 5: llm_synthesis()                     │
│  ├── Step 6: pue_metrics() ← S5.5b               │
│  └── render_markdown() + persist()               │
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│  Existing modules (read-only consumption)        │
│  ├── physics_engine.validate_site()              │
│  ├── physics_engine.compute_pue() ← S5.5b NEW    │
│  ├── graphrag_service.query("redundancy")        │
│  ├── database.query (incidents table)            │
│  ├── rag_service.query (Chroma tier-priority)    │
│  └── httpx → LM Studio /v1/chat/completions      │
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│  Config (S5.5b)                                  │
│  config/pue_targets.yml ← architecture baselines │
│  backend/pue_thresholds.py ← parser              │
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│  Persistence (Tier IV audit trail)               │
│  PostgreSQL: shift_briefings table               │
│  (schema con pue_json opcional desde S5.5a)      │
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│  Response: BriefingDocument (Pydantic)           │
│  → Frontend renders markdown                     │
│  → Architecture-aware PUE color coding (S5.5b)   │
│  → "Export to PDF" → /api/shift/report           │
└──────────────────────────────────────────────────┘
```

### 6.2 Pipeline Detallado

| # | Paso | Función | Módulo | Sprint | Tiempo Target |
|---|---|---|---|---|---|
| 1 | Subsystem Status | `_step1_subsystem_status()` | `physics_engine.validate_site()` | S5.5a | <50ms |
| 2 | Topology Awareness | `_step2_topology_awareness()` | `graphrag_service.query("redundancy")` | S5.5a | ~100ms |
| 3 | Incidents Last 12h | `_step3_incidents_12h()` | `database.fetch_incidents(window=12h)` | S5.5a | <30ms |
| 4 | Relevant Procedures | `_step4_relevant_procedures()` | `rag_service.query()` | S5.5a | ~200ms |
| 5 | LLM Synthesis | `_step5_llm_synthesis()` | LM Studio gemma-4-e2b-it | S5.5a | 2-5s |
| 6 | **PUE Metrics** | `_step6_pue_metrics()` | `physics_engine.compute_pue()` + `pue_thresholds.classify()` | **S5.5b** | <100ms |

**Latency Target End-to-End**: p95 < 8s (tanto S5.5a solo como S5.5a+b combinados)

---

## 7. Output Schema (Pydantic)

### 7.1 Modelos Core (S5.5a)

```python
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field

class SubsystemStatus(BaseModel):
    name: str
    status: Literal["NOMINAL", "CAUTION", "CRITICAL"]
    primary_metric: str
    metric_value: float
    metric_unit: str
    physical_justification: str
    suggested_action: Optional[str]

class TopologyInsight(BaseModel):
    path_a_summary: str
    path_b_summary: str
    redundancy_state: Literal["VERIFIED", "DEGRADED", "LOST"]
    affected_components: list[str]

class IncidentSummary(BaseModel):
    incident_id: str
    timestamp: datetime
    severity: Literal["INFO", "WARNING", "HIGH", "CRITICAL"]
    category: str
    one_line_summary: str

class ProcedureRef(BaseModel):
    doc_id: str
    title: str
    tier: int
    relevance_score: float
    reason: str
```

### 7.2 PUE Models (S5.5b)

```python
class PUEBreakdown(BaseModel):
    """Component breakdown for first-law cross-check."""
    it_equipment_kw: float       # Suma de cargas IT (it_thermal module)
    cooling_total_kw: float      # chillers + towers + CHW pumps + CDU pumps + secondary
    electrical_losses_kw: float  # Transformer + UPS + busway Joule losses
    misc_loads_kw: float          # Lighting, security, BMS infra (placeholder fixed)
    total_facility_kw: float      # Sum of all above
    first_law_residual_pct: float # (validation) abs((measured_total - sum) / sum) * 100

class PUEThresholdConfig(BaseModel):
    """Loaded from config/pue_targets.yml at request time."""
    baseline_id: str              # "a3_alpha_phase1_480vac" | "building_d_800vdc_phase2"
    optimal_max: float            # Verde si pue < this
    deviation_max: float          # Amarillo si optimal_max <= pue < this; Rojo >=
    rationale: str
    references: list[str]

class PUEMetrics(BaseModel):
    """Populated by S5.5b. None in S5.5a (placeholder)."""
    current_pue: float
    pue_design_target: float
    pue_delta: float
    pue_status: Literal["OPTIMAL", "DEVIATION", "CRITICAL", "UNVERIFIED"]
    breakdown: PUEBreakdown
    threshold_config: PUEThresholdConfig
    architecture_baseline: str    # ej. "480VAC_2N_phase1"
    cross_check_passed: bool      # True si first_law_residual_pct < 2.0
```

### 7.3 BriefingDocument

```python
class BriefingDocument(BaseModel):
    # Identification
    briefing_id: str = Field(default_factory=lambda: f"BRF-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}")
    timestamp: datetime
    cet_on_duty: str
    shift_start: datetime
    facility: str = "A3-Alpha Toronto Area"
    
    # S5.5a — Steps 1-5
    subsystem_status: dict[str, SubsystemStatus]
    site_health_index: float
    severity_summary: Literal["NOMINAL", "CAUTION", "CRITICAL"]
    topology_insight: TopologyInsight
    incidents_12h: list[IncidentSummary]
    active_maintenance: list[str]
    relevant_procedures: list[ProcedureRef]
    llm_summary: Optional[str]
    llm_synthesis_status: Literal["success", "timeout", "skipped"]
    
    # S5.5b — Step 6 (None en S5.5a, populated en S5.5b)
    pue_metrics: Optional[PUEMetrics] = None
    
    # Provenance (V9 discipline)
    sources_consulted: dict[str, str]
    decision_time_ms: int
    api_version: str = "1.0"
```

---

## 8. PUE Calculation Logic (S5.5b Detallado)

### 8.1 Fórmula Base

```
PUE = Total_Facility_Power / IT_Equipment_Power

Donde:
  Total_Facility_Power = IT_Equipment_Power 
                       + Cooling_Power 
                       + Electrical_Losses 
                       + Misc_Loads
```

### 8.2 Implementación en `physics_engine.compute_pue()`

```python
def compute_pue(self, measurements: dict) -> PUEBreakdown:
    """
    Compute facility PUE with first-law cross-check.
    
    Aggregates power consumption from each of the 4 sub-modules:
    - it_thermal: sum of rack power (electrical-to-thermal Q_it)
    - heat_rejection: chillers compressor + cooling tower fans + condenser pumps
    - mechanical: CDU pumps + secondary loop pumps + primary CHW pumps
    - electrical: transformer copper + iron losses + UPS conversion + busway Joule
    
    First-law cross-check: total facility power should equal sum of components
    within 2% (instrumentation tolerance + minor unmodeled loads like lighting).
    
    If residual > 2%, PUEMetrics.cross_check_passed = False and
    pue_status = "UNVERIFIED" — briefing entrega resto de secciones, 
    PUE marcado para investigación.
    """
    it_kw = self._it_thermal.compute_total_power(measurements)
    cooling_kw = (self._heat_rejection.compute_total_power(measurements) 
                  + self._mechanical.compute_pump_power(measurements))
    elec_losses_kw = self._electrical.compute_losses(measurements)
    misc_kw = self.MISC_LOADS_FIXED_KW  # placeholder ~50 kW lighting/BMS
    
    total = it_kw + cooling_kw + elec_losses_kw + misc_kw
    
    measured_total = measurements.get('utility_meter_kw')
    if measured_total:
        residual_pct = abs((measured_total - total) / total) * 100
    else:
        residual_pct = 0.0  # No measurement available, skip cross-check
    
    return PUEBreakdown(
        it_equipment_kw=it_kw,
        cooling_total_kw=cooling_kw,
        electrical_losses_kw=elec_losses_kw,
        misc_loads_kw=misc_kw,
        total_facility_kw=total,
        first_law_residual_pct=residual_pct,
    )
```

### 8.3 Architecture Baseline Detection

```python
def detect_architecture_baseline(site_model: SiteModel) -> str:
    """
    Returns the active baseline_id based on what's deployed in site_model.
    
    Logic:
    - If any component has voltage_nominal >= 800: "building_d_800vdc_phase2"
    - Else: "a3_alpha_phase1_480vac"
    
    Future: when both phases coexist (post Building D deploy), 
    could return per-building baseline. For now, single facility-wide baseline.
    """
```

### 8.4 Threshold Classification

```python
def classify_pue(current_pue: float, config: PUEThresholdConfig) -> Literal["OPTIMAL", "DEVIATION", "CRITICAL"]:
    if current_pue < config.optimal_max:
        return "OPTIMAL"   # Verde
    elif current_pue < config.deviation_max:
        return "DEVIATION" # Amarillo
    else:
        return "CRITICAL"  # Rojo
```

---

## 9. Configuration File (S5.5b — Decisión I1)

### 9.1 `config/pue_targets.yml` (NUEVO archivo)

```yaml
# config/pue_targets.yml
# Architecture-aware PUE thresholds for A3-Alpha Toronto Area.
# Loaded by backend/pue_thresholds.py. Reload requires server restart.
# 
# Honest engineering targets — NOT marketing claims.
# References cited inline for defensibility under deep-dive.

pue_targets:
  
  a3_alpha_phase1_480vac:
    optimal_max: 1.30
    deviation_max: 1.45
    # Color logic: < optimal_max = green; < deviation_max = yellow; >= deviation_max = red
    rationale: |
      Tier IV facility with 480 VAC trifásico distribution, 2N redundancy,
      UPS Schneider Galaxy VX, York YZ chillers (3× N+1), partial DLC retrofit
      on Blackwell racks. Industry baseline 2024-2026 for this architecture
      class is 1.25-1.40. Optimal target 1.30 reflects achievable steady-state
      with current cooling envelope (ASHRAE A2) and Toronto climate (free-cooling
      hours limited by dry-bulb >18°C April-October).
    references:
      - "Uptime Institute Tier IV Topology Standard"
      - "ASHRAE TC 9.9 Class A2 Thermal Guidelines"
      - "Schneider Electric WP122 Critical Power Best Practices"
    architecture_summary: "480 VAC trifásico → UPS Galaxy VX 2N → RPP/PDU → racks"
  
  building_d_800vdc_phase2:
    optimal_max: 1.15
    deviation_max: 1.25
    rationale: |
      Engineered target (NOT marketing). Building D Phase 2 deployment Q2 2026
      with full architecture upgrade:
      - Upstream 3-phase AC (35 kVAC trifásico) → MV Rectifier 
        (balanced rectification, reduced ripple, harmonic mitigation to grid)
      - 800 VDC unipolar TN-S downstream (sin fases — bus DC)
      - SSCBs for fault clearing 1-100 µs (IEC 60947-2)
      - Full DLC retrofit GB300 NVL144 (200 kW/rack, 800VDC → 12VDC at GPU)
      - BESS 2.5 MWh for load-swing absorption (sub-100ms capacitive buffer)
      
      Target 1.15 is achievable per OCP-LVDC modeling for this exact stack.
      Marketing claims of 1.10 require year-round free-cooling AND complete
      DLC adoption — neither present at A3-Alpha.
    references:
      - "NVIDIA 800VDC Architecture for Next-Generation AI Infrastructure"
      - "Open Compute Project: Data Center Facility LVDC Power Distribution"
      - "IEC TR 63282 Voltage Bands for LVDC Systems"
      - "STMicroelectronics: Designing an Advanced BMS"
      - "03_TECHNICAL_SPECS_800VDC.md (project internal spec)"
    architecture_summary: "Upstream 3-phase AC → MV Rectifier → 800 VDC unipolar TN-S → SSCB → racks"

# Misc loads constant (lighting, BMS, security panels)
misc_loads_constant_kw: 50.0
```

### 9.2 Parser (`backend/pue_thresholds.py`)

```python
"""
backend/pue_thresholds.py — S5.5b
Parser for config/pue_targets.yml.
Lazy-loaded once per request, cached in module-level dict.
"""
from pathlib import Path
import yaml
from typing import Optional

class PUEThresholdRegistry:
    _cache: Optional[dict] = None
    
    @classmethod
    def load(cls, config_path: Path) -> dict:
        if cls._cache is None:
            with open(config_path) as f:
                raw = yaml.safe_load(f)
            cls._cache = raw['pue_targets']
        return cls._cache
    
    @classmethod
    def get(cls, baseline_id: str) -> PUEThresholdConfig:
        targets = cls.load(...)
        if baseline_id not in targets:
            raise ValueError(f"Unknown baseline: {baseline_id}")
        t = targets[baseline_id]
        return PUEThresholdConfig(
            baseline_id=baseline_id,
            optimal_max=t['optimal_max'],
            deviation_max=t['deviation_max'],
            rationale=t['rationale'],
            references=t['references'],
        )
```

---

## 10. Frontend HMI (S5.5a + S5.5b)

### 10.1 S5.5a Components

- 1 botón en sidebar: **"Pre-Shift Briefing"** con icono Lucide `clipboard-check`
- 1 panel HTML que renderiza markdown (vía `marked.js` o `showdown`)
- 1 botón secundario **"Export to PDF"** post-render
- 1 NetworkX progressive overlay durante chequeo (loading state honesto)

### 10.2 S5.5b PUE Visual Gauge

Después del paso 6 (PUE compute), el frontend renderiza:

```html
<div class="pue-gauge" data-status="OPTIMAL|DEVIATION|CRITICAL|UNVERIFIED">
  <div class="pue-current">PUE: 1.28</div>
  <div class="pue-target">Target: 1.30 (Phase 1: 480 VAC trifásico 2N)</div>
  <div class="pue-delta">Δ: -0.02 (within optimal envelope)</div>
  <div class="pue-references" title="Click for sources">📚</div>
</div>

<style>
  [data-status="OPTIMAL"]   { background: #2ecc71; }  /* Green */
  [data-status="DEVIATION"] { background: #f39c12; }  /* Yellow */
  [data-status="CRITICAL"]  { background: #e74c3c; }  /* Red */
  [data-status="UNVERIFIED"] { 
    background: #95a5a6;                              /* Gray */
    border: 2px dashed #34495e;                       /* dashed = "data, no judgment" */
  }
</style>
```

### 10.3 Architecture Baseline Display

El gauge muestra el baseline activo explícitamente. Si solo está deployed Phase 1, muestra: *"Operating in Phase 1: 480 VAC trifásico 2N — target PUE < 1.30. Phase 2 (800 VDC Building D) target 1.15 will activate when deployed."*

Esto **previene confusión del CET** (¿por qué mi target es 1.30 si NVIDIA dice 1.10?) y **arma respuesta defendible para entrevista** (sistema sabe distinguir su propia arquitectura).

---

## 11. Persistence Layer

### 11.1 Tabla `shift_briefings` (PostgreSQL)

**Schema definido en S5.5a, columna `pue_json` opcional desde el inicio para evitar migration en S5.5b**:

```sql
CREATE TABLE shift_briefings (
    briefing_id          TEXT PRIMARY KEY,
    timestamp            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cet_on_duty          TEXT NOT NULL,
    shift_start          TIMESTAMPTZ NOT NULL,
    facility             TEXT NOT NULL DEFAULT 'A3-Alpha Toronto Area',
    
    severity_summary     TEXT NOT NULL CHECK (severity_summary IN ('NOMINAL', 'CAUTION', 'CRITICAL')),
    site_health_index    NUMERIC(4,3) NOT NULL,
    
    briefing_json        JSONB NOT NULL,  -- Full BriefingDocument serialized
    markdown_rendered    TEXT NOT NULL,    -- For PDF export reuse
    
    -- S5.5b: PUE block, NULL en S5.5a (placeholder), populated en S5.5b
    pue_json             JSONB,            -- PUEMetrics serialized
    pue_status           TEXT CHECK (pue_status IS NULL OR pue_status IN ('OPTIMAL', 'DEVIATION', 'CRITICAL', 'UNVERIFIED')),
    
    llm_synthesis_status TEXT NOT NULL CHECK (llm_synthesis_status IN ('success', 'timeout', 'skipped')),
    decision_time_ms     INTEGER NOT NULL,
    
    api_version          TEXT NOT NULL DEFAULT '1.0',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT chk_decision_time CHECK (decision_time_ms > 0)
);

CREATE INDEX idx_shift_briefings_timestamp ON shift_briefings(timestamp DESC);
CREATE INDEX idx_shift_briefings_cet ON shift_briefings(cet_on_duty);
CREATE INDEX idx_shift_briefings_severity ON shift_briefings(severity_summary)
    WHERE severity_summary IN ('CAUTION', 'CRITICAL');
CREATE INDEX idx_shift_briefings_pue_status ON shift_briefings(pue_status)
    WHERE pue_status IN ('CRITICAL', 'UNVERIFIED');  -- partial index for alerts
```

### 11.2 Migration Path

- Crear archivo `backend/migrations/2026_05_W6_5_add_shift_briefings.sql` (S5.5a, schema completo desde el inicio)
- Aplicar manualmente o vía script `scripts/apply_migration.py`
- **No hay migration adicional en S5.5b** — `pue_json` ya existe como NULLable

---

## 12. Endpoint Specification

### 12.1 `POST /api/shift/briefing` (S5.5a + S5.5b)

**Request Body**:
```json
{
  "trigger_source": "manual",
  "include_llm_synthesis": true,
  "include_pue_metrics": true,
  "incident_window_hours": 12
}
```

**Response 200 OK**: `BriefingDocument` con o sin `pue_metrics` según sprint activo

**Response 503**: solo si `physics_engine.validate_site()` falla completamente

**Failure modes con HTTP 200 (graceful degradation)**:
- LM Studio timeout → `llm_synthesis_status: "timeout"`, briefing parcial
- PUE first-law residual > 2% → `pue_status: "UNVERIFIED"`, briefing entregado
- Chroma o GraphRAG fallan → flags en `sources_consulted`

### 12.2 `POST /api/shift/report?briefing_id=BRF-...`

Reuse de `shift_report.py` con argumento `briefing_id`. Recupera `markdown_rendered` y genera PDF vía reportlab.

---

## 13. Tests Plan

### 13.1 S5.5a Tests (15 tests)

**Unit (8) — `tests/test_shift_briefing.py`**:
1. `test_briefing_doc_serialization`
2. `test_step1_subsystem_status_aggregation`
3. `test_step2_topology_query_keyword`
4. `test_step3_incident_filter_12h_window`
5. `test_step4_relevant_procedures_tier_priority`
6. `test_step5_llm_timeout_fallback`
7. `test_severity_summary_calculation`
8. `test_sources_consulted_provenance_complete`

**Integration (4) — `tests/integration/test_briefing_e2e.py`**:
1. `test_briefing_full_pipeline_happy_path`
2. `test_briefing_with_active_incident_boosts_tier1_safety`
3. `test_briefing_with_lm_studio_unavailable_returns_partial`
4. `test_briefing_pdf_export_via_shift_report`

**Smoke (3) — `scripts/smoke_briefing.py`**:
1. `test_endpoint_responds_200`
2. `test_briefing_markdown_well_formed`
3. `test_briefing_under_8s_latency_p95`

### 13.2 S5.5b Tests (9 tests adicionales)

**Unit (6) — `tests/test_pue_logic.py`**:
1. `test_compute_pue_aggregation_4_modules`
2. `test_compute_pue_first_law_cross_check_within_tolerance`
3. `test_compute_pue_first_law_residual_exceeds_2pct_marks_unverified`
4. `test_pue_thresholds_yaml_load_phase1_baseline`
5. `test_pue_thresholds_yaml_load_phase2_baseline`
6. `test_classify_pue_optimal_deviation_critical_boundaries`

**Integration (2) — `tests/integration/test_briefing_pue_e2e.py`**:
1. `test_briefing_with_pue_phase1_baseline_returns_correct_thresholds`
2. `test_briefing_pue_unverified_status_when_first_law_fails`

**Smoke (1) — `scripts/smoke_briefing.py` (extension)**:
1. `test_pue_gauge_renders_with_correct_color_status`

**Total tests adicionados**: 24 → **370 tests** post-implementación combinada

---

## 14. Implementation Plans

### 14.1 S5.5a — Hour-by-Hour (6-8h)

| Hour | Task | Deliverable |
|---|---|---|
| H1 | Pydantic models + DB migration | `BriefingDocument` (con `pue_metrics: None`), `shift_briefings` table |
| H2 | Step 1 + Step 2 + unit tests | `_step1_subsystem_status`, `_step2_topology_awareness` |
| H3 | Step 3 + Step 4 + unit tests | `_step3_incidents_12h`, `_step4_relevant_procedures` |
| H4 | Step 5 LLM + failsafe + unit tests | `_step5_llm_synthesis` con timeout=10s |
| H5 | Markdown render + persistencia + endpoint | `POST /api/shift/briefing` activo |
| H6 | Frontend (botón + panel + overlay) | HMI funcional |
| H7 | Integration tests | 4 tests E2E |
| H8 | Smoke tests + latency profiling + buffer | p95 medido, README actualizado |

### 14.2 S5.5b — Hour-by-Hour (5-6h)

| Hour | Task | Deliverable |
|---|---|---|
| H1 | `config/pue_targets.yml` + `pue_thresholds.py` parser + 2 unit tests | Config loadable, baselines defined |
| H2 | `physics_engine.compute_pue()` aggregation logic + 2 unit tests | PUE calculation funcional |
| H3 | First-law cross-check + UNVERIFIED status + 2 unit tests | Cross-check passing/failing tested |
| H4 | Integrate `_step6_pue_metrics()` en BriefingGenerator + 2 integration tests | BriefingDocument retorna `pue_metrics` populado |
| H5 | Frontend PUE gauge + architecture baseline display + 1 smoke test | UI muestra PUE con color coding |
| H6 | Buffer + README actualizado + ADR-009 draft | Documentación completa |

---

## 15. Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| LM Studio cuelga sistema entero | Media | Alta | Timeout estricto 10s + decisión B1 (failsafe parcial) |
| GraphRAG lazy-load primer query 2-3s | Alta | Media | Pre-warm en lifespan startup |
| Migration falla en runtime | Baja | Alta | Aplicar manualmente antes de deploy + rollback documentado |
| PUE first-law cross-check siempre falla por measurements incompletos | Media | Media | UNVERIFIED status diseñado para esto; degradación gradual |
| Threshold values defendidos por panel | Media | Alta | Rationale + references explícitas en `pue_targets.yml`; NO valores hardcoded |
| "Trifásico" usado incorrectamente en docs | Baja | Alta | Spec lo aclara explícitamente: trifásico = AC upstream, NO el bus DC |
| Briefing genera demasiado output (>5000 tokens) | Media | Media | Truncar incidents > 20, procedures > 3 |
| Tabla shift_briefings crece sin bound | Baja | Baja | Documentar política retención (90 días) en runbook V10 |

---

## 16. Audit Trail

### 16.1 Decision Log

| ID | Decisión | Voto Aprobado | Sesión |
|---|---|---|---|
| **A** | Naming módulo + endpoint | A1 (`shift_briefing.py` + `/api/shift/briefing`) | 2026-05-03 |
| **B** | LM Studio failure mode | B1 (briefing parcial con flag) | 2026-05-03 |
| **C** | Persistencia | C1 (tabla `shift_briefings` — innegociable Tier IV) | 2026-05-03 |
| **D** | Trigger | D1 (manual; D2 cron como Future Enhancement) | 2026-05-03 |
| **E** | Posición en doc | E2 (in-line en Sección 10 + Apéndice B) | 2026-05-03 |
| **F** | Scope PUE | **F2 (split S5.5a + S5.5b)** | 2026-05-03 |
| **G** | Architecture baseline thresholds A3-Alpha actual | **G1 (Verde < 1.30, Amarillo < 1.45)** | 2026-05-03 |
| **H** | PUE design target Building D | **H1 (Verde < 1.15, Amarillo < 1.25 — número de ingeniero, no de folleto)** | 2026-05-03 |
| **I** | Localización pue_targets | **I1 (`config/pue_targets.yml` standalone)** | 2026-05-03 |

### 16.2 Aclaraciones Técnicas Documentadas

- **2026-05-03**: Vocabulario eléctrico Building D refinado. "800VDC trifásico" es shorthand impreciso. Documentación oficial usa: "Upstream 3-phase AC (35 kVAC trifásico) → MV Rectifier (rectificación balanceada, reducción de ripple, mitigación de armónicos reflejados a la red) → 800 VDC unipolar TN-S downstream (bus DC, sin fases)". La trifasidad vive exclusivamente en el AC upstream.

### 16.3 Trazabilidad

- **Documento padre**: `02_STATUS_SUMMARY_REAL.md` Apéndice B
- **Conversación de aprobación**: sesión Claude 2026-05-03 (auditoría arqueológica + S5.5 design + PUE addendum)
- **ADRs propuestas**: ADR-009 "Architecture-aware PUE thresholds via config-driven targets" (a escribir en S5.5b H6)

---

## 17. Acceptance Criteria

### 17.1 S5.5a DONE cuando

✅ `POST /api/shift/briefing` responde 200 OK con `BriefingDocument` válido (pue_metrics=None)
✅ Tabla `shift_briefings` persiste cada briefing (con pue_json NULL)
✅ Botón HMI dispara generación + render markdown + opción PDF
✅ NetworkX progressive overlay funciona durante el chequeo
✅ Failsafe LM Studio timeout demostrado en integration test
✅ p95 latency < 8s medido en smoke test
✅ 15 tests S5.5a pasan
✅ README actualizado con sección "Pre-Shift Briefing"

### 17.2 S5.5b DONE cuando

✅ `physics_engine.compute_pue()` operativo con first-law cross-check
✅ `config/pue_targets.yml` cargable, ambos baselines definidos
✅ `BriefingDocument.pue_metrics` populado con threshold correcto según baseline
✅ Frontend PUE gauge renderiza con color coding correcto
✅ Architecture baseline mostrado al CET
✅ UNVERIFIED status manejado correctamente cuando first-law residual > 2%
✅ 9 tests S5.5b pasan (total acumulado: 24 nuevos tests, 370 total proyecto)
✅ ADR-009 escrita y commit
✅ `02_STATUS_SUMMARY_REAL.md` Apéndice B marca status como ✅ Implementado

---

## 18. Future Enhancements (NO en S5.5)

Documentados aquí para trazabilidad. **NO se construyen en estos sprints**.

- **FE-1**: Botón industrial físico + microcontrolador (ESP32 o RPi) + webhook → Q3 2026
- **FE-2**: Auto-trigger en cambio de turno (cron + `paperclip_org.yml shift schedule`) → S10 V9 polish
- **FE-3**: Integración con monitor OLED 39" físico → depende de hardware acquisition
- **FE-4**: Multi-CET briefing personalizado (cada CET ve sus zonas asignadas) → V10
- **FE-5**: Briefing diferencial ("¿qué cambió desde mi último briefing?") → V10
- **FE-6**: Voice synthesis del briefing (TTS) → V10
- **FE-7**: Briefing en español/inglés según preferencia CET → V10
- **FE-8**: 800VDC subsystem en briefing → cuando S3 V9 deploy Building D Phase 2
- **FE-9**: PUE histórico con trend chart (últimos 30 días) → V10
- **FE-10**: PUE breakdown drill-down por subsystem → V10

---

## 19. CV Implications (Post-Implementation Combined)

Línea defendible para CV Versión B+ una vez S5.5a + S5.5b estén DONE:

> *"Designed and implemented a Pre-Operational Briefing orchestrator with architecture-aware PUE monitoring for hyperscale data center shift handover: HMI-triggered synthesizer that fan-outs across physics_engine validation (4 subsystems with first-principles checks), GraphRAG topology query (NetworkX MultiDiGraph + FAISS), TimescaleDB incident retrieval (12h window), tier-aware ChromaDB procedure recall (20-doc corpus across Safety/Vendor/Standards/MOPs tiers), and local LLM (gemma-4-e2b-it) synthesis with 10s timeout failsafe; sub-8s p95 end-to-end. PUE calculation cross-checks first-law energy balance across the 4 physical sub-modules with config-driven thresholds dynamic to facility baseline (480 VAC trifásico 2N Phase 1 vs. upstream 3-phase AC → MV Rectifier → 800 VDC unipolar TN-S Phase 2). Full audit trail in PostgreSQL `shift_briefings` table preserving Tier IV compliance."*

---

**Documento generado**: 2026-05-03
**Status del Sprint**: 🟡 Diseño Lógico Aprobado — Pendiente de Implementación
**S5.5a position**: W6.5 del roadmap V9 12-semanas Opción A
**S5.5b position**: W7 del roadmap V9 12-semanas Opción A
**Próximo gate**: implementación post-S5 (W6) y pre-S6 (mid-W7) del roadmap
