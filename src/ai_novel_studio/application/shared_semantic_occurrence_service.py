from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid5

from ai_novel_studio.application.shared_semantic_import_service import (
    SharedSemanticChapterResult,
)
from ai_novel_studio.core.context.semantic_windowing import SemanticWindow
from ai_novel_studio.core.context.shared_semantic_result import (
    ParticipantLinkCandidate,
    SharedSemanticResult,
    SourceSpan,
    SubjectMentionCandidate,
)
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType
from ai_novel_studio.domain.occurrence import (
    OCCURRENCE_TYPE_VOCABULARY_V1,
    Occurrence,
    OccurrenceSourceRange,
    OccurrenceType,
    SubjectOccurrenceLink,
    SubjectOccurrenceLinkSourceRange,
)
from ai_novel_studio.domain.subject import SubjectType
from ai_novel_studio.infrastructure.storage.occurrence_repository import (
    OccurrenceRepository,
    OccurrenceRepositoryError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository

_MAX_OCCURRENCES = 100
_MAX_LINKS = 500
_MAX_RECORDS = 600
_MAX_CANDIDATE_ID = 512
_RECORD_NAMESPACE_V1 = UUID("5030cea3-779a-5530-a221-86e34158ba1f")
_FAILURE_MESSAGES = {
    "LIMIT_EXCEEDED": "occurrence binding candidate limit exceeded",
    "DUPLICATE_RESOLVED_PARTICIPANT": (
        "occurrence binding has duplicate resolved participant"
    ),
    "INVALID_SOURCE_RANGES": "occurrence binding source ranges are invalid",
    "INVALID_CANDIDATE": "occurrence binding candidate is invalid",
    "PERSISTENCE_FAILED": "occurrence binding could not be persisted",
}


class OccurrenceBindingStatus(StrEnum):
    APPLIED = "APPLIED"
    FAILED = "FAILED"


class OccurrenceBindingIssueCode(StrEnum):
    UNKNOWN_OCCURRENCE_TYPE = "UNKNOWN_OCCURRENCE_TYPE"
    MISSING_OCCURRENCE_REFERENCE = "MISSING_OCCURRENCE_REFERENCE"
    OCCURRENCE_OMITTED = "OCCURRENCE_OMITTED"
    UNRESOLVED_SUBJECT = "UNRESOLVED_SUBJECT"
    AMBIGUOUS_SUBJECT = "AMBIGUOUS_SUBJECT"
    SUBJECT_UNAVAILABLE = "SUBJECT_UNAVAILABLE"


class OccurrenceBindingFailureCode(StrEnum):
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    DUPLICATE_RESOLVED_PARTICIPANT = "DUPLICATE_RESOLVED_PARTICIPANT"
    INVALID_SOURCE_RANGES = "INVALID_SOURCE_RANGES"
    INVALID_CANDIDATE = "INVALID_CANDIDATE"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"


@dataclass(frozen=True, slots=True)
class OccurrenceBindingIssue:
    candidate_source_id: str
    code: OccurrenceBindingIssueCode

    def __post_init__(self) -> None:
        if (
            not isinstance(self.candidate_source_id, str)
            or not self.candidate_source_id
            or self.candidate_source_id != self.candidate_source_id.strip()
            or len(self.candidate_source_id) > _MAX_CANDIDATE_ID
            or not isinstance(self.code, OccurrenceBindingIssueCode)
        ):
            raise ValueError("occurrence binding issue is invalid")


@dataclass(frozen=True, slots=True)
class OccurrenceBindingFailure:
    code: OccurrenceBindingFailureCode
    message: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.code, OccurrenceBindingFailureCode)
            or self.message != _FAILURE_MESSAGES[self.code.value]
        ):
            raise ValueError("occurrence binding failure is invalid")


