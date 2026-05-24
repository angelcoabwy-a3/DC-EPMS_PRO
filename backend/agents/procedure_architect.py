"""
backend/agents/procedure_architect.py
=====================================
Epic 6 — Procedure Architect agent.

Generates SOP / MOP / EOP / EMP documents for Tier-IV data-center
operations. The agent is *authoring* — distinct from the reactive
:mod:`backend.multi_agent` fleet (which votes on operator queries) and
from :mod:`backend.procedure_generator` (which compiles deterministic
DRAFT skeletons from the asset registry per ADR-010).

Pipeline:

  1. Caller posts ``{doc_type, context}``.
  2. The Agent builds a hermetic Gemma prompt (H17) carrying the EXACT
     system prompt the Staff SRE pinned in Epic 6 spec — no rewording,
     no injection. The conditional template block tells the model
     which structure to render.
  3. The LLM returns a markdown document. When no LLM client is
     wired, the Agent falls back to a deterministic skeleton built
     from the same template — operator still sees something
     structured, just empty.
  4. :func:`audit_procedure_safety` runs a DETERMINISTIC text-pattern
     scan over the result. Required terms missing from a MOP (LOTO /
     PPE / CSA Z462) emit ``hard_stop``. Per-template required terms
     are pinned in :data:`SAFETY_REQUIRED_TERMS`.

The audit is the Safety Officer's role on this surface — but it does
NOT run the live :class:`backend.multi_agent.SafetyOfficerAgent` here
(that agent reasons about assets / telemetry / LOTO state). For a
generated *document*, the audit is a precision text gate.

S-DET-01 / ADR-006: only the *authoring* call is LLM-driven. The
*audit verdict* is computed by pure-Python pattern matching — the
deterministic gate every Architect output crosses before the operator
sees it.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.agent_continuity import (
    PHASE_POST_LLM,
    PHASE_PRE_LLM,
    CheckpointStore,
)
from backend.agent_harness import (
    ArtifactDependencyError,
    hermetic_prompt,
    require_artifact,
)

log = logging.getLogger(__name__)


# ─── Safety priority directive — operator mandate 2026-05-23 ─────────
# Prepended to the system prompt so the LLM author treats it as the
# top-of-stack rule before any template-specific guidance. The audit
# gate enforces the same contract deterministically — the prompt is
# the soft nudge, the audit is the hard gate (S-DET-01 / ADR-006).
SAFETY_PRIORITY_DIRECTIVE = """# DIRECTIVA SUPREMA -- CERO INCIDENTES
ANTES de proponer cualquier paso operativo, evalúa si introduce riesgo de
incidente. Si lo introduce, recházalo o exige mitigación explícita. Las
salvaguardas no son opcionales:
* Aplica LOTO (Lockout/Tagout) cuando el equipo se desenergice.
* Verifica ausencia de tensión con el método Vivo-Muerto-Vivo antes de
  cualquier manipulación física.
* En trabajo en vivo, respeta el límite de aproximación restringida y
  exige PPE de la categoría correspondiente al Arc Flash etiquetado
  (CSA Z462-24 / NFPA 70E).
* Toda maniobra debe declarar un Plan de Reversión (Back-out Plan)
  explícito con criterios de aborto.
* Cuando la maniobra involucre transferencia de carga en PDU / RPP / STS,
  exige primero revisar el historial de alarmas + estado de la caja SCR
  antes de autorizar la transferencia.
* Si el contexto del operador menciona equipo Eaton (SOW R-48), añade
  verificación BCMS, fibra óptica, historial de alarmas, evaluación FSB
  y aprobación previa de actualización de firmware.

---

"""


# ─── System prompt — EXACTLY as pinned in the Epic 6 spec ─────────────
# This string is byte-frozen by Release Engineering. Tests assert its
# SHA-256 to surface any accidental edit (a stray translation, a
# whitespace tidy) loud and early.
#
# The MOP template body adopts the operator-mandated Universal 5-Point
# Structure (2026-05-23). The audit gate enforces presence of each
# section; missing any section -> hard_stop.
PROCEDURE_ARCHITECT_SYSTEM_PROMPT = SAFETY_PRIORITY_DIRECTIVE + """# ROL DEL AGENTE
Eres el Procedure Architect, el agente experto en redacción técnica para infraestructura crítica de Data Centers. Tu objetivo es generar documentación operativa con precisión militar, eliminando cualquier ambigüedad. Tu filosofía fundamental es "cero incidentes".

# INSTRUCCIONES GLOBALES
1. Escribe en un tono directivo, claro y secuencial.
2. Todo paso que involucre riesgo eléctrico o mecánico debe invocar obligatoriamente una revisión del Safety Officer.
3. Utiliza la nomenclatura estándar de la industria (UPS, CRAC, ATS, PDU, STS).
4. Aplica estrictamente la plantilla correspondiente según el tipo de solicitud (SOP, MOP, EOP o EMP).

---
# PLANTILLAS CONDICIONALES (Aplica solo la solicitada)

## [TEMPLATE: SOP] - Standard Operating Procedure
**Contexto:** Operaciones de rutina, rondas de inspección, cambios de estado preventivos.
**Estructura Obligatoria:**
1. **Propósito:** (Una línea clara del objetivo).
2. **Frecuencia:** (Ej. Por turno, Semanal, Mensual).
3. **Condiciones Previas:** (Estado esperado del equipo antes de iniciar).
4. **Pasos de Ejecución:** (Acciones exactas en el HMI o físicamente en sala).
5. **Criterios de Éxito:** (Qué parámetros del BMS/EPMS indican que la tarea terminó bien).

## [TEMPLATE: MOP] - Method of Procedure (Generador Universal -- Mission Critical / Zero Incidents)
**Directiva:** Eres un Arquitecto de Procedimientos de Infraestructura Crítica. Prioriza la protección de la vida humana (Arc Flash, LOTO) y la continuidad de la carga IT (Uptime) por encima de todo. Sustituye cada `_TBD_` razonando la disciplina a la que pertenece el equipo.

**Estructura Universal Obligatoria (5 puntos -- TODOS requeridos por el audit gate):**

1. **Alcance y Objetivo:**
   * **Identificador (Tag):** Especifica el tipo de equipo y su nomenclatura estándar (ej. `UPS-A`, `CRAH-02`, `CDU-01`, `VESDA-Z3`).
   * **Estado Final Esperado:** Define exactamente en qué estado físico y lógico debe quedar el equipo al finalizar la maniobra (ej. "Aislado galvánicamente para mantenimiento", "En derivación mecánica sin carga", "Lazo de detección en bypass").

