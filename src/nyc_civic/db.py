from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from nyc_civic.config import Settings


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS geography (
    geo_id TEXT PRIMARY KEY,
    level TEXT NOT NULL,
    name TEXT NOT NULL,
    borough TEXT,
    population INTEGER,
    is_residential INTEGER NOT NULL DEFAULT 1,
    context_json TEXT NOT NULL DEFAULT '[]',
    infrastructure_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS score_value (
    node_type TEXT NOT NULL,
    node_id TEXT NOT NULL,
    geo_id TEXT NOT NULL REFERENCES geography(geo_id),
    score REAL,
    coverage REAL NOT NULL,
    status TEXT NOT NULL,
    raw_value REAL,
    unit TEXT,
    reason TEXT,
    is_relative INTEGER NOT NULL DEFAULT 0,
    reference_period TEXT,
    PRIMARY KEY (node_type, node_id, geo_id)
);

CREATE INDEX IF NOT EXISTS idx_score_lookup
ON score_value (node_type, node_id, geo_id);

CREATE TABLE IF NOT EXISTS district_insight (
    geo_id TEXT NOT NULL REFERENCES geography(geo_id),
    node_type TEXT NOT NULL,
    node_id TEXT NOT NULL,
    data_version TEXT NOT NULL,
    model_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    PRIMARY KEY (geo_id, node_type, node_id, data_version)
);

CREATE TABLE IF NOT EXISTS submission (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    description TEXT NOT NULL,
    photo_keys_json TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    observed_at TEXT NOT NULL,
    category_hint TEXT,
    status TEXT NOT NULL,
    error TEXT,
    classification_json TEXT,
    public_visible INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS policy_document (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_path TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS policy_chunk (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES policy_document(id) ON DELETE CASCADE,
    section_ref TEXT,
    page INTEGER,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commitment (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES policy_document(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES policy_chunk(id) ON DELETE CASCADE,
    statement_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    section_ref TEXT,
    page INTEGER,
    agencies_json TEXT NOT NULL,
    target_value REAL,
    target_unit TEXT,
    deadline TEXT,
    tags_json TEXT NOT NULL,
    review_status TEXT NOT NULL,
    UNIQUE(document_id, excerpt)
);
"""


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.settings.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.settings.storage_dir.mkdir(parents=True, exist_ok=True)
        self.settings.upload_dir.mkdir(parents=True, exist_ok=True)
        self.settings.policy_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self.set_metadata(connection, "data_version", self.current_data_version(connection))

    @staticmethod
    def utc_now() -> str:
        return datetime.now(UTC).isoformat()

    def current_data_version(self, connection: sqlite3.Connection | None = None) -> str:
        if connection is None:
            with self.connect() as local_connection:
                return self.current_data_version(local_connection)
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'data_version'"
        ).fetchone()
        return row["value"] if row else "local-empty"

    @staticmethod
    def set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def bump_data_version(self, connection: sqlite3.Connection) -> str:
        version = uuid4().hex[:12]
        self.set_metadata(connection, "data_version", version)
        return version

    def list_geographies(self, level: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT geo_id, level, name, borough, population, is_residential "
                "FROM geography WHERE level = ? ORDER BY geo_id",
                (level,),
            ).fetchall()
        return [dict(row) for row in rows]

    def geography(self, geo_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM geography WHERE geo_id = ?", (geo_id,)).fetchone()
        return dict(row) if row else None

    def list_scores(self, node_type: str, node_id: str, level: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT s.* FROM score_value s JOIN geography g ON g.geo_id = s.geo_id "
                "WHERE s.node_type = ? AND s.node_id = ? AND g.level = ? ORDER BY s.geo_id",
                (node_type, node_id, level),
            ).fetchall()
        return [dict(row) for row in rows]

    def score(self, node_type: str, node_id: str, geo_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM score_value WHERE node_type = ? AND node_id = ? AND geo_id = ?",
                (node_type, node_id, geo_id),
            ).fetchone()
        return dict(row) if row else None

    def city_scores(self, node_type: str, node_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM score_value WHERE node_type = ? AND node_id = ? AND geo_id LIKE 'city:%' "
                "ORDER BY geo_id",
                (node_type, node_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_district_insight(
        self,
        *,
        geo_id: str,
        node_type: str,
        node_id: str,
        data_version: str,
        model_id: str,
        payload: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO district_insight(
                    geo_id, node_type, node_id, data_version, model_id, payload_json, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(geo_id, node_type, node_id, data_version) DO UPDATE SET
                    model_id = excluded.model_id,
                    payload_json = excluded.payload_json,
                    generated_at = excluded.generated_at""",
                (
                    geo_id,
                    node_type,
                    node_id,
                    data_version,
                    model_id,
                    json.dumps(payload),
                    self.utc_now(),
                ),
            )

    def district_insight(
        self, geo_id: str, node_type: str, node_id: str, data_version: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT payload_json, generated_at FROM district_insight
                WHERE geo_id = ? AND node_type = ? AND node_id = ? AND data_version = ?""",
                (geo_id, node_type, node_id, data_version),
            ).fetchone()
        return dict(row) if row else None

    def create_submission(self, payload: dict[str, Any]) -> str:
        identifier = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO submission(
                    id, created_at, description, photo_keys_json, lat, lng, observed_at,
                    category_hint, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'processing')""",
                (
                    identifier,
                    self.utc_now(),
                    payload["description"],
                    json.dumps(payload["photo_keys"]),
                    payload["lat"],
                    payload["lng"],
                    payload["observed_at"],
                    payload.get("category_hint"),
                ),
            )
        return identifier

    def submission(self, identifier: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM submission WHERE id = ?", (identifier,)).fetchone()
        return dict(row) if row else None

    def update_submission(
        self,
        identifier: str,
        *,
        status: str,
        classification: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE submission SET status = ?, classification_json = ?, error = ? WHERE id = ?",
                (status, json.dumps(classification) if classification else None, error, identifier),
            )

    def visible_submissions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM submission WHERE public_visible = 1 ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_policy_document(self, title: str, source_path: str, file_hash: str) -> str:
        identifier = str(uuid4())
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM policy_document WHERE file_hash = ?", (file_hash,)
            ).fetchone()
            if existing:
                return str(existing["id"])
            connection.execute(
                "INSERT INTO policy_document(id, title, source_path, imported_at, file_hash) VALUES (?, ?, ?, ?, ?)",
                (identifier, title, source_path, self.utc_now(), file_hash),
            )
        return identifier

    def replace_document_chunks(self, document_id: str, chunks: list[dict[str, Any]]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM policy_chunk WHERE document_id = ?", (document_id,))
            connection.executemany(
                "INSERT INTO policy_chunk(id, document_id, section_ref, page, text) VALUES (?, ?, ?, ?, ?)",
                [
                    (str(uuid4()), document_id, item.get("section_ref"), item.get("page"), item["text"])
                    for item in chunks
                ],
            )

    def document_chunks(self, document_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM policy_chunk WHERE document_id = ? ORDER BY page, id", (document_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def document_title(self, document_id: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT title FROM policy_document WHERE id = ?", (document_id,)
            ).fetchone()
        return str(row["title"]) if row else None

    def add_commitment(self, commitment: dict[str, Any]) -> str | None:
        identifier = str(uuid4())
        try:
            with self.connect() as connection:
                connection.execute(
                    """INSERT INTO commitment(
                        id, document_id, chunk_id, statement_type, summary, excerpt, section_ref,
                        page, agencies_json, target_value, target_unit, deadline, tags_json, review_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'needs_review')""",
                    (
                        identifier,
                        commitment["document_id"],
                        commitment["chunk_id"],
                        commitment["statement_type"],
                        commitment["summary"],
                        commitment["excerpt"],
                        commitment.get("section_ref"),
                        commitment.get("page"),
                        json.dumps(commitment.get("agencies", [])),
                        commitment.get("target_value"),
                        commitment.get("target_unit"),
                        commitment.get("deadline"),
                        json.dumps(commitment.get("tags", [])),
                    ),
                )
        except sqlite3.IntegrityError:
            return None
        return identifier

    def commitments(self, approved_only: bool = True) -> list[dict[str, Any]]:
        where = "WHERE c.review_status = 'approved'" if approved_only else ""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT c.*, d.title AS document_title FROM commitment c "
                "JOIN policy_document d ON d.id = c.document_id "
                f"{where} ORDER BY d.title, c.page, c.id"
            ).fetchall()
        return [dict(row) for row in rows]

    def commitment(self, identifier: str, approved_only: bool = True) -> dict[str, Any] | None:
        where = "AND c.review_status = 'approved'" if approved_only else ""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT c.*, d.title AS document_title FROM commitment c "
                "JOIN policy_document d ON d.id = c.document_id "
                f"WHERE c.id = ? {where}",
                (identifier,),
            ).fetchone()
        return dict(row) if row else None

    def set_commitment_review_status(self, identifier: str, review_status: str) -> bool:
        if review_status not in {"approved", "rejected"}:
            raise ValueError("review_status must be approved or rejected")
        with self.connect() as connection:
            result = connection.execute(
                "UPDATE commitment SET review_status = ? WHERE id = ?",
                (review_status, identifier),
            )
            if result.rowcount:
                self.bump_data_version(connection)
            return result.rowcount == 1


def json_load(value: str) -> Any:
    return json.loads(value)


def upload_path(settings: Settings, key: str) -> Path:
    candidate = (settings.storage_dir / key).resolve()
    root = settings.upload_dir.resolve()
    if root not in candidate.parents:
        raise ValueError("Invalid upload key")
    return candidate
