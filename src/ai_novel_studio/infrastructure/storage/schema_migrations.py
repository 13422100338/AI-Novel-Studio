import sqlite3
from collections.abc import Callable

from ai_novel_studio.infrastructure.storage.schema_migrations_v1_to_v15 import (
    MIGRATIONS_V1_TO_V15,
)
from ai_novel_studio.infrastructure.storage.schema_migrations_v16 import MIGRATIONS_V16


def _compose_migrations(
    *groups: dict[int, Callable[[sqlite3.Connection], None]],
) -> dict[int, Callable[[sqlite3.Connection], None]]:
    migrations: dict[int, Callable[[sqlite3.Connection], None]] = {}
    for group in groups:
        for version, migration in group.items():
            if version < 1:
                raise RuntimeError(f"invalid schema migration version: {version}")
            if version in migrations:
                raise RuntimeError(f"duplicate schema migration version: {version}")
            migrations[version] = migration
    if not migrations:
        raise RuntimeError("schema migration registry cannot be empty")
    expected = set(range(1, max(migrations) + 1))
    missing = sorted(expected.difference(migrations))
    if missing:
        raise RuntimeError(f"missing schema migration versions: {missing}")
    return migrations


MIGRATIONS = _compose_migrations(MIGRATIONS_V1_TO_V15, MIGRATIONS_V16)
LATEST_SCHEMA_VERSION = max(MIGRATIONS)

__all__ = ["LATEST_SCHEMA_VERSION", "MIGRATIONS"]
