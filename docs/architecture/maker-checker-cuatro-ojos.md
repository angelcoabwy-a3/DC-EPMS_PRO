# Cuatro Ojos / Maker-Checker — Alignment Note

**Status:** Architecture mapping. No new implementation — documents how
the operator-mandated Universal §4 ("casillas de verificación para la
firma del técnico ejecutante y el supervisor — Principio de los Cuatro
Ojos") is already satisfied by the Sprint 3 Phase 4 Maker-Checker
witness gate.

**Drivers:**
- Operator catalog 2026-05-23 (MOPs distribution: PDU/RPP/Busway +
  Eaton SOW R-48): "Lista de Pasos Secuenciales ... con casillas de
  verificación para la firma del técnico ejecutante y el supervisor."
- Tier IV operational practice (Uptime Institute Tier IV, CSA Z462-24,
  NFPA 70E §130) — independent verification of physical maintenance
  steps by two distinct operators.

---

## Where Cuatro Ojos is enforced

### Layer 1 — In the MOP body (per step)

Each step in a fully-canonical MOP (see
[`docs/operaciones/mops/MOP-*.md`](../operaciones/mops/)) ships with
an inline checkbox pair:

```
1. Verificar en el HMI que no existan alarmas activas...
   [ ] Técnico: __________  [ ] Supervisor: __________
```

This is the **physical/paper trail** — the two operators check + sign
each step at execution time. The Procedure Architect's deterministic
audit gate verifies the section exists (S-SAFETY-01 enforces
"Pasos Secuenciales" presence) but does NOT parse individual checkbox
states — that's an out-of-band human signing surface.

### Layer 2 — At the document signing level (digital trail)

When the operator signs a generated MOP into the Forensic Ledger
(`POST /api/procedures/architect/sign`), the **Maker-Checker witness
gate** (`backend/procedure_routes.py:_process_mop_signature`)
enforces:

1. **First sign** (`operator_id = "maker.alice"`) → HTTP 202
   `awaiting_second_signature`. The draft is NOT in the ledger yet.
   Server stashes the first signature in `_pending_mop_signatures`
   keyed by `draft_id`.
2. **Second sign** (`operator_id = "checker.bob"`, **different**
   operator) → HTTP 200, sealed PROCEDURE_SIGNED entry in the
   Forensic Ledger naming both signers (`first_signer` +
   `second_signer`).
3. **Same operator twice** → HTTP 403, `Maker-Checker violation: self-
   witness ban`.
4. **Content drift between signs** (checker submits different body
   than maker did) → HTTP 409, `content drift`.

SOPs, EOPs, EMPs follow the **single-sign path** — Cuatro Ojos applies
only to MOPs by design (the procedure type that touches physical
infrastructure under maintenance windows).

---

## Why this is sufficient

The combination is the Tier IV-grade witness chain:

| Plane | Verification | Authority |
|---|---|---|
| Physical (paper) | Step-level signoff via §4 checkboxes | Two physical operators in the field |
| Digital (ledger) | Document-level signoff via the witness gate | Two distinct `operator_id`s server-enforced |
| Cryptographic | HMAC-chained ledger entry | Forensic Ledger ADR-011 / IEC 62443-3-3 SR 6.1 / 6.2 |

No bypass is possible:

- A hostile HMI cannot stash a single-sign MOP: the server re-audits
  on `/sign` and the witness gate runs server-side
  (defence in depth — see `test_mop_second_sign_must_pass_safety_audit_too`).
- Self-witnessing is blocked by `operator_id` comparison, not by
  client-side UI hiding.
- Content tampering between signs is caught by `content_sha256`
  comparison in `_process_mop_signature` (returns 409 `content drift`).

---

## Cross-references

- `backend/procedure_routes.py:_process_mop_signature` — the gate.
- `backend/procedure_routes.py:_pending_mop_signatures` — the pending
  store (in-memory; crash-mid-witness = operator re-signs, which is
  the safe failure mode).
- `tests/test_procedure_architect.py::TestMakerCheckerWitnessGate` —
  6 tests covering happy path + every refusal class.
- `frontend/assets/js/views/procedures.js` — `awaiting-second-signature`
  badge surfaces the 202 state to the operator.
- ADR-011 — Forensic Ledger (HMAC-chained, append-only).
- Skill `S-SAFETY-01` — universal 5-point structure + voltage
  verification (the audit gate before the witness gate).

The Cuatro Ojos contract is **complete**; no additional implementation
is required to satisfy the operator's 2026-05-23 directive.
