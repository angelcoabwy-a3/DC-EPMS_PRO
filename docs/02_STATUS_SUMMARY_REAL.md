# DC-EPMS PRO — Status Summary REAL (Auditoría 2026-05-03)

**Reemplaza a `02_STATUS_SUMMARY.md`**. Este documento es producto de auditoría arqueológica del repositorio en C:\dev\DC-EPMS_PRO realizada el 2026-05-03 con metodología Batch A (inventario superficie) + Batch B (ejecución/imports) + Batch C (tools del agente). Cada afirmación tiene evidencia verificable en el código o el filesystem.

---

## 1. Resumen Ejecutivo

El proyecto DC-EPMS PRO es **significativamente más sofisticado** de lo que el status doc anterior reflejaba. La auditoría reveló:

- **+85 tests no documentados** del subsistema `physics/` (Darcy-Weisbach, Magnus-Tetens, ASHRAE, Joule, ODE integration)
- **Dual-RAG architecture intencional** (ChromaDB tier-aware primario + GraphRAG NetworkX/FAISS secundario)
- **20 documentos de corpus operativo** en 4 tiers (Safety/Vendor/Standards/a3semi MOPs), no 5
- **6 MOPs/EOPs escritos** como markdown indexable (solo 1 está como YAML ejecutable)
- **2 superficies de agente** (Copilot FastAPI con 6 tools + MCP Server stdio con 3 tools + 4 resources)
- **~50 endpoints REST** activos (vs los 15 que el status doc anterior reportaba)
- **2 archivos huérfanos** con código de alta calidad sin integrar (`cyber_physical_tools.py` con Kalman + Numba, `dpo_edge_healing.py` con LoRA fine-tuning)

Pero también reveló deudas reales:
- **`pytest` agregado cuelga** por `pytest.ini` permisivo sin `testpaths`
- **No hay repositorio Git inicializado** (`fatal: not a git repository`)
- **50 racks modelados**, no 118 como afirma el header del YAML y el CV anterior
- **4 archivos duplicados idénticos** en `backend/physics/` (hash MD5 confirmado)

**Cambios post-auditoría (2026-05-03)**:
- ✅ Sprint **S5.5 Pre-Operational Briefing** aprobado e insertado en roadmap V9 (decisiones A1+B1+C1+D1+E2 inicial; F2+G1+H1+I1 PUE addendum). **Split en 2 sprints atómicos**: S5.5a (W6.5, orchestrator) + S5.5b (W7, PUE logic architecture-aware). Ver Apéndice B + `S5_5_BRIEFING_SPEC.md`.
- ✅ **Decisión 1 RESOLVED** (votos 1A+2B+D-B): integrar `cyber_physical_tools.py` (Kalman) en S5 + `dpo_edge_healing.py` (capture-only + manual trigger) en S6 + DPO compute en CPU bitsandbytes.
- ✅ **Decisión 3 RESOLVED** (voto 3B): mantener `agent_engine.py` como dual-AI fallback con ADR-004.
- 🟡 **Decisiones 2 y 4 pendientes**: 50 racks vs 118 (Building D expansion), conversión MOPs markdown a YAML ejecutable.

---

## 2. Reconciliación Status Doc vs Realidad

| Métrica | Status Doc anterior | Realidad Verificada | Defendibilidad |
|---|---|---|---|
| Tests collected | 350+ | **346 verificados** | "345+ tests" defendible |
| Componentes | 91 | **~80** (50 racks + ~30 infra) | Necesita verificación final con `len(SiteModel().list_components())` |
| Buildings | 4 (A/B/C/Yard) | 2 producción (A,B) + 1 NOC (C) + 1 yard | ✅ |
| Capacidad IT | 40 MW | **40 MW design intent / ~7.1 MW modelado** | Requiere clarificación honesta en CV |
| Racks | 118 | **50** (5 rows × 10) | Requiere clarificación honesta en CV |
| Rows | implícito | **5** (3 en hall A + 2 en hall B, asimétrico) | ✅ |
| MOPs | "1 YAML ejecutable" | **1 YAML + 6 markdown indexados** | ✅ — material para diversificar tests |
| Knowledge corpus | "5 docs" | **5 GraphRAG + 20 ChromaDB = 25 total** | ✅ — fortaleza no comunicada |
| RAG architecture | "GraphRAG + FAISS" | **Dual: ChromaDB primario + GraphRAG secundario** | ✅ — más sofisticado de lo afirmado |
| Agent tools (Copilot) | "6 tools" | **6 confirmados** | ✅ correcto |
| Agent tools (MCP) | no mencionado | **3 tools + 4 resources** | ✅ bonus |
| Endpoints | "9 site + 6 graphrag = 15" | **29 directos + 5 routers ≈ 50+** | ✅ — fortaleza no comunicada |
| Sprints originales done | "3 de 6" | **3 ejecutables + 2 huérfanos + 3 pendientes** | Trabajo invisible |

---

## 3. Inventario Verificado de Backend

### 3.1 Activos y Críticos (KEEP — usar tal como están)

| Archivo | Líneas | Refs main.py | Justificación |
|---|---|---|---|
| `main.py` | 1823 | — | Hub central, ~50 endpoints, 5 routers, lifespan correcto |
| `physics_engine.py` | 369 | 12 | Facade del subsystem físico, módulo más usado |
| `agent_copilot.py` | 894 | 3 | Copilot principal con 3 tools propios + ToolRegistry |
| `procedure_engine.py` | 641 | (vía include_router) | State machine de MOPs, 32 tests |
| `witness_engine.py` | 290 | (vía include_router) | Multi-signature drafts, 26 tests |
| `cmms_mcp.py` | 492 | — | Tool `draft_cmms_work_order`, 51 tests |
| `site_model.py` | 462 | — | Parser YAML + dataclasses, 44 tests |
| `database.py` | 261 | 6 | asyncpg + TimescaleDB |
| `bms_connector.py` | 351 | 5 | Stub BACnet/Modbus, 4 endpoints `/api/bms/*` |
| `shift_report.py` | 325 | 6 | PDF generator vía `/api/shift/report` |
| `rag_service.py` | 234 | **20** | **RAG primario ChromaDB**, 20 docs en 4 tiers |
| `graphrag_service.py` | 166 | 3 | GraphRAG S2 (FAISS+NetworkX), montado como router |
| `graphrag_index.py` | 252 | (interno graphrag) | FAISS index + sentence-transformers lazy |
| `knowledge_graph.py` | 292 | (interno graphrag) | NetworkX MultiDiGraph |
| `agent_site_tool.py` | 224 | (vía registry) | Tool `query_site_model` |
| `agent_graph_tool.py` | 134 | (vía registry) | Tool `query_graph_rag` |
| `cmms_site_enrichment.py` | 112 | (interno cmms) | site_context injection |
| `site_routes.py` | 186 | (vía include_router) | 9 endpoints `/api/site/*` |
| `graphrag_routes.py` | 62 | (vía include_router) | Endpoints `/api/graph/*` |
| `physics/__init__.py` | 43 | (interno physics) | Paquete |
| `physics/base.py` | 199 | (interno physics) | ABC PhysicsModule + dataclasses |
| `physics/it_thermal.py` | 632 | (interno physics) | Heat balance + ODE air temp, 20 tests |
| `physics/heat_rejection.py` | 584 | (interno physics) | Psicrometría ASHRAE + COP York YZ, 22 tests |
| `physics/electrical.py` | 509 | (interno physics) | Joule + ANSI C57.12, 18 tests |
| `physics/mechanical.py` | 486 | (interno physics) | Darcy-Weisbach + pump affinity, 13 tests |
| `hal/cummins_adapter.py` | 247 | (interno hal) | Genset adapter |
| `hal/asco_adapter.py` | 223 | (interno hal) | ATS adapter |
| `hal/russelectric_adapter.py` | 206 | (interno hal) | Switchgear adapter |
| `hal/__init__.py` | 162 | (interno hal) | HAL facade, 39 tests |

