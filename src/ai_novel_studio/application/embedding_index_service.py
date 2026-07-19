from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ai_novel_studio.infrastructure.storage.search_repository import (
    MAX_RECALL_CANDIDATES,
    SearchRepository,
)

MAX_EMBEDDING_BATCH_SIZE = 64


class DocumentEmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    def embed_documents(
        self,
        texts: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]: ...


@dataclass(frozen=True, slots=True)
class EmbeddingIndexFailure:
    document_id: str
    message: str


@dataclass(frozen=True, slots=True)
class EmbeddingIndexReport:
    model_id: str
    selected_sources: int
    indexed_embeddings: int
    failures: tuple[EmbeddingIndexFailure, ...]


class EmbeddingIndexService:
    def __init__(
        self,
        repository: SearchRepository,
        provider: DocumentEmbeddingProvider,
    ) -> None:
        self.repository = repository
        self.provider = provider

    def rebuild_pending(
        self,
        *,
        limit: int = 100,
        batch_size: int = 16,
    ) -> EmbeddingIndexReport:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
            or limit > MAX_RECALL_CANDIDATES
        ):
            raise ValueError(
                f"embedding index limit must be between 1 and {MAX_RECALL_CANDIDATES}"
            )
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size <= 0
            or batch_size > MAX_EMBEDDING_BATCH_SIZE
        ):
            raise ValueError(
                f"embedding batch size must be between 1 and {MAX_EMBEDDING_BATCH_SIZE}"
            )
        model_id = self.provider.model_id
        sources = self.repository.pending_embedding_sources(
            model_id,
            limit=limit,
        )
        failures: list[EmbeddingIndexFailure] = []
        indexed = 0
        expected_dimensions: int | None = None
        for offset in range(0, len(sources), batch_size):
            batch = sources[offset : offset + batch_size]
            try:
                vectors = self.provider.embed_documents(
                    tuple(source.text for source in batch)
                )
            except Exception as error:
                failures.extend(
                    EmbeddingIndexFailure(source.document_id, _safe_message(error))
                    for source in batch
                )
                continue
            if not isinstance(vectors, tuple) or len(vectors) != len(batch):
                failures.extend(
                    EmbeddingIndexFailure(
                        source.document_id,
                        "embedding provider output count must match input batch",
                    )
                    for source in batch
                )
                continue
            dimensions = {
                len(vector) for vector in vectors if isinstance(vector, tuple)
            }
            if len(dimensions) > 1 or (
                expected_dimensions is not None
                and dimensions
                and dimensions != {expected_dimensions}
            ):
                failures.extend(
                    EmbeddingIndexFailure(
                        source.document_id,
                        "embedding provider dimensions changed for one model",
                    )
                    for source in batch
                )
                continue
            for source, vector in zip(batch, vectors, strict=True):
                try:
                    if not isinstance(vector, tuple):
                        raise ValueError("embedding provider vector must be a tuple")
                    self.repository.save_embedding(
                        source.document_id,
                        model_id,
                        vector,
                        expected_content_hash=source.content_hash,
                    )
                except Exception as error:
                    failures.append(
                        EmbeddingIndexFailure(
                            source.document_id,
                            _safe_message(error),
                        )
                    )
                else:
                    if expected_dimensions is None:
                        expected_dimensions = len(vector)
                    indexed += 1
        return EmbeddingIndexReport(
            model_id.strip(),
            len(sources),
            indexed,
            tuple(failures),
        )


def _safe_message(error: BaseException) -> str:
    message = str(error).strip() or type(error).__name__
    return message[:500]