@dataclass(frozen=True, slots=True)
class OccurrenceChapterBindingResult:
    chapter_id: str
    source_revision: int
    status: OccurrenceBindingStatus
    accepted_occurrence_ids: tuple[str, ...]
    accepted_link_ids: tuple[str, ...]
    issues: tuple[OccurrenceBindingIssue, ...]
    failure: OccurrenceBindingFailure | None

    def __post_init__(self) -> None:
        try:
            validate_id(self.chapter_id)
            for record_id in (*self.accepted_occurrence_ids, *self.accepted_link_ids):
                validate_id(record_id)
        except (TypeError, ValueError):
            raise ValueError("occurrence binding result is invalid") from None
        if (
            isinstance(self.source_revision, bool)
            or not isinstance(self.source_revision, int)
            or self.source_revision < 0
            or not isinstance(self.status, OccurrenceBindingStatus)
            or not isinstance(self.accepted_occurrence_ids, tuple)
            or not isinstance(self.accepted_link_ids, tuple)
            or not isinstance(self.issues, tuple)
            or any(not isinstance(item, OccurrenceBindingIssue) for item in self.issues)
            or len(set(self.accepted_occurrence_ids))
            != len(self.accepted_occurrence_ids)
            or len(set(self.accepted_link_ids)) != len(self.accepted_link_ids)
            or len(
                set((*self.accepted_occurrence_ids, *self.accepted_link_ids))
            )
            != len(self.accepted_occurrence_ids) + len(self.accepted_link_ids)
        ):
            raise ValueError("occurrence binding result is invalid")
        if self.status is OccurrenceBindingStatus.APPLIED:
            if self.failure is not None:
                raise ValueError("occurrence binding result is invalid")
        elif (
            not isinstance(self.failure, OccurrenceBindingFailure)
            or self.accepted_occurrence_ids
            or self.accepted_link_ids
        ):
            raise ValueError("occurrence binding result is invalid")

    @property
    def accepted_occurrence_count(self) -> int:
        return len(self.accepted_occurrence_ids)

    @property
    def accepted_link_count(self) -> int:
        return len(self.accepted_link_ids)

    @property
    def unresolved_count(self) -> int:
        return sum(
            item.code
            in {
                OccurrenceBindingIssueCode.UNRESOLVED_SUBJECT,
                OccurrenceBindingIssueCode.SUBJECT_UNAVAILABLE,
            }
            for item in self.issues
        )

    @property
    def ambiguous_count(self) -> int:
        return sum(
            item.code is OccurrenceBindingIssueCode.AMBIGUOUS_SUBJECT
            for item in self.issues
        )

    @property
    def omitted_count(self) -> int:
        return len(self.issues) - self.unresolved_count - self.ambiguous_count

    @property
    def failed_count(self) -> int:
        return int(self.status is OccurrenceBindingStatus.FAILED)


@dataclass(frozen=True, slots=True)
class _OccurrencePlan:
    record_id: str
    candidate_source_id: str
    type_code: OccurrenceType
    title: str
    summary: str
    narrative_sequence: int
    ranges: tuple[OccurrenceSourceRange, ...]


@dataclass(frozen=True, slots=True)
class _LinkPlan:
    record_id: str
    candidate_source_id: str
    occurrence_id: str
    subject_id: str
    role: str
    subject_summary: str
    ranges: tuple[SubjectOccurrenceLinkSourceRange, ...]


class _InvalidRanges(RuntimeError):
    pass


class _ResolutionStorageFailure(RuntimeError):
    pass


