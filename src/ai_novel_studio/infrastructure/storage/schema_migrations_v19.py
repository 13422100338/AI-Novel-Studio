from __future__ import annotations

import sqlite3
from collections.abc import Callable


def _migration_19(connection: sqlite3.Connection) -> None:
    statements = (
        """
        ALTER TABLE memory_documents
        ADD COLUMN source_start INTEGER
        CHECK(source_start IS NULL OR source_start >= 0)
        """,
        """
        ALTER TABLE memory_documents
        ADD COLUMN source_end INTEGER
        CHECK(source_end IS NULL OR source_end > 0)
        """,
        """
        ALTER TABLE memory_documents
        ADD COLUMN chunk_ordinal INTEGER
        CHECK(chunk_ordinal IS NULL OR chunk_ordinal >= 0)
        """,
        """
        ALTER TABLE memory_documents
        ADD COLUMN chunk_policy_version TEXT
        CHECK(
            chunk_policy_version IS NULL
            OR length(trim(chunk_policy_version)) BETWEEN 1 AND 100
        )
        """,
        """
        CREATE INDEX memory_documents_formal_chapter_projection
        ON memory_documents(
            document_type,
            chapter_id,
            source_revision,
            status,
            chunk_policy_version,
            chunk_ordinal
        )
        """,
        "DROP TABLE memory_embeddings",
        """
        CREATE TABLE memory_embeddings (
            document_id TEXT NOT NULL
                REFERENCES memory_documents(id) ON DELETE CASCADE,
            provider_id TEXT NOT NULL
                CHECK(length(trim(provider_id)) BETWEEN 1 AND 200),
            model_id TEXT NOT NULL
                CHECK(length(trim(model_id)) BETWEEN 1 AND 200),
            embedding_schema_version INTEGER NOT NULL
                CHECK(embedding_schema_version BETWEEN 1 AND 1000000),
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
            PRIMARY KEY(
                document_id,
                provider_id,
                model_id,
                embedding_schema_version
            )
        )
        """,
        """
        CREATE INDEX memory_embeddings_rebuild
        ON memory_embeddings(
            provider_id,
            model_id,
            embedding_schema_version,
            status,
            document_id
        )
        """,
        """
        CREATE INDEX memory_embeddings_recall
        ON memory_embeddings(
            provider_id,
            model_id,
            embedding_schema_version,
            status,
            dimensions,
            document_id
        )
        """,
    )
    for statement in statements:
        connection.execute(statement)


MIGRATIONS_V19: dict[int, Callable[[sqlite3.Connection], None]] = {
    19: _migration_19,
}
