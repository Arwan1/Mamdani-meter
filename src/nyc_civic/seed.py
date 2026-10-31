from __future__ import annotations

import json

from nyc_civic.db import Database
from nyc_civic.scoring import ChildScore, aggregate_scores, citywide_mean, normalize_value, population_weighted_mean
from nyc_civic.schemas import ScoreStatus


DEMO_GEOGRAPHIES = [
    {
        "geo_id": "cd:101",
        "level": "cd",
        "name": "Manhattan Community District 1",
        "borough": "Manhattan",
        "population": 170000,
        "context": [{"key": "population", "label": "Population", "value": 170000, "year": "2020", "source_slug": "census_pl_2020"}],
        "infrastructure": [{"key": "park_acres", "label": "Public park acres", "value": 306, "unit": "acres", "year": "demo 2026", "source_slug": "parks_properties"}],
    },
    {
        "geo_id": "cd:305",
        "level": "cd",
        "name": "Brooklyn Community District 5",
        "borough": "Brooklyn",
        "population": 160000,
        "context": [{"key": "population", "label": "Population", "value": 160000, "year": "2020", "source_slug": "census_pl_2020"}],
        "infrastructure": [{"key": "park_acres", "label": "Public park acres", "value": 448, "unit": "acres", "year": "demo 2026", "source_slug": "parks_properties"}],
    },
    {
        "geo_id": "cd:407",
        "level": "cd",
        "name": "Queens Community District 7",
        "borough": "Queens",
        "population": 240000,
        "context": [{"key": "population", "label": "Population", "value": 240000, "year": "2020", "source_slug": "census_pl_2020"}],
        "infrastructure": [{"key": "park_acres", "label": "Public park acres", "value": 240, "unit": "acres", "year": "demo 2026", "source_slug": "parks_properties"}],
    },
]


def seed_demo(database: Database) -> str:
    """Reset only demo configuration/results; user submissions and policies are preserved."""
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM score_value")
        connection.execute("DELETE FROM geography")
        for geography in DEMO_GEOGRAPHIES:
            connection.execute(
                """INSERT INTO geography(
                    geo_id, level, name, borough, population, is_residential,
                    context_json, infrastructure_json
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    geography["geo_id"], geography["level"], geography["name"], geography["borough"],
                    geography["population"], json.dumps(geography["context"]),
                    json.dumps(geography["infrastructure"]),
                ),
            )
        connection.executemany(
            """INSERT INTO geography(geo_id, level, name, is_residential, context_json, infrastructure_json)
            VALUES (?, 'city', 'New York City', 0, '[]', '[]')""",
            [("city:district_mean",), ("city:population_weighted",)],
        )
        raw_values = {
            "public_parks.walk_access_10min": {"cd:101": 74.2, "cd:305": 85.5, "cd:407": 48.1},
            "public_parks.acreage_per_1000": {"cd:101": 1.8, "cd:305": 2.8, "cd:407": 1.0},
        }
        targets = {"public_parks.walk_access_10min": 100.0, "public_parks.acreage_per_1000": 2.5}
        units = {"public_parks.walk_access_10min": "percent", "public_parks.acreage_per_1000": "acres_per_1000_residents"}
        parent_rows: dict[str, list[ChildScore]] = {geo["geo_id"]: [] for geo in DEMO_GEOGRAPHIES}
        for indicator_id, values in raw_values.items():
            for geo_id, raw_value in values.items():
                score = normalize_value(raw_value, method="target", direction="higher_better", target=targets[indicator_id], floor=0)
                connection.execute(
                    """INSERT INTO score_value(node_type, node_id, geo_id, score, coverage, status, raw_value, unit, reference_period)
                    VALUES ('indicator', ?, ?, ?, 1, 'ok', ?, ?, 'demo 2026')""",
                    (indicator_id, geo_id, score, raw_value, units[indicator_id]),
                )
                parent_rows[geo_id].append(ChildScore(score, 1, ScoreStatus.OK))
        subcategory_scores: list[tuple[float, int]] = []
        for geography in DEMO_GEOGRAPHIES:
            aggregate = aggregate_scores(parent_rows[geography["geo_id"]], 0.6)
            for node_type, node_id in (("subcategory", "public_parks"), ("domain", "public_amenities_spaces")):
                connection.execute(
                    """INSERT INTO score_value(node_type, node_id, geo_id, score, coverage, status)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (node_type, node_id, geography["geo_id"], aggregate.score, aggregate.coverage, aggregate.status.value),
                )
            if aggregate.score is not None:
                subcategory_scores.append((aggregate.score, geography["population"]))
        for node_type, node_id in (("subcategory", "public_parks"), ("domain", "public_amenities_spaces")):
            unweighted = citywide_mean([score for score, _ in subcategory_scores])
            weighted = population_weighted_mean(subcategory_scores)
            for method, score in (("district_mean", unweighted), ("population_weighted", weighted)):
                connection.execute(
                    """INSERT INTO score_value(node_type, node_id, geo_id, score, coverage, status, unit)
                    VALUES (?, ?, ?, ?, 1, 'ok', ?)""",
                    (node_type, node_id, f"city:{method}", score, method),
                )
        return database.bump_data_version(connection)
