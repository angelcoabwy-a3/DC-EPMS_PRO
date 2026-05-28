"""
tests/test_bb84_crypto.py
=========================
Epic 9 -- BB84 simulator invariants.

This is an EDUCATIONAL deterministic simulator of the BB84 protocol
(Bennett & Brassard 1984). Real QKD requires single-photon hardware
on a free-space or fibre channel; this module simulates the bit-and-
basis bookkeeping with seeded `random.Random` instances so the entire
flow is reproducible (S-DET-01 spirit).

Invariants under test:
  - Single-photon measurement: same-basis preserves the bit; orthogonal
    basis yields a uniform 50/50 outcome.
  - Clean channel: bases-matched bits agree -> QBER == 0.0 across the
    sifted set.
  - Sifted key length is approximately N/2 (Bob's basis matches Alice's
    half the time on average).
  - Determinism: identical seeds -> identical (alice_bits, bob_meas,
    sample_indices, qber, final_key).
  - Eavesdropper detection: intercept-and-resend introduces ~25% QBER
    on the sifted key (the famous BB84 signature).
  - Threshold abort: QBER >= 0.11 sets aborted=True; final_key MUST be
    empty in the aborted path so a downstream consumer cannot
    accidentally use a contaminated key.
  - Fingerprint helper: stable hex, length-truncated, avalanches on a
    one-bit flip, deterministic on the empty key.
"""

from __future__ import annotations

import pytest

from backend.crypto import bb84_core


# ────────────────────────────────────────────────────────────────────
# Single-photon measurement
# ────────────────────────────────────────────────────────────────────
class TestBasisMeasurement:
    def test_same_basis_plus_preserves_bit(self) -> None:
        import random

        rng = random.Random(0)
        for bit in (0, 1):
            for _ in range(50):
                assert bb84_core.measure_photon(bit, "+", "+", rng) == bit

    def test_same_basis_cross_preserves_bit(self) -> None:
        import random

        rng = random.Random(0)
        for bit in (0, 1):
            for _ in range(50):
                assert bb84_core.measure_photon(bit, "x", "x", rng) == bit

    def test_orthogonal_basis_yields_uniform_distribution(self) -> None:
        import random

        rng = random.Random(42)
        # 1000 measurements of bit=0 prepared in '+' but measured in 'x'
        outcomes = [
            bb84_core.measure_photon(0, "+", "x", rng) for _ in range(1000)
        ]
        ones = sum(outcomes)
        # 95% binomial CI for p=0.5, n=1000: roughly 470..530
        assert 430 <= ones <= 570, f"expected ~500, got {ones}"

    def test_invalid_basis_raises(self) -> None:
        import random

        rng = random.Random(0)
        with pytest.raises(ValueError, match="meas_basis"):
            bb84_core.measure_photon(0, "+", "y", rng)
        with pytest.raises(ValueError, match="prep_basis"):
            bb84_core.measure_photon(0, "z", "+", rng)

    def test_invalid_bit_raises(self) -> None:
        import random

        rng = random.Random(0)
        with pytest.raises(ValueError, match="bit must be 0 or 1"):
            bb84_core.measure_photon(2, "+", "+", rng)


# ────────────────────────────────────────────────────────────────────
# Clean channel (no Eve)
# ────────────────────────────────────────────────────────────────────
class TestRunBB84CleanChannel:
    def test_clean_channel_qber_zero(self) -> None:
        result = bb84_core.run_bb84(
            n_photons=400,
            seed_alice=11,
            seed_bob=22,
            seed_sample=33,
            eavesdrop=False,
            qber_threshold=0.11,
        )
        assert result.qber == 0.0
        assert result.aborted is False

    def test_sifted_key_length_roughly_half(self) -> None:
        result = bb84_core.run_bb84(
            n_photons=1000,
            seed_alice=1,
            seed_bob=2,
            seed_sample=3,
        )
        sifted_len = len(result.sifted_alice)
        # Binomial p=0.5, n=1000 -> 95% CI ~ 438..562
        assert 400 <= sifted_len <= 600, (
            f"sifted_len={sifted_len} far from N/2=500"
        )

    def test_sifted_bob_matches_sifted_alice_on_clean_channel(self) -> None:
        result = bb84_core.run_bb84(
            n_photons=200,
            seed_alice=7,
            seed_bob=8,
            seed_sample=9,
        )
        assert result.sifted_alice == result.sifted_bob

    def test_final_key_excludes_sample_indices(self) -> None:
        result = bb84_core.run_bb84(
            n_photons=200,
            seed_alice=7,
            seed_bob=8,
            seed_sample=9,
            sample_fraction=0.5,
        )
        # Sample bits are revealed publicly -> dropped from final key.
        expected_len = len(result.sifted_alice) - len(result.sample_indices)
        assert len(result.final_key) == expected_len


