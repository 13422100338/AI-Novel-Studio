from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.formal_manuscript_evidence_service import (
    EvidenceSet,
    FormalEvidenceCandidate,
    FormalEvidenceHydrationRequest,
    FormalEvidenceLimits,
    FormalManuscriptEvidenceService,
)
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.infrastructure.storage.search_repository import (
    MAX_SEARCH_QUERY_CHARS,
)

_MAX_RECALL_LIMIT = 200
_FORMAL_DOCUMENT_TYPE = "FORMAL_MANUSCRIPT"


@dataclass(frozen=True, slots=True)
class EvidenceQueryRequest:
    query: str
    target_chapter_id: str
    participants: tuple[str, ...] = ()
    required_hits: int | None = None
    limit: int = 20

    def __post_init__(self) -> None:
        if not isinstance(self.query, str):
            raise ValueError("evidence query request is invalid")
        if not self.query.strip() and not any(
            isinstance(item, str) and item.strip() for item in self.participants
        ):
            raise ValueError("evidence query request is invalid")
        if not isinstance(self.target_chapter_id, str) or not (
            self.target_chapter_id.strip()
        ):
            raise ValueError("evidence query request is invalid")
        try:
            validate_id(self.target_chapter_id)
        except ValueError:
            raise ValueError("evidence query request is invalid") from None
        if self.required_hits is not None and (
            isinstance(self.required_hits, bool)
            or not isinstance(self.required_hits, int)
            or self.required_hits < 1
        ):
            raise ValueError("evidence query request is invalid")
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= _MAX_RECALL_LIMIT
        ):
            raise ValueError("evidence query request is invalid")


class EvidenceQueryService:
    """Bounded Formal-current evidence query facade (R3b-Q1)."""

    def __init__(
        self,
        *,
        retriever: HistoryRetriever,
        evidence: FormalManuscriptEvidenceService,
        limits: FormalEvidenceLimits | None = None,
    ) -> None:
        if not isinstance(retriever, HistoryRetriever):
            raise TypeError("evidence query retriever is invalid")
        if not isinstance(evidence, FormalManuscriptEvidenceService):
            raise TypeError("evidence query hydration service is invalid")
        if limits is None:
            limits = FormalEvidenceLimits()
        if not isinstance(limits, FormalEvidenceLimits):
            raise TypeError("evidence query limits are invalid")
        self.retriever = retriever
        self.evidence = evidence
        self.limits = limits

    def query(self, request: EvidenceQueryRequest) -> EvidenceSet:
        if not isinstance(request, EvidenceQueryRequest):
            raise TypeError("evidence query request is invalid")
        normalized_query = request.query.strip()[:MAX_SEARCH_QUERY_CHARS]
        participants = tuple(
            dict.fromkeys(
                item.strip() for item in request.participants if item.strip()
            )
        )
        hits = self.retriever.search(
            normalized_query,
            request.target_chapter_id,
            participants=participants,
            limit=request.limit,
        )
        candidates = tuple(
            FormalEvidenceCandidate(
                document_id=hit.document_id,
                retrieval_routes=hit.retrieval_routes,
                lexical_score=hit.lexical_score,
                semantic_score=hit.semantic_score,
                participant_boost=hit.participant_boost,
                pinned_weight=hit.pinned_weight,
                recency_score=hit.recency_score,
                stale_penalty=hit.stale_penalty,
                total_score=hit.total_score,
            )
            for hit in hits
            if hit.document_type == _FORMAL_DOCUMENT_TYPE
            and hit.chapter_id is not None
        )[: self.limits.max_candidates]
        return self.evidence.hydrate(
            FormalEvidenceHydrationRequest(
                target_chapter_id=request.target_chapter_id,
                candidates=candidates,
                required_hits=request.required_hits,
            )
        )
