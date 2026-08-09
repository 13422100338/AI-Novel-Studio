from __future__ import annotations

from dataclasses import dataclass

CURRENT_EMBEDDING_SCHEMA_VERSION = 1
MAX_EMBEDDING_ID_CHARS = 200
MAX_EMBEDDING_SCHEMA_VERSION = 1_000_000


@dataclass(frozen=True, slots=True)
class EmbeddingIndexIdentity:
    provider_id: str
    model_id: str
    embedding_schema_version: int

    def __post_init__(self) -> None:
        provider_id = _bounded_id(self.provider_id, "provider")
        model_id = _bounded_id(self.model_id, "model")
        schema_version = self.embedding_schema_version
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or not 1 <= schema_version <= MAX_EMBEDDING_SCHEMA_VERSION
        ):
            raise ValueError("embedding schema version is invalid")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "model_id", model_id)


def _bounded_id(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"embedding {field} ID is invalid")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_EMBEDDING_ID_CHARS:
        raise ValueError(f"embedding {field} ID is invalid")
    return normalized
