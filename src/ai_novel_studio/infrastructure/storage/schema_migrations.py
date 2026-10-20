import sqlite3
from collections.abc import Callable

from ai_novel_studio.infrastructure.storage.schema_migrations_v1_to_v15 import (
    MIGRATIONS_V1_TO_V15,
)
from ai_novel_studio.infrastructure.storage.schema_migrations_v16 import MIGRATIONS_V16
from ai_novel_studio.infrastructure.storage.schema_migrations_v17 import MIGRATIONS_V17
from ai_novel_studio.infrastructure.storage.schema_migrations_v18 import MIGRATIONS_V18
from ai_novel_studio.infrastructure.storage.schema_migrations_v19 import MIGRATIONS_V19
from ai_novel_studio.infrastructure.storage.schema_migrations_v20 import MIGRATIONS_V20
from ai_novel_studio.infrastructure.storage.schema_migrations_v21 import MIGRATIONS_V21
from ai_novel_studio.infrastructure.storage.schema_migrations_v22 import MIGRATIONS_V22
from ai_novel_studio.infrastructure.storage.schema_migrations_v23 import MIGRATIONS_V23
from ai_novel_studio.infrastructure.storage.schema_migrations_v24 import MIGRATIONS_V24
from ai_novel_studio.infrastructure.storage.schema_migrations_v25 import MIGRATIONS_V25
from ai_novel_studio.infrastructure.storage.schema_migrations_v26 import MIGRATIONS_V26
from ai_novel_studio.infrastructure.storage.schema_migrations_v27 import MIGRATIONS_V27


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


MIGRATIONS = _compose_migrations(
    MIGRATIONS_V1_TO_V15,
    MIGRATIONS_V16,
    MIGRATIONS_V17,
    MIGRATIONS_V18,
    MIGRATIONS_V19,
    MIGRATIONS_V20,
    MIGRATIONS_V21,
    MIGRATIONS_V22,
    MIGRATIONS_V23,
    MIGRATIONS_V24,
    MIGRATIONS_V25,
    MIGRATIONS_V26,
    MIGRATIONS_V27,
)
LATEST_SCHEMA_VERSION = max(MIGRATIONS)

__all__ = ["LATEST_SCHEMA_VERSION", "MIGRATIONS"]
