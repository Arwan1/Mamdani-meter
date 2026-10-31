"""Local synchronization of the first real NYC Civic Priorities data slice.

The download is intentional and user-initiated through ``nycp data sync``.
It stores the resulting geography snapshot and scores locally; serving the UI
afterwards needs no database server or recurring cloud job.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from nyc_civic.config import Settings
from nyc_civic.db import Database
from nyc_civic.schemas import ScoreStatus
from nyc_civic.scoring import (
    ChildScore,
    aggregate_scores,
    citywide_mean,
    normalize_value,
    population_weighted_mean,
)

COMMUNITY_DISTRICTS_URL = "https://data.cityofnewyork.us/resource/5crt-au7u.geojson?$limit=1000"
PARKS_PROPERTIES_URL = (
    "https://data.cityofnewyork.us/resource/enfh-gkve.json?"
    "$select=communityboard,acres,class&$limit=5000"
)
POPULATION_URL = "https://data.cityofnewyork.us/resource/xi7c-iiu2.json?$limit=100"

BOROUGH_CODES = {
    "Manhattan": 1,
    "Bronx": 2,
    "Brooklyn": 3,
    "Queens": 4,
    "Staten Island": 5,
}
BOROUGH_NAMES = {code: name for name, code in BOROUGH_CODES.items()}
EXPECTED_CD_COUNT = 59
PARKS_REFERENCE = "NYC Parks Properties retrieved {retrieved}; population: DCP 2010"
WALK_ACCESS_REASON = (
    "Not calculated: a routed walking-network and population-allocation pipeline has not "
    "been imported locally."
)


def _read_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "MamdaniMeter local-data-sync/1.0"})
    with urlopen(request, timeout=45) as response:  # noqa: S310 - fixed HTTPS NYC Open Data URLs
        return json.loads(response.read().decode("utf-8"))


def _cd_code(value: object) -> int | None:
    try:
        code = int(str(value))
    except (TypeError, ValueError):
        return None
    borough, district = divmod(code, 100)
    return code if borough in BOROUGH_NAMES and 1 <= district <= 18 else None


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep only standard CDs and attach the stable local API geography ID."""
    result: list[dict[str, Any]] = []
    for feature in features:
        code = _cd_code(feature.get("properties", {}).get("boro_cd"))
        if code is None:
            continue
        result.append(
            {
                "type": "Feature",
                "properties": {"geo_id": f"cd:{code:03d}", "boro_cd": f"{code:03d}"},
                "geometry": feature["geometry"],
            }
        )
    result.sort(key=lambda feature: feature["properties"]["geo_id"])
    if len(result) != EXPECTED_CD_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_CD_COUNT} standard community districts; received {len(result)}"
        )
    return {"type": "FeatureCollection", "features": result}


def _population_by_cd(
    rows: list[dict[str, Any]],
) -> tuple[dict[int, tuple[int, str]], dict[int, str]]:
    values: dict[int, tuple[int, str]] = {}
    names: dict[int, str] = {}
    for row in rows:
        borough = BOROUGH_CODES.get(str(row.get("borough", "")))
        try:
            district = int(str(row["cd_number"]))
            population = int(str(row["_2010_population"]))
        except (KeyError, TypeError, ValueError):
            continue
        code = borough * 100 + district if borough is not None else None
        if code is None or _cd_code(code) is None or population <= 0:
            continue
        values[code] = (population, str(row.get("borough", "")))
        names[code] = str(row.get("cd_name") or f"Community District {code:03d}")
    if len(values) != EXPECTED_CD_COUNT:
        raise ValueError(
            f"Expected population values for {EXPECTED_CD_COUNT} districts; received {len(values)}"
        )
    return values, names


def _park_acres_by_cd(rows: list[dict[str, Any]]) -> dict[int, float]:
    totals: defaultdict[int, float] = defaultdict(float)
    for row in rows:
        code = _cd_code(row.get("communityboard"))
        if code is None or str(row.get("class", "")).upper() != "PARK":
            continue
        try:
            acres = float(str(row["acres"]))
        except (KeyError, TypeError, ValueError):
            continue
        if acres >= 0:
            totals[code] += acres
    if not totals:
        raise ValueError("No park acreage records could be matched to a community district")
    return dict(totals)


