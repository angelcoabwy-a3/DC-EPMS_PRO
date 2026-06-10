r"""
backend.telemetry_proto.v1 -- canonical v1 wire schema (Epic 8).

Source of truth: ``telemetry.proto`` (versioned in git alongside this
package). The generated proto3 stub lives at ``telemetry_pb2.py`` --
regenerate with:

    .\scripts\gen_telemetry_proto_stubs.ps1

The schema is audited by ``tests/test_telemetry_proto_schema.py``
which parses the .proto as text and asserts panel-grade invariants
(vocabulary fence, strict SI units, MeasurementQuality propagation,
sub-us PTP timestamps on event messages, UPS 5-way split, OCP CDU
mapping).

Public re-exports
-----------------
The generated module is re-exported by name so callers can do::

    from backend.telemetry_proto.v1 import telemetry_pb2

which is the canonical import path.
"""
from __future__ import annotations

import contextlib

# If the stub has not been generated yet, run the orchestrator.
with contextlib.suppress(ImportError):
    from . import telemetry_pb2  # noqa: F401  (re-export)