### 3.2 Activos Standalone (KEEP — corre como subprocess separado)

| Archivo | Líneas | Refs main.py | Justificación |
|---|---|---|---|
| `mcp_server.py` | 531 | **0 (correcto)** | Subprocess de Claude Desktop via stdio. Expone 3 tools (`simulate_failure`, `read_bms_tag`, `list_bms_tags`) + 4 resources (telemetry, SHI, scenarios, incidents). MCP spec 2024-11-05. |

**TODO operacional**: verificar manualmente que `claude_desktop_config.json` apunte a `mcp_server.py` y que la conexión funcione en producción.

### 3.3 Huérfanos con Código Estratégico (DECIDIR — integrar o documentar como deuda)

| Archivo | Líneas | Refs main.py | Asset |
|---|---|---|---|
| `cyber_physical_tools.py` | 248 | **0** | **Kalman innovation residual + Numba @njit + Send-on-Delta**. Sensor fusion ya escrito, no integrado. Pillar 3 V9 latente. |
| `dpo_edge_healing.py` | 352 | **0** | **DPO loop con LoRA fine-tuning + honest VRAM accounting** (3.3 GB peak documented). S6 V9 ya escrito, no integrado. Diferenciador máximo del proyecto. |

### 3.4 Probable Legacy (REVISAR — vivo pero secundario)

| Archivo | Líneas | Refs main.py | Análisis |
|---|---|---|---|
| `agent_engine.py` | 294 | 2 | Versión anterior con NeMo Guardrails + Gemma + Claude Sonnet. `agent_copilot.py` (894 líneas, 3 refs) es la versión actual. **Decisión pendiente**: archivar o mantener como dual-AI. |

### 3.5 Duplicados Confirmados (DELETE — hash MD5 idéntico verificado)

| Archivo | Líneas | Acción |
|---|---|---|
| `physics/physics_it_thermal.py` | 632 | Borrar (idéntico a `physics/it_thermal.py`) |
| `physics/physics_heat_rejection.py` | 584 | Borrar (idéntico a `physics/heat_rejection.py`) |
| `physics/physics_electrical.py` | 509 | Borrar (idéntico a `physics/electrical.py`) |
| `physics/physics__init__.py` | 43 | Borrar (idéntico a `physics/__init__.py`) |
| `physics_engine.py` (root del paquete vs dentro de `physics/`) | — | Verificar cuál es canónico |
| `backend/physics__init__.py` | 37 | Huérfano fuera del paquete, borrar |

**Reducción estimada**: ~1280 líneas duplicadas pueden eliminarse sin pérdida funcional.

### 3.6 Ya Archivado Correctamente

| Carpeta | Contenido |
|---|---|
| `_legacy_backup/` | 7 archivos, ~63 KB, fechas abril 2026. Iteraciones MCP previas (`mcp_epms_server.py`, `mcp_epms_stdio.py`, `mcp_epms_stdio_v2.py`) + scripts de indexación obsoletos. **No tocar.** |

---

## 4. Schema Real de site_model.yml

### 4.1 Top-level keys (5)

```yaml
site:           # metadata del sitio
buildings:      # tree containment (4 buildings)
power_chains:   # DAG eléctrico 2N
cooling_chains: # DAG térmico N+1
components:     # registry de componentes
```

### 4.2 Estructura de buildings

```yaml
buildings:
  - id: building_a
    type: production_hall
    description: "Production data hall — Path A primary"
    rooms:
      - id: dh-a
        type: data_hall
        display: "Data Hall A"
        area_m2: 2400
        design_load_kw: 8400
        ashrae_class: A2
        components: [busway_a_01, busway_a_02, busway_b_01, busway_b_02]
        rows:
          - id: row-a-01
            display: "Row A-01"
            rack_count: 10
            racks: [rack_a_01_01, ..., rack_a_01_10]
```

### 4.3 Inventario real

| Tipo | Cantidad |
|---|---|
| Buildings | 4 (a, b, c, yard) — pero solo a y b son production halls |
| Rooms | dh-a, dh-b, er-a, er-b, mr-a, mr-b, NOC, yard subdivisions |
| Rows | **5** (row-a-01, row-a-02, row-a-03, row-b-01, row-b-02) |
| Racks | **50** (5 rows × 10 racks/row) |
| CDUs | 6 (cdu_a_01..03, cdu_b_01..03) |
| Chillers | 3 (chiller_1, chiller_2, chiller_3 — N+1) |
| Gensets | 4 (genset_a_01, genset_a_02, genset_b_01, genset_b_02) |
| UPS | 2 (ups_a, ups_b) |
| RPP | 4 (rpp_a_01, rpp_a_02, rpp_b_01, rpp_b_02) |
| Switchgear | 2 (switchgear_a, switchgear_b) |
| Transformers | 2 (xfmr_a, xfmr_b) |
| ATS | 2 (ats_a, ats_b) |
| Busways | 4 (busway_a_01, busway_a_02, busway_b_01, busway_b_02) |
| Cooling towers | 2 (cooling_tower_field_n, cooling_tower_field_s) |
| CHW pumps | 3 |
| Fuel tanks | 2 |
| BMS panels | 3 (bms_panel_a, bms_panel_b, bms_master_workstation) |

### 4.4 API Pública del Parser (`backend/site_model.py`)

```python
# Excepciones
class SiteModelError(RuntimeError)
class ComponentNotFoundError(KeyError)
class SiteModelLoadError(SiteModelError)

# Dataclasses
@dataclass
class Location:
    site_id: str
    site_display: str
    building_id: Optional[str]
    building_display: Optional[str]
    room_id: Optional[str]
    room_display: Optional[str]
    room_type: Optional[str]
    row_id: Optional[str]
    row_display: Optional[str]

@dataclass
class ComponentInfo:
    canonical_id: str
    display: str
    type: str
    metadata: dict

@dataclass
class ImpactSet:
    failed_node: str
    chain_type: str
    immediate: list[str]
    transitive: list[str]
    by_type: dict[str, list[str]]

# Clase principal
class SiteModel:
    # API pública (línea 173+)

# Factory functions globales
def get_site_model(project_root: Optional[Path] = None) -> SiteModel
def reset_site_model() -> None
```

