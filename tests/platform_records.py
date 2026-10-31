from __future__ import annotations

import json

from nyc_civic.db import Database


def load_records(database: Database) -> str:
    """Install a minimal isolated database state for API unit tests."""
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO geography(
                geo_id, level, name, borough, population, is_residential, context_json, infrastructure_json
            ) VALUES (?, 'cd', ?, ?, ?, 1, ?, ?)""",
            (
                "cd:101",
                "Financial District",
                "Manhattan",
                61400,
                json.dumps([]),
                json.dumps([]),
            ),
        )
        connection.execute(
            """INSERT INTO score_value(
                node_type, node_id, geo_id, score, coverage, status, raw_value, unit, reference_period
            ) VALUES ('indicator', 'public_parks.acreage_per_1000', 'cd:101', 50, 1, 'ok', 1.25,
                      'acres_per_1000_residents', 'NYC Parks Properties retrieved 2026-01-01; population: DCP 2010')"""
        )
        connection.execute(
            """INSERT INTO score_value(
                node_type, node_id, geo_id, score, coverage, status, reason, unit
            ) VALUES ('indicator', 'public_parks.walk_access_10min', 'cd:101', NULL, 0, 'unavailable',
                      'No routed walking analysis.', 'percent')"""
        )
        for node_type, node_id in (
            ("subcategory", "public_parks"),
            ("domain", "public_amenities_spaces"),
        ):
            connection.execute(
                """INSERT INTO score_value(node_type, node_id, geo_id, score, coverage, status)
                VALUES (?, ?, 'cd:101', NULL, 0.5, 'insufficient_coverage')""",
                (node_type, node_id),
            )
        return database.bump_data_version(connection)
