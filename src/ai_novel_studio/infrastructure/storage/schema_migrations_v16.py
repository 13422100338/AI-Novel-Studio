from __future__ import annotations

import sqlite3
from collections.abc import Callable


def _migration_16(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE memory_embeddings (
            document_id TEXT NOT NULL
                REFERENCES memory_documents(id) ON DELETE CASCADE,
            model_id TEXT NOT NULL
                CHECK(length(trim(model_id)) BETWEEN 1 AND 200),
            dimensions INTEGER NOT NULL
                CHECK(dimensions BETWEEN 1 AND 32768),
            vector_json TEXT NOT NULL
                CHECK(length(vector_json) BETWEEN 2 AND 1000000)
                CHECK(substr(vector_json, 1, 1) = '[')
                CHECK(substr(vector_json, -1, 1) = ']'),
            content_hash TEXT NOT NULL CHECK(length(content_hash) = 64),
            status TEXT NOT NULL CHECK(status IN ('CURRENT', 'STALE')),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            updated_at TEXT NOT NULL CHECK(length(trim(updated_at)) > 0),
            PRIMARY KEY(document_id, model_id)
        )
        """,
        """
        CREATE INDEX memory_embeddings_rebuild
        ON memory_embeddings(model_id, status, document_id)
        """,
    )
    for statement in statements:
        connection.execute(statement)


MIGRATIONS_V16: dict[int, Callable[[sqlite3.Connection], None]] = {
    16: _migration_16,
}
