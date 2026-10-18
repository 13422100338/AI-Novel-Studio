from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.evidence_query_service import (
    EvidenceQueryRequest,
    EvidenceQueryService,
)
from ai_novel_studio.application.formal_manuscript_evidence_service import (
    EvidenceSet,
)
from ai_novel_studio.domain.memory import ReviewStatus
from ai_novel_studio.domain.occurrence import OccurrenceType
from ai_novel_studio.infrastructure.storage.occurrence_repository import (
    OccurrenceRepository,
    OccurrenceRepositoryError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_MAX_INDEX_LIMIT = 500
_MAX_PARTICIPANT_LIMIT = 100
_DEFAULT_PARTICIPANT_LIMIT = 50
_TRUSTED_REVIEW_STATUSES: tuple[ReviewStatus, ...] = (
    ReviewStatus.APPROVED,
    ReviewStatus.LOCKED,
)


@dataclass(frozen=True, slots=True)
class SubjectHistoryIndexItem:
    occurrence_id: str
    link_id: str
    narrative_sequence: int
    occurrence_type: OccurrenceType
    title: str
    role: str
    subject_summary: str
    review_status: ReviewStatus


@dataclass(frozen=True, slots=True)
class SubjectHistoryParticipant:
    link_id: str
    subject_id: str
    role: str
    subject_summary: str
    review_status: ReviewStatus


@dataclass(frozen=True, slots=True)
class SubjectHistorySourceRange:
    chapter_id: str
    revision: int
    source_hash: str
    semantic_window_source_id: str
    policy_version: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class SubjectHistoryDetail:
    occurrence_id: str
    narrative_sequence: int
    occurrence_type: OccurrenceType
    title: str
    summary: str
    review_status: ReviewStatus
    participants: tuple[SubjectHistoryParticipant, ...]
    source_ranges: tuple[SubjectHistorySourceRange, ...]


class SubjectHistoryService:
    """Exposes the compact Level-1 subject history index (H1)."""

    def __init__(
        self,
        project: ProjectRepository,
        *,
        evidence_query: EvidenceQueryService | None = None,
    ) -> None:
        self.project = project
        self.repository = OccurrenceRepository(project)
        if evidence_query is not None and not isinstance(
            evidence_query, EvidenceQueryService
        ):
            raise TypeError("subject history evidence service is invalid")
        self._evidence_query = evidence_query

    def list_index(
        self,
        subject_id: str,
        *,
        limit: int = 100,
        review_statuses: tuple[ReviewStatus, ...] | None = _TRUSTED_REVIEW_STATUSES,
        include_stale: bool = False,
        include_source_changed: bool = False,
    ) -> tuple[SubjectHistoryIndexItem, ...]:
        if not isinstance(subject_id, str) or not subject_id.strip():
            raise ValueError("subject history subject ID is invalid")
        _validate_limit(limit)
        records = self.repository.list_subject_occurrences(
            subject_id,
            occurrence_review_statuses=review_statuses,
            link_review_statuses=review_statuses,
            include_stale=include_stale,
            include_source_changed=include_source_changed,
            limit=limit,
        )
        return tuple(
            SubjectHistoryIndexItem(
                occurrence_id=record.occurrence.id,
                link_id=record.link.id,
                narrative_sequence=record.occurrence.narrative_sequence,
                occurrence_type=record.occurrence.type_code,
                title=record.occurrence.title,
                role=record.link.role,
                subject_summary=record.link.subject_summary,
                review_status=record.occurrence.review_status,
            )
            for record in records
        )

    def get_detail(
        self,
        occurrence_id: str,
        *,
        participant_limit: int = _DEFAULT_PARTICIPANT_LIMIT,
        review_statuses: tuple[ReviewStatus, ...] = _TRUSTED_REVIEW_STATUSES,
        include_stale: bool = False,
        include_source_changed: bool = False,
    ) -> SubjectHistoryDetail:
        if not isinstance(occurrence_id, str) or not occurrence_id.strip():
            raise ValueError("subject history occurrence ID is invalid")
        _validate_participant_limit(participant_limit)
        _validate_review_filter(review_statuses)
        try:
            occurrence = self.repository.get_occurrence(occurrence_id)
        except KeyError:
            raise
        except OccurrenceRepositoryError:
            raise ValueError("subject history detail is unavailable") from None
        if (
            occurrence.review_status not in review_statuses
            or (occurrence.stale and not include_stale)
            or (occurrence.source_changed and not include_source_changed)
        ):
            raise ValueError("subject history detail is unavailable")
        links = self.repository.list_links_for_occurrence(
            occurrence.id,
            review_statuses=review_statuses,
            include_stale=include_stale,
            include_source_changed=include_source_changed,
            limit=participant_limit + 1,
        )
        if len(links) > participant_limit:
            raise ValueError("subject history detail exceeds participant limit")
        return SubjectHistoryDetail(
            occurrence_id=occurrence.id,
            narrative_sequence=occurrence.narrative_sequence,
            occurrence_type=occurrence.type_code,
            title=occurrence.title,
            summary=occurrence.summary,
            review_status=occurrence.review_status,
            participants=tuple(
                SubjectHistoryParticipant(
                    link_id=link.id,
                    subject_id=link.subject_id,
                    role=link.role,
                    subject_summary=link.subject_summary,
                    review_status=link.review_status,
                )
                for link in links
            ),
            source_ranges=tuple(
                SubjectHistorySourceRange(
                    chapter_id=source_range.source_chapter_id,
                    revision=source_range.source_revision,
                    source_hash=source_range.source_hash,
                    semantic_window_source_id=(
                        source_range.semantic_window_source_id
                    ),
                    policy_version=source_range.policy_version,
                    start=source_range.source_start,
                    end=source_range.source_end,
                )
                for source_range in sorted(
                    occurrence.source_ranges,
                    key=lambda item: item.ordinal,
                )
            ),
        )

    def get_evidence(
        self,
        occurrence_id: str,
        *,
        target_chapter_id: str,
        required_hits: int | None = None,
        limit: int = 20,
    ) -> EvidenceSet:
        if self._evidence_query is None:
            raise ValueError("subject history evidence service is unavailable")
        if not isinstance(target_chapter_id, str) or not target_chapter_id.strip():
            raise ValueError("evidence query request is invalid")
        detail = self.get_detail(occurrence_id)
        query = "\n".join(
            part for part in (detail.title, detail.summary) if part.strip()
        )
        participants = tuple(
            dict.fromkeys(item.subject_id for item in detail.participants)
        )
        return self._evidence_query.query(
            EvidenceQueryRequest(
                query=query,
                target_chapter_id=target_chapter_id,
                participants=participants,
                required_hits=required_hits,
                limit=limit,
            )
        )


def _validate_limit(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= _MAX_INDEX_LIMIT
    ):
        raise ValueError("subject history index limit is invalid")


def _validate_participant_limit(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= _MAX_PARTICIPANT_LIMIT
    ):
        raise ValueError("subject history participant limit is invalid")


def _validate_review_filter(value: tuple[ReviewStatus, ...]) -> None:
    if (
        isinstance(value, tuple)
        and (
            not value
            or any(not isinstance(item, ReviewStatus) for item in value)
        )
    ):
        raise ValueError("subject history detail filter is invalid")
