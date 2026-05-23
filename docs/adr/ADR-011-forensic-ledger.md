# ADR-011: Forensic Ledger — HMAC-Chained Append-Only Audit of Control-Surface Writes

- Status: ACCEPTED
- Date: 2026-05-22
- Decision-maker: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
- Sprint: Epic 4 (Forensic Ledger + Proposer Chain Closure)
- Supersedes: nothing
- Supersedes-partially: ADR-006 §4 ("Auditable provenance") — extends from per-artifact `_provenance` to a system-wide ledger
- MADR template: https://adr.github.io/madr/

## Context

The MSD v2.0 forensic audit (2026-05-22, this conversation) found that the
project satisfies the *intent* of ADR-006 (Deterministic Sandbox) but lacks
the **infrastructure** that IEC 62443-3-3 SR 6.1 / SR 6.2 and NIST SP
800-82r3 AU-9 / AU-10 demand for a Tier IV OT-adjacent environment:

- `backend/bms_connector.py` keeps a `WriteAuditEntry` list **truncated to
  the last 200 entries in RAM**, lost on process restart (line 362-364).
- A recursive grep across `backend/**/*.py` for `hmac | sha256 | signature
  | prev_hash | chain_hash | merkle` returned **zero matches** — no
  cryptographic chaining anywhere in the backend.
- `POST /api/bms/write` is RBAC-gated to SME_L6 but otherwise direct —
  there is no end-to-end audit linkage from operator intent → consensus
  decision → BMS write → outcome.
- Zero rollback capability — no `tests/test_rollback.py`, no `snapshot`
  primitive, no `revert` endpoint.

For the Microsoft CO+I panel (target early August 2026), the question
*"how do you prove that a setpoint write was not tampered with after the
fact, and how do you revert it if it was wrong?"* needs a structural
answer, not a policy answer.

## Decision

Introduce a **Forensic Ledger** module under `backend/ledger/` as the
single source of truth for all control-surface mutations. The ledger:

