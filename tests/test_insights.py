from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from nyc_civic.api import create_app
from nyc_civic.config import Settings
from nyc_civic.db import Database
from nyc_civic.insights import district_score_context, indicator_ids_for_node
from nyc_civic.schemas import DistrictInsight
from tests.platform_records import load_records


def test_district_context_contains_only_stored_indicator_data(tmp_path) -> None:
    settings = Settings(storage_dir=tmp_path, database_path=tmp_path / "platform.sqlite3")
    store = Database(settings)
    load_records(store)
    context, evidence = district_score_context(store, "cd:101", "subcategory", "public_parks")
    assert context["selected_node"] == {"node_type": "subcategory", "node_id": "public_parks"}
    assert {item.indicator_id for item in evidence} == {
        "public_parks.walk_access_10min",
        "public_parks.acreage_per_1000",
    }
    assert context["evidence"] == [item.model_dump(mode="json") for item in evidence]


def test_domain_indicator_lookup_comes_from_taxonomy() -> None:
    assert indicator_ids_for_node("domain", "public_amenities_spaces") == [
        "public_parks.acreage_per_1000",
        "public_parks.walk_access_10min",
    ]


def test_precomputed_insight_is_served_for_current_data_version(tmp_path) -> None:
    settings = Settings(storage_dir=tmp_path, database_path=tmp_path / "platform.sqlite3")
    store = Database(settings)
    version = load_records(store)
    insight = DistrictInsight(
        geo_id="cd:101",
        node_type="subcategory",
        node_id="public_parks",
        data_version=version,
        headline="Park acreage context",
        explanation="The stored acreage-per-resident measure is available while walking access is unavailable.",
        priority_indicator_ids=["public_parks.acreage_per_1000"],
        evidence=[],
        caveat="Test-only fixture.",
        generated_at=datetime.now(UTC),
    )
    store.save_district_insight(
        geo_id=insight.geo_id,
        node_type=insight.node_type,
        node_id=insight.node_id,
        data_version=version,
        model_id="test",
        payload=insight.model_dump(mode="json"),
    )
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/v1/geographies/cd:101/insight",
        params={"node_type": "subcategory", "node_id": "public_parks"},
    )
    assert response.status_code == 200
    assert response.json()["headline"] == "Park acreage context"
