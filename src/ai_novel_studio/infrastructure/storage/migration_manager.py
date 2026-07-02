import sqlite3
from collections.abc import Callable

LATEST_SCHEMA_VERSION = 1


def _migration_1(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            format_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE volumes (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            synopsis TEXT NOT NULL DEFAULT '',
            sort_index INTEGER NOT NULL CHECK(sort_index >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE chapters (
            id TEXT PRIMARY KEY,
            volume_id TEXT NOT NULL REFERENCES volumes(id),
            declared_number TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            synopsis TEXT NOT NULL DEFAULT '',
            content_path TEXT NOT NULL UNIQUE,
            content_hash TEXT NOT NULL,
            sort_index INTEGER NOT NULL CHECK(sort_index >= 0),
            revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
            memory_status TEXT NOT NULL DEFAULT 'pending',
            is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0, 1)),
            deleted_content_path TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE chapter_versions (
            id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL REFERENCES chapters(id),
            revision INTEGER NOT NULL CHECK(revision >= 0),
            content_snapshot_path TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            UNIQUE(chapter_id, revision)
        )
        """,
        "CREATE INDEX chapters_volume_order ON chapters(volume_id, sort_index)",
    )
    for statement in statements:
        connection.execute(statement)


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {1: _migration_1}


class MigrationManager:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def migrate(self) -> None:
        current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if current > LATEST_SCHEMA_VERSION:
            raise RuntimeError(
                f"project uses newer schema {current}; supported version is {LATEST_SCHEMA_VERSION}"
            )
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for version in range(current + 1, LATEST_SCHEMA_VERSION + 1):
                MIGRATIONS[version](self._connection)
                self._connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
                )
                self._connection.execute(f"PRAGMA user_version = {version}")
