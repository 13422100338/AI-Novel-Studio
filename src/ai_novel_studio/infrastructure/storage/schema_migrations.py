from ai_novel_studio.infrastructure.storage.schema_migrations_v1_to_v15 import (
    MIGRATIONS_V1_TO_V15,
)

MIGRATIONS = dict(MIGRATIONS_V1_TO_V15)
LATEST_SCHEMA_VERSION = max(MIGRATIONS)

__all__ = ["LATEST_SCHEMA_VERSION", "MIGRATIONS"]