# ────────────────────────────────────────────────────────────────────
# Determinism (S-DET-01)
# ────────────────────────────────────────────────────────────────────
class TestDeterminism:
    def test_same_seeds_same_output(self) -> None:
        a = bb84_core.run_bb84(
            n_photons=300, seed_alice=5, seed_bob=6, seed_sample=7,
        )
        b = bb84_core.run_bb84(
            n_photons=300, seed_alice=5, seed_bob=6, seed_sample=7,
        )
        assert a == b

    def test_different_alice_seed_different_output(self) -> None:
        a = bb84_core.run_bb84(
            n_photons=300, seed_alice=5, seed_bob=6, seed_sample=7,
        )
        b = bb84_core.run_bb84(
            n_photons=300, seed_alice=999, seed_bob=6, seed_sample=7,
        )
        assert a.raw_alice_bits != b.raw_alice_bits

    def test_different_bob_seed_changes_sifted_set(self) -> None:
        a = bb84_core.run_bb84(
            n_photons=300, seed_alice=5, seed_bob=6, seed_sample=7,
        )
        b = bb84_core.run_bb84(
            n_photons=300, seed_alice=5, seed_bob=42, seed_sample=7,
        )
        # Same Alice bits + bases, different Bob bases -> different
        # sifted set in general.
        assert a.bob_bases != b.bob_bases


# ────────────────────────────────────────────────────────────────────
# Eavesdropper detection (the BB84 signature)
# ────────────────────────────────────────────────────────────────────
class TestEavesdropper:
    def test_eve_introduces_qber_near_25pct(self) -> None:
        """Intercept-and-resend in a random basis disturbs ~25% of
        the bases-matched bits (when Eve picks the wrong basis, Bob
        sees a 50/50 outcome -> 50% of 50% = 25% error rate)."""
        result = bb84_core.run_bb84(
            n_photons=2000,
            seed_alice=11,
            seed_bob=22,
            seed_sample=33,
            eavesdrop=True,
            seed_eve=44,
            qber_threshold=0.99,  # don't abort -- we want to observe QBER
        )
        # Expected ~0.25. Wide tolerance for the n=~1000 sample.
        assert 0.18 <= result.qber <= 0.32, (
            f"intercept-resend QBER={result.qber:.3f} far from 0.25"
        )

    def test_eve_triggers_abort_above_threshold(self) -> None:
        result = bb84_core.run_bb84(
            n_photons=2000,
            seed_alice=11,
            seed_bob=22,
            seed_sample=33,
            eavesdrop=True,
            seed_eve=44,
            qber_threshold=0.11,
        )
        assert result.aborted is True
        assert result.qber >= 0.11
        # Contaminated key MUST NOT be returned -- aborted runs yield
        # an empty final_key so downstream consumers cannot misuse it.
        assert result.final_key == ()

    def test_no_eve_does_not_abort(self) -> None:
        result = bb84_core.run_bb84(
            n_photons=400,
            seed_alice=11,
            seed_bob=22,
            seed_sample=33,
            eavesdrop=False,
            qber_threshold=0.11,
        )
        assert result.aborted is False
        assert len(result.final_key) > 0


# ────────────────────────────────────────────────────────────────────
# Fingerprint helper (for ledger payload + HMI display)
# ────────────────────────────────────────────────────────────────────
class TestKeyFingerprint:
    def test_fingerprint_is_hex(self) -> None:
        fp = bb84_core.key_fingerprint((0, 1, 1, 0, 1, 0, 1, 1), length=16)
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)

    def test_fingerprint_default_length(self) -> None:
        fp = bb84_core.key_fingerprint((0, 1, 0, 1))
        assert len(fp) == 16  # default

    def test_fingerprint_avalanches_on_one_bit_flip(self) -> None:
        fp_a = bb84_core.key_fingerprint((0,) * 64)
        flipped = (1,) + (0,) * 63
        fp_b = bb84_core.key_fingerprint(flipped)
        # SHA-256 avalanche: a 1-bit input flip changes ~50% of output
        # bits. We just assert non-equality (the test would be flaky
        # otherwise on a 16-char truncation).
        assert fp_a != fp_b

    def test_fingerprint_empty_key_stable(self) -> None:
        fp_a = bb84_core.key_fingerprint(())
        fp_b = bb84_core.key_fingerprint(())
        assert fp_a == fp_b

    def test_fingerprint_rejects_non_bit_values(self) -> None:
        with pytest.raises(ValueError, match="bits must be 0 or 1"):
            bb84_core.key_fingerprint((0, 1, 2))
