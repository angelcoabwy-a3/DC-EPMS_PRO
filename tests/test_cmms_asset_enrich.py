"""Tests for PATCH /api/cmms/assets/{asset_id} (Sprint 7.1d-followup).

Coverage:
  - AssetEnrichRequest validation (extra=forbid, ge=0)
  - PATCH writes vendor + model into the asset row
  - PATCH writes serial + voltage into metadata_json
  - PATCH preserves untouched columns
  - PATCH 404 on nonexistent asset_id
  - PATCH 422 on extra forbidden body field
  - PATCH 422 on negative rated_capacity_kw
  - PATCH no-op body returns the asset unchanged with empty fields_written
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.cmms_models import Asset, AssetEnrichRequest
from backend.cmms_repository import MockCMMSRepository
from backend.cmms_routes import register_cmms_routes


# ─── App fixture ──────────────────────────────────────────────────────
@pytest.fixture
def client() -> tuple[TestClient, MockCMMSRepository]:
    app = FastAPI()
    repo = MockCMMSRepository()
    # The production register_cmms_routes wires app.state.cmms_repo from
    # the postgres connection pool. For tests we inject the mock directly.
    app.state.cmms_repo = repo
    from backend.cmms_routes import router
    app.include_router(router)
    return TestClient(app), repo


# ─── Pydantic model validation ────────────────────────────────────────
def test_request_extra_field_rejected():
    with pytest.raises(Exception):  # pydantic.ValidationError
        AssetEnrichRequest(
            vendor="Schneider", model="GVX750", rogue_field="should_be_blocked",
        )


def test_request_negative_capacity_rejected():
    with pytest.raises(Exception):
        AssetEnrichRequest(rated_capacity_kw=-50.0)


def test_request_negative_voltage_rejected():
    with pytest.raises(Exception):
        AssetEnrichRequest(voltage_v=-1.0)


def test_request_all_fields_optional():
    req = AssetEnrichRequest()
    assert req.vendor is None
    assert req.model is None
    assert req.serial is None
    assert req.rated_capacity_kw is None
    assert req.voltage_v is None


# ─── Endpoint behavior ────────────────────────────────────────────────
def test_patch_404_on_nonexistent_asset(client):
    c, _ = client
    r = c.patch(
        "/api/cmms/assets/nonexistent_xyz",
        json={"vendor": "Schneider Electric"},
    )
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_patch_writes_vendor_and_model(client):
    c, repo = client
    import asyncio
    asyncio.run(repo.upsert_asset_async(
        Asset(asset_id="ups_a", display_name="UPS A", asset_type="ups",
              vendor=None, model=None, criticality_class="critical"),
    ))
    r = c.patch(
        "/api/cmms/assets/ups_a",
        json={
            "vendor": "Schneider Electric",
            "model": "GVX750-N480",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["asset"]["vendor"] == "Schneider Electric"
    assert body["asset"]["model"] == "GVX750-N480"
    assert sorted(body["fields_written"]) == ["model", "vendor"]


def test_patch_writes_serial_into_metadata_json(client):
    c, repo = client
    import asyncio
    asyncio.run(repo.upsert_asset_async(
        Asset(asset_id="ups_a", display_name="UPS A", asset_type="ups",
              metadata_json={"existing_key": "preserve_me"}),
    ))
    r = c.patch(
        "/api/cmms/assets/ups_a",
        json={
            "serial": "SVX-2024-008812",
            "voltage_v": 480.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    md = body["asset"]["metadata_json"]
    assert md["serial"] == "SVX-2024-008812"
    assert md["voltage_nominal_v"] == 480.0
    assert md["existing_key"] == "preserve_me"   # not clobbered
    assert body["fields_written"] == ["metadata_json"]


def test_patch_preserves_untouched_columns(client):
    c, repo = client
    import asyncio
    asyncio.run(repo.upsert_asset_async(
        Asset(asset_id="ups_a", display_name="UPS A", asset_type="ups",
              vendor="Old Vendor", model="OLD-001",
              rated_capacity_kw=2500.0, criticality_class="critical",
              redundancy_pillar="2N", path="A"),
    ))
    r = c.patch(
        "/api/cmms/assets/ups_a",
        json={"vendor": "Schneider Electric"},
    )
    assert r.status_code == 200
    asset = r.json()["asset"]
    assert asset["vendor"] == "Schneider Electric"   # changed
    assert asset["model"] == "OLD-001"                # preserved
    assert asset["rated_capacity_kw"] == 2500.0       # preserved
    assert asset["criticality_class"] == "critical"   # preserved
    assert asset["redundancy_pillar"] == "2N"         # preserved
    assert asset["path"] == "A"                       # preserved


def test_patch_extra_field_returns_422(client):
    c, repo = client
    import asyncio
    asyncio.run(repo.upsert_asset_async(
        Asset(asset_id="ups_a", display_name="UPS A", asset_type="ups"),
    ))
    r = c.patch(
        "/api/cmms/assets/ups_a",
        json={"vendor": "Schneider", "rogue": "blocked"},
    )
    assert r.status_code == 422
    assert "extra_forbidden" in str(r.json())


def test_patch_empty_body_is_noop(client):
    c, repo = client
    import asyncio
    asyncio.run(repo.upsert_asset_async(
        Asset(asset_id="ups_a", display_name="UPS A", asset_type="ups",
              vendor="Schneider"),
    ))
    r = c.patch("/api/cmms/assets/ups_a", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["asset"]["vendor"] == "Schneider"
    assert body["fields_written"] == []


def test_patch_audit_trail_records_enriched_by(client):
    c, repo = client
    import asyncio
    asyncio.run(repo.upsert_asset_async(
        Asset(asset_id="ups_a", display_name="UPS A", asset_type="ups"),
    ))
    r = c.patch(
        "/api/cmms/assets/ups_a",
        json={"vendor": "Schneider", "enriched_by": "wilmer"},
    )
    assert r.status_code == 200
    md = r.json()["asset"]["metadata_json"]
    assert md.get("enriched_by") == "wilmer"


# ─── End-to-end matcher closure ───────────────────────────────────────
def test_patch_then_match_returns_link_to_existing(client):
    """The whole point of the endpoint: enrichment closes the loop so
    nameplate matcher returns link_to_existing on the next extract."""
    from backend.tech_assist.nameplate_ocr import (
        NameplateFields, match_assets, suggest_action,
    )
    c, repo = client
    import asyncio
    asyncio.run(repo.upsert_asset_async(
        Asset(asset_id="ups_a", display_name="UPS A", asset_type="ups",
              vendor=None, model=None, rated_capacity_kw=2500.0),
    ))

    # Before enrichment: no match (vendor is null on the asset)
    fields = NameplateFields(
        vendor="Schneider Electric", model="GVX750-N480",
        serial="SVX-2024-008812",
        rated_capacity_value=2500.0, rated_capacity_unit="kVA",
        voltage_nominal_v=480.0,
    )
    cands_before = match_assets(
        fields,
        asyncio.run(repo.list_assets_async()),
        top_k=3,
    )
    action_before = suggest_action(cands_before)
    assert action_before["action"] == "seed_new_asset"

    # Enrich via the endpoint
    r = c.patch(
        "/api/cmms/assets/ups_a",
        json={
            "vendor": "Schneider Electric",
            "model": "GVX750-N480",
            "serial": "SVX-2024-008812",
            "voltage_v": 480.0,
        },
    )
    assert r.status_code == 200

    # After enrichment: serial_exact + vendor + model + voltage all match
    cands_after = match_assets(
        fields,
        asyncio.run(repo.list_assets_async()),
        top_k=3,
    )
    action_after = suggest_action(cands_after)
    assert action_after["action"] == "link_to_existing"
    assert action_after["asset_id"] == "ups_a"
    assert cands_after[0].score >= 0.80