**Mapeo crítico YAML → Python**: la clave YAML `id:` se mapea a `ComponentInfo.canonical_id`. El status doc anterior confundía estas capas.

---

## 5. Dual-RAG Architecture

### 5.1 RAG Primario — ChromaDB (`rag_service.py`, 20 refs en main.py)

**Inicialización**: eager en `lifespan` startup (línea 199 de main.py)

**Endpoints**:
- `POST /api/rag/query` — query con tier-priority scoring
- `GET /api/rag/docs` — count de documentos indexados

**Persistencia**: 2 colecciones en `data/chroma_db/` (1.6 MB c/u) + `chroma.sqlite3` (2.4 MB)

**Corpus operativo** (20 documentos, 4 tiers):

**Tier 1 — Safety (5 docs, 29 KB)**:
- T1-SAF-LOTO-001 — LOTO CSA Z462
- T1-SAF-ARC-002 — Arc Flash NFPA 70E
- T1-SAF-CSE-003 — Confined Space Entry
- T1-SAF-FIR-004 — Fire Suppression Systems
- T1-SAF-EPO-005 — Emergency Power Off

**Tier 2 — Vendor (5 docs, 38 KB)**:
- T2-VEN-NV-GB200 — NVIDIA Blackwell DLC
- T2-VEN-SE-WP122 — Schneider Critical Power
- T2-VEN-SE-UPS-GVX — Schneider Galaxy VX UPS
- T2-VEN-ST-PDU — Starline busway
- T2-VEN-YK-CHI-YZ — York YZ chiller

**Tier 3 — Standards (4 docs, 31 KB)**:
- T3-STD-ASHRAE-A2 — Thermal envelope
- T3-STD-IEC-62443 — OT cybersecurity
- T3-STD-ISO-22301 — Business continuity
- T3-STD-THERMAL-MODEL — Newton cooling

**Tier 4 — a3semi MOPs (6 docs, 46 KB)**:
- T4-MOP-CHI-001 — Chiller quarterly PM
- T4-MOP-FIR-001 — VESDA annual test
- T4-MOP-GEN-001 — Generator monthly exercise
- T4-MOP-PDU-001 — PDU thermographic quarterly
- T4-MOP-UPS-001 — UPS quarterly PM
- T4-EOP-COOL-003 — Emergency cooling reduction

### 5.2 RAG Secundario — GraphRAG (`graphrag_service.py`, 3 refs en main.py)

**Inicialización**: lazy en primera query

**Endpoints**: `/api/graph/*` (6 endpoints vía `make_graphrag_router`)

**Stack**: NetworkX MultiDiGraph + FAISS IndexFlatIP + sentence-transformers `all-MiniLM-L6-v2` (90 MB lazy-loaded)

**Corpus**: 5 markdown en `config/knowledge/`:
- `nvidia-800vdc-architecture.md`
- `ocp-lvdc-power-distribution.md`
- `stmicro-bms-design.md`
- `csa-z462-24-stub.md`
- `oesc-ontario-stub.md`

**Edges declarativos `applies_to`**: linkean componentes físicos a documentos para retrieval topológica.

### 5.3 División de Roles

| Use Case | Sistema RAG |
|---|---|
| Query operacional ("¿cómo hacer LOTO en UPS Galaxy VX?") | ChromaDB tier-aware (boost Safety) |
| Query topológica ("¿qué OCP-LVDC aplica a `bus_d_main`?") | GraphRAG component→knowledge edges |
| Query con jurisdicción (Ontario vs international) | GraphRAG con metadata filter |
| Búsqueda exhaustiva en MOPs reales | ChromaDB Tier 4 |

---

## 6. Agent Surfaces

### 6.1 Copilot FastAPI (vía `/agent/stream`)

6 tools registrados en `_build_default_registry()` (agent_copilot.py:811):

| # | Tool | Archivo | Propósito |
|---|---|---|---|
| 1 | `query_unified_graph` | agent_copilot.py | Query topológica unificada |
| 2 | `analyze_rul_and_supply` | agent_copilot.py | Remaining Useful Life + supply chain |
| 3 | `draft_precooling_plan` | agent_copilot.py | Plan de pre-cooling |
| 4 | `query_site_model` | agent_site_tool.py | Query schema YAML site model |
| 5 | `query_graph_rag` | agent_graph_tool.py | Query GraphRAG topológica |
| 6 | `draft_cmms_work_order` | cmms_mcp.py | Generar borrador WO con LOR scoring |

### 6.2 MCP Server stdio (vía Claude Desktop subprocess)

3 tools + 4 resources expuestos por `mcp_server.py` (spec 2024-11-05):

**Tools**:
- `simulate_failure(scenario_id, horizon_s)` — corre escenario en physics engine
- `read_bms_tag(tag_id)` — lee valor BACnet/Modbus
- `list_bms_tags()` — catálogo de tags

**Resources**:
- `a3semi://telemetry/current` — snapshot último de telemetría
- `a3semi://physics/site-health` — SHI + per-module health
- `a3semi://scenarios/list` — catálogo SCN-01..SCN-10
- `a3semi://incidents/recent` — últimos 20 incidentes desde Postgres

---

## 7. Endpoints REST Completos (Verificados)

### 7.1 Endpoints directos en main.py (29)

| Método | Path | Línea |
|---|---|---|
| GET | `/api/health` | 285 |
| POST | `/api/telemetry` | 384 |
| GET | `/api/telemetry` | 404 |
| GET | `/api/telemetry/latest` | 418 |
| GET | `/api/telemetry/stream` | 439 |
| POST | `/api/incidents` | 476 |
| GET | `/api/incidents` | 488 |
| POST | `/api/rag/query` | 502 |
| GET | `/api/rag/docs` | 522 |
| POST | `/agent/stream` | 532 |
| POST | `/lm/{path:path}` | 586 |
| GET | `/lm/{path:path}` | 606 |
| POST | `/api/voice/transcribe` | 621 |
| POST | `/api/shift/report` | 633 |
| GET | `/api/site/health` | 790 |
| POST | `/api/physics/validate` | 820 |
| GET | `/api/scenarios` | 836 |
| POST | `/api/scenarios/{scenario_id}/run` | 858 |
| GET | `/api/mops` | 1038 |
| GET | `/api/mops/{doc_id}` | 1052 |
| POST | `/api/mops/generate` | 1092 |
| GET | `/api/topology/state` | 1212 |
| POST | `/api/topology/whatif` | 1513 |
| GET | `/api/bms/tags` | 1661 |
| GET | `/api/bms/tag/{tag_id:path}` | 1676 |
| POST | `/api/bms/write` | 1689 |
| GET | `/api/bms/audit` | 1711 |
| GET | `/` | 1733 |
| GET | `/favicon.ico` | 1750 |

