import sqlite3

from ai_novel_studio.infrastructure.storage.schema_migrations import (
    LATEST_SCHEMA_VERSION,
    MIGRATIONS,
)
from ai_novel_studio.infrastructure.storage.schema_migrations_v1_to_v15 import (
    _migration_1,
    _migration_2,
    _migration_3,
    _migration_4,
)

__all__ = [
    "LATEST_SCHEMA_VERSION",
    "MIGRATIONS",
    "MigrationManager",
    "_migration_1",
    "_migration_2",
    "_migration_3",
    "_migration_4",
]


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
            # sqlite3 does not implicitly start a transaction for DDL. Begin one
            # explicitly so schema changes and version records roll back together.
            self._connection.execute("BEGIN IMMEDIATE")
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
