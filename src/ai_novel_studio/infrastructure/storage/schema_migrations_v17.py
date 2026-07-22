from __future__ import annotations

import sqlite3
from collections.abc import Callable


def _migration_17(connection: sqlite3.Connection) -> None:
    for table in ("generation_runs", "audit_runs"):
        connection.execute(
            f"""
            ALTER TABLE {table}
            ADD COLUMN audit_policy TEXT
            CHECK(audit_policy IS NULL OR audit_policy IN ('MINIMAL', 'STANDARD', 'DEEP'))
            """
        )


MIGRATIONS_V17: dict[int, Callable[[sqlite3.Connection], None]] = {
    17: _migration_17,
}
