from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.evidence_query_service import (
    EvidenceQueryRequest,
    EvidenceQueryService,
)
from ai_novel_studio.application.formal_manuscript_evidence_service import (
    EvidenceSet,
    FormalManuscriptEvidenceService,
)
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.infrastructure.storage.search_repository import (
    MAX_FORMAL_EVIDENCE_CANDIDATES,
    MAX_SEARCH_QUERY_CHARS,
)
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository


@dataclass(frozen=True, slots=True)
class FormalEvidenceQueryRequest:
    """Bounded query request for the R3b facade (supplemental Ticket R3)."""

    query: str
    before_chapter_id: str
    participants: tuple[str, ...] = ()
    limit: int = 20
    required_hits: int | None = None

    def __post_init__(self) -> None:
        normalized = self.query.strip()
        if not normalized:
            raise ValueError("formal evidence query cannot be empty")
        object.__setattr__(self, "query", normalized[:MAX_SEARCH_QUERY_CHARS])
        try:
            object.__setattr__(
                self, "before_chapter_id", validate_id(self.before_chapter_id)
            )
        except ValueError:
            raise ValueError("formal evidence before_chapter_id is invalid") from None
        if not isinstance(self.participants, tuple) or any(
            not isinstance(participant, str) for participant in self.participants
        ):
            raise ValueError("formal evidence participants are invalid")
        if not 1 <= self.limit <= MAX_FORMAL_EVIDENCE_CANDIDATES:
            raise ValueError("formal evidence limit is out of bounds")
        if self.required_hits is not None and not (
            1 <= self.required_hits <= MAX_FORMAL_EVIDENCE_CANDIDATES
        ):
            raise ValueError("formal evidence required_hits is out of bounds")


class FormalEvidenceQueryService:
    """Compatibility facade over the canonical Formal evidence query service."""

    def __init__(
        self,
        retriever: HistoryRetriever,
        subjects: SubjectRepository,
        evidence: FormalManuscriptEvidenceService,
    ) -> None:
        if not isinstance(subjects, SubjectRepository):
            raise TypeError("formal evidence subjects are invalid")
        self.subjects = subjects
        self._query_service = EvidenceQueryService(
            retriever=retriever,
            evidence=evidence,
            limits=evidence.limits,
        )

    def query(self, request: FormalEvidenceQueryRequest) -> EvidenceSet:
        if not isinstance(request, FormalEvidenceQueryRequest):
            raise TypeError("formal evidence query request is invalid")
        active_ids = {subject.id for subject in self.subjects.list_active_characters()}
        unknown = [p for p in request.participants if p not in active_ids]
        if unknown:
            raise ValueError("formal evidence participants must be active subjects")
        if request.limit > self._query_service.limits.max_candidates:
            raise ValueError("formal evidence limit exceeds hydration limits")
        return self._query_service.query(
            EvidenceQueryRequest(
                query=request.query,
                target_chapter_id=request.before_chapter_id,
                participants=request.participants,
                required_hits=request.required_hits,
                limit=request.limit,
            )
        )