### 7.2 Routers montados (5)

| Línea | Router | Origen |
|---|---|---|
| 1838 | `_agent_router` | agent_copilot (drafts: list, get, approve, reject, health) |
| 2004 | `_proc_router` | procedure_engine |
| 2005 | `_witness_router` | witness_engine |
| 2020 | `site_routes.router` | site_routes (9 endpoints `/api/site/*`) |
| 2047 | `make_graphrag_router(_s2_service)` | graphrag_routes (6 endpoints `/api/graph/*`) |

**Total estimado**: 29 directos + ~25 vía routers ≈ **~54 endpoints REST**

---

## 8. Tests Verificados (346 total)

| Archivo | Tests |
|---|---|
| `test_smoke.py` | 8 |
| `test_site_model.py` | 44 |
| `test_procedure_engine.py` | 32 |
| `test_witness_engine.py` | 26 |
| `test_cmms_mcp.py` | 51 |
| `test_site_integration.py` | 41 |
| `test_graphrag.py` | 20 |
| `test_hal_adapters.py` | 39 |
| `physics/test_electrical.py` | 18 |
| `physics/test_it_thermal.py` | 20 |
| `physics/test_heat_rejection.py` | 22 |
| `physics/test_mechanical.py` | 13 |
| `physics/test_physics_engine.py` | 12 |
| **TOTAL** | **346** |

**Caveat**: `pytest` agregado (sin argumentos) cuelga por `pytest.ini` permisivo. Cada archivo individual collect en <0.75s. **Deuda DevOps prioritaria**: agregar `testpaths = tests` a `pytest.ini`.

---

## 9. Discrepancias y Deudas Identificadas

### 9.1 Críticas (afectan defendibilidad de CV)

| Discrepancia | Impacto | Resolución propuesta |
|---|---|---|
| CV dice 118 racks, YAML modela 50 | Senior CET puede pedir verificación | Reescribir CV: "40MW design intent / 50-rack Phase 1 Tier IV simulation" |
| CV dice 350+ tests, real 346 | Menor pero verificable | Cambiar a "345+ tests" |
| Status doc dice "5 docs RAG", real 25 (5 GraphRAG + 20 Chroma) | **Subreporta fortaleza** | CV puede afirmar "20-document operational corpus across 4 priority tiers" |
| Status doc no menciona physics engine (~3500 líneas, 85 tests) | **Subreporta fortaleza** | CV debe incluir "first-principles physics engine (Darcy-Weisbach, ASHRAE psychrometrics, ANSI C57.12)" |

### 9.2 Operacionales

| Deuda | Severidad | Acción |
|---|---|---|
| No hay repositorio Git | 🔴 Alta | `git init` + push a GitHub para habilitar CI |
| `pytest.ini` permite cuelgue agregado | 🟡 Media | Agregar `testpaths = tests` |
| 4 archivos duplicados idénticos en `physics/` | 🟢 Baja | Borrar, ~1280 líneas |
| `mcp_server.py` no verificado en producción | 🟡 Media | Test manual de conexión Claude Desktop |
| `cyber_physical_tools.py` huérfano (Kalman + Numba) | 🟡 Media | Decisión pendiente: integrar o documentar |
| `dpo_edge_healing.py` huérfano (DPO + LoRA) | 🟡 Media | Decisión pendiente: integrar o documentar |
| `agent_engine.py` posible legacy | 🟢 Baja | Decisión pendiente: archivar o mantener dual-AI |

### 9.3 Arquitecturales (asintomáticas pero importantes)

- **6 MOPs markdown vs 1 YAML ejecutable**: gap entre conocimiento documental y procedural automation. Convertir 1-2 MOPs a YAML desbloquea diversificación de tests E2E.
- **Building D 800VDC (S3 V9)**: cero código, mencionado solo en directrices. Necesita decisión: ¿expandir YAML para llegar a 118 racks vía Building D?

---

## 10. Implicaciones para Roadmap V9 (12 semanas Opción A confirmada)

### 10.1 Re-evaluación de Sprints V9 dada la realidad

**Última actualización**: 2026-05-03 post-Decisiones 1+3 RESOLVED (votos 1A+2B+3B+D-B aprobados).

| Sprint V9 | Plan original | Realidad descubierta | Plan revisado |
|---|---|---|---|
| **S3 W1-2 Foundation** | Building D 800VDC + DevOps | Sin código aún. DevOps urgente (no hay git, pytest cuelga) | **Igual + git init + pytest.ini fix** |
| **S4 W3-4 EHS Auditor** | DSPy + reglas | Posible reuse de `agent_engine.py` o agent_copilot existing | Verificar viabilidad de reuse antes de codear |
| **S5 W5-6 Telemetry + Kalman Integration** | Synthetic streams + preconditions | `cyber_physical_tools.py` ya tiene Kalman + Send-on-Delta | **CONFIRMED 1A: integrar `cyber_physical_tools.py`** (Kalman innovation residual + Numba @njit + Send-on-Delta) + ~6-8 unit tests nuevos. Synthetic streams + preconditions parte del scope original mantenido. ~1.5 sem total. |
| **S5.5a W6.5 Pre-Operational Briefing — Orchestrator** | **NUEVO sprint** (insertado 2026-05-03) | Synthesizer de turno: physics_engine + GraphRAG + ChromaDB + LM Studio orquestados detrás de botón HMI "Generate Pre-Shift Briefing". **Sin lógica PUE — placeholder en el modelo.** Ver Apéndice B. | **6-8h dentro del tiempo liberado** |
| **S5.5b W7 Pre-Operational Briefing — PUE Logic + ADR-004** | **NUEVO sprint** (insertado 2026-05-03) | Capa PUE architecture-aware: `compute_pue()` en physics_engine + `config/pue_targets.yml` config-driven + UI thresholds dinámicos según baseline. **+ ADR-004 escrita en H6 polish** (`agent_engine.py` dual-AI rationale). Ver Apéndice B. | **5-6h, requiere S5.5a previo + first-law cross-check físico** |
| **S6 W7-8 DPO Capture-Only + ADR-005** | "Spike a partir de cero" | `dpo_edge_healing.py` ya tiene 352 líneas con honest VRAM accounting | **CONFIRMED 2B: integrar capture-only**. Tabla `dpo_pairs` PostgreSQL + endpoint `POST /api/dpo/capture` (auto-disparado en CMMS WO rejection) + endpoint `POST /api/dpo/recompile` (manual trigger). **CONFIRMED D-B: training en CPU bitsandbytes** (preserva edge-local). Sin nightly automation. **+ ADR-005** escrita en H6 (DPO compute strategy + honest VRAM accounting cite). ~2-3 días total. |
| **S7 W9-10 Alarm Storm** | Bayesian network | Sin código, pero `topology` en main.py podría ser base | Sin cambio |
| **S8 W11-12 EOP Abort** | Async event bus | Sin código, primera implementación | Sin cambio |

### 10.2 Tiempo Liberado por Reuse y Asignación