2. **Evaluación de Impacto y Riesgos (Vectores Multi-Disciplina) -- identifica el vector y aplícalo:**
   * **Vector Eléctrico** (UPS, PDU, STS, ATS): categoría de energía incidente (Arc Flash boundary), riesgo de choque, estado del bus redundante A/B.
   * **Vector Mecánico/Térmico** (Chillers, CRAHs, CDUs, Torres): "Tiempo de Inercia" -- minutos que el Data Hall soporta sin el equipo antes de cruzar ASHRAE TC 9.9.
   * **Vector Life Safety / Contra Incendios** (VESDA, Novec/FM-200): riesgo de descarga accidental; panel en modo "Mantenimiento" o aislamiento de solenoides.
   * **Vector Combustible** (Tanques, Bombas): riesgo de derrame; autonomía restante en Day Tanks.
   * **Vector Lógico y Controles** (BMS, DC-EPMS, PLCs): "Pérdida de Visibilidad" -- si reinicia un controlador, ¿el sistema entra en fail-safe?
   * **Impacto Aguas Arriba/Abajo:** enumera exactamente qué tableros, válvulas o servidores están en la ruta crítica.

3. **Prerrequisitos (Gatekeeper Universal y Conciencia del Sistema):**
   * **Herramientas Especializadas:** lista exacta (multímetro calibrado CAT IV, torquímetro, kit anti-derrames, calibrador de lazo).
   * **EPP Específico:** Categoría Arc Flash (cal/cm²) per CSA Z462-24 / NFPA 70E + LOTO + protección facial / respiradores / guantes dieléctricos.
   * **Condiciones Lógicas y Bypass:** confirmación de cero alarmas activas en DC-EPMS o zonas de detección silenciadas.
   * **Operabilidad de Agentes (Health Check):** confirmación estricta de que el Agente Revisor (Checker) y los Agentes de Disciplina (HVAC AI, Electrical AI) necesarios para el monitoreo concurrente están `ONLINE` y reportando telemetría vía **MCP**.
   * **Aprobaciones:** Permiso de trabajo (PTW) + confirmación explícita del NOC (Humano).

4. **Lista de Pasos Secuenciales (Step-by-Step, Cuatro Ojos / Maker-Checker):**
   * **Sintaxis Obligatoria** -- cada paso atómico: `Verbo de acción + Componente Físico + Resultado Esperado + [ ] Técnico ___ [ ] Supervisor ___`.
     * Ejemplo correcto: "Abrir el interruptor Q2 (Bypass Input Breaker) y verificar visualmente la bandera verde de 'Abierto'. `[ ] Técnico ___ [ ] Supervisor ___`"
     * Ejemplo INCORRECTO: "Apagar el bypass."
   * **Regla Vivo-Muerto-Vivo / LOTO:** obligatorio insertar verificación de energía cero o despiche de presión antes de cualquier contacto físico.
   * **Puntos de Espera (`[HOLD POINT]`):** inserta marcadores donde el técnico debe detenerse y confirmar un parámetro en HMI antes de continuar (ej. `[HOLD POINT]` "Verificar sincronismo de fase" / "Confirmar ATD en CDU").

5. **Plan de Reversión (Back-out Plan) -- no existe maniobra sin salida de emergencia:**
   * **Disparadores de Aborto (Triggers):** parámetros exactos que cancelan el MOP (ej. "Si el ATS no conmuta en `< 12 segundos`", "Si la presión de agua helada cae por debajo de `20 PSI`", "Si T_inlet rack > 27 °C por más de 60 s"). Cada disparador con número + unidad.
   * **Secuencia de Restauración:** lista explícita de pasos para devolver el equipo a su estado original. **PROHIBIDA la frase "deshacer los pasos anteriores"** -- enumera cada paso ("Cerrar interruptor X, verificar alarma Y").

## [TEMPLATE: EOP] - Emergency Operating Procedure
**Contexto:** Falla de equipo, caída de redundancia, eventos térmicos o eléctricos activos.
**Estructura Obligatoria:**
1. **Síntomas del Incidente:** (Qué alarmas o condiciones disparan este EOP).
2. **Acción de Contención Inmediata:** (Pasos críticos en los primeros 5 minutos para detener la degradación).
3. **Aislamiento de la Falla:** (Secuencia para separar el equipo afectado del bus crítico).
4. **Matriz de Escalamiento:** (A quién notificar inmediatamente: Management, Proveedor, NOC).

