"""DC-EPMS PRO -- cryptographic primitives.

Currently houses the BB84 educational simulator (Epic 9). Production
HMAC keying lives in backend.ledger.forensic_ledger; this package is
deliberately separate so the EDUCATIONAL framing of bb84_core stays
unambiguous in import paths.
"""
