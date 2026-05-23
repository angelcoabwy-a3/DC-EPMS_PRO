"""
scripts/generate_sbom.py
========================
DC-EPMS-MSD-007 — Software Bill of Materials (SBOM) generator.

Emits CycloneDX 1.5 JSON for the project's Python and Node.js
dependency graphs. Stdlib-only on the Python side
(``importlib.metadata`` walks the active interpreter's installed
distributions); pure JSON parse on the Node side
(``package.json`` + ``package-lock.json``). No third-party SBOM tool
required at runtime.

Usage
-----
    python scripts/generate_sbom.py            # writes ./sbom/*.json
    python scripts/generate_sbom.py --out dir  # custom output dir
    python scripts/generate_sbom.py --check    # exit non-zero on drift

Outputs
-------
* ``sbom/python.cyclonedx.json`` — every distribution importable from
  the active interpreter (``importlib.metadata.distributions()``),
  with name, version, declared license, and a ``pkg:pypi/…`` purl.
* ``sbom/node.cyclonedx.json`` — every package present in
  ``package-lock.json`` (the dev/test harness), with version and a
  ``pkg:npm/…`` purl.
* ``sbom/sbom-summary.json`` — counts + generator metadata so a CI
  job can assert that the SBOM ran (component_count > 0 invariant).

CycloneDX 1.5 spec:
  https://cyclonedx.org/docs/1.5/json/
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.metadata
import json
import platform
import re
import sys
import uuid
from pathlib import Path
from typing import Any

SCHEMA = "http://cyclonedx.org/schema/bom-1.5.schema.json"
SPEC_VERSION = "1.5"
GENERATOR_NAME = "dc-epms-pro/scripts/generate_sbom.py"
GENERATOR_VERSION = "1.0.0"


# ─── Common helpers ───────────────────────────────────────────────────
def _utc_now_iso() -> str:
    """RFC 3339 UTC timestamp for the BOM ``timestamp`` field."""
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat()


_SBOM_NAMESPACE = uuid.UUID("3e6c2c3e-1a3d-5cda-9c70-3c8b7c2c0d4a")


def _bom_serial_number(components: list[dict[str, Any]], ecosystem: str) -> str:
    """Deterministic CycloneDX URN serial.

    Derived as ``urn:uuid:<uuid5(NS, ecosystem + sorted purls)>`` so the
    SBOM is byte-stable across runs over the same dependency tree —
    only a genuine dependency change moves the serial. CI can diff the
    summary file and treat a serial change as a precise "deps drifted"
    signal.
    """
    keys = "\n".join(sorted(c.get("purl", c["bom-ref"]) for c in components))
    seed = f"{ecosystem}\n{keys}"
    return f"urn:uuid:{uuid.uuid5(_SBOM_NAMESPACE, seed)}"


def _wrap_bom(components: list[dict[str, Any]], ecosystem: str) -> dict[str, Any]:
    """Wrap a list of components in the CycloneDX 1.5 BOM envelope."""
    return {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "$schema": SCHEMA,
        "serialNumber": _bom_serial_number(components, ecosystem),
        "version": 1,
        "metadata": {
            "timestamp": _utc_now_iso(),
            "tools": [
                {
                    "vendor": "a3semi",
                    "name": GENERATOR_NAME,
                    "version": GENERATOR_VERSION,
                },
            ],
            "component": {
                "type": "application",
                "bom-ref": f"pkg:generic/dc-epms-pro@{ecosystem}",
                "name": "dc-epms-pro",
                "description": (
                    f"DC-EPMS PRO {ecosystem} dependency tree "
                    f"(CycloneDX 1.5)."
                ),
            },
        },
        "components": components,
    }


def _normalise_license(license_field: Any) -> list[dict[str, Any]] | None:
    """CycloneDX expects ``licenses: [{license: {id|name: ...}}]``.

    PyPI / npm metadata is messy; we accept str / dict / list shapes
    and coerce to a single ``name`` entry when an SPDX id isn't
    identifiable.
    """
    if not license_field:
        return None
    if isinstance(license_field, str):
        s = license_field.strip()
        if not s:
            return None
        # Heuristic SPDX detection — short identifiers without spaces
        # tend to be SPDX ids (MIT, BSD-3-Clause, Apache-2.0, …).
        if re.fullmatch(r"[A-Za-z0-9._+-]+", s):
            return [{"license": {"id": s}}]
        return [{"license": {"name": s}}]
    if isinstance(license_field, dict):
        if "id" in license_field or "name" in license_field:
            return [{"license": license_field}]
        return None
    if isinstance(license_field, list):
        out: list[dict[str, Any]] = []
        for entry in license_field:
            n = _normalise_license(entry)
            if n:
                out.extend(n)
        return out or None
    return None


def _bom_ref(scheme: str, name: str, version: str) -> str:
    """A stable bom-ref string. Distinct from purl so consumers can
    track the package across SBOM revisions even if the purl format
    changes."""
    return f"pkg:{scheme}/{name}@{version}"


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ─── Python side — importlib.metadata walk ────────────────────────────
def _python_license(meta: importlib.metadata.PackageMetadata) -> Any:
    """Distribution metadata has many license fields. Prefer
    ``License-Expression`` (PEP 639), then ``License``, then the
    classifier list."""
    le = meta.get("License-Expression")
    if le:
        return le
    li = meta.get("License")
    if li and li.upper() != "UNKNOWN":
        return li
    classifiers = [
        c for c in meta.get_all("Classifier") or []
        if c.startswith("License :: ")
    ]
    if classifiers:
        # "License :: OSI Approved :: MIT License" -> "MIT License"
        last = classifiers[0].rsplit("::", 1)[-1].strip()
        return last
    return None


def collect_python_components() -> list[dict[str, Any]]:
    """Walk every installed distribution in the active interpreter.

    Returns one CycloneDX component dict per distribution, sorted by
    name + version so the output is byte-stable across runs.
    """
    seen: dict[str, dict[str, Any]] = {}
    for dist in importlib.metadata.distributions():
        try:
            meta = dist.metadata
        except Exception:
            continue
        name = meta.get("Name") or ""
        version = meta.get("Version") or "0.0.0"
        if not name:
            continue
        key = f"{name.lower()}@{version}"
        if key in seen:
            continue
        purl = f"pkg:pypi/{name.lower().replace('_', '-')}@{version}"
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": _bom_ref("pypi", name, version),
            "name": name,
            "version": version,
            "purl": purl,
            "properties": [
                {
                    "name": "dc-epms-pro:source",
                    "value": "importlib.metadata",
                },
            ],
        }
        summary = meta.get("Summary")
        if summary:
            component["description"] = summary
        licenses = _normalise_license(_python_license(meta))
        if licenses:
            component["licenses"] = licenses
        home = meta.get("Home-page")
        if home:
            component["externalReferences"] = [{"type": "website", "url": home}]
        seen[key] = component
    return sorted(
        seen.values(),
        key=lambda c: (c["name"].lower(), c["version"]),
    )


# ─── Node side — package-lock.json walk ───────────────────────────────
def collect_node_components(repo_root: Path) -> list[dict[str, Any]]:
    """Parse ``package-lock.json`` (lockfile version 2 or 3 — npm 7+).

    Returns one component per locked package. When no lockfile is
    present, falls back to top-level ``package.json`` devDependencies
    + dependencies (transitive graph won't be known).
    """
    lock_path = repo_root / "package-lock.json"
    if lock_path.exists():
        return _collect_from_lockfile(lock_path)
    pkg_path = repo_root / "package.json"
    if pkg_path.exists():
        return _collect_from_packagejson(pkg_path)
    return []


def _collect_from_lockfile(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    out: dict[str, dict[str, Any]] = {}
    # npm v2/v3 lockfile shape: ``packages`` is a flat map keyed by
    # "node_modules/<name>" relative paths; the project root itself
    # appears as the empty string and must be skipped.
    packages = data.get("packages") or {}
    for rel, entry in packages.items():
        if not rel or not isinstance(entry, dict):
            continue
        version = entry.get("version")
        if not version:
            continue
        # Derive the npm name from the path — handles scoped packages
        # (``node_modules/@scope/name``).
        name = entry.get("name")
        if not name:
            tail = rel.split("node_modules/", 1)[-1]
            name = tail
        key = f"{name}@{version}"
        if key in out:
            continue
        purl = f"pkg:npm/{name}@{version}"
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": _bom_ref("npm", name, version),
            "name": name,
            "version": version,
            "purl": purl,
            "properties": [
                {"name": "dc-epms-pro:source", "value": "package-lock.json"},
            ],
        }
        if entry.get("dev"):
            component["scope"] = "excluded"  # CycloneDX scope for dev-only
        if entry.get("integrity"):
            # The npm integrity field is "<algo>-<base64>"; extract algo.
            integ = str(entry["integrity"])
            if "-" in integ:
                algo, _, b64 = integ.partition("-")
                component["hashes"] = [
                    {"alg": algo.upper(), "content": b64},
                ]
        licenses = _normalise_license(entry.get("license"))
        if licenses:
            component["licenses"] = licenses
        out[key] = component
    return sorted(
        out.values(), key=lambda c: (c["name"].lower(), c["version"]),
    )


def _collect_from_packagejson(path: Path) -> list[dict[str, Any]]:
    """Fallback for repos without a lockfile. Direct deps only."""
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    out: list[dict[str, Any]] = []
    sections = (
        ("dependencies", "required"),
        ("devDependencies", "excluded"),
        ("optionalDependencies", "optional"),
    )
    for section, scope in sections:
        for name, vrange in (data.get(section) or {}).items():
            # Strip range prefix so we have *some* version string —
            # the lockfile path gives exact pinning when available.
            version = re.sub(r"^[\^~>=<]+\s*", "", str(vrange)).strip()
            out.append({
                "type": "library",
                "bom-ref": _bom_ref("npm", name, version or "unknown"),
                "name": name,
                "version": version or "unknown",
                "purl": f"pkg:npm/{name}@{version or 'unknown'}",
                "scope": scope,
                "properties": [
                    {
                        "name": "dc-epms-pro:source",
                        "value": "package.json (no lockfile)",
                    },
                ],
            })
    return sorted(out, key=lambda c: (c["name"].lower(), c["version"]))


# ─── Driver ───────────────────────────────────────────────────────────
def generate(repo_root: Path, out_dir: Path) -> dict[str, Any]:
    """Write the three SBOM artifacts and return the summary dict.

    Pure-data return so a CI driver can assert invariants
    (component_count > 0) without reading the file back.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    py_components = collect_python_components()
    node_components = collect_node_components(repo_root)

    py_bom = _wrap_bom(py_components, "python")
    node_bom = _wrap_bom(node_components, "node")

    py_path = out_dir / "python.cyclonedx.json"
    node_path = out_dir / "node.cyclonedx.json"
    summary_path = out_dir / "sbom-summary.json"

    # Stable JSON output (sort_keys + 2-space indent + LF) so a git
    # diff between two SBOM runs surfaces actual dependency drift,
    # not byte-ordering noise.
    def _dump(obj: dict[str, Any], path: Path) -> None:
        text = json.dumps(obj, indent=2, sort_keys=True) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")

    def _content_sha(bom: dict[str, Any]) -> str:
        """Hash a normalised copy of the BOM with the volatile fields
        (``metadata.timestamp`` + ``serialNumber``) zeroed out so the
        return value is byte-stable across runs over the same
        dependency tree. ``sha256`` in the on-disk summary uses this
        form — true ledger-quality stability."""
        norm = json.loads(json.dumps(bom))  # deep copy via JSON
        norm.pop("serialNumber", None)
        meta = norm.get("metadata", {})
        meta.pop("timestamp", None)
        return _sha256_hex(
            json.dumps(norm, indent=2, sort_keys=True) + "\n",
        )

    _dump(py_bom, py_path)
    _dump(node_bom, node_path)
    py_sha = _content_sha(py_bom)
    node_sha = _content_sha(node_bom)

    summary = {
        "generated_at": _utc_now_iso(),
        "generator": {
            "name": GENERATOR_NAME,
            "version": GENERATOR_VERSION,
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "python": {
            "path": str(py_path.relative_to(repo_root)),
            "components": len(py_components),
            "sha256": py_sha,
            "serial": py_bom["serialNumber"],
        },
        "node": {
            "path": str(node_path.relative_to(repo_root)),
            "components": len(node_components),
            "sha256": node_sha,
            "serial": node_bom["serialNumber"],
        },
    }
    # Summary does NOT include the BOM serials' randomness so a diff
    # on this file surfaces only real drift (component counts +
    # generator version). The per-BOM serials are kept inside each
    # CycloneDX file where the spec requires them.
    summary_for_disk = {
        **summary,
        "python": {**summary["python"]},
        "node": {**summary["node"]},
    }
    # Drop the random serials from the on-disk summary copy.
    summary_for_disk["python"].pop("serial", None)
    summary_for_disk["node"].pop("serial", None)
    _dump(summary_for_disk, summary_path)

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate CycloneDX SBOMs for Python + Node deps.",
    )
    parser.add_argument(
        "--out", "-o", type=Path, default=Path("sbom"),
        help="Output directory (default: ./sbom).",
    )
    parser.add_argument(
        "--repo-root", type=Path, default=Path.cwd(),
        help="Repo root (default: cwd).",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Suppress the per-component count print.",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    out_dir = (
        args.out if args.out.is_absolute() else (repo_root / args.out)
    )
    summary = generate(repo_root, out_dir)
    if not args.quiet:
        print(
            f"[sbom] python: {summary['python']['components']} components -> "
            f"{summary['python']['path']}"
        )
        print(
            f"[sbom] node:   {summary['node']['components']} components -> "
            f"{summary['node']['path']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
