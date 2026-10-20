import sqlite3
from collections.abc import Callable


def _migration_26(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE outline_documents (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 400),
            sort_index INTEGER NOT NULL CHECK(sort_index >= 0),
            revision INTEGER NOT NULL CHECK(revision >= 1),
            content_hash TEXT NOT NULL CHECK(
                length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*'
            ),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE outline_versions (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES outline_documents(id),
            revision INTEGER NOT NULL CHECK(revision >= 1),
            content_hash TEXT NOT NULL CHECK(
                length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*'
            ),
            created_at TEXT NOT NULL,
            UNIQUE(document_id, revision)
        )
        """
    )
    connection.execute(
        "CREATE INDEX outline_documents_project_order ON outline_documents(project_id, sort_index)"
    )


MIGRATIONS_V26: dict[int, Callable[[sqlite3.Connection], None]] = {26: _migration_26}
