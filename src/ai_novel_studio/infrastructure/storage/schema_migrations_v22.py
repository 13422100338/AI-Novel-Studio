from __future__ import annotations

import sqlite3
from collections.abc import Callable


def _migration_22(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE harness_approvals (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES harness_runs(id),
            kind TEXT NOT NULL CHECK(kind IN (
                'CHANGESET', 'PROMPT_CHANGE', 'PROJECT_CONSTITUTION',
                'SUBJECT_MERGE', 'SKILL_CHANGE'
            )),
            summary TEXT NOT NULL CHECK(length(trim(summary)) > 0),
            payload_json TEXT NOT NULL DEFAULT '{}',
            expected_revisions_json TEXT NOT NULL DEFAULT '[]',
            idempotency_key TEXT NOT NULL CHECK(length(trim(idempotency_key)) > 0),
            status TEXT NOT NULL CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED')),
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolution_note TEXT,
            UNIQUE(run_id, idempotency_key)
        )
        """,
        "CREATE INDEX harness_approvals_run "
        "ON harness_approvals(run_id, status, created_at)",
    )
    for statement in statements:
        connection.execute(statement)


MIGRATIONS_V22: dict[int, Callable[[sqlite3.Connection], None]] = {22: _migration_22}