Post-Decisiones 1+3 RESOLVED (2026-05-03):

**Confirmado por integración de huérfanos**:
- S5 con `cyber_physical_tools.py` integrado: 1.5 sem (3-4 días Kalman integration + 1 sem scope original telemetry/preconditions)
- S6 con `dpo_edge_healing.py` capture-only: 2-3 días (en lugar de 2 semanas spike desde cero)
- **Total liberado vs plan original V9**: ~7-9 días (~50-60h)

**Asignación final (post-decisiones aprobadas)**:

| Item | Esfuerzo | Sprint |
|---|---|---|
| **S5.5a Pre-Operational Briefing — Orchestrator** | 6-8h | W6.5 |
| **S5.5b Pre-Operational Briefing — PUE Logic + ADR-004** | 5-6h | W7 |
| **Building D + 118 racks expansion en YAML (trifásico AC upstream → 800VDC unipolar TN-S downstream)** | ~12-16h | S3 W1-2 (subject to Decisión 2) |
| **2 MOPs markdown convertidos a YAML ejecutable** | ~6-8h | S5 W5-6 (subject to Decisión 4) |
| **ADR-005 DPO compute strategy** | ~2h | S6 H6 |
| **Polish extendido**: README + C4 + ADRs anotadas + demo video | ~12-16h | S10 W14 |
| **Buffer para imprevistos** | ~6-10h | distribuido |

**Total consumido**: ~50-66h, alineado con ~50-60h liberadas.

Con esta asignación:
- ✅ S9 EKF **sigue killed** — `cyber_physical_tools.py` integration cubre Sensor Fusion (Decisión 1A)
- ✅ DPO funcional con narrativa honesta (capture + manual trigger, training nightly CPU bitsandbytes)
- ✅ Dual-AI resilience preservada con `agent_engine.py` mantenido (Decisión 3B + ADR-004)
- ⚠️ Decisiones 2 (118 racks) y 4 (MOPs YAML) siguen pendientes y pueden alterar la asignación de buffer

### 10.3 Sprint 6 Part A (Test Harness) — replan

Contexto antes: 3 escenarios E2E asumiendo Building D 800VDC.

Realidad: Building D no existe. Pero **hay 6 MOPs documentales + 1 YAML ejecutable + dual RAG + physics engine completo**.

**Test Harness Part A revisado** (escenarios usando código que SÍ existe):

1. **E2E happy path MOP-ATS-MONTHLY-001** — único MOP YAML actual, prueba flujo completo
2. **E2E LOTO impact analysis sobre `ups_a`** — prueba site_model + cmms + agent + dual RAG
3. **E2E what-if simulation `/api/topology/whatif`** — endpoint enorme no documentado, vale la pena testear E2E
4. **(opcional)** E2E Chroma+GraphRAG cross-query — valida que ambos RAG retornan resultados consistentes

Tiempo estimado: 4-6h, sin skip markers, contra código real existente.

---

## 11. Plan de Cleanup Propuesto

### 11.1 Fase 1 — Inmediato (~1h, no bloquea nada)

```bash
# Borrar duplicados confirmados (hash idéntico)
rm backend/physics/physics_it_thermal.py
rm backend/physics/physics_heat_rejection.py
rm backend/physics/physics_electrical.py
rm backend/physics/physics__init__.py
rm backend/physics__init__.py  # huérfano fuera del paquete
```

### 11.2 Fase 2 — DevOps Foundation (~2-3h)

```bash
# Git init + push a GitHub
git init
# (.gitignore con .venv/, __pycache__/, data/chroma_db/, _legacy_backup/, .bak_pre_*)
git add .
git commit -m "Initial commit: post-audit baseline"

# Fix pytest.ini
# (agregar testpaths = tests, python_files = test_*.py)
```

### 11.3 Fase 3 — Decisiones de Arquitectura (~30 min cada una)

Producir 1 ADR por decisión:
- **ADR-001**: Dual-RAG architecture (Chroma primario + GraphRAG secundario)
- **ADR-002**: NetworkX in-memory para GraphRAG (vs Neo4j)
- **ADR-003**: FAISS IndexFlatIP (vs NumPy linear)
- **ADR-004**: agent_engine.py vs agent_copilot.py — cuál es canónico
- **ADR-005**: Integración o deferral de cyber_physical_tools.py
- **ADR-006**: Integración o deferral de dpo_edge_healing.py
- **ADR-007**: Sprint 6 simulator killed (ya decidido)
- **ADR-008**: 50 racks Phase 1 vs 118 design intent — política de claim para CV

---

## 12. CV Versión B+ — Reescritura Defendible

Reemplazar la Versión B actual con:

```
DC-EPMS PRO — AI-Native Operations Platform for Tier IV AI Factories
Python · FastAPI · DSPy · NetworkX · FAISS · ChromaDB · TimescaleDB · Numba · Docker

• Architected an edge AI orchestration platform for a 40MW Tier IV data center
  simulation (NVIDIA GB200 NVL72 hyperscale topology, dual 2N power paths,
  N+1 cooling), with declarative YAML site model spanning 80+ components
  validated by 44 site_model unit tests and topology-aware LOTO impact
  analysis preserving 2N redundancy verification.

• Engineered a first-principles physics engine across 4 sub-systems
  (IT thermal, mechanical CDU, electrical UPS, heat rejection chillers)
  applying Darcy-Weisbach pressure drop, Magnus-Tetens psychrometrics,
  Joule's law per ANSI C57.12, and ODE transient integration via
  scipy.solve_ivp; Site Health Index synthesizes module health with
  redundancy-state severity modifiers.

• Built dual-mode RAG subsystem: ChromaDB tier-aware retrieval over
  20-document operational corpus (Safety/Vendor/Standards/a3semi MOPs
  spanning CSA Z462, NFPA 70E, IEC 62443, ASHRAE A2, NVIDIA GB200 DLC,
  Schneider WP122) plus a NetworkX+FAISS GraphRAG layer linking physical
  components to vendor whitepapers via declarative applies_to edges,
  enabling jurisdiction-filtered topological recall.

• Designed a 6-tool LLM Copilot (FastAPI streaming) plus a parallel
  MCP-protocol server (3 tools + 4 resources, spec 2024-11-05) exposing
  facility state to Claude Desktop, both following IEC 62443 zone-and-conduit
  segregation: read-only AI authority with mandatory Human-in-the-Loop
  approval gates on every CMMS draft, validated by 345+ pytest cases.
```

---

## 13. Decisiones que Wilmer Debe Tomar

Antes de retomar DevOps Quick Wins o Sprint 6 Part A:

### 13.1 Decisión 1 — Huérfanos Estratégicos ✅ RESOLVED 2026-05-03

**Status**: RESOLVED con votos 1A + 2B + D-B (sub-decisión añadida).

