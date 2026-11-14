"""
tests/conftest.py -- session-wide test settings.

DC-EPMS-069: any test that enters the REAL app lifespan
(``with TestClient(main.app)``) would run the boot warmup, which
imports sentence-transformers -> sklearn -> pyarrow and FAISS AVX2.
On the operator's AMD Ryzen + Windows workstation both die with a
native access violation (DC-EPMS-001 family) and take the whole pytest
process down. The warmup is a latency optimisation, never under test,
so it is off for the whole session. A test that wants it back must
``monkeypatch.delenv("DC_EPMS_SKIP_WARMUP")`` explicitly (see
tests/test_no_database_mode.py::TestWarmupSkip).
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _skip_boot_warmup():
    previous = os.environ.get("DC_EPMS_SKIP_WARMUP")
    os.environ["DC_EPMS_SKIP_WARMUP"] = "1"
    yield
    if previous is None:
        os.environ.pop("DC_EPMS_SKIP_WARMUP", None)
    else:
        os.environ["DC_EPMS_SKIP_WARMUP"] = previous
