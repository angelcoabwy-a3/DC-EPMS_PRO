"""
backend/ot_security.py
======================
Release R2-A -- OT Security posture (replaces the "Morpheus OT" stub).

Honest scope
------------
This module does NOT inspect network traffic and there is no NVIDIA
Morpheus pipeline behind it. It reports the cyber-physical posture
the platform can actually prove about itself from in-process state:

  access      session gate, JWT secret source, seeded users and
              whether each still uses a repository-default password
  ledger      Forensic Ledger chain verification (ADR-011), key
              source, persistence backend
  bms         control-surface inventory (writable tags by protocol)
              and the BMS write audit buffer (accepted vs denied)
  edge        Modbus edge-gateway ingest counters
  monitoring  what is NOT monitored, stated as a finding

Every check is deterministic Python -- no LLM in the path (S-DET-01).
The endpoint is read-only (ADR-006) and never returns a secret, a
password, a hash or a token: only booleans, counts and names.

Standard references
-------------------
Each check names the IEC 62443-3-3 system requirement (SR) it relates
to. This is a design-time mapping made by reading the requirement
titles; it is NOT a conformance assessment and the platform makes no
compliance claim ("designed following IEC 62443 principles").
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import FastAPI, Request

log = logging.getLogger(__name__)

__all__ = [
    "DISCLAIMER",
    "SEVERITY_ORDER",
    "collect_facts",
    "evaluate_checks",
    "register_ot_security_routes",
    "summarise",
]

DISCLAIMER = (
    "Self-reported posture of this platform instance. No network traffic "
    "is inspected and no intrusion detection is deployed. IEC 62443-3-3 "
    "references are a design-time mapping, not a conformance assessment."
)

SEVERITY_ORDER = ("critical", "high", "medium", "low")

STATUS_FAIL = "fail"
STATUS_PASS = "pass"
STATUS_INFO = "info"

_AUDIT_RECENT_LIMIT = 12


# ─────────────────────────────────────────────────────────────────────
#  Facts -- read app state, never raise
# ─────────────────────────────────────────────────────────────────────
def _access_facts(app: FastAPI) -> dict[str, Any]:
    from backend.auth.jwt_handler import ENV_JWT_SECRET, ENV_PASSWORD_PREFIX
    from backend.auth.session_gate import gate_enabled

    store = getattr(app.state, "user_store", None)
    users: list[dict[str, str]] = []
    if store is not None:
        for user in store.all_users():
            override = os.environ.get(ENV_PASSWORD_PREFIX + user.username.upper(), "")
            users.append(
                {
                    "username": user.username,
                    "role": user.role.value,
                    "password_source": "environment" if override else "repo_default",
                }
            )
    users.sort(key=lambda u: u["username"])
    return {
        "gate_enabled": gate_enabled(),
        "jwt_secret_from_env": bool(os.environ.get(ENV_JWT_SECRET)),
        "user_store_ready": store is not None,
        "users": users,
    }


async def _ledger_facts(app: FastAPI) -> dict[str, Any]:
    ledger = getattr(app.state, "forensic_ledger", None)
    if ledger is None:
        return {"available": False}
    from backend.ledger import LedgerChainBrokenError
    from backend.ledger.forensic_ledger import EPHEMERAL_KEY_VERSION

    facts: dict[str, Any] = {
        "available": True,
        "verified": True,
        "divergence_index": None,
        "reason": None,
        "key_version": ledger.current_key_version,
        "hmac_key_from_env": ledger.current_key_version != EPHEMERAL_KEY_VERSION,
    }
    persistence_name = type(ledger.persistence).__name__
    if persistence_name == "PostgresPersistence":
        facts["persistence"] = "postgres"
    elif persistence_name == "InMemoryPersistence":
        facts["persistence"] = "memory"
    else:
        facts["persistence"] = persistence_name
    try:
        await ledger.verify_chain()
    except LedgerChainBrokenError as exc:
        facts["verified"] = False
        facts["divergence_index"] = exc.divergence_index
        facts["reason"] = str(exc.reason)[:200]
    facts["total_entries"] = await ledger.count()
    return facts


def _bms_facts(bms: Any | None) -> dict[str, Any]:
    if bms is None:
        return {"available": False}
    by_protocol: dict[str, int] = {}
    writable_by_protocol: dict[str, int] = {}
    writable = 0
    for tag in bms.tags.values():
        by_protocol[tag.protocol] = by_protocol.get(tag.protocol, 0) + 1
        if tag.writable:
            writable += 1
            writable_by_protocol[tag.protocol] = (
                writable_by_protocol.get(tag.protocol, 0) + 1
            )
    audit = list(bms.write_audit_log)
    denied = sum(1 for e in audit if not e.success)
    recent = [
        {
            "ts": e.ts,
            "tag_id": e.tag_id,
            "user": e.user,
            "success": bool(e.success),
            "error": str(e.error)[:160],
        }
        for e in reversed(audit[-_AUDIT_RECENT_LIMIT:])
    ]
    return {
        "available": True,
        "total_tags": len(bms.tags),
        "writable_tags": writable,
        "by_protocol": dict(sorted(by_protocol.items())),
        "writable_by_protocol": dict(sorted(writable_by_protocol.items())),
        "audit_total": len(audit),
        "audit_denied": denied,
        "audit_accepted": len(audit) - denied,
        "audit_recent": recent,
    }


def _edge_facts(app: FastAPI) -> dict[str, Any]:
    store = getattr(app.state, "edge_channel_store", None)
    if store is None:
        return {"available": False}
    return {
        "available": True,
        "channel_count": len(getattr(store, "_channels", {})),
        "batches_accepted": int(store.batches_accepted),
        "envelopes_accepted": int(store.envelopes_accepted),
        "envelopes_rejected": int(store.envelopes_rejected),
        "last_ingest_ts": store.last_ingest_ts,
        # The gateway presents no device credential today: a batch is
        # accepted on a valid wire format alone (or on a human session
        # when the gate is on). Stated as a fact so the check is honest.
        "device_authenticated": False,
    }


async def collect_facts(app: FastAPI, bms: Any | None) -> dict[str, Any]:
    """Assemble the fact sheet. Each section degrades independently."""
    facts: dict[str, Any] = {}
    try:
        facts["access"] = _access_facts(app)
    except Exception as e:
        log.warning("[ot-security] access facts failed: %s", e)
        facts["access"] = {"error": str(e)[:200]}
    try:
        facts["ledger"] = await _ledger_facts(app)
    except Exception as e:
        log.warning("[ot-security] ledger facts failed: %s", e)
        facts["ledger"] = {"available": False, "error": str(e)[:200]}
    try:
        facts["bms"] = _bms_facts(bms)
    except Exception as e:
        log.warning("[ot-security] bms facts failed: %s", e)
        facts["bms"] = {"available": False, "error": str(e)[:200]}
    try:
        facts["edge"] = _edge_facts(app)
    except Exception as e:
        log.warning("[ot-security] edge facts failed: %s", e)
        facts["edge"] = {"available": False, "error": str(e)[:200]}
    facts["monitoring"] = {
        "traffic_inspection": False,
        "zones_and_conduits_modelled": False,
    }
    return facts


# ─────────────────────────────────────────────────────────────────────
#  Checks -- pure, deterministic
# ─────────────────────────────────────────────────────────────────────
def _check(
    check_id: str,
    status: str,
    severity: str | None,
    title: str,
    detail: str,
    reference: str,
    remediation: str = "",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "severity": severity if status == STATUS_FAIL else None,
        "title": title,
        "detail": detail,
        "reference": reference,
        "remediation": remediation if status == STATUS_FAIL else "",
    }


def evaluate_checks(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn the fact sheet into an ordered list of checks.

    Pure function: same facts, same checks. A section that could not
    be read produces a failing check rather than a silent pass.
    """
    checks: list[dict[str, Any]] = []
    access = facts.get("access") or {}
    ledger = facts.get("ledger") or {}
    bms = facts.get("bms") or {}
    edge = facts.get("edge") or {}
    monitoring = facts.get("monitoring") or {}

    # ── Identification and authentication ──────────────────────────
    ref_sr11 = "IEC 62443-3-3 SR 1.1 (human user identification and authentication)"
    if "error" in access:
        checks.append(_check(
            "OT-AUTH-00", STATUS_FAIL, "high", "Access posture could not be read",
            f"Reading the IAM state failed: {access['error']}", ref_sr11,
            "Check the backend log for the IAM initialisation error.",
        ))
    else:
        if access.get("gate_enabled"):
            checks.append(_check(
                "OT-AUTH-01", STATUS_PASS, None, "Session required on every API route",
                "The session gate is ON: http and websocket routes outside the "
                "public allow-list reject requests without a valid session.",
                ref_sr11,
            ))
        else:
            checks.append(_check(
                "OT-AUTH-01", STATUS_FAIL, "high", "API reachable without a session",
                "The session gate is OFF. The login view gates the HMI only; "
                "every API route, the telemetry stream and the Hermes websocket "
                "answer unauthenticated callers.",
                ref_sr11,
                "Set DC_EPMS_REQUIRE_AUTH=1 (see docs/DEPLOY_PUBLIC.md). "
                "Acceptable only on a loopback development machine.",
            ))

        ref_sr15 = "IEC 62443-3-3 SR 1.5 (authenticator management)"
        if access.get("jwt_secret_from_env"):
            checks.append(_check(
                "OT-AUTH-02", STATUS_PASS, None, "Session signing secret is configured",
                "DC_EPMS_JWT_SECRET is set; sessions survive a restart and the "
                "secret is not generated per process.",
                ref_sr15,
            ))
        else:
            checks.append(_check(
                "OT-AUTH-02", STATUS_FAIL, "medium", "Session signing secret is ephemeral",
                "DC_EPMS_JWT_SECRET is not set. A random secret is generated at "
                "each boot, so every restart invalidates all sessions.",
                ref_sr15,
                "Set DC_EPMS_JWT_SECRET to a private value of 32 or more characters.",
            ))

        users = access.get("users") or []
        defaults = [u["username"] for u in users if u.get("password_source") == "repo_default"]
        if not access.get("user_store_ready"):
            checks.append(_check(
                "OT-AUTH-03", STATUS_FAIL, "high", "User store is not initialised",
                "No user can sign in: the IAM store failed to seed at boot.",
                ref_sr15, "Check the backend log for the IAM seeding error.",
            ))
        elif defaults:
            checks.append(_check(
                "OT-AUTH-03", STATUS_FAIL, "high",
                "Accounts still use repository-default passwords",
                f"{len(defaults)} of {len(users)} account(s) use the password "
                f"published in the source repository: {', '.join(defaults)}.",
                ref_sr15,
                "Set DC_EPMS_PWD_<USERNAME> for each account. On a gated "
                "deployment accounts without one are not created at all.",
            ))
        else:
            checks.append(_check(
                "OT-AUTH-03", STATUS_PASS, None, "No repository-default passwords in use",
                f"All {len(users)} seeded account(s) take their password from "
                "the environment.",
                ref_sr15,
            ))

    # ── Audit trail integrity ──────────────────────────────────────
    ref_sr39 = "IEC 62443-3-3 SR 3.9 (protection of audit information)"
    ref_sr28 = "IEC 62443-3-3 SR 2.8 (auditable events)"
    if not ledger.get("available"):
        checks.append(_check(
            "OT-AUD-01", STATUS_FAIL, "high", "Forensic ledger is not running",
            "Control-surface writes cannot be chained into the tamper-evident "
            "ledger (ADR-011)." + (f" Error: {ledger['error']}" if ledger.get("error") else ""),
            ref_sr28, "Check the backend log for the ledger initialisation error.",
        ))
    else:
        total = ledger.get("total_entries", 0)
        if ledger.get("verified"):
            checks.append(_check(
                "OT-AUD-01", STATUS_PASS, None, "Ledger hash chain verifies",
                f"All {total} entr{'y' if total == 1 else 'ies'} replay cleanly "
                "under the HMAC chain (ADR-011).",
                ref_sr39,
            ))
        else:
            checks.append(_check(
                "OT-AUD-01", STATUS_FAIL, "critical", "Ledger hash chain is BROKEN",
                f"Verification diverges at entry index {ledger.get('divergence_index')}: "
                f"{ledger.get('reason') or 'no reason reported'}. Entries from that "
                "point on cannot be trusted.",
                ref_sr39,
                "Treat as a security incident: preserve the ledger store, do not "
                "append further writes, investigate the divergent entry.",
            ))
        if ledger.get("hmac_key_from_env"):
            checks.append(_check(
                "OT-AUD-02", STATUS_PASS, None, "Ledger HMAC key is configured",
                f"Key version {ledger.get('key_version')} comes from "
                "DC_EPMS_LEDGER_HMAC_KEY.",
                ref_sr39,
            ))
        else:
            checks.append(_check(
                "OT-AUD-02", STATUS_FAIL, "medium", "Ledger HMAC key is ephemeral",
                "DC_EPMS_LEDGER_HMAC_KEY is not set. Entries are signed with a "
                "key generated at boot and cannot be verified after a restart.",
                ref_sr39,
                "Set DC_EPMS_LEDGER_HMAC_KEY to a hex string of at least 64 hex "
                "digits (32 bytes).",
            ))
        if ledger.get("persistence") == "postgres":
            checks.append(_check(
                "OT-AUD-03", STATUS_PASS, None, "Ledger entries are persisted",
                "The ledger writes to PostgreSQL (append-only table).",
                ref_sr28,
            ))
        else:
            checks.append(_check(
                "OT-AUD-03", STATUS_FAIL, "medium", "Ledger entries are held in memory",
                "Audit records are generated but not retained: a restart "
                "discards the whole chain.",
                ref_sr28,
                "Run with PostgreSQL and apply the forensic-ledger migration.",
            ))

    # ── Control surface ────────────────────────────────────────────
    ref_sr21 = "IEC 62443-3-3 SR 2.1 (authorization enforcement)"
    if not bms.get("available"):
        checks.append(_check(
            "OT-CTL-01", STATUS_INFO, None, "BMS connector is not loaded",
            "No control-surface inventory is available on this instance.",
            ref_sr21,
        ))
    else:
        checks.append(_check(
            "OT-CTL-01", STATUS_INFO, None, "Control-surface inventory",
            f"{bms.get('writable_tags', 0)} of {bms.get('total_tags', 0)} BMS tags "
            "accept a write command. Every write requires the SME_L6 role claim "
            "and traverses the forensic ledger (S-SEC-02, S-LEDGER-01).",
            ref_sr21,
        ))
        denied = bms.get("audit_denied", 0)
        total_audit = bms.get("audit_total", 0)
        checks.append(_check(
            "OT-CTL-02", STATUS_INFO, None, "BMS write attempts in the audit buffer",
            f"{total_audit} attempt(s) recorded since boot: "
            f"{bms.get('audit_accepted', 0)} accepted, {denied} denied by the "
            "connector. The buffer keeps the last 200 attempts. Requests "
            "refused by the role check never reach the connector and are "
            "not counted here.",
            ref_sr21,
        ))

    # ── Edge devices ───────────────────────────────────────────────
    ref_sr12 = "IEC 62443-3-3 SR 1.2 (software process and device identification and authentication)"
    if not edge.get("available"):
        checks.append(_check(
            "OT-DEV-01", STATUS_INFO, None, "Edge ingest is not mounted",
            "The Modbus edge-gateway ingest endpoint is not available on this "
            "instance, so no field device can deliver telemetry.",
            ref_sr12,
        ))
    else:
        if edge.get("device_authenticated"):
            checks.append(_check(
                "OT-DEV-01", STATUS_PASS, None, "Edge gateway is authenticated as a device",
                "Batches are accepted only from an identified gateway.", ref_sr12,
            ))
        else:
            checks.append(_check(
                "OT-DEV-01", STATUS_FAIL, "medium",
                "Edge gateway is not authenticated as a device",
                "The ingest endpoint accepts a batch on a valid wire format. "
                "The gateway presents no device credential, so a batch cannot "
                "be attributed to a specific gateway.",
                ref_sr12,
                "Add a per-gateway credential (mutual TLS or a signed batch "
                "header) before connecting a real PLC.",
            ))
        rejected = edge.get("envelopes_rejected", 0)
        if rejected:
            checks.append(_check(
                "OT-DEV-02", STATUS_FAIL, "low", "Edge envelopes were rejected",
                f"{rejected} envelope(s) failed wire-schema validation since boot "
                f"({edge.get('envelopes_accepted', 0)} accepted).",
                "IEC 62443-3-3 SR 3.5 (input validation)",
                "Inspect the gateway register map and the backend log for the "
                "rejected batches.",
            ))
        else:
            checks.append(_check(
                "OT-DEV-02", STATUS_PASS, None, "No rejected edge envelopes",
                f"{edge.get('envelopes_accepted', 0)} envelope(s) accepted in "
                f"{edge.get('batches_accepted', 0)} batch(es) since boot; none rejected.",
                "IEC 62443-3-3 SR 3.5 (input validation)",
            ))

    # ── What is NOT monitored ──────────────────────────────────────
    if not monitoring.get("traffic_inspection"):
        checks.append(_check(
            "OT-NET-01", STATUS_FAIL, "medium", "No OT network traffic inspection",
            "Nothing on this platform observes Modbus, BACnet or DNP3 traffic. "
            "There is no intrusion or anomaly detection on the OT network; "
            "no NVIDIA Morpheus pipeline is deployed.",
            "IEC 62443-3-3 SR 6.2 (continuous monitoring)",
            "Out of scope for this release. Requires a traffic capture point "
            "and a detection pipeline.",
        ))
    if not monitoring.get("zones_and_conduits_modelled"):
        checks.append(_check(
            "OT-NET-02", STATUS_FAIL, "low", "Zones and conduits are not modelled",
            "config/site_model.yml describes the electrical and cooling "
            "topology but assigns no security zone or conduit to any asset.",
            "IEC 62443-3-3 SR 5.1 (network segmentation)",
            "Add a zone attribute per component and declare the conduits "
            "between zones in the site model.",
        ))
    return checks