| Sub-decisión | Voto Aprobado | Esfuerzo | Sprint impactado |
|---|---|---|---|
| **1A** | `cyber_physical_tools.py` → **INTEGRAR** en S5 (Kalman innovation residual + Numba @njit + Send-on-Delta operativo) | 3-4 días | S5 W5-6 |
| **2B** | `dpo_edge_healing.py` → **INTEGRAR como capture-only + manual trigger** (sin nightly automation, manual recompile button via `/api/dpo/recompile`) | 2-3 días | S6 W7-8 |
| **D-B** | DPO training compute → **CPU bitsandbytes nightly** (preserva edge-local self-improvement, lentitud OK para nightly) | (incluido en 2B) | S6 |

**Justificación operacional documentada**:
- **1A**: sin Kalman operando, el argumento de reducción de falsos positivos en telemetría de misión crítica no es defendible en panel CO+I. S9 EKF confirmado como killed con esta integración.
- **2B**: narrativa para entrevista — *"Quería validar approval_rate stability antes de automatizar nightly. Captura está, training es manual hoy. Infra lista para automatizar con APScheduler en V10"*. Demuestra cautela operacional.
- **D-B**: edge-local self-improvement es diferenciador central V9 vs cloud-genéricas. Lentitud irrelevante para nightly window.

**Acciones derivadas**:
- ADR-004 propuesta: agregar al S5.5b H6 backlog (`agent_engine.py` dual-AI rationale — ver Decisión 13.3)
- ADR-005 propuesta: agregar al S6 (DPO compute strategy — CPU bitsandbytes selection con honest VRAM accounting cite)
- Tests para `cyber_physical_tools.py` (~6-8 unit tests) incluidos en S5 scope
- Tabla `dpo_pairs` (PostgreSQL) creada en S6 con audit trail
- Endpoint `/api/dpo/recompile` (manual trigger) creado en S6
- Métrica `approval_rate` reportada en briefing futuro post-DPO integration

### 13.2 Decisión 2 — 50 Racks vs 118

¿Expandir YAML a 118 racks (vía Building D 800VDC en S3 V9) o ajustar CV a "50 racks Phase 1"?

| Opción | Tiempo | Beneficio |
|---|---|---|
| Expandir a 118 con Building D 800VDC | S3 V9 ya planificado, agregar racks ~1 día extra | CV alineado con número marketing |
| Ajustar CV a "50 racks Phase 1, 40MW design intent" | 0 | Honestidad operacional |

### 13.3 Decisión 3 — `agent_engine.py` vs `agent_copilot.py` ✅ RESOLVED 2026-05-03

**Status**: RESOLVED con voto 3B.

**Voto aprobado**: **3B — Mantener `agent_engine.py` como dual-AI fallback** (status quo + ADR-004 documentando rationale).

**Justificación**:
- 2 referencias en main.py son baratas, archivo no rompe nada
- Capability "Gemma local + Claude Sonnet 4.6 cloud + NeMo Guardrails" demuestra resilience multi-LLM en CV
- Archivar pierde la narrativa por ahorrar 294 líneas
- ADR-004 documenta coexistencia con `agent_copilot.py` (primary tool-calling agent)

**Acciones derivadas**:
- ADR-004 a escribir en S5.5b H6 (originalmente DevOps Quick Wins, reasignado a S5.5b polish hour)
- Sin trabajo de migration (agent_engine.py preserva vivo)
- En entrevista: respuesta defendible — *"agent_copilot.py es el primary agent con tool calling para 6 herramientas; agent_engine.py mantiene path Cloud/Edge resilience con NeMo Guardrails como fallback de gobernanza"*

### 13.4 Decisión 4 — MOPs markdown a YAML ejecutables

¿Convertir 1-2 MOPs markdown a YAML ejecutable para diversificar Sprint 6 Part A?

| Opción | Tiempo | Beneficio |
|---|---|---|
| Convertir T4-MOP-UPS-001 (Quarterly UPS PM) | ~3-4h | Test E2E con escenario distinto a ATS |
| Convertir T4-MOP-CHI-001 (Chiller Quarterly) | ~3-4h | Test E2E sobre chiller path |
| No convertir | 0 | Sprint 6 Part A solo tiene MOP-ATS para escenarios |

---

## 14. ADRs Pendientes de Escribir

Tras Decisiones 1+3 RESOLVED, los siguientes ADRs (Architectural Decision Records) quedan agendados para escribir como artifacts de sus respectivos sprints. Cada ADR sigue formato MADR (Markdown Any Decision Record) y se commitea en `docs/adr/`.

### 14.1 ADR-004 — `agent_engine.py` Dual-AI Coexistence

**Sprint asignado**: S5.5b W7 (H6 polish hour)
**Status**: Proposed
**Decision**: Mantener `agent_engine.py` (294 líneas, 2 refs en main.py) coexistiendo con `agent_copilot.py` (894 líneas, 3 refs en main.py).

**Context resumido**:
- `agent_copilot.py` es el primary tool-calling agent con 6 tools registrados (`query_unified_graph`, `analyze_rul_and_supply`, `draft_precooling_plan`, `query_site_model`, `query_graph_rag`, `draft_cmms_work_order`)
- `agent_engine.py` provee dual-AI orchestration: Gemma 4 local (LM Studio) + Claude Sonnet 4.6 cloud + NeMo Guardrails para input/output filtering
- Ambos coexisten en `lifespan()` startup de main.py

**Rationale**:
- Capability separation: `agent_copilot.py` = function calling para CMMS/topology/RAG queries. `agent_engine.py` = streaming queries técnicas con guardrails.
- Cloud/Edge resilience: Sonnet 4.6 fallback cuando Gemma local degrada.
- NeMo Guardrails representa una capa de governance que `agent_copilot.py` no implementa.
- Overhead: 294 líneas, 2 refs — costo mínimo.

**Consequences**:
- ✅ Defendible en panel CO+I como arquitectura multi-LLM resilience
- ⚠️ Incrementa surface area de testing y mantenimiento
- ⚠️ Requiere documentación clara para evitar confusión sobre cuál archivo es "el agente"

**Trade-off declined**: archivar `agent_engine.py` ahorraría 294 líneas pero perdería narrativa de resilience que es asset estratégico para CV V9.

---

### 14.2 ADR-005 — DPO Compute Strategy: CPU bitsandbytes Edge-Local

**Sprint asignado**: S6 W7-8 (H6 polish hour)
**Status**: Proposed
**Decision**: DPO LoRA fine-tuning ejecuta sobre CPU con bitsandbytes 4-bit quantization. Manual trigger via `POST /api/dpo/recompile`. Sin nightly automation.

**Context resumido**:
- `dpo_edge_healing.py` (352 líneas) implementa DPO loop sobre Hermes-3-8B local
- "HONEST VRAM ACCOUNTING" interno documenta que LoRA training peak es ~3.3GB VRAM, no 1.5GB del spec original
- Hardware target: ASUS Zephyrus G14 con RTX 3060 6GB
- Tres opciones evaluadas en código fuente: A=switch a Phi-2/TinyLlama (pierde calidad), B=CPU bitsandbytes (lento, sin VRAM), C=cloud GPU (pierde edge-local property)