## [TEMPLATE: EMP] - Emergency Management Plan
**Contexto:** Gestión integral de la crisis a nivel de toda la instalación o múltiples sitios.
**Estructura Obligatoria:**
1. **Comando del Incidente:** (Quién lidera el cuarto de guerra o puente de crisis).
2. **Logística y Acceso:** (Gestión de técnicos en sitio y escoltas de seguridad).
3. **Comunicaciones:** (Plantillas de estado para informar a stakeholders y clientes).
4. **Soporte Externo:** (Protocolo de despacho de ingenieros de campo externos).
"""


# ─── Doc-type vocabulary ──────────────────────────────────────────────
DOC_TYPE_SOP = "SOP"
DOC_TYPE_MOP = "MOP"
DOC_TYPE_EOP = "EOP"
DOC_TYPE_EMP = "EMP"

VALID_DOC_TYPES: frozenset[str] = frozenset({
    DOC_TYPE_SOP, DOC_TYPE_MOP, DOC_TYPE_EOP, DOC_TYPE_EMP,
})


# ─── Safety audit — per-template required terms ───────────────────────
# Pattern-match list: each entry is (label, regex) — the label appears
# in audit findings, the regex (case-insensitive) is what we search
# for. A MOP MUST mention LOTO + PPE + the CSA Z462 / NFPA 70E
# electrical-safety standard. A SOP needs an HMI/BMS verification
# signal. An EOP needs contention + isolation language. An EMP needs
# an incident commander reference.
#
# Regex authoring rule: use ``\b...\b`` word boundaries to avoid
# matching inside larger words (e.g. ``mopu`` should NOT match
# ``mop``). Patterns are deliberately broad — the goal is to catch
# omissions, not to grade prose quality.
SAFETY_REQUIRED_TERMS: dict[str, list[tuple[str, str]]] = {
    DOC_TYPE_SOP: [
        ("HMI/BMS verification", r"\b(BMS|HMI|EPMS|setpoint)\b"),
    ],
    DOC_TYPE_MOP: [
        # CSA Z462 / NFPA 70E references the live-electrical safety
        # standard. Either is acceptable; missing both is hard_stop.
        (
            "CSA Z462 / NFPA 70E electrical safety standard",
            r"\b(CSA\s*Z462|NFPA\s*70E)\b",
        ),
        # PPE — personal protective equipment, the load-bearing
        # protective gear callout per the standard above.
        ("PPE (personal protective equipment)", r"\bPPE\b"),
        # LOTO — Lockout/Tagout protocol. The match accepts the
        # abbreviation OR either of the long forms; one is enough.
        (
            "LOTO (Lockout/Tagout)",
            r"\b(LOTO|Lockout\s*/?\s*Tagout|lockout|tagout)\b",
        ),
    ],
    DOC_TYPE_EOP: [
        # Containment action — must mention some contention / stop /
        # contain language. Spanish OR English (the system prompt is
        # bilingual).
        (
            "containment language",
            r"\b(contención|contain|isolation|aisla|stop|halt)\b",
        ),
    ],
    DOC_TYPE_EMP: [
        # Incident command — must reference an incident commander or
        # crisis lead (the spec calls it 'Comando del Incidente').
        (
            "incident command reference",
            r"\b(incident\s*command|comando\s*del\s*incidente|crisis\s*lead)\b",
        ),
    ],
}

AUDIT_VERDICT_APPROVE = "approve"
AUDIT_VERDICT_CAUTION = "caution"
AUDIT_VERDICT_HARD_STOP = "hard_stop"


# ─── Universal 5-Point Structure (operator mandate 2026-05-23) ────────
# Every MOP draft MUST contain ALL 5 sections. The patterns are broad
# on purpose: a draft authored in English, Spanish, or a mix should
# still satisfy them. Missing any section -> hard_stop and the finding
# enumerates exactly which section is absent.
# (S-SAFETY-01)
MOP_UNIVERSAL_SECTIONS: list[tuple[str, str]] = [
    (
        "Alcance y Objetivo (universal section 1)",
        r"\b(Alcance|Objetivo|Prop[oó]sito|Scope|Purpose)\b",
    ),
    (
        "Evaluación de Impacto y Riesgos (universal section 2)",
        r"\b(Impacto|Riesgos?|Identificaci[oó]n\s+de\s+Riesgos|Risk\s+Assessment|Risks?)\b",
    ),
    (
        "Prerrequisitos (universal section 3)",
        r"\b(Prerrequisitos|Requisitos\s+Previos|Prerequisites)\b",
    ),
    (
        "Pasos Secuenciales (universal section 4)",
        r"\b(Pasos|Secuencia|Step[-\s]*by[-\s]*Step|Plan\s+de\s+Ejecuci[oó]n|Sequential\s+Steps?)\b",
    ),
    (
        "Plan de Reversión / Back-out (universal section 5)",
        r"\b(Reversi[oó]n|Back[-\s]?out|Backout|Rollback|Aborto|Abort\s+Criteria)\b",
    ),
]

# Voltage absence verification (de-energized work) OR live-work approach
# limit (energized work) -- AT LEAST ONE required. Both absent ->
# hard_stop. The rule accepts the OR because some MOPs run on energized
# equipment where Vivo-Muerto-Vivo is not applicable (e.g. ATS
# commutation tests rely on the restricted approach limit + PPE Cat 4
# as the salvaguarda primaria).
# (S-SAFETY-01)
MOP_VOLTAGE_VERIFICATION_PATTERNS: list[tuple[str, str]] = [
    (
        "Vivo-Muerto-Vivo / voltage absence (de-energized work)",
        r"Vivo[\s\-]*Muerto[\s\-]*Vivo|ausencia\s+de\s+tensi[oó]n|voltage\s+absence",
    ),
    (
        "Límite de aproximación restringida (live work)",
        r"l[íi]mite\s+de\s+aproximaci[oó]n|restricted\s+approach\s+limit|approach\s+boundary",
    ),
]

# Distribution-layer (PDU / RPP / STS) pre-transfer rule.
# When the operator context or asset_id names distribution gear AND the
# doc is a MOP, the body MUST declare the alarm-history review AND the
# STS / SCR-box state check before authorizing the transfer. Missing
# either -> hard_stop. Source: operator directive 2026-05-23 + Eaton
# SOW R-48 pre-transfer validation.
# (S-DISTRIBUTION-01)
# Uses explicit non-letter lookarounds instead of \b because Python's
# word-boundary treats '_' as a word char -- so \bRPP\b would NOT match
# inside the canonical asset_id 'rpp_a1'. The lookarounds catch the
# token at start/end of string or against any non-letter neighbour.
DISTRIBUTION_CONTEXT_PATTERN = r"(?<![A-Za-z])(PDU|RPP|STS)(?![A-Za-z])"
DISTRIBUTION_REQUIRED_TERMS: list[tuple[str, str]] = [
    (
        "alarm history review (pre-transfer requirement)",
        r"\b(historial\s+de\s+alarmas|alarm\s+history|alarm\s+log)\b",
    ),
    (
        "STS state / caja SCR check (pre-transfer requirement)",
        r"\b(SCR|caja\s+SCR|STS\s+state|estado\s+STS|tiristor|thyristor)\b",
    ),
]

# Eaton SOW R-48 vendor-specific checklist.
# CAUTION severity (NOT hard_stop) because the operating fleet is
# multi-brand; forcing hard_stop on Eaton-only checks would refuse
# legitimate MOPs on non-Eaton equipment. The omission surfaces as
# advisory findings so the operator can re-prompt or acknowledge.
#
# Vendor resolution (since v0.16.1 -- the schema-migration close-out):
#   1. If `draft.asset_id` resolves in the in-memory _vendor_cache,
#      the deterministic vendor wins (no fallback even if cache says
#      "vertiv" -- we trust the registry).
#   2. If asset_id is missing OR not in the cache OR has vendor=None,
#      fall back to string-match on context + asset_id.
# The cache is populated at boot via `set_vendor_cache()` -- see
# `backend/main.py` lifespan. Sync dict lookup keeps the audit gate
# deterministic and microsecond-fast (no I/O in the verdict path).
# (S-VENDOR-EATON-01)
EATON_CONTEXT_PATTERN = r"\beaton\b"
EATON_REQUIRED_TERMS: list[tuple[str, str]] = [
    (
        "BCMS card check (Eaton SOW R-48)",
        r"\b(BCMS|monitoring\s+card)\b",
    ),
    (
        "fiber optic / FSB / firmware verification (Eaton SOW R-48)",
        r"\b(fibra\s+[óo]ptica|fiber\s+optic|FSB|firmware)\b",
    ),
    (
        "alarm history review (Eaton SOW R-48)",
        r"\b(historial\s+de\s+alarmas|alarm\s+history|alarm\s+log)\b",
    ),
]


# ─── Vendor cache (deterministic Eaton lookup -- v0.16.1) ─────────────
# Module-level dict mapping `asset_id.lower() -> vendor.lower() | None`.
# Populated at boot via `set_vendor_cache()` from `cmms_repository.
# list_assets_async()` results. Read synchronously by the audit gate
# (no I/O in the verdict path -- microsecond latency preserved).
#
# Refresh policy: the cache is loaded ONCE at backend boot. Vendor
# changes (asset retrofit, rename) require a backend restart to
# propagate -- acceptable because vendor changes are operationally
# rare. A `/api/admin/refresh-vendor-cache` endpoint can be added if
# the refresh cadence becomes a pain point.
_vendor_cache: dict[str, str | None] = {}


def set_vendor_cache(cache: dict[str, str | None] | None) -> None:
    """Wire the deterministic `asset_id -> vendor` lookup. Keys MUST
    be lowercased asset_ids; values are lowercased vendor strings or
    None. Called once from `backend/main.py` lifespan after the CMMS
    repository has seeded its assets. Pass an empty dict to clear
    (used by tests + by the absence-of-CMMS path)."""
    global _vendor_cache
    _vendor_cache = dict(cache) if cache else {}


def _reset_vendor_cache_for_test() -> None:
    """Test helper -- isolates each test from prior cache state."""
    global _vendor_cache
    _vendor_cache = {}


# ─── Commit 11 -- richer-prompt audit rules (operator mandate 2026-05-24) ─
# All CAUTION-level by default; the seeded bodies surface as caution
# until Commit 12 brings them up to the richer template. The
# parameterized-abort rule becomes HARD_STOP in Commit 12 -- TODO marker
# below for that promotion.
#
# (S-VECTOR-01 / S-MCP-HEALTH-01 / S-HOLD-POINT-01)

# §1 sub-field: Identificador (Tag) -- the equipment's canonical name.
MOP_TAG_PATTERN = (
    "Identificador / Tag (universal section 1 sub-field)",
    r"\b(Identificador|Tag|Equipment\s+ID|Asset\s+ID)\b",
)

# §1 sub-field: Estado Final Esperado -- exact end-state.
MOP_FINAL_STATE_PATTERN = (
    "Estado Final Esperado (universal section 1 sub-field)",
    r"(Estado\s+Final|Final\s+State|End\s+State|Estado\s+Esperado)",
)

# §2 vector classification -- at least ONE of the 6 vectors must
# appear explicitly. Allows operator to omit irrelevant vectors but
# requires at least one explicit categorization.
MOP_VECTOR_PATTERNS: list[tuple[str, str]] = [
    (
        "Vector Eléctrico classification",
        r"\bVector\s+El[ée]ctrico\b",
    ),
    (
        "Vector Mecánico/Térmico classification",
        r"\bVector\s+Mec[áa]nico(?:\s*/\s*T[ée]rmico)?\b|\bVector\s+T[ée]rmico\b",
    ),
    (
        "Vector Life Safety classification",
        r"\bVector\s+Life\s+Safety\b|\bVector\s+Contra\s+Incendios\b",
    ),
    (
        "Vector Combustible classification",
        r"\bVector\s+Combustible\b",
    ),
    (
        "Vector Lógico/Controles classification",
        r"\bVector\s+L[óo]gico\b|\bVector\s+Controles\b",
    ),
    (
        "Vector Aguas Arriba/Abajo (impact chain)",
        r"(Aguas\s+Arriba|Aguas\s+Abajo|Impacto\s+Aguas)",
    ),
]

# §3 Agentes Health Check via MCP -- the operator-mandated runtime
# precondition. String-match only (no network ping per operator
# calibration Q3 = option (i)).
MOP_MCP_HEALTH_PATTERNS: list[tuple[str, str]] = [
    (
        "MCP / Agentes ONLINE health check (gatekeeper)",
        r"\bMCP\b|\b(Health\s+Check|Agente\s+Revisor|Checker\s+ONLINE|Discipline\s+AI|HVAC\s+AI|Electrical\s+AI)\b",
    ),
]

# §4 HOLD POINT markers -- explicit checkpoint convention. The pattern
# matches both the bracketed marker and the operator-friendly synonyms.
MOP_HOLD_POINT_PATTERN = (
    "[HOLD POINT] markers in step sequence",
    r"\[HOLD\s*POINT\]|HOLD\s+POINT|Hold\s+Point",
)

# §5 parameterized abort triggers -- at least one numeric+unit
# threshold must appear somewhere in the back-out section. Patterns
# accept common units across electrical, thermal, hydraulic, and
# time dimensions. **PROMOTED to HARD_STOP in Commit 12** (operator
# mandate 2026-05-24): all 23 seed bodies now carry parameterized
# triggers, so any new draft missing them indicates a safety-critical
# omission that must block signing.
MOP_PARAMETERIZED_ABORT_PATTERN = (
    "Parameterized abort trigger (numeric + unit in §5)",
    # Number (int or decimal) followed by recognized unit token.
    # Units cover s/seg/min/h, °C/°F/K, PSI/bar/kPa, %, V/Hz/Hz/A/W/kW,
    # ppm, CFU, MΩ/Ω, GPM/LPM, cal/cm². Word boundary or non-word
    # neighbour to avoid matching inside identifiers like 'foo10bar'.
    (
        r"(?:[<>≤≥]\s*)?\d+(?:[\.,]\d+)?\s*"
        r"(?:s|sec|seg|segundos?|min|minutos?|h|hours?|horas?|"
        r"°\s*C|°\s*F|K|"
        r"PSI|bar|kPa|MPa|"
        r"%|"
        r"V|Hz|A|W|kW|MW|"
        r"ppm|CFU|"
        r"M[ΩO]|m[ΩO]|"
        r"GPM|LPM|cal/cm²|cal/cm2)"
        r"(?![A-Za-z0-9])"
    ),
)


# ─── Data classes ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class ProcedureDraft:
    """One Procedure Architect output. Frozen so consumers can pass it
    through the audit + sign pipeline without defensive copying.

    ``metadata`` (Epic 6 industry-notes follow-up) carries live
    operating data the operator pulled in at request time — typically
    ``{pue, load_kw, criticality, ...}`` — surfaced into the hermetic
    prompt so the LLM author grounds the document in current state
    rather than an averaged baseline. Empty dict when absent; the
    field is part of the persisted draft so ledger entries can later
    audit which telemetry snapshot informed the document.
    """

    draft_id: str
    doc_type: str
    context: str
    content: str               # markdown body produced by the agent
    asset_id: str | None
    generated_at: float
    llm_present: bool          # True iff a real LLM client was wired
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _format_metadata_block(metadata: dict[str, Any] | None) -> str:
    """Render the metadata dict as a labelled block for the hermetic
    prompt. Returns an empty string when no metadata is supplied so
    the prompt stays clean for callers that don't enrich.

    Values are stringified defensively — operator-supplied metadata
    can be anything (numbers, nested dicts, lists). The function
    deliberately does NOT pretty-print nested structures because the
    LLM gets confused by indented JSON inside a markdown prompt;
    instead, nested values flatten to a compact str(value) on a
    single line per key.
    """
    if not metadata or not isinstance(metadata, dict):
        return ""
    lines = ["LIVE OPERATING METADATA (supplied by the operator at request time):"]
    for k in sorted(metadata.keys()):
        v = metadata[k]
        # One line per key; nested structures flattened to str().
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


@dataclass(frozen=True)
class SafetyAuditResult:
    """Outcome of :func:`audit_procedure_safety`. The Safety Officer's
    verdict on a draft. ``hard_stop`` means the operator MUST NOT see
    the draft as approved — the HMI surfaces it as a refusal."""

    doc_type: str
    verdict: str               # approve / caution / hard_stop
    findings: list[str] = field(default_factory=list)
    required_terms_present: dict[str, bool] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        return self.verdict == AUDIT_VERDICT_HARD_STOP

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─── Deterministic skeleton (fallback when no LLM) ────────────────────
# Used when ``llm_client`` is None — the operator still sees the
# template scaffolding. The audit will (correctly) emit hard_stop on a
# MOP skeleton because the empty scaffold does not mention LOTO/PPE/
# CSA Z462 — that's the right behaviour: an empty MOP is not safe to
# sign.
_DETERMINISTIC_SKELETONS: dict[str, str] = {
    DOC_TYPE_SOP: (
        "# SOP — Standard Operating Procedure\n\n"
        "**Context:** {context}\n\n"
        "## 1. Propósito\n_TBD_\n\n"
        "## 2. Frecuencia\n_TBD_\n\n"
        "## 3. Condiciones Previas\n_TBD_\n\n"
        "## 4. Pasos de Ejecución\n_TBD_\n\n"
        "## 5. Criterios de Éxito\n_TBD_ (BMS / HMI verification)\n"
    ),
    DOC_TYPE_MOP: (
        "# MOP — Method of Procedure\n\n"
        "**Context:** {context}\n\n"
        "## 1. Alcance y Objetivo\n"
        "* **Identificador (Tag):** _TBD_\n"
        "* **Estado Final Esperado:** _TBD_\n\n"
        "## 2. Evaluación de Impacto y Riesgos (vectores)\n"
        "* Vector (Eléctrico / Mecánico-Térmico / Life Safety / "
        "Combustible / Lógico): _TBD_\n"
        "* Impacto Aguas Arriba/Abajo: _TBD_\n\n"
        "## 3. Prerrequisitos\n"
        "* Herramientas + EPP + PTW: _TBD_\n"
        "* Agentes Health Check (Checker + Discipline AI ONLINE via "
        "MCP): _TBD_\n\n"
        "## 4. Lista de Pasos Secuenciales (Step-by-Step)\n"
        "1. _TBD verbo + componente + resultado_ "
        "`[ ] Técnico ___ [ ] Supervisor ___`\n"
        "2. `[HOLD POINT]` _TBD verificar parámetro en HMI_\n\n"
        "## 5. Plan de Reversión (Back-out Plan)\n"
        "* Disparadores de Aborto (numéricos + unidad): _TBD_\n"
        "* Secuencia de Restauración (explícita, NO 'deshacer los "
        "pasos anteriores'): _TBD_\n"
    ),
    DOC_TYPE_EOP: (
        "# EOP — Emergency Operating Procedure\n\n"
        "**Context:** {context}\n\n"
        "## 1. Síntomas del Incidente\n_TBD_\n\n"
        "## 2. Acción de Contención Inmediata\n_TBD_\n\n"
        "## 3. Aislamiento de la Falla\n_TBD_\n\n"
        "## 4. Matriz de Escalamiento\n_TBD_\n"
    ),
    DOC_TYPE_EMP: (
        "# EMP — Emergency Management Plan\n\n"
        "**Context:** {context}\n\n"
        "## 1. Comando del Incidente\n_TBD_\n\n"
        "## 2. Logística y Acceso\n_TBD_\n\n"
        "## 3. Comunicaciones\n_TBD_\n\n"
        "## 4. Soporte Externo\n_TBD_\n"
    ),
}


def _deterministic_skeleton(doc_type: str, context: str) -> str:
    """Return the template scaffold for ``doc_type``. Used when no
    LLM client is wired — the operator sees the structure with all
    sections marked ``_TBD_`` so the audit gate still meaningfully
    classifies the draft (MOP skeleton -> hard_stop)."""
    tpl = _DETERMINISTIC_SKELETONS.get(doc_type)
    if tpl is None:
        return ""
    # Escape stray braces in operator context so .format() doesn't
    # raise — context is free-form text.
    safe_ctx = context.replace("{", "{{").replace("}", "}}")
    return tpl.format(context=safe_ctx)


# ─── The Agent ────────────────────────────────────────────────────────
class ProcedureArchitectAgent:
    """LLM-driven document authoring with deterministic skeleton fallback.

    Wiring:
      * ``llm_client`` — duck-typed Gemma client (``await client
        .complete_gemma(prompt, max_tokens=...)`` is the contract).
        When ``None`` the agent returns the deterministic skeleton.
      * ``model_router`` — optional :class:`backend.agent_harness
        .ModelRouter`. When wired, the routing decision is stamped
        into the draft metadata via the ``model_id`` field of the
        emitted log line; the dispatch itself stays whatever the
        ``llm_client`` knows about. Pure observability.
    """

    name = "Procedure Architect"
    SYSTEM_PROMPT = PROCEDURE_ARCHITECT_SYSTEM_PROMPT

    def __init__(
        self,
        llm_client: Any | None = None,
        model_router: Any | None = None,
        max_tokens: int = 800,
        checkpoint_store: CheckpointStore | None = None,
    ):
        self._llm_client = llm_client
        self._model_router = model_router
        self._max_tokens = int(max_tokens)
        # H13 Apply Continuity. When None, generate() works exactly as
        # before (backwards-compatible). When wired, pre/post-LLM
        # checkpoints are appended so a crashed process can resume.
        self._checkpoint_store = checkpoint_store

    # ─── H13 Apply Continuity helpers ──────────────────────────────────
    def _checkpoint(
        self,
        draft_id: str,
        phase: str,
        payload: dict[str, Any],
    ) -> None:
        """Persist a checkpoint when a store is wired. Best-effort: a
        store I/O failure must NOT propagate into the agent's primary
        contract (a checkpoint is recovery instrumentation, not the
        load-bearing data path)."""
        if self._checkpoint_store is None:
            return
        try:
            self._checkpoint_store.record(
                draft_id=draft_id, phase=phase, payload=payload,
            )
        except Exception as exc:                             # pragma: no cover
            log.warning(
                "[procedure_architect] checkpoint %s for draft %s failed: %s",
                phase, draft_id, exc,
            )

    async def generate(
        self,
        doc_type: str,
        context: str,
        asset_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProcedureDraft:
        """Build a hermetic prompt + dispatch to the LLM (or return a
        deterministic skeleton). Always succeeds — an LLM failure
        falls back to the skeleton rather than raising.

        ``metadata`` is optional. When supplied (typically by the
        HMI from a /api/telemetry snapshot) it is rendered as a
        LIVE OPERATING METADATA block inside the hermetic prompt so
        the LLM author has current PUE / load / criticality numbers
        instead of guessing from a static baseline. The dict is also
        persisted on the returned :class:`ProcedureDraft` so the
        ledger entry that signs the draft can audit which telemetry
        snapshot informed the document.
        """
        require_artifact("doc_type", doc_type)
        require_artifact("context", context)
        if doc_type not in VALID_DOC_TYPES:
            raise ArtifactDependencyError(
                f"doc_type must be one of {sorted(VALID_DOC_TYPES)}, "
                f"got {doc_type!r}"
            )
        if metadata is not None and not isinstance(metadata, dict):
            raise ArtifactDependencyError(
                f"metadata must be dict or None, got {type(metadata).__name__}"
            )
        normalised_metadata = dict(metadata) if metadata else {}

        draft_id = str(uuid.uuid4())
        if self._llm_client is None or not hasattr(self._llm_client, "complete_gemma"):
            # Path A — no LLM wired. There is no expensive call to
            # guard, so only post_llm is meaningful (it captures the
            # final reconstructible state).
            generated_at = time.time()
            content = _deterministic_skeleton(doc_type, context)
            self._checkpoint(
                draft_id, PHASE_POST_LLM,
                {
                    "doc_type": doc_type,
                    "context": context,
                    "asset_id": asset_id,
                    "metadata": normalised_metadata,
                    "content": content,
                    "llm_present": False,
                    "generated_at": generated_at,
                },
            )
            return ProcedureDraft(
                draft_id=draft_id,
                doc_type=doc_type,
                context=context,
                content=content,
                asset_id=asset_id,
                generated_at=generated_at,
                llm_present=False,
                metadata=normalised_metadata,
            )

        # Path B — LLM wired. Emit pre_llm BEFORE the (potentially
        # crash-prone) dispatch so a hard interrupt leaves a recovery
        # anchor on disk.
        metadata_block = _format_metadata_block(normalised_metadata)
        body = (
            f"{self.SYSTEM_PROMPT}\n"
            f"---\n"
            f"# OPERATOR REQUEST\n"
            f"DOCUMENT TYPE: {doc_type}\n"
            f"CONTEXT: {context}\n"
            f"ASSET ID (when known): {asset_id or 'n/a'}\n"
            + (f"\n{metadata_block}\n" if metadata_block else "")
            + f"\n"
            f"Generate the {doc_type} document strictly using the "
            f"[TEMPLATE: {doc_type}] structure above. Omit the other "
            f"templates. Output markdown. Begin now."
        )
        prompt = hermetic_prompt(
            self.name, body,
            deterministic_decision=None,   # the agent is authoring, not voting
            decision_authority=None,
        )

        # H13 pre_llm checkpoint — carries everything needed to
        # re-dispatch the LLM on resume.
        self._checkpoint(
            draft_id, PHASE_PRE_LLM,
            {
                "doc_type": doc_type,
                "context": context,
                "asset_id": asset_id,
                "metadata": normalised_metadata,
                "prompt": prompt,
                "max_tokens": self._max_tokens,
            },
        )

        # Existing contract preserved: ``llm_present=True`` means "an
        # LLM client was wired AND dispatch was attempted" -- regardless
        # of whether the call succeeded or fell back to the skeleton.
        try:
            text = await self._llm_client.complete_gemma(
                prompt, max_tokens=self._max_tokens,
            )
        except Exception as exc:
            log.warning(
                "[procedure_architect] LLM dispatch failed (%s) — "
                "falling back to deterministic skeleton", exc,
            )
            text = _deterministic_skeleton(doc_type, context)

        text = (text or "").strip()
        if not text or text.startswith(("[Gemma error", "[Gemma stream error")):
            text = _deterministic_skeleton(doc_type, context)

        llm_present = True
        generated_at = time.time()
        # H13 post_llm checkpoint — carries the full reconstructible
        # draft so a resume returns a completed object with NO new LLM
        # dispatch (idempotency property).
        self._checkpoint(
            draft_id, PHASE_POST_LLM,
            {
                "doc_type": doc_type,
                "context": context,
                "asset_id": asset_id,
                "metadata": normalised_metadata,
                "content": text,
                "llm_present": llm_present,
                "generated_at": generated_at,
            },
        )

        return ProcedureDraft(
            draft_id=draft_id,
            doc_type=doc_type,
            context=context,
            content=text,
            asset_id=asset_id,
            generated_at=generated_at,
            llm_present=llm_present,
            metadata=normalised_metadata,
        )

    # ─── H13 — Resume from checkpoint ─────────────────────────────────
    async def resume_from_checkpoint(
        self, draft_id: str,
    ) -> ProcedureDraft | None:
        """Recover a draft from its latest checkpoint.

        Three paths:

        * **No checkpoint** — returns ``None``. The draft was never
          started, or its checkpoints were purged.
        * **Latest = post_llm** — reconstruct the
          :class:`ProcedureDraft` from the payload and return it
          *without* re-dispatching the LLM. This is the idempotency
          property — re-resuming a completed draft costs zero LLM tokens.
        * **Latest = pre_llm** — the LLM call was in flight when the
          process crashed. Re-dispatch using the persisted prompt; then
          write a post_llm checkpoint so a subsequent crash short-
          circuits via the path above.

        Returns ``None`` only when no checkpoint exists; in every other
        case a fully-formed :class:`ProcedureDraft` is returned (the
        deterministic skeleton fallback fires if the LLM is now absent
        or fails again).
        """
        require_artifact("draft_id", draft_id)
        if self._checkpoint_store is None:
            log.warning(
                "[procedure_architect] resume_from_checkpoint(%s) called "
                "without a checkpoint_store wired -- nothing to resume from",
                draft_id,
            )
            return None

        latest = self._checkpoint_store.latest_for_draft(draft_id)
        if latest is None:
            return None

        payload = latest.payload or {}
        doc_type = payload.get("doc_type") or ""
        context = payload.get("context") or ""
        asset_id = payload.get("asset_id")
        metadata = dict(payload.get("metadata") or {})

        if latest.phase == PHASE_POST_LLM:
            # Idempotent path — work was already done. Rebuild + return.
            return ProcedureDraft(
                draft_id=draft_id,
                doc_type=doc_type,
                context=context,
                content=str(payload.get("content", "")),
                asset_id=asset_id,
                generated_at=float(payload.get("generated_at") or time.time()),
                llm_present=bool(payload.get("llm_present", False)),
                metadata=metadata,
            )

        if latest.phase == PHASE_PRE_LLM:
            # Re-dispatch path — the LLM was mid-flight at crash time.
            prompt = str(payload.get("prompt") or "")
            max_tokens = int(payload.get("max_tokens") or self._max_tokens)

            # llm_present mirrors generate()'s contract: True iff an
            # LLM client is wired AND dispatch was attempted. The
            # skeleton fallback does NOT flip the flag.
            llm_present = self._llm_client is not None and hasattr(
                self._llm_client, "complete_gemma",
            )
            text = ""
            if llm_present:
                try:
                    text = await self._llm_client.complete_gemma(
                        prompt, max_tokens=max_tokens,
                    )
                except Exception as exc:
                    log.warning(
                        "[procedure_architect] resume LLM dispatch failed "
                        "(%s) -- falling back to skeleton", exc,
                    )
                    text = ""

            text = (text or "").strip()
            if not text or text.startswith(("[Gemma error", "[Gemma stream error")):
                text = _deterministic_skeleton(doc_type, context)

            generated_at = time.time()
            # Anchor the recovered work with a post_llm checkpoint so a
            # subsequent crash returns to the idempotent path.
            self._checkpoint(
                draft_id, PHASE_POST_LLM,
                {
                    "doc_type": doc_type,
                    "context": context,
                    "asset_id": asset_id,
                    "metadata": metadata,
                    "content": text,
                    "llm_present": llm_present,
                    "generated_at": generated_at,
                },
            )
            return ProcedureDraft(
                draft_id=draft_id,
                doc_type=doc_type,
                context=context,
                content=text,
                asset_id=asset_id,
                generated_at=generated_at,
                llm_present=llm_present,
                metadata=metadata,
            )

        # Unknown phase — defensive return None rather than reconstruct
        # something the caller cannot trust.
        log.warning(
            "[procedure_architect] resume_from_checkpoint(%s) found "
            "unknown phase %r -- refusing to reconstruct",
            draft_id, latest.phase,
        )
        return None


# ─── Safety Officer audit (deterministic — S-DET-01) ──────────────────
def audit_procedure_safety(draft: ProcedureDraft) -> SafetyAuditResult:
    """Pattern-scan a :class:`ProcedureDraft` for the per-template
    required terms in :data:`SAFETY_REQUIRED_TERMS` plus, for MOPs, the
    extended safety contract (operator mandate 2026-05-23).

    Phase 1 — per-template required terms (legacy):
      * MOP — missing ANY of {CSA Z462/NFPA 70E, PPE, LOTO} -> hard_stop.
      * SOP — missing the BMS/HMI verification term -> caution.
      * EOP — missing containment language -> caution.
      * EMP — missing incident-command reference -> caution.

    Phase 2 — MOP-only extended contract (Epic 6 hardening):
      * **Universal 5-Point Structure** (S-SAFETY-01) — Alcance,
        Impacto/Riesgos, Prerrequisitos, Pasos Secuenciales, Plan de
        Reversión. Missing ANY -> hard_stop.
      * **Voltage verification OR approach limit** (S-SAFETY-01) -- at
        least one of Vivo-Muerto-Vivo (de-energized) or
        límite de aproximación restringida (live). Both absent ->
        hard_stop.
      * **Distribution-layer pre-transfer** (S-DISTRIBUTION-01) -- when
        the context or asset_id names PDU/RPP/STS, the body must mention
        alarm history review AND STS state / caja SCR check. Missing ->
        hard_stop.
      * **Eaton SOW R-48** (S-VENDOR-EATON-01) -- when the context or
        asset_id mentions "eaton", surface BCMS / fiber / FSB / firmware
        / alarm-history omissions as CAUTION (NOT hard_stop) so the
        operator can re-prompt or acknowledge for multi-brand fleets.
      * **Richer-template structural** (S-VECTOR-01 / S-MCP-HEALTH-01 /
        S-HOLD-POINT-01) -- Identificador (Tag), Estado Final Esperado,
        at least one Vector classification, MCP Health Check, [HOLD POINT]
        markers, parameterized abort triggers (numeric+unit). All
        CAUTION today; the parameterized-abort rule is promoted to
        HARD_STOP in Commit 12 once the 23 seed bodies satisfy it.

    Pure-Python. No LLM call. S-DET-01 / ADR-006 — the verdict gate is
    deterministic by construction.
    """
    require_artifact(
        "draft", draft,
        predicate=lambda d: isinstance(d, ProcedureDraft),
        message="audit_procedure_safety requires a ProcedureDraft instance",
    )

    doc_type = draft.doc_type
    text = draft.content or ""
    context = (draft.context or "").lower()
    asset_id = (draft.asset_id or "").lower()
    required = SAFETY_REQUIRED_TERMS.get(doc_type, [])
    present: dict[str, bool] = {}
    findings: list[str] = []

    # ── Phase 1 — per-template required terms (legacy contract) ──
    base_missing: list[str] = []
    for label, pat in required:
        match = re.search(pat, text, flags=re.IGNORECASE)
        present[label] = bool(match)
        if not match:
            base_missing.append(label)
            findings.append(f"missing required {doc_type} term: {label}")

    # ── Phase 2 — MOP-only extended contract (Epic 6 hardening) ──
    extra_hard_stops: list[str] = []
    eaton_cautions: list[str] = []
    richer_cautions: list[str] = []

    if doc_type == DOC_TYPE_MOP:
        # Rule 2.1 — Universal 5-Point Structure (S-SAFETY-01)
        for label, pat in MOP_UNIVERSAL_SECTIONS:
            match = re.search(pat, text, flags=re.IGNORECASE)
            present[label] = bool(match)
            if not match:
                findings.append(f"missing universal MOP section: {label}")
                extra_hard_stops.append(label)

        # Rule 2.2 — voltage verification OR approach limit (S-SAFETY-01)
        voltage_or_approach_present = False
        for label, pat in MOP_VOLTAGE_VERIFICATION_PATTERNS:
            match = re.search(pat, text, flags=re.IGNORECASE)
            present[label] = bool(match)
            if match:
                voltage_or_approach_present = True
        if not voltage_or_approach_present:
            findings.append(
                "missing safety verification: include EITHER "
                "'Vivo-Muerto-Vivo / ausencia de tensión' (de-energized "
                "work) OR 'límite de aproximación restringida' (live "
                "work)"
            )
            extra_hard_stops.append("voltage verification or approach limit")

        # Rule 2.3 — PDU / RPP / STS pre-transfer (S-DISTRIBUTION-01)
        distribution_hit = bool(
            re.search(DISTRIBUTION_CONTEXT_PATTERN, context, flags=re.IGNORECASE)
            or re.search(DISTRIBUTION_CONTEXT_PATTERN, asset_id, flags=re.IGNORECASE),
        )
        if distribution_hit:
            for label, pat in DISTRIBUTION_REQUIRED_TERMS:
                match = re.search(pat, text, flags=re.IGNORECASE)
                present[label] = bool(match)
                if not match:
                    findings.append(
                        f"distribution-layer (PDU/RPP/STS) maneuver "
                        f"requires: {label}"
                    )
                    extra_hard_stops.append(label)

        # Rule 2.4 — Eaton SOW R-48 (S-VENDOR-EATON-01) -- CAUTION only.
        # Vendor resolution order:
        #   (a) Deterministic: asset_id present + vendor known via
        #       the in-memory cache. If vendor is 'eaton' -> hit;
        #       if vendor is something else -> NOT a hit (and we do
        #       NOT fall through to string-match, because the
        #       registry is authoritative).
        #   (b) Fallback: asset_id missing OR cache empty OR cache
        #       returns None -> string-match the operator context.
        cache_vendor = _vendor_cache.get(asset_id) if asset_id else None
        vendor_source = None
        if asset_id and asset_id in _vendor_cache:
            # Deterministic answer wins.
            eaton_hit = (cache_vendor == "eaton")
            vendor_source = (
                f"deterministic lookup (asset_id={asset_id}, "
                f"vendor={cache_vendor or 'unknown'})"
            )
        else:
            # Fallback: string-match context + asset_id.
            eaton_hit = bool(
                re.search(EATON_CONTEXT_PATTERN, context, flags=re.IGNORECASE)
                or re.search(EATON_CONTEXT_PATTERN, asset_id, flags=re.IGNORECASE),
            )
            if eaton_hit:
                vendor_source = "string-match fallback (cache miss)"
        if eaton_hit:
            for label, pat in EATON_REQUIRED_TERMS:
                match = re.search(pat, text, flags=re.IGNORECASE)
                present[label] = bool(match)
                if not match:
                    findings.append(
                        f"Eaton SOW R-48 advisory: missing {label} "
                        f"[{vendor_source}]"
                    )
                    eaton_cautions.append(label)

        # ── Commit 11 -- Richer-prompt structural rules (CAUTION) ──
        # All six rules below surface as CAUTION (not HARD_STOP). The
        # existing 23 seed bodies may not satisfy them; Commit 12
        # brings them up to spec. The parameterized-abort rule
        # specifically is promoted to HARD_STOP in Commit 12.
        # (S-VECTOR-01 / S-MCP-HEALTH-01 / S-HOLD-POINT-01)
        # `richer_cautions` is initialized above with the other
        # accumulators -- safe to populate here.

        # Rule 2.5 -- §1 Identificador / Tag sub-field.
        tag_label, tag_pat = MOP_TAG_PATTERN
        tag_match = re.search(tag_pat, text, flags=re.IGNORECASE)
        present[tag_label] = bool(tag_match)
        if not tag_match:
            findings.append(f"richer-template advisory: missing {tag_label}")
            richer_cautions.append(tag_label)

        # Rule 2.6 -- §1 Estado Final Esperado sub-field.
        final_label, final_pat = MOP_FINAL_STATE_PATTERN
        final_match = re.search(final_pat, text, flags=re.IGNORECASE)
        present[final_label] = bool(final_match)
        if not final_match:
            findings.append(f"richer-template advisory: missing {final_label}")
            richer_cautions.append(final_label)

        # Rule 2.7 -- §2 at least ONE vector classification.
        vector_present = False
        for label, pat in MOP_VECTOR_PATTERNS:
            m = re.search(pat, text, flags=re.IGNORECASE)
            present[label] = bool(m)
            if m:
                vector_present = True
        if not vector_present:
            findings.append(
                "richer-template advisory: §2 must explicitly name "
                "at least ONE vector (Eléctrico / Mecánico / Life "
                "Safety / Combustible / Lógico / Aguas Arriba-Abajo)"
            )
            richer_cautions.append("vector classification")

        # Rule 2.8 -- §3 MCP / Agentes Health Check (string-match).
        mcp_present = False
        for label, pat in MOP_MCP_HEALTH_PATTERNS:
            m = re.search(pat, text, flags=re.IGNORECASE)
            present[label] = bool(m)
            if m:
                mcp_present = True
        if not mcp_present:
            findings.append(
                "richer-template advisory: §3 must mention MCP / "
                "Agentes ONLINE health check (operator-supplied "
                "system-prompt gatekeeper)"
            )
            richer_cautions.append("MCP health check")

        # Rule 2.8b -- v0.16.1 MCP probe option (ii). When the env
        # flag DC_EPMS_MCP_PROBE is enabled, an async background
        # task in backend.mcp_health polls a configured URL (default
        # LM Studio's /v1/models). Audit reads the cached state
        # sync. If probe disabled (state=None), behavior is identical
        # to v0.16.0 -- string-match only. If probe is UP, no
        # additional finding. If probe is DOWN, emit a caution
        # annotating the probe reason so operator knows the
        # Discipline AI agents are unreachable.
        try:
            from backend.mcp_health import get_mcp_health
            mcp_state, mcp_reason, _last_ts = get_mcp_health()
            present["MCP probe state"] = mcp_state if mcp_state is not None else "disabled"
            if mcp_state is False:
                findings.append(
                    f"MCP health probe FAILED [{mcp_reason}] -- "
                    "Discipline AI agents may not be reachable; "
                    "operator should verify before signing"
                )
                richer_cautions.append("MCP probe failed")
        except Exception:
            # Probe module unavailable / import error -- silently
            # degrade to string-match-only behavior. This keeps the
            # audit gate robust against partial deployments.
            pass

        # Rule 2.9 -- §4 [HOLD POINT] markers.
        hold_label, hold_pat = MOP_HOLD_POINT_PATTERN
        hold_match = re.search(hold_pat, text, flags=re.IGNORECASE)
        present[hold_label] = bool(hold_match)
        if not hold_match:
            findings.append(f"richer-template advisory: missing {hold_label}")
            richer_cautions.append(hold_label)

        # Rule 2.10 -- §5 at least ONE parameterized abort trigger
        # (numeric + unit). Promoted to HARD_STOP in Commit 12 --
        # vague abort criteria are safety-critical.
        param_label, param_pat = MOP_PARAMETERIZED_ABORT_PATTERN
        param_match = re.search(param_pat, text, flags=re.IGNORECASE)
        present[param_label] = bool(param_match)
        if not param_match:
            findings.append(
                "richer-template REFUSAL: §5 must include at least "
                "one parameterized abort trigger (number + unit, e.g. "
                "'< 12 segundos', '> 27 °C', '< 20 PSI'). Vague "
                "abort criteria are safety-critical and block signing."
            )
            extra_hard_stops.append(param_label)

    # ── Phase 3 — verdict resolution ──
    if doc_type == DOC_TYPE_MOP:
        if base_missing or extra_hard_stops:
            verdict = AUDIT_VERDICT_HARD_STOP
            findings.append(
                "MOP refused: a Method of Procedure must satisfy the "
                "full safety contract (universal sections + voltage "
                "verification + LOTO/PPE/CSA Z462 + distribution "
                "pre-transfer checks when applicable) before signing "
                "(Epic 6 hardening, operator mandate 2026-05-23)."
            )
        elif eaton_cautions or richer_cautions:
            # Advisory: either vendor-specific (Eaton multi-brand
            # fleet) or richer-template structural rules (Commit 11
            # operator-supplied prompt). The seal still proceeds; the
            # operator sees the findings to re-prompt or acknowledge.
            verdict = AUDIT_VERDICT_CAUTION
        else:
            verdict = AUDIT_VERDICT_APPROVE
    elif base_missing:
        verdict = AUDIT_VERDICT_CAUTION
    else:
        verdict = AUDIT_VERDICT_APPROVE

    return SafetyAuditResult(
        doc_type=doc_type,
        verdict=verdict,
        findings=findings,
        required_terms_present=present,
    )
