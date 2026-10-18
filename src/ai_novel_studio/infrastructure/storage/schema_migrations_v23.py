from __future__ import annotations

import sqlite3
from collections.abc import Callable


def _migration_23(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE project_constitutions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            revision INTEGER NOT NULL CHECK(revision >= 1),
            shared_creative_rules_json TEXT NOT NULL DEFAULT '[]',
            agent_only_rules_json TEXT NOT NULL DEFAULT '[]',
            writer_only_rules_json TEXT NOT NULL DEFAULT '[]',
            overridable_rules_json TEXT NOT NULL DEFAULT '[]',
            non_overridable_rules_json TEXT NOT NULL DEFAULT '[]',
            source_decisions_json TEXT NOT NULL DEFAULT '[]',
            unresolved_exclusions_json TEXT NOT NULL DEFAULT '[]',
            approved_by_author INTEGER NOT NULL CHECK(approved_by_author IN (0, 1)),
            created_at TEXT NOT NULL,
            UNIQUE(project_id, revision)
        )
        """,
        "CREATE INDEX project_constitutions_project "
        "ON project_constitutions(project_id, revision)",
    )
    for statement in statements:
        connection.execute(statement)


MIGRATIONS_V23: dict[int, Callable[[sqlite3.Connection], None]] = {23: _migration_23}