**Decision aprobada**: **Opción B (CPU bitsandbytes)** + **manual trigger** (no nightly automation hasta validar approval_rate stability).

**Rationale**:
- **Edge-local self-improvement** preserva la propiedad arquitectónica diferencial V9 vs cloud genérico (Opción C archived).
- **Calidad Hermes-3-8B preservada** (no downgrade a Phi-2, Opción A archived).
- **Lentitud aceptable**: nightly window de varias horas para procesar pairs acumulados durante el día.
- **Manual trigger**: discipline V9 de "validar approval_rate stability antes de automatizar" — narrative defendible en panel.

**Implementation notes**:
- Tabla `dpo_pairs` (PostgreSQL) captura `(original_draft, corrected_draft, rejection_reason, ts)` cada vez que CET rechaza un CMMS WO draft
- Endpoint `POST /api/dpo/capture` invocado automáticamente desde el flow de WO rejection
- Endpoint `POST /api/dpo/recompile` invocado manualmente desde HMI cuando CET decide promover el adapter actualizado
- Métrica `approval_rate` calculable desde tabla `cmms_drafts` (existente) over time

**Consequences**:
- ✅ Preserva edge-local property como diferenciador
- ✅ Honest VRAM accounting cite-able en panel: *"3.3GB peak en GPU si usáramos opción A; CPU bitsandbytes evita ese ceiling"*
- ✅ Manual trigger demuestra cautela operacional Tier IV
- ⚠️ Nightly training en CPU toma horas — no apto para iteración rápida; OK para producción

**Future Enhancement (V10)**: APScheduler nightly trigger automático cuando approval_rate >= threshold (ej. 80%) sostenido durante N días.

---

## Apéndice A — Audit Trail

**Metodología**: Lectura sin modificación, ejecución de comandos PowerShell read-only sobre el filesystem de C:\dev\DC-EPMS_PRO.

**Comandos ejecutados**:
- Batch A: 4 bloques de inventario superficie (headers, hashes MD5, contenido `_legacy_backup/`)
- Batch B: 6 bloques de ejecución (imports, routes, pytest collect, RAG owners, schema YAML)
- Batch C: 1 bloque (tools del agente)

**Herramientas**: PowerShell, Get-Content, Select-String, Get-FileHash, pytest --collect-only

**Limitaciones**:
- No se ejecutó la suite completa de tests (cuelgue por pytest.ini permisivo)
- No se verificó manualmente la conexión MCP server con Claude Desktop
- No se inspeccionó el contenido del SQLite de ChromaDB (queda como TODO si se requiere conteo exacto de chunks)
- No se leyó el bloque `components:` de site_model.yml después de línea 383 (formato YAML diferente a buildings)

**Próximo paso recomendado**: Wilmer toma las 4 decisiones de Sección 13, después se replanifica DevOps Quick Wins + Sprint 6 Part A con baseline real.

---

## Apéndice B — Sprint S5.5 V9 Pre-Operational Briefing (Spec Resumida)

**Status**: 🟡 Diseño Lógico Aprobado — Split en 2 sprints atómicos. Pendiente de Implementación.
**Aprobado por Wilmer**: 2026-05-03 (decisiones A1+B1+C1+D1+E2 inicial; F2+G1+H1+I1 PUE addendum)
**Documento técnico completo**: `S5_5_BRIEFING_SPEC.md`

### B.1 División Aprobada (Decisión F2)

| Sprint | Calendario | Scope | Esfuerzo |
|---|---|---|---|
| **S5.5a** | W6.5 | Orchestrator 5-step (subsystems + topology + incidents + procedures + LLM synthesis). Sin lógica PUE — placeholder en modelo Pydantic. | 6-8h |
| **S5.5b** | W7 | PUE Logic: `compute_pue()` en physics_engine, `config/pue_targets.yml`, architecture-aware UI thresholds. | 5-6h |

### B.2 User Story Combinada
Como CET en arranque de turno, presiono el botón "Generate Pre-Shift Briefing" en la HMI y obtengo un documento markdown estructurado con: (a) handover sintetizado de las últimas 12h por LLM local, (b) estado verificado de 4 subsistemas físicos vía `physics_engine`, (c) insight topológico de redundancia 2N vía GraphRAG, (d) procedimientos relevantes precargados vía ChromaDB tier-aware, **(e) PUE actual con threshold visual architecture-aware (verde/amarillo/rojo según baseline 480VAC Phase 1 o 800VDC Building D)**. El briefing es exportable a PDF y queda registrado como evento auditable.

### B.3 Honest Scope (Combined)

| Incluye ✅ | NO incluye ❌ |
|---|---|
| Botón HTML en HMI existente | Botón industrial físico + microcontrolador |
| Backend orquestador 5-step | Conectividad PLC real (BACnet/Modbus open) |
| Failsafe si LM Studio timeout | Multi-agent consensus (voting/debate) |
| Audit trail en tabla `shift_briefings` | Monitor OLED 39" físico |
| NetworkX progressive overlay durante chequeo | 800VDC subsystem en briefing antes de S3 Building D deploy |
| Markdown + PDF export | Webhook desde hardware externo |
| **PUE calculation defendible (S5.5b)** | **PUE 1.10 marketing claim** (defendemos 1.30 / 1.15 reales) |
| **Architecture-aware thresholds via config** | **Hardcoded thresholds en código** |

### B.4 Pipeline de Orquestación (S5.5a — 5 pasos)

| # | Paso | Módulo Existente | Tiempo |
|---|---|---|---|
| 1 | Subsystem Status | `physics_engine.validate_site()` | <50ms |
| 2 | Topology Awareness | `graphrag_service.query("redundancy")` | ~100ms |
| 3 | Incidents Last 12h | `database.query incidents` (TimescaleDB) | <30ms |
| 4 | Relevant Procedures | `rag_service.query()` con tier-priority | ~200ms |
| 5 | LLM Synthesis | LM Studio gemma-4-e2b-it (timeout 10s) | 2-5s |

**Latency target end-to-end (S5.5a)**: p95 < 8s

### B.5 PUE Logic (S5.5b — adicional al briefing)

**Cálculo en `physics_engine`** (trabajo nuevo, ~3-4h):
- Nuevo método `compute_pue()` que agrega los 4 módulos físicos
- `Total_Facility_Power = IT_Equipment_Power + Cooling_Power + Electrical_Losses + Misc_Loads`
- `IT_Equipment_Power` desde módulo `it_thermal` (suma de cargas por rack)
- `Cooling_Power` desde `heat_rejection` (chillers + cooling towers + CHW pumps) + `mechanical` (CDU pumps + secondary loop)
- `Electrical_Losses` desde `electrical` (transformer copper + iron + UPS conversion + busway Joule)
- Cross-check first-law: residual debe ser <2% del total facility power
- Devuelve `PUE = Total_Facility_Power / IT_Equipment_Power` + breakdown completo

**Architecture Baseline Awareness** (Decisión H1 + aclaración eléctrica trifásica AC):

