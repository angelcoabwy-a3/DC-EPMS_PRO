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

## [TEMPLATE: MOP] - Method of Procedure
**Contexto:** Mantenimiento programado, maniobras de transferencia de carga, intervenciones físicas.
**Estructura Universal Obligatoria (5 puntos -- TODOS requeridos por el audit gate):**
1. **Alcance y Objetivo:** Definición exacta del equipo, ubicación (Site / Data Hall) y propósito de la intervención.
2. **Evaluación de Impacto y Riesgos:** Posibles interrupciones a la carga IT, nivel de energía incidente (cal/cm²), dependencias aguas arriba/abajo, nivel de PPE requerido según CSA Z462-24.
3. **Prerrequisitos:** Protocolo Lockout/Tagout (LOTO) cuando aplique, herramientas aisladas, Permisos de Trabajo (PTW), categoría de PPE.
4. **Lista de Pasos Secuenciales (Step-by-Step):** Instrucciones no ambiguas con casillas de verificación Cuatro Ojos (técnico + supervisor). Cuando la maniobra desenergiza el equipo, incluir verificación Vivo-Muerto-Vivo antes de manipulación física; cuando es trabajo en vivo, declarar el límite de aproximación restringida + PPE Cat 4.
5. **Plan de Reversión (Back-out Plan):** CRÍTICO -- cómo abortar y volver al estado seguro si la secuencia falla; criterios de aborto explícitos.

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
# TODO(asset-manufacturer-migration): today the agent string-matches the
# operator-supplied context (and asset_id) for "eaton". Once
# backend/cmms_models.py:Asset gains a `manufacturer` field (next sprint),
# switch this to a deterministic asset lookup. Until then operators are
# responsible for naming the vendor in the context free-text. Tracked
# at docs/skills/skill-registry.md under S-VENDOR-EATON-01.
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
        "## 1. Alcance y Objetivo\n_TBD_\n\n"
        "## 2. Evaluación de Impacto y Riesgos\n_TBD_\n\n"
        "## 3. Prerrequisitos\n_TBD_\n\n"
        "## 4. Lista de Pasos Secuenciales (Step-by-Step)\n_TBD_\n\n"
        "## 5. Plan de Reversión (Back-out Plan)\n_TBD_\n"
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
    ):
        self._llm_client = llm_client
        self._model_router = model_router
        self._max_tokens = int(max_tokens)

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
            return ProcedureDraft(
                draft_id=draft_id,
                doc_type=doc_type,
                context=context,
                content=_deterministic_skeleton(doc_type, context),
                asset_id=asset_id,
                generated_at=time.time(),
                llm_present=False,
                metadata=normalised_metadata,
            )

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

        return ProcedureDraft(
            draft_id=draft_id,
            doc_type=doc_type,
            context=context,
            content=text,
            asset_id=asset_id,
            generated_at=time.time(),
            llm_present=True,
            metadata=normalised_metadata,
        )


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

        # Rule 2.4 — Eaton SOW R-48 (S-VENDOR-EATON-01) -- CAUTION only
        eaton_hit = bool(
            re.search(EATON_CONTEXT_PATTERN, context, flags=re.IGNORECASE)
            or re.search(EATON_CONTEXT_PATTERN, asset_id, flags=re.IGNORECASE),
        )
        if eaton_hit:
            for label, pat in EATON_REQUIRED_TERMS:
                match = re.search(pat, text, flags=re.IGNORECASE)
                present[label] = bool(match)
                if not match:
                    findings.append(f"Eaton SOW R-48 advisory: missing {label}")
                    eaton_cautions.append(label)

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
        elif eaton_cautions:
            # Vendor-specific omissions are advisory only -- multi-brand
            # fleet reality.
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