class SharedSemanticOccurrenceService:
    def __init__(
        self,
        project: ProjectRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not isinstance(project, ProjectRepository):
            raise TypeError("occurrence binding project is invalid")
        if not callable(clock):
            raise TypeError("occurrence binding clock is invalid")
        self._repository = OccurrenceRepository(project)
        self._subjects = SubjectRepository(project)
        self._clock = clock
        self._resolved_names: dict[str, tuple[str, ...]] = {}

    def persist_chapter(
        self,
        chapter: SharedSemanticChapterResult,
    ) -> OccurrenceChapterBindingResult:
        if not isinstance(chapter, SharedSemanticChapterResult):
            raise TypeError("occurrence binding chapter result is invalid")
        _validate_chapter_result(chapter)
        self._resolved_names.clear()
        occurrence_count = sum(len(item.occurrences) for item in chapter.results)
        link_count = sum(len(item.participant_links) for item in chapter.results)
        if (
            occurrence_count > _MAX_OCCURRENCES
            or link_count > _MAX_LINKS
            or occurrence_count + link_count > _MAX_RECORDS
        ):
            return _failed(chapter, OccurrenceBindingFailureCode.LIMIT_EXCEEDED)

        issues: list[OccurrenceBindingIssue] = []
        occurrence_plans: list[_OccurrencePlan] = []
        occurrence_ids: dict[str, str] = {}
        omitted_occurrences: set[str] = set()
        try:
            for result in chapter.results:
                for occurrence_candidate in result.occurrences:
                    try:
                        type_code = OccurrenceType(
                            occurrence_candidate.occurrence_type
                        )
                    except ValueError:
                        omitted_occurrences.add(
                            occurrence_candidate.candidate_id
                        )
                        issues.append(
                            OccurrenceBindingIssue(
                                occurrence_candidate.candidate_id,
                                OccurrenceBindingIssueCode.UNKNOWN_OCCURRENCE_TYPE,
                            )
                        )
                        continue
                    record_id = _record_id(
                        "OCCURRENCE",
                        occurrence_candidate.candidate_id,
                    )
                    ranges = _occurrence_ranges(
                        result.window,
                        occurrence_candidate.spans,
                    )
                    occurrence_ids[occurrence_candidate.candidate_id] = record_id
                    occurrence_plans.append(
                        _OccurrencePlan(
                            record_id,
                            occurrence_candidate.candidate_id,
                            type_code,
                            occurrence_candidate.title,
                            occurrence_candidate.summary,
                            chapter.narrative_sequence,
                            ranges,
                        )
                    )
        except _InvalidRanges:
            return _failed(chapter, OccurrenceBindingFailureCode.INVALID_SOURCE_RANGES)

        link_plans: list[_LinkPlan] = []
        pairs: set[tuple[str, str]] = set()
        try:
            for result in chapter.results:
                mentions = {
                    item.candidate_id: item for item in result.subject_mentions
                }
                for link_candidate in result.participant_links:
                    occurrence_candidate_id = link_candidate.occurrence_candidate_id
                    if occurrence_candidate_id is None:
                        issues.append(
                            OccurrenceBindingIssue(
                                link_candidate.candidate_id,
                                OccurrenceBindingIssueCode.MISSING_OCCURRENCE_REFERENCE,
                            )
                        )
                        continue
                    if occurrence_candidate_id in omitted_occurrences:
                        issues.append(
                            OccurrenceBindingIssue(
                                link_candidate.candidate_id,
                                OccurrenceBindingIssueCode.OCCURRENCE_OMITTED,
                            )
                        )
                        continue
                    occurrence_id = occurrence_ids.get(occurrence_candidate_id)
                    if occurrence_id is None:
                        issues.append(
                            OccurrenceBindingIssue(
                                link_candidate.candidate_id,
                                OccurrenceBindingIssueCode.MISSING_OCCURRENCE_REFERENCE,
                            )
                        )
                        continue
                    subject_id, issue_code = self._resolve_subject(
                        link_candidate,
                        mentions,
                    )
                    if issue_code is not None:
                        issues.append(
                            OccurrenceBindingIssue(
                                link_candidate.candidate_id,
                                issue_code,
                            )
                        )
                        continue
                    if subject_id is None:
                        raise RuntimeError("resolved subject result is inconsistent")
                    pair = (occurrence_id, subject_id)
                    if pair in pairs:
                        return _failed(
                            chapter,
                            OccurrenceBindingFailureCode.DUPLICATE_RESOLVED_PARTICIPANT,
                        )
                    pairs.add(pair)
                    link_plans.append(
                        _LinkPlan(
                            _record_id(
                                "SUBJECT_OCCURRENCE_LINK",
                                link_candidate.candidate_id,
                            ),
                            link_candidate.candidate_id,
                            occurrence_id,
                            subject_id,
                            link_candidate.role,
                            link_candidate.subject_summary,
                            _link_ranges(result.window, link_candidate.spans),
                        )
                    )
        except _InvalidRanges:
            return _failed(chapter, OccurrenceBindingFailureCode.INVALID_SOURCE_RANGES)
        except _ResolutionStorageFailure:
            return _failed(chapter, OccurrenceBindingFailureCode.PERSISTENCE_FAILED)

        timestamp = self._clock()
        _validate_clock_value(timestamp)
        try:
            occurrences = tuple(
                Occurrence(
                    plan.record_id,
                    plan.candidate_source_id,
                    plan.type_code,
                    OCCURRENCE_TYPE_VOCABULARY_V1,
                    plan.title,
                    plan.summary,
                    plan.narrative_sequence,
                    Authority.MODEL_EXTRACTED,
                    ReviewStatus.REVIEW,
                    SourceType.MODEL,
                    False,
                    False,
                    plan.ranges,
                    timestamp,
                    timestamp,
                )
                for plan in occurrence_plans
            )
            links = tuple(
                SubjectOccurrenceLink(
                    plan.record_id,
                    plan.candidate_source_id,
                    plan.occurrence_id,
                    plan.subject_id,
                    plan.role,
                    plan.subject_summary,
                    Authority.MODEL_EXTRACTED,
                    ReviewStatus.REVIEW,
                    SourceType.MODEL,
                    False,
                    False,
                    plan.ranges,
                    timestamp,
                    timestamp,
                )
                for plan in link_plans
            )
        except ValueError:
            return _failed(chapter, OccurrenceBindingFailureCode.INVALID_CANDIDATE)
        try:
            self._repository.create_model_candidates_for_chapter(
                chapter.chapter_id,
                expected_revision=chapter.source_revision,
                expected_source_hash=chapter.source_hash,
                occurrences=occurrences,
                links=links,
            )
        except (OccurrenceRepositoryError, sqlite3.Error):
            return _failed(chapter, OccurrenceBindingFailureCode.PERSISTENCE_FAILED)
        return OccurrenceChapterBindingResult(
            chapter.chapter_id,
            chapter.source_revision,
            OccurrenceBindingStatus.APPLIED,
            tuple(item.id for item in occurrences),
            tuple(item.id for item in links),
            tuple(issues),
            None,
        )

    def _resolve_subject(
        self,
        candidate: ParticipantLinkCandidate,
        mentions: Mapping[str, SubjectMentionCandidate],
    ) -> tuple[str | None, OccurrenceBindingIssueCode | None]:
        if candidate.subject is not None:
            try:
                subject = self._subjects.get(candidate.subject.subject_id)
            except KeyError:
                return None, OccurrenceBindingIssueCode.SUBJECT_UNAVAILABLE
            except (sqlite3.Error, TypeError, ValueError):
                raise _ResolutionStorageFailure from None
            if not subject.active or subject.type is not SubjectType.CHARACTER:
                return None, OccurrenceBindingIssueCode.SUBJECT_UNAVAILABLE
            return subject.id, None
        mention = mentions.get(candidate.subject_mention_candidate_id or "")
        name = getattr(mention, "mention", None)
        if not isinstance(name, str):
            return None, OccurrenceBindingIssueCode.UNRESOLVED_SUBJECT
        normalized = name.strip()
        try:
            matches = self._resolved_names.get(normalized)
            if matches is None:
                matches = self._confirmed_subject_ids(normalized)
                self._resolved_names[normalized] = matches
        except (sqlite3.Error, TypeError, ValueError):
            raise _ResolutionStorageFailure from None
        if not matches:
            return None, OccurrenceBindingIssueCode.UNRESOLVED_SUBJECT
        if len(matches) > 1:
            return None, OccurrenceBindingIssueCode.AMBIGUOUS_SUBJECT
        return matches[0], None

    def _confirmed_subject_ids(self, name: str) -> tuple[str, ...]:
        accepted: list[str] = []
        for subject in self._subjects.resolve_character_name(name):
            if not subject.active or subject.type is not SubjectType.CHARACTER:
                continue
            if subject.canonical_name == name:
                accepted.append(subject.id)
                continue
            if any(
                alias.confirmed and alias.alias == name
                for alias in self._subjects.list_aliases(subject.id)
            ):
                accepted.append(subject.id)
        return tuple(sorted(set(accepted)))


def _validate_chapter_result(chapter: SharedSemanticChapterResult) -> None:
    if (
        not isinstance(chapter.results, tuple)
        or any(
            not isinstance(result, SharedSemanticResult)
            or result.window.chapter_id != chapter.chapter_id
            or result.window.source_revision != chapter.source_revision
            or result.window.source_hash != chapter.source_hash
            or result.window.narrative_sequence != chapter.narrative_sequence
            or result.window.window_ordinal != ordinal
            for ordinal, result in enumerate(chapter.results)
        )
    ):
        raise ValueError("occurrence binding chapter result is invalid")


def _record_id(kind: str, candidate_source_id: str) -> str:
    return str(uuid5(_RECORD_NAMESPACE_V1, f"{kind}\x1f{candidate_source_id}"))


def _occurrence_ranges(
    window: SemanticWindow,
    spans: tuple[SourceSpan, ...],
) -> tuple[OccurrenceSourceRange, ...]:
    absolute = _absolute_spans(window, spans)
    return tuple(
        OccurrenceSourceRange(
            ordinal,
            window.chapter_id,
            window.source_revision,
            window.source_hash,
            window.source_id,
            window.policy_version,
            start,
            end,
        )
        for ordinal, (start, end) in enumerate(absolute)
    )


def _link_ranges(
    window: SemanticWindow,
    spans: tuple[SourceSpan, ...],
) -> tuple[SubjectOccurrenceLinkSourceRange, ...]:
    absolute = _absolute_spans(window, spans)
    return tuple(
        SubjectOccurrenceLinkSourceRange(
            ordinal,
            window.chapter_id,
            window.source_revision,
            window.source_hash,
            window.source_id,
            window.policy_version,
            start,
            end,
        )
        for ordinal, (start, end) in enumerate(absolute)
    )


def _absolute_spans(
    window: SemanticWindow,
    spans: tuple[SourceSpan, ...],
) -> tuple[tuple[int, int], ...]:
    if not isinstance(spans, tuple) or not spans:
        raise _InvalidRanges
    result: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for span in spans:
        if (
            not isinstance(span, SourceSpan)
            or span.end > len(window.text)
            or span.quote != window.text[span.start : span.end]
        ):
            raise _InvalidRanges
        absolute = (
            window.source_start + span.start,
            window.source_start + span.end,
        )
        if absolute in seen:
            raise _InvalidRanges
        seen.add(absolute)
        result.append(absolute)
    return tuple(result)


def _validate_clock_value(value: object) -> None:
    if not isinstance(value, datetime):
        raise ValueError("occurrence binding clock is invalid")
    try:
        if value.utcoffset() is None:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError("occurrence binding clock is invalid") from None


def _failed(
    chapter: SharedSemanticChapterResult,
    code: OccurrenceBindingFailureCode,
) -> OccurrenceChapterBindingResult:
    return OccurrenceChapterBindingResult(
        chapter.chapter_id,
        chapter.source_revision,
        OccurrenceBindingStatus.FAILED,
        (),
        (),
        (),
        OccurrenceBindingFailure(code, _FAILURE_MESSAGES[code.value]),
    )


__all__ = [
    "OccurrenceBindingFailure",
    "OccurrenceBindingFailureCode",
    "OccurrenceBindingIssue",
    "OccurrenceBindingIssueCode",
    "OccurrenceBindingStatus",
    "OccurrenceChapterBindingResult",
    "SharedSemanticOccurrenceService",
]
