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


# ─── System prompt — EXACTLY as pinned in the Epic 6 spec ─────────────
# This string is byte-frozen by Release Engineering. Tests assert its
# SHA-256 to surface any accidental edit (a stray translation, a
# whitespace tidy) loud and early.
PROCEDURE_ARCHITECT_SYSTEM_PROMPT = """# ROL DEL AGENTE
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
**Estructura Obligatoria:**
1. **Identificación de Riesgos:** (Definir nivel de riesgo y PPE requerido según CSA Z462-24).
2. **Protocolo de Aislamiento:** (Pasos exactos de Lockout/Tagout - LOTO).
3. **Prerrequisitos:** (Herramientas, personal requerido, permisos de trabajo).
4. **Secuencia de Intervención (Step-by-Step):** (Pasos granulares con casillas de verificación mental para el técnico).
5. **Plan de Reversión (Back-out Plan):** (CRÍTICO: Cómo abortar y volver al estado seguro si la secuencia falla).

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


# ─── Data classes ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class ProcedureDraft:
    """One Procedure Architect output. Frozen so consumers can pass it
    through the audit + sign pipeline without defensive copying."""

    draft_id: str
    doc_type: str
    context: str
    content: str               # markdown body produced by the agent
    asset_id: str | None
    generated_at: float
    llm_present: bool          # True iff a real LLM client was wired

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        "## 1. Identificación de Riesgos\n_TBD_\n\n"
        "## 2. Protocolo de Aislamiento\n_TBD_\n\n"
        "## 3. Prerrequisitos\n_TBD_\n\n"
        "## 4. Secuencia de Intervención (Step-by-Step)\n_TBD_\n\n"
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
    ) -> ProcedureDraft:
        """Build a hermetic prompt + dispatch to the LLM (or return a
        deterministic skeleton). Always succeeds — an LLM failure
        falls back to the skeleton rather than raising."""
        require_artifact("doc_type", doc_type)
        require_artifact("context", context)
        if doc_type not in VALID_DOC_TYPES:
            raise ArtifactDependencyError(
                f"doc_type must be one of {sorted(VALID_DOC_TYPES)}, "
                f"got {doc_type!r}"
            )

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
            )

        body = (
            f"{self.SYSTEM_PROMPT}\n"
            f"---\n"
            f"# OPERATOR REQUEST\n"
            f"DOCUMENT TYPE: {doc_type}\n"
            f"CONTEXT: {context}\n"
            f"ASSET ID (when known): {asset_id or 'n/a'}\n"
            f"\n"
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
        )


# ─── Safety Officer audit (deterministic — S-DET-01) ──────────────────
def audit_procedure_safety(draft: ProcedureDraft) -> SafetyAuditResult:
    """Pattern-scan a :class:`ProcedureDraft` for the per-template
    required terms in :data:`SAFETY_REQUIRED_TERMS`.

    Rules:
      * MOP — missing ANY of {CSA Z462/NFPA 70E, PPE, LOTO} -> hard_stop.
        The spec is explicit: a MOP without those callouts CANNOT
        ship. Every missing term is enumerated in ``findings`` so the
        operator sees exactly what to add before re-generating.
      * SOP — missing the BMS/HMI verification term -> caution
        (informational; operator can sign with an override).
      * EOP — missing containment language -> caution.
      * EMP — missing incident-command reference -> caution.
      * approve — all required terms present.

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
    required = SAFETY_REQUIRED_TERMS.get(doc_type, [])
    present: dict[str, bool] = {}
    missing: list[str] = []

    for label, pat in required:
        match = re.search(pat, text, flags=re.IGNORECASE)
        present[label] = bool(match)
        if not match:
            missing.append(label)

    findings: list[str] = []
    if missing:
        for label in missing:
            findings.append(
                f"missing required {doc_type} term: {label}"
            )

    if doc_type == DOC_TYPE_MOP:
        # MOP is the load-bearing case — any missing term = hard_stop.
        verdict = AUDIT_VERDICT_HARD_STOP if missing else AUDIT_VERDICT_APPROVE
        if missing:
            findings.append(
                "MOP refused: a Method of Procedure without LOTO + PPE + "
                "CSA Z462/NFPA 70E callouts cannot be signed (Epic 6 spec)."
            )
    elif missing:
        # Other templates are advisory.
        verdict = AUDIT_VERDICT_CAUTION
    else:
        verdict = AUDIT_VERDICT_APPROVE

    return SafetyAuditResult(
        doc_type=doc_type,
        verdict=verdict,
        findings=findings,
        required_terms_present=present,
    )