def summarise(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts by status and by severity of the failing checks."""
    by_severity = dict.fromkeys(SEVERITY_ORDER, 0)
    failed = passed = info = 0
    for c in checks:
        if c["status"] == STATUS_FAIL:
            failed += 1
            if c["severity"] in by_severity:
                by_severity[c["severity"]] += 1
        elif c["status"] == STATUS_PASS:
            passed += 1
        else:
            info += 1
    worst = next((s for s in SEVERITY_ORDER if by_severity[s]), None)
    return {
        "failed": failed,
        "passed": passed,
        "info": info,
        "by_severity": by_severity,
        "worst_severity": worst,
    }


# ─────────────────────────────────────────────────────────────────────
#  Route
# ─────────────────────────────────────────────────────────────────────
def register_ot_security_routes(app: FastAPI, bms_getter: Any) -> None:
    """Mount GET /api/ot-security/posture (read-only, ADR-006).

    ``bms_getter`` is a zero-argument callable returning the BMS
    connector or ``None`` -- injected so this module does not import
    backend.main.
    """

    @app.get("/api/ot-security/posture")
    async def get_ot_security_posture(request: Request) -> dict[str, Any]:
        try:
            bms = bms_getter()
        except Exception as e:
            log.warning("[ot-security] BMS connector unavailable: %s", e)
            bms = None
        facts = await collect_facts(request.app, bms)
        checks = evaluate_checks(facts)
        return {
            "schema": "ot_security_posture_v1",
            "generated_at": time.time(),
            "disclaimer": DISCLAIMER,
            "summary": summarise(checks),
            "checks": checks,
            "facts": facts,
        }
