from __future__ import annotations

from fastapi.testclient import TestClient

from nyc_civic.api import create_app
from nyc_civic.config import Settings
from nyc_civic.db import Database
from tests.platform_records import load_records


def test_scores_follow_contract(tmp_path) -> None:
    settings = Settings(storage_dir=tmp_path, database_path=tmp_path / "platform.sqlite3")
    load_records(Database(settings))
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/v1/scores",
        params={"level": "cd", "node_type": "subcategory", "node_id": "public_parks"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["node"]["node_id"] == "public_parks"
    assert len(body["values"]) == 1
    assert response.headers["X-Data-Version"]


def test_missing_score_has_explicit_status(tmp_path) -> None:
    settings = Settings(storage_dir=tmp_path, database_path=tmp_path / "platform.sqlite3")
    load_records(Database(settings))
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/v1/scores",
        params={"level": "cd", "node_type": "indicator", "node_id": "not.a.real.indicator"},
    )
    assert response.status_code == 200
    assert {item["status"] for item in response.json()["values"]} == {"unavailable"}
