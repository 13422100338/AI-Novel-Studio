from __future__ import annotations

import sqlite3
from collections.abc import Callable


def _migration_18(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        ALTER TABLE character_state_events
        ADD COLUMN location TEXT NOT NULL DEFAULT ''
        """
    )
    connection.execute(
        """
        ALTER TABLE character_state_events
        ADD COLUMN injury_status TEXT NOT NULL DEFAULT ''
        """
    )


MIGRATIONS_V18: dict[int, Callable[[sqlite3.Connection], None]] = {
    18: _migration_18,
}
