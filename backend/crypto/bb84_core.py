"""
backend/crypto/bb84_core.py
===========================
Epic 9 -- BB84 quantum-key-distribution **educational simulator**.

What this is
------------
A deterministic, seeded simulation of the BB84 protocol (Bennett &
Brassard, 1984). Alice prepares photons in random bits + random
bases ('+' rectilinear, 'x' diagonal); Bob measures each photon in
his own random basis; they publicly sift to the bases-matched subset;
they sacrifice a sample to estimate the Quantum Bit Error Rate (QBER);
if QBER >= threshold (default 11%) the run is aborted and the final
key is discarded.

What this is NOT
----------------
Real QKD. Real QKD requires single-photon hardware (entangled-pair
sources, single-photon detectors, fibre/free-space optical channels)
that this codebase does NOT model. The "quantum no-cloning theorem"
that gives BB84 its security guarantee has NO software analogue --
this module simulates the bit-and-basis bookkeeping only. The keys
this module emits have the entropy of `random.Random`, not of a
physical quantum source. Use the keys as audit-trail salt or for
educational demonstration; do NOT treat them as cryptographically
strong on their own.

Why deterministic
-----------------
S-DET-01 (Verdict before LLM, always) requires every consequential
verdict path in DC-EPMS to be reproducible from inputs. The QKD
service consumes keys for ledger annotation -- reproducibility lets
us replay an audit-trail diff exactly under test. Seeded
`random.Random` instances (Alice / Bob / Sample / Eve) give us that.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable
from dataclasses import dataclass

# Basis symbols. The protocol uses only these two.
BASIS_PLUS = "+"
BASIS_CROSS = "x"
_VALID_BASES = frozenset({BASIS_PLUS, BASIS_CROSS})

# Default QBER abort threshold. 11% is the Shor-Preskill bound for
# one-way classical reconciliation of BB84; ~25% is the QBER signature
# of full intercept-and-resend by an eavesdropper.
DEFAULT_QBER_THRESHOLD = 0.11

# Default fraction of the sifted key sacrificed to estimate QBER.
DEFAULT_SAMPLE_FRACTION = 0.5


@dataclass(frozen=True)
class BB84Result:
    """One end-to-end BB84 run's full audit trail.

    Field order is informational only -- equality is structural over
    every field, so two runs with identical seeds compare equal.
    """

    raw_alice_bits: tuple[int, ...]
    alice_bases: tuple[str, ...]
    bob_bases: tuple[str, ...]
    bob_measurements: tuple[int, ...]
    sifted_indices: tuple[int, ...]
    sifted_alice: tuple[int, ...]
    sifted_bob: tuple[int, ...]
    sample_indices: tuple[int, ...]
    qber: float
    final_key: tuple[int, ...]
    aborted: bool
    qber_threshold: float

    @property
    def sample_size(self) -> int:
        return len(self.sample_indices)

    @property
    def sifted_size(self) -> int:
        return len(self.sifted_alice)


def measure_photon(
    bit: int, prep_basis: str, meas_basis: str, rng: random.Random,
) -> int:
    """Measure a single photon prepared in ``bit`` / ``prep_basis``
    using ``meas_basis``.

    If the bases match, quantum mechanics guarantees the outcome
    equals the prepared bit. If they differ, the outcome is a uniform
    coin flip drawn from ``rng`` (the Born rule for orthogonal-basis
    projection).
    """
    if bit not in (0, 1):
        raise ValueError(f"bit must be 0 or 1, got {bit!r}")
    if prep_basis not in _VALID_BASES:
        raise ValueError(
            f"prep_basis must be one of {sorted(_VALID_BASES)}, "
            f"got {prep_basis!r}",
        )
    if meas_basis not in _VALID_BASES:
        raise ValueError(
            f"meas_basis must be one of {sorted(_VALID_BASES)}, "
            f"got {meas_basis!r}",
        )
    if prep_basis == meas_basis:
        return bit
    return rng.randint(0, 1)


def run_bb84(
    n_photons: int,
    *,
    seed_alice: int,
    seed_bob: int,
    seed_sample: int = 0,
    eavesdrop: bool = False,
    seed_eve: int = 0,
    qber_threshold: float = DEFAULT_QBER_THRESHOLD,
    sample_fraction: float = DEFAULT_SAMPLE_FRACTION,
) -> BB84Result:
    """Run one full BB84 cycle and return the structured result.

    Parameters
    ----------
    n_photons
        Number of photons Alice prepares.
    seed_alice, seed_bob, seed_sample, seed_eve
        Seeds for the four independent RNG streams (S-DET-01).
    eavesdrop
        When True, Eve performs an intercept-and-resend attack: she
        measures every photon in a random basis (her own RNG) and
        re-prepares for Bob using HER measured value and basis. This
        introduces a ~25% QBER on the sifted key -- the BB84 signature
        that flags eavesdropping.
    qber_threshold
        Abort threshold. Sample QBER >= threshold -> aborted=True and
        final_key=().
    sample_fraction
        Fraction of the sifted key revealed publicly to estimate QBER.
        Revealed bits are excluded from final_key.
    """
    if n_photons <= 0:
        raise ValueError(f"n_photons must be positive, got {n_photons}")
    if not 0.0 < sample_fraction < 1.0:
        raise ValueError(
            f"sample_fraction must be in (0, 1), got {sample_fraction}",
        )

    rng_alice = random.Random(seed_alice)
    rng_bob = random.Random(seed_bob)
    rng_sample = random.Random(seed_sample)
    rng_eve = random.Random(seed_eve)
    # Each photon's measurement (Eve's and Bob's) draws its own coin
    # flip from a single RNG -- this is deterministic as long as
    # measurements happen in a fixed iteration order, which they do.
    rng_meas = random.Random((seed_alice ^ seed_bob ^ seed_eve) & 0xFFFFFFFF)

    alice_bits = tuple(rng_alice.randint(0, 1) for _ in range(n_photons))
    alice_bases = tuple(
        rng_alice.choice((BASIS_PLUS, BASIS_CROSS)) for _ in range(n_photons)
    )
    bob_bases = tuple(
        rng_bob.choice((BASIS_PLUS, BASIS_CROSS)) for _ in range(n_photons)
    )

    bob_measurements: list[int] = []
    for i in range(n_photons):
        prep_bit = alice_bits[i]
        prep_basis = alice_bases[i]
        if eavesdrop:
            # Eve picks a random basis, measures, re-prepares.
            eve_basis = rng_eve.choice((BASIS_PLUS, BASIS_CROSS))
            eve_bit = measure_photon(
                prep_bit, prep_basis, eve_basis, rng_meas,
            )
            # Bob now sees Eve's re-prepared state.
            prep_bit = eve_bit
            prep_basis = eve_basis
        meas = measure_photon(
            prep_bit, prep_basis, bob_bases[i], rng_meas,
        )
        bob_measurements.append(meas)

    # Sift: keep indices where Alice's and Bob's bases match.
    sifted_indices: list[int] = []
    for i in range(n_photons):
        if alice_bases[i] == bob_bases[i]:
            sifted_indices.append(i)

    sifted_alice = tuple(alice_bits[i] for i in sifted_indices)
    sifted_bob = tuple(bob_measurements[i] for i in sifted_indices)

    # Sample reveal: pick a sub-fraction of sifted indices to compare
    # publicly. Sample QBER estimates the true QBER on the sifted key.
    n_sift = len(sifted_indices)
    n_sample = max(1, int(round(n_sift * sample_fraction))) if n_sift > 0 else 0
    # Without replacement, deterministic via rng_sample.sample over the
    # sifted-key positions.
    positions = list(range(n_sift))
    if n_sample > 0 and n_sample <= n_sift:
        sample_positions = sorted(rng_sample.sample(positions, n_sample))
    else:
        sample_positions = []
    sample_indices = tuple(sifted_indices[p] for p in sample_positions)

    if sample_positions:
        errors = sum(
            1
            for p in sample_positions
            if sifted_alice[p] != sifted_bob[p]
        )
        qber = errors / len(sample_positions)
    else:
        qber = 0.0

    aborted = qber >= qber_threshold

    if aborted:
        final_key: tuple[int, ...] = ()
    else:
        sample_set = set(sample_positions)
        final_key = tuple(
            sifted_alice[p] for p in range(n_sift) if p not in sample_set
        )

    return BB84Result(
        raw_alice_bits=alice_bits,
        alice_bases=alice_bases,
        bob_bases=bob_bases,
        bob_measurements=tuple(bob_measurements),
        sifted_indices=tuple(sifted_indices),
        sifted_alice=sifted_alice,
        sifted_bob=sifted_bob,
        sample_indices=sample_indices,
        qber=qber,
        final_key=final_key,
        aborted=aborted,
        qber_threshold=qber_threshold,
    )


def key_fingerprint(bits: Iterable[int], length: int = 16) -> str:
    """SHA-256 hex digest of the bit-packed key, truncated to ``length``
    hex characters.

    Used for ledger annotation and HMI display. The full bit-stream is
    never displayed in the HMI (per S-SEC-01 it would be a secret in
    production); only this fingerprint surfaces.

    A length of 16 hex chars = 64 bits of preimage resistance, plenty
    for "did the ledger entry consume *this* QKD key?" disambiguation.
    """
    if length <= 0:
        raise ValueError(f"length must be positive, got {length}")
    bit_list = list(bits)
    for b in bit_list:
        if b not in (0, 1):
            raise ValueError(f"bits must be 0 or 1, got {b!r}")
    # Pack bits into bytes MSB-first. Empty bit list -> hash of b"".
    n = len(bit_list)
    n_bytes = (n + 7) // 8
    buf = bytearray(n_bytes)
    for idx, bit in enumerate(bit_list):
        if bit:
            buf[idx // 8] |= 1 << (7 - (idx % 8))
    digest = hashlib.sha256(bytes(buf)).hexdigest()
    return digest[:length]