1. **Is append-only.** Every facility-state change appends a `LedgerEntry`.
   Updates and deletes on the persistence table are rejected at the DB
   level by `BEFORE UPDATE / BEFORE DELETE` triggers raising an exception
   (IEC 62443-3-3 SR 6.1 — *"audit records shall be protected against
   unauthorised modification"*). NIST SP 800-53r5 AU-9.

2. **Is HMAC-chained.** Each entry carries `entry_hmac = HMAC-SHA256(key,
   prev_hash || entry_id || ts || actor || action || sha256(canonical_json
   (payload)))`. The next entry's `prev_hash` is the previous entry's
   `entry_hmac`. The chain is the same construction used by Google
   Trillian / Certificate Transparency (RFC 6962). Tamper on any field
   of any entry invalidates that entry's HMAC AND breaks the chain at
   every subsequent entry — verification is O(n) and produces the index
   of the first divergence.

3. **Persists to TimescaleDB.** Schema lives in
   `backend/migrations/2026_05_W4_forensic_ledger.sql` — a `ledger_entries`
   table with `entry_id UUID PK`, `sequence_no BIGSERIAL UNIQUE` (gapless
   ordering), `ts`, `actor`, `action`, `payload JSONB`, `prev_hash BYTEA`,
   `entry_hmac BYTEA NOT NULL`, `key_version INTEGER`. Retention: 7 years
   (NERC CIP-007-6 R4.4 floor of 90 days + 3 years warm; NIST SP 800-82r3
   §6.2.4 recommends >= 3 years for OT; we double it). Indexed on `ts DESC`
   and `(actor, action)`.

4. **Has two persistence backends behind a Protocol.**
   - `PostgresPersistence` — production. Uses the existing asyncpg pool
     from `backend.database.DBManager`.
   - `InMemoryPersistence` — tests. Still respects the append-only
     contract (UPDATE / DELETE raise `LedgerImmutabilityError`). Lets
     unit tests run without a live Postgres.

5. **Has key management via `DC_EPMS_LEDGER_HMAC_KEY` env.**
   - Production: 32-byte random key from a secret manager, supplied via
     environment.
   - Dev / tests: if unset, the module generates an ephemeral key,
     **logs a loud warning**, and stores entries with `key_version=0`
     (reserved). Verification with the ephemeral key still works in
     the same process; a restart invalidates verification — *by design*,
     this forces production to set the key.
   - Rotation: `key_version` is recorded per entry. A rotation appends
     a `KEY_ROTATION` action entry (signed under the new key) referencing
     the prior version. Old entries verify under their own version.

6. **Is the single seam for all BMS writes.** The existing
   `BmsWriteFn` callable (wired by `backend/main.py` lifespan and
   consumed by `backend/optimizer_routes.py` and the `/api/bms/write`
   handler) is wrapped by `forensic_ledger.wrap_bms_write_fn(...)`. The
   wrapper:
   - Reads the current value of the tag (the `prev_value`).
   - Appends a `BMS_WRITE_REQUESTED` entry with `{tag_id, requested_value,
     prev_value, source, proposal_id?}` to the ledger.
   - Invokes the underlying `bms.write()`.
   - Appends a `BMS_WRITE_RESULT` entry with `{ref_entry_id, success,
     message}` to the ledger.
   - Returns the same `(success, message)` tuple the caller already
     expects — fully backward compatible.

7. **Powers the Rollback Harness.** Because every `BMS_WRITE_REQUESTED`
   entry carries `prev_value`, a new endpoint `POST /api/bms/revert/
   {entry_id}` (SME_L6) reads the entry, calls the same wrapped
   `BmsWriteFn` with `prev_value`, and appends a `BMS_REVERT` entry
   referencing the original `entry_id`. Reverting a revert is allowed
   (creates a new entry; the chain stays intact). This satisfies IEC
   62443-3-3 SR 7.3 / SR 7.4 (control-system backup + recovery).

## Consequences

### Positive

- **IEC 62443-3-3 SR 6.1 / SR 6.2 / SR 7.3 / SR 7.4 satisfied at the
  architecture level.** A paper audit on the schema + the HMAC
  construction + the immutability triggers + the rollback endpoint
  passes without policy waivers.
- **Cryptographic tamper-evidence.** A change to any prior entry is
  detectable by `verify_chain()` in O(n); the index of the first
  divergence is reported. NIST SP 800-82r3 AU-9 / AU-10 satisfied.
- **End-to-end audit linkage.** An approved Optimizer proposal carries
  a `proposal_id` UUID through the consensus log → approval log →
  ledger → revert log. A single query joins five tables to reconstruct
  any actuation.
- **Rollback in <100 ms.** The wrapper's `prev_value` capture is a
  single dict lookup; revert is a normal `BmsWriteFn` call. NFPA 70E
  §130 EOP-abort latency budget respected.
- **Production-ready without rewrite.** Drop-in once the migration is
  applied; the in-memory persistence keeps unit tests fast and
  hermetic.

### Negative / Trade-offs

- **Storage growth.** At 100 ops/day with ~300 bytes/entry, the table
  grows ~11 MB/year. TimescaleDB compression brings this to ~2 MB/year
  for compressed chunks. Negligible.
- **HMAC key management is now load-bearing.** Lose the key, lose
  verifiability of prior entries (the data is still readable but the
  cryptographic chain cannot be replayed). Mitigation: key is stored
  in the same secret manager that already holds the Postgres password;
  rotation is supported via `key_version`.
- **Two writes per BMS actuation.** The pre- and post-write entries
  double the ledger row count vs. a "log only on success" design. The
  trade is intentional: pre-write captures intent + prev_value (needed
  for revert) even if the actual write fails or times out. Per IEC
  62443-3-3 SR 6.1.RE2 ("audit log storage capacity") this is
  affordable.
- **ADR-006 §4 ("`_provenance` field on draft artifacts") is now a
  *complement* to the ledger, not the audit source-of-truth.** Existing
  `_provenance` fields are preserved for backward compatibility but
  the ledger is the binding record.

## Alternatives Considered and Rejected

- **In-process append-only file (jsonl).** Rejected — no atomic
  guarantee against concurrent processes; restart races; no SQL query
  surface; the project already has TimescaleDB.
- **External SaaS QLDB (AWS QLDB, Azure Confidential Ledger).** Rejected
  — breaks the edge-autonomy posture of ADR-008 (single-host edge node
  must function under degraded uplink). Cost not justified for an
  on-edge ledger.
- **Hyperledger Fabric / blockchain.** Rejected — over-engineering for
  a single-tenant ledger; consensus overhead is wasted when there is
  no Byzantine adversary in the deployment model.
- **Sign every entry with an asymmetric key (Ed25519) and verify with
  a public key.** Rejected for V11 — HMAC is sufficient because there
  is no external verifier; the system verifying its own ledger holds
  the same key it used to sign. Asymmetric signing is the natural V12
  upgrade for "shared with auditor" scenarios.
- **Per-write Merkle proofs.** Rejected — adds O(log n) work per
  append for negligible benefit at our volume; a simple chain is
  sufficient. Re-evaluate at >1M entries.

## References

### Internal
- ADR-006 — Deterministic Sandbox (this ADR extends §4 "Auditable provenance")
- ADR-008 — Image-size / edge-autonomy posture
- `backend/optimizer.py` — gold-standard Proposer Pattern (no actor_role, AST invariants)
- `backend/optimizer_routes.py` — operator approval seam (`BmsWriteFn`)
- `backend/bms_connector.py` — the legacy in-RAM ring buffer this ADR replaces
- `docs/audit/E2E_Security_Orphan_Audit.md` — original audit that surfaced the gap
- The MSD-v2.0 forensic audit (2026-05-22 conversation) — finding IDs
  DC-EPMS-MSD-001 / 002 / 003 / 004 closed by this ADR's implementation

### External standards
- IEC 62443-3-3 §SR 6.1 + RE1 + RE2 (Audit log accessibility, modification
  protection, storage capacity)
- IEC 62443-3-3 §SR 6.2 (Continuous monitoring)
- IEC 62443-3-3 §SR 7.3 + SR 7.4 (Control system backup + recovery)
- NIST SP 800-82r3 §6.2.4 (audit retention >= 3 years for OT)
- NIST SP 800-53r5 AU-2 / AU-3 / AU-9 / AU-10 / AU-12 (audit content,
  protection, non-repudiation, generation)
- NERC CIP-007-6 R4.4 (security event logging, 90-day + 3-year retention)
- NIST AI RMF MEASURE 2.7 (LLM non-determinism contained — referenced
  for the AI-originated write path through the consensus chain)
- RFC 2104 (HMAC), RFC 6234 (SHA-2), RFC 6962 (Certificate Transparency
  — the inspiration for the chain construction, not a literal CT log)
- SLSA Framework v1.0 (referenced for the broader supply-chain posture;
  not consumed by this ADR directly)

## Verification

This ADR is binding when all of the following are green:

- `tests/test_forensic_ledger.py` (new this sprint):
  - `test_hmac_verifies_when_untouched` — full chain verifies clean
  - `test_hmac_detects_payload_tamper` — mutating any payload field
    surfaces the divergence index
  - `test_hmac_detects_chain_break` — re-pointing `prev_hash` to a
    wrong predecessor surfaces the divergence index
  - `test_immutability_in_memory` — `InMemoryPersistence` raises
    `LedgerImmutabilityError` on `_force_update` / `_force_delete`
  - `test_genesis_entry_prev_hash_is_empty` — first entry's
    `prev_hash == b""` and HMAC verifies under that convention
  - `test_concurrent_appends_preserve_order` — multi-task asyncio
    appends produce a gapless `sequence_no` series and a valid chain
  - `test_ephemeral_key_warns` — when `DC_EPMS_LEDGER_HMAC_KEY` is
    unset, the module emits a `WARNING` log and uses `key_version=0`
  - `test_key_rotation_does_not_break_prior_entries` — rotating the
    key appends a `KEY_ROTATION` entry; prior entries still verify
    under their recorded `key_version`

- `tests/test_bms_write_proposer_chain.py` (new this sprint):
  - `test_direct_write_appends_pre_and_post_ledger_entries`
  - `test_optimizer_approve_path_appends_ledger_entries`
  - `test_failed_bms_write_still_appends_result_entry`
  - `test_ledger_entry_carries_prev_value_for_revert`

- `tests/test_rollback_harness.py` (new this sprint):
  - `test_revert_restores_prev_value`
  - `test_revert_appends_own_ledger_entry`
  - `test_revert_of_revert_is_allowed` (creates new entry chain)
  - `test_revert_requires_sme_l6`
  - `test_revert_unknown_entry_id_returns_404`

- Skill registry adds `S-LEDGER-01` (all control-surface writes traverse
  `forensic_ledger.wrap_bms_write_fn`) and `S-PROPOSER-01` (AI-originated
  writes carry `proposal_id` linking to an approved consensus row).
