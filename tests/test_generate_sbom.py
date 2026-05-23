"""
tests/test_generate_sbom.py
============================
DC-EPMS-MSD-007 — scripts/generate_sbom.py.

Validates the CycloneDX 1.5 SBOM generator contract:
  * BOM envelope shape (specVersion, $schema, serialNumber, metadata).
  * Python component walk emits at least one entry (the interpreter
    that runs the tests is itself an importlib.metadata source).
  * Node component walk parses package-lock.json (lockfile v3) and
    package.json (no-lockfile fallback).
  * License normalisation collapses str / dict / list shapes into the
    CycloneDX ``licenses`` array.
  * The driver emits the three artifacts (python / node / summary)
    with stable JSON formatting (LF newlines, sort_keys=True).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the script importable as a module without installing it.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import generate_sbom  # noqa: E402


# ─── License normalisation ────────────────────────────────────────────
def test_normalise_license_handles_spdx_str():
    out = generate_sbom._normalise_license("MIT")
    assert out == [{"license": {"id": "MIT"}}]


def test_normalise_license_handles_freeform_str():
    out = generate_sbom._normalise_license("MIT or commercial")
    assert out == [{"license": {"name": "MIT or commercial"}}]


def test_normalise_license_returns_none_for_empty():
    assert generate_sbom._normalise_license("") is None
    assert generate_sbom._normalise_license("   ") is None
    assert generate_sbom._normalise_license(None) is None


def test_normalise_license_handles_dict():
    out = generate_sbom._normalise_license({"id": "Apache-2.0"})
    assert out == [{"license": {"id": "Apache-2.0"}}]


def test_normalise_license_handles_list():
    out = generate_sbom._normalise_license(["MIT", {"id": "BSD-3-Clause"}])
    assert out == [
        {"license": {"id": "MIT"}},
        {"license": {"id": "BSD-3-Clause"}},
    ]


# ─── Python component walk ────────────────────────────────────────────
def test_collect_python_components_non_empty():
    components = generate_sbom.collect_python_components()
    # The interpreter that runs pytest has at least pytest itself,
    # ruff, fastapi, etc. — well above one component.
    assert len(components) >= 1
    sample = components[0]
    for key in ("type", "bom-ref", "name", "version", "purl"):
        assert key in sample
    assert sample["type"] == "library"
    assert sample["purl"].startswith("pkg:pypi/")


def test_collect_python_components_is_sorted_and_deduped():
    components = generate_sbom.collect_python_components()
    names = [c["name"].lower() for c in components]
    assert names == sorted(names)
    # No duplicates by (name, version)
    keys = [(c["name"].lower(), c["version"]) for c in components]
    assert len(keys) == len(set(keys))


def test_collect_python_picks_up_pytest():
    components = generate_sbom.collect_python_components()
    names = {c["name"].lower() for c in components}
    # Pytest is what's running this test — it must appear.
    assert "pytest" in names


# ─── Node component walk ──────────────────────────────────────────────
def test_collect_node_components_from_lockfile(tmp_path: Path):
    lock = {
        "name": "fake", "version": "0.0.1", "lockfileVersion": 3,
        "packages": {
            "": {"name": "fake", "version": "0.0.1"},
            "node_modules/foo": {
                "version": "1.2.3", "license": "MIT",
                "integrity": "sha512-AAAA",
            },
            "node_modules/@scope/bar": {
                "version": "0.5.0", "license": "Apache-2.0", "dev": True,
            },
        },
    }
    (tmp_path / "package-lock.json").write_text(
        json.dumps(lock), encoding="utf-8",
    )
    out = generate_sbom.collect_node_components(tmp_path)
    names = [c["name"] for c in out]
    assert "foo" in names
    assert "@scope/bar" in names
    foo = next(c for c in out if c["name"] == "foo")
    assert foo["version"] == "1.2.3"
    assert foo["purl"] == "pkg:npm/foo@1.2.3"
    assert foo["licenses"] == [{"license": {"id": "MIT"}}]
    assert foo["hashes"] == [{"alg": "SHA512", "content": "AAAA"}]
    # Dev-only dep marked as excluded scope
    bar = next(c for c in out if c["name"] == "@scope/bar")
    assert bar["scope"] == "excluded"


def test_collect_node_components_fallback_to_packagejson(tmp_path: Path):
    pkg = {
        "name": "no-lockfile",
        "dependencies": {"runtime-dep": "^1.0.0"},
        "devDependencies": {"dev-dep": "~2.0.0"},
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    # No lockfile -> packagejson fallback.
    out = generate_sbom.collect_node_components(tmp_path)
    names = {c["name"] for c in out}
    assert names == {"runtime-dep", "dev-dep"}
    rd = next(c for c in out if c["name"] == "runtime-dep")
    assert rd["version"] == "1.0.0"  # range prefix stripped
    assert rd["scope"] == "required"
    dd = next(c for c in out if c["name"] == "dev-dep")
    assert dd["scope"] == "excluded"


def test_collect_node_components_empty_repo_returns_empty(tmp_path: Path):
    assert generate_sbom.collect_node_components(tmp_path) == []


# ─── Driver — generate() emits all three artifacts ───────────────────
def test_generate_writes_three_files(tmp_path: Path):
    # Build a minimal repo: just a package.json so node walk has data.
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"d": "1.0.0"}}),
        encoding="utf-8",
    )
    out = tmp_path / "sbom"
    summary = generate_sbom.generate(tmp_path, out)
    assert (out / "python.cyclonedx.json").exists()
    assert (out / "node.cyclonedx.json").exists()
    assert (out / "sbom-summary.json").exists()
    # Summary mirrors the in-memory return.
    assert summary["python"]["components"] >= 1
    assert summary["node"]["components"] >= 1


def test_generate_bom_envelope_is_cyclonedx_1_5(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x"}), encoding="utf-8",
    )
    out = tmp_path / "sbom"
    generate_sbom.generate(tmp_path, out)
    for fn in ("python.cyclonedx.json", "node.cyclonedx.json"):
        d = json.loads((out / fn).read_text(encoding="utf-8"))
        assert d["bomFormat"] == "CycloneDX"
        assert d["specVersion"] == "1.5"
        assert d["$schema"].endswith("bom-1.5.schema.json")
        assert d["serialNumber"].startswith("urn:uuid:")
        assert isinstance(d["components"], list)
        # Metadata envelope
        assert "metadata" in d
        assert "timestamp" in d["metadata"]
        assert "tools" in d["metadata"]


def test_generate_outputs_are_lf_terminated(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x"}), encoding="utf-8",
    )
    out = tmp_path / "sbom"
    generate_sbom.generate(tmp_path, out)
    # Stable JSON: 2-space indent + LF terminator so a `git diff` shows
    # real dependency drift, not CRLF noise.
    raw = (out / "python.cyclonedx.json").read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r\n" not in raw


def test_generate_summary_is_byte_stable_excluding_timestamps(tmp_path: Path):
    """Running the generator twice over the same repo MUST produce
    summaries that differ only in ``generated_at`` (and the per-BOM
    serials, which are not in the summary). This is the contract that
    lets CI compare SBOM drift across commits."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"d": "1.0.0"}}),
        encoding="utf-8",
    )
    out = tmp_path / "sbom"
    generate_sbom.generate(tmp_path, out)
    s1 = json.loads((out / "sbom-summary.json").read_text(encoding="utf-8"))
    generate_sbom.generate(tmp_path, out)
    s2 = json.loads((out / "sbom-summary.json").read_text(encoding="utf-8"))
    # Strip the volatile fields then compare.
    for s in (s1, s2):
        s.pop("generated_at", None)
        for k in ("python", "node"):
            s.get(k, {}).pop("serial", None)
    assert s1 == s2


# ─── Driver — CLI ────────────────────────────────────────────────────
def test_main_returns_zero_and_writes_default_out(tmp_path: Path, monkeypatch):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x"}), encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    rc = generate_sbom.main(["--quiet"])
    assert rc == 0
    assert (tmp_path / "sbom" / "python.cyclonedx.json").exists()
    assert (tmp_path / "sbom" / "node.cyclonedx.json").exists()


@pytest.mark.parametrize("subdir", ["custom-out", "deep/nested/out"])
def test_main_respects_out_flag(tmp_path: Path, monkeypatch, subdir: str):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x"}), encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    rc = generate_sbom.main(["--quiet", "--out", subdir])
    assert rc == 0
    assert (tmp_path / subdir / "python.cyclonedx.json").exists()
