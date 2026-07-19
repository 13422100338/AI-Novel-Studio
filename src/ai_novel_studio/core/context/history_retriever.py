from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.memory import MemoryStatus
from ai_novel_studio.infrastructure.storage.search_repository import (
    RetrievalRoute,
    SearchRepository,
)


@dataclass(frozen=True, slots=True)
class SearchHit:
    document_id: str
    document_type: str
    source_id: str
    chapter_id: str | None
    source_revision: int
    source_hash: str
    title: str
    excerpt: str
    status: MemoryStatus
    lexical_score: float
    participant_boost: float
    pinned_weight: float
    recency_score: float
    stale_penalty: float
    total_score: float
    retrieval_routes: tuple[RetrievalRoute, ...]


class HistoryRetriever:
    def __init__(self, repository: SearchRepository) -> None:
        self.repository = repository

    def search(
        self,
        query: str,
        before_chapter_id: str,
        *,
        participants: tuple[str, ...] = (),
        limit: int = 20,
    ) -> tuple[SearchHit, ...]:
        if limit <= 0:
            raise ValueError("检索数量必须大于零")
        participant_set = set(participants)
        hits: list[SearchHit] = []
        for row in self.repository.search_rows(
            query,
            before_chapter_id,
            participants=participants,
            limit=limit,
        ):
            document = row.document
            lexical_score = (
                1.0 + max(0.0, -row.lexical_rank)
                if row.lexical_rank is not None
                else 0.0
            )
            overlap = participant_set.intersection(document.participants)
            participant_boost = float(len(overlap) * 2)
            recency_score = (
                1 / (1 + row.chapter_distance)
                if row.chapter_distance is not None and row.chapter_distance >= 0
                else 0
            )
            stale_penalty = -10.0 if document.status == MemoryStatus.STALE else 0.0
            total = (
                lexical_score
                + participant_boost
                + document.pinned_weight
                + recency_score
                + stale_penalty
            )
            hits.append(
                SearchHit(
                    document.id,
                    document.document_type,
                    document.source_id,
                    document.chapter_id,
                    document.source_revision,
                    document.source_hash,
                    document.title,
                    row.excerpt,
                    document.status,
                    lexical_score,
                    participant_boost,
                    document.pinned_weight,
                    recency_score,
                    stale_penalty,
                    total,
                    row.retrieval_routes,
                )
            )
        return tuple(
            sorted(hits, key=lambda hit: (-hit.total_score, hit.document_id))[:limit]
        )