def sync_parks_data(database: Database, settings: Settings) -> str:
    """Fetch official NYC data, overwrite score records, and write local CD geometry.

    The raw inputs remain in the public source systems. The reproducible local
    result is a SQLite snapshot plus ``data/geo/cd.geojson``.
    """
    database.initialize()
    retrieved = datetime.now(UTC).date().isoformat()
    geography_payload = _read_json(COMMUNITY_DISTRICTS_URL)
    population_rows = _read_json(POPULATION_URL)
    parks_rows = _read_json(PARKS_PROPERTIES_URL)
    geojson = _feature_collection(geography_payload["features"])
    populations, district_names = _population_by_cd(population_rows)
    acres_by_cd = _park_acres_by_cd(parks_rows)
    reference_period = PARKS_REFERENCE.format(retrieved=retrieved)

    score_rows: list[tuple[Any, ...]] = []
    parent_rows: dict[str, list[ChildScore]] = {}
    acreage_scores: list[tuple[float, int]] = []
    for code in sorted(populations):
        geo_id = f"cd:{code:03d}"
        population, borough = populations[code]
        acres = round(acres_by_cd.get(code, 0.0), 4)
        raw_value = round(acres * 1000 / population, 4)
        score = normalize_value(
            raw_value, method="benchmark", direction="higher_better", target=2.5, floor=0
        )
        assert score is not None
        score_rows.append(
            (
                "indicator",
                "public_parks.acreage_per_1000",
                geo_id,
                score,
                1.0,
                "ok",
                raw_value,
                "acres_per_1000_residents",
                None,
                0,
                reference_period,
            )
        )
        score_rows.append(
            (
                "indicator",
                "public_parks.walk_access_10min",
                geo_id,
                None,
                0.0,
                ScoreStatus.UNAVAILABLE.value,
                None,
                "percent",
                WALK_ACCESS_REASON,
                0,
                None,
            )
        )
        parent_rows[geo_id] = [
            ChildScore(score, 1.0, ScoreStatus.OK),
            ChildScore(None, 0.0, ScoreStatus.UNAVAILABLE),
        ]
        acreage_scores.append((score, population))

    aggregates: list[tuple[str, str, str, float | None, float, str]] = []
    for code in sorted(populations):
        geo_id = f"cd:{code:03d}"
        result = aggregate_scores(parent_rows[geo_id], settings.min_coverage)
        for node_type, node_id in (
            ("subcategory", "public_parks"),
            ("domain", "public_amenities_spaces"),
        ):
            aggregates.append(
                (node_type, node_id, geo_id, result.score, result.coverage, result.status.value)
            )

    for method, score in (
        ("district_mean", citywide_mean([score for score, _ in acreage_scores])),
        ("population_weighted", population_weighted_mean(acreage_scores)),
    ):
        score_rows.append(
            (
                "indicator",
                "public_parks.acreage_per_1000",
                f"city:{method}",
                score,
                1.0,
                "ok",
                None,
                method,
                None,
                0,
                reference_period,
            )
        )
        score_rows.append(
            (
                "indicator",
                "public_parks.walk_access_10min",
                f"city:{method}",
                None,
                0.0,
                ScoreStatus.UNAVAILABLE.value,
                None,
                method,
                WALK_ACCESS_REASON,
                0,
                None,
            )
        )
        for node_type, node_id in (
            ("subcategory", "public_parks"),
            ("domain", "public_amenities_spaces"),
        ):
            score_rows.append(
                (
                    node_type,
                    node_id,
                    f"city:{method}",
                    None,
                    0.5,
                    ScoreStatus.INSUFFICIENT_COVERAGE.value,
                    None,
                    method,
                    "Only one of two configured indicators is currently available.",
                    0,
                    None,
                )
            )

    with database.connect() as connection:
        connection.execute("DELETE FROM district_insight")
        connection.execute("DELETE FROM score_value")
        connection.execute("DELETE FROM geography")
        for code in sorted(populations):
            population, borough = populations[code]
            acres = round(acres_by_cd.get(code, 0.0), 4)
            connection.execute(
                """INSERT INTO geography(
                    geo_id, level, name, borough, population, is_residential, context_json, infrastructure_json
                ) VALUES (?, 'cd', ?, ?, ?, 1, ?, ?)""",
                (
                    f"cd:{code:03d}",
                    district_names[code],
                    borough,
                    population,
                    json.dumps(
                        [
                            {
                                "key": "population_2010",
                                "label": "Population",
                                "value": population,
                                "year": "2010",
                                "source_slug": "nyc_population_by_cd_2010",
                            }
                        ]
                    ),
                    json.dumps(
                        [
                            {
                                "key": "park_acres",
                                "label": "Public park acres",
                                "value": acres,
                                "unit": "acres",
                                "year": retrieved,
                                "source_slug": "parks_properties",
                            }
                        ]
                    ),
                ),
            )
        connection.executemany(
            """INSERT INTO geography(geo_id, level, name, is_residential, context_json, infrastructure_json)
            VALUES (?, 'city', 'New York City', 0, '[]', '[]')""",
            [("city:district_mean",), ("city:population_weighted",)],
        )
        connection.executemany(
            """INSERT INTO score_value(
                node_type, node_id, geo_id, score, coverage, status, raw_value, unit, reason,
                is_relative, reference_period
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            score_rows,
        )
        connection.executemany(
            """INSERT INTO score_value(node_type, node_id, geo_id, score, coverage, status)
            VALUES (?, ?, ?, ?, ?, ?)""",
            aggregates,
        )
        version = database.bump_data_version(connection)

    geo_path: Path = settings.storage_dir / "geo" / "cd.geojson"
    geo_path.parent.mkdir(parents=True, exist_ok=True)
    geo_path.write_text(json.dumps(geojson, separators=(",", ":")) + "\n", encoding="utf-8")
    return version