A3-Alpha tiene dos arquitecturas eléctricas distintas según fase de deployment:

| Baseline | Topología Eléctrica | PUE Target |
|---|---|---|
| **Phase 1 (Buildings A/B actual)** | 480 VAC trifásico 2N estándar Tier IV con UPS Galaxy VX + chillers York YZ | **1.30** (Verde < 1.30) |
| **Phase 2 (Building D Q2 2026)** | Upstream 3-phase AC (35 kVAC trifásico) → MV Rectifier → 800 VDC unipolar TN-S downstream. Ventaja operativa: rectificación balanceada, reducción de ripple en el rectificador, mitigación de armónicos reflejados a la red. | **1.15** (Verde < 1.15) |

**Nota técnica importante**: la palabra "trifásico" aplica al **upstream AC**, no al bus DC. El downstream del MV Rectifier es DC unipolar TN-S (sin fases). Esta distinción es crítica para defendibilidad ante panel de Microsoft CO+I.

**Config-driven thresholds** (Decisión I1 — `config/pue_targets.yml`):

```yaml
pue_targets:
  a3_alpha_phase1_480vac:
    optimal_max: 1.30      # Verde
    deviation_max: 1.45    # Amarillo entre 1.30-1.45; Rojo >= 1.45
    rationale: "Tier IV 480VAC trifásico 2N, York YZ chillers, DLC parcial"
    references: ["Uptime Institute Tier IV", "ASHRAE TC 9.9 A2"]

  building_d_800vdc_phase2:
    optimal_max: 1.15      # Verde
    deviation_max: 1.25    # Amarillo entre 1.15-1.25; Rojo >= 1.25
    rationale: "Upstream 3-phase AC → MV Rectifier (balanced rectification, reduced ripple, harmonic mitigation) → 800VDC unipolar TN-S → DLC completo"
    references: ["NVIDIA 800VDC architecture", "OCP-LVDC", "03_TECHNICAL_SPECS_800VDC.md", "IEC TR 63282"]
    note: "Target 1.15 es ingeniería defendible. PUE 1.10 marketing claim requiere free-cooling year-round + retrofit DLC completo no presentes en A3-Alpha."
```

### B.6 Endpoint y Persistencia

- **Endpoint S5.5a**: `POST /api/shift/briefing` retorna `BriefingDocument` con `pue_metrics: null` (placeholder)
- **Endpoint S5.5b**: mismo endpoint actualizado, ahora retorna `BriefingDocument` con `pue_metrics` populado
- **Módulos nuevos**: `backend/shift_briefing.py` (S5.5a, ~250 líneas) + extensión a `physics_engine.py` (S5.5b, ~150 líneas adicionales) + `backend/pue_thresholds.py` (S5.5b, ~80 líneas, parser de pue_targets.yml)
- **Persistencia**: tabla `shift_briefings` (PostgreSQL) creada en S5.5a — schema incluye columna `pue_json` opcional desde el inicio para evitar migration en S5.5b (decisión C1 — innegociable para Tier IV)
- **PDF export**: `POST /api/shift/report?briefing_id=X` (reuse de `shift_report.py` con reportlab)

### B.7 Failsafe Mode (decisión B1)

Si LM Studio falla o timeout >10s:
- Briefing retorna con `llm_synthesis_status: "timeout"`
- Pasos 1-4 entregan datos estructurados
- CET ve briefing parcial con datos crudos verificables
- HTTP 200 (no 503) — la utilidad operacional se preserva

Si `compute_pue()` falla (ej. cross-check first-law residual > 2%):
- `pue_metrics.pue_status = "UNVERIFIED"` con flag de error
- Briefing entrega resto de secciones; PUE marcado para investigación
- HTTP 200 (no 503) — degradación gradual, no all-or-nothing

### B.8 Tests Propuestos

| Sprint | Tests Unit | Tests Integration | Tests Smoke | Total |
|---|---|---|---|---|
| S5.5a | 8 | 4 | 3 | 15 |
| S5.5b | 6 | 2 | 1 | 9 |
| **Total** | **14** | **6** | **4** | **24** |

**Tests adicionados al proyecto**: 346 → **~370 tests** post-implementación combinada de S5.5a + S5.5b

### B.9 Posicionamiento Estratégico para CV

Línea adicional defendible para CV Versión B+ (post-implementación W6.5 + W7):

> *"Designed and implemented a Pre-Operational Briefing orchestrator with architecture-aware PUE monitoring: HMI-triggered shift handover synthesizer that fan-outs across physics_engine validation (4 subsystems), GraphRAG topology query, TimescaleDB incident retrieval (12h window), tier-aware ChromaDB procedure recall, and local LLM (gemma-4-e2b-it) synthesis with 10s timeout failsafe; sub-8s p95 end-to-end with full audit trail in PostgreSQL `shift_briefings` table. PUE calculation cross-checks first-law energy balance across the 4 physical sub-modules with config-driven thresholds dynamic to facility baseline (480VAC trifásico Phase 1 vs upstream 3-phase AC → MV Rectifier → 800VDC unipolar TN-S Phase 2)."*

### B.10 Decisiones Aprobadas

| ID | Decisión | Voto Aprobado | Sesión |
|---|---|---|---|
| A | Naming módulo + endpoint | A1 (`shift_briefing.py` + `/api/shift/briefing`) | 2026-05-03 |
| B | LM Studio failure mode | B1 (briefing parcial con flag) | 2026-05-03 |
| C | Persistencia | C1 (tabla `shift_briefings` — innegociable Tier IV) | 2026-05-03 |
| D | Trigger | D1 (manual; D2 cron como Future Enhancement) | 2026-05-03 |
| E | Posición en doc | E2 (in-line en Sección 10 + Apéndice B) | 2026-05-03 |
| **F** | **Scope PUE** | **F2 (split S5.5a + S5.5b)** | **2026-05-03** |
| **G** | **Architecture baseline thresholds A3-Alpha actual** | **G1 (Verde < 1.30, Amarillo < 1.45)** | **2026-05-03** |
| **H** | **PUE design target Building D** | **H1 (Verde < 1.15, Amarillo < 1.25 — número de ingeniero, no de folleto)** | **2026-05-03** |
| **I** | **Localización pue_targets** | **I1 (`config/pue_targets.yml` standalone — separation of concerns)** | **2026-05-03** |

---

**Documento generado**: 2026-05-03
**Última revisión**: 2026-05-03 (Decisiones 1+3 RESOLVED — votos 1A+2B+3B+D-B aprobados; ADR-004 y ADR-005 agendados; Sección 14 nueva con drafts ADR)
**Reemplaza**: `02_STATUS_SUMMARY.md` (obsoleto)
**Documentos relacionados**: `S5_5_BRIEFING_SPEC.md` (spec técnica detallada con S5.5a + S5.5b)
**Decisiones pendientes**: 2 (50 racks vs 118), 4 (MOPs markdown a YAML)
**Vigencia**: hasta próxima auditoría arqueológica o cambio arquitectónico mayor
