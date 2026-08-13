from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType

OCCURRENCE_TYPE_VOCABULARY_V1 = "occurrence-type-v1"
_MAX_CANDIDATE_SOURCE_ID = 512
_MAX_TITLE = 500
_MAX_SUMMARY = 4_000
_MAX_ROLE = 100
_MAX_SUBJECT_SUMMARY = 2_000
_MAX_WINDOW_SOURCE_ID = 512
_MAX_POLICY_VERSION = 100
_MAX_ORDINAL = 10_000
_MAX_SOURCE_CODEPOINTS = 20_000_000
_SHA256 = re.compile(r"[0-9a-f]{64}")


class OccurrenceType(StrEnum):
    ACTION = "ACTION"
    CONVERSATION = "CONVERSATION"
    CONFLICT = "CONFLICT"
    DISCOVERY = "DISCOVERY"
    DECISION = "DECISION"
    REVELATION = "REVELATION"
    TRANSITION = "TRANSITION"
    RELATIONSHIP_CHANGE = "RELATIONSHIP_CHANGE"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class OccurrenceSourceRange:
    ordinal: int
    source_chapter_id: str
    source_revision: int
    source_hash: str
    semantic_window_source_id: str
    policy_version: str
    source_start: int
    source_end: int

    def __post_init__(self) -> None:
        _validate_source_range(self)


@dataclass(frozen=True, slots=True)
class SubjectOccurrenceLinkSourceRange:
    ordinal: int
    source_chapter_id: str
    source_revision: int
    source_hash: str
    semantic_window_source_id: str
    policy_version: str
    source_start: int
    source_end: int

    def __post_init__(self) -> None:
        _validate_source_range(self)


@dataclass(frozen=True, slots=True)
class Occurrence:
    id: str
    candidate_source_id: str
    type_code: OccurrenceType
    vocabulary_version: str
    title: str
    summary: str
    narrative_sequence: int
    authority: Authority
    review_status: ReviewStatus
    source_type: SourceType
    stale: bool
    source_changed: bool
    source_ranges: tuple[OccurrenceSourceRange, ...]
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _record_id(self.id)
        _candidate_source_id(self.candidate_source_id)
        if not isinstance(self.type_code, OccurrenceType):
            raise ValueError("occurrence type is invalid")
        if self.vocabulary_version != OCCURRENCE_TYPE_VOCABULARY_V1:
            raise ValueError("occurrence vocabulary is invalid")
        _bounded_text(self.title, "title", _MAX_TITLE)
        _bounded_text(self.summary, "summary", _MAX_SUMMARY)
        _positive_integer(self.narrative_sequence, "narrative sequence")
        _model_record_contract(
            self.authority,
            self.review_status,
            self.source_type,
        )
        _status_flags(self.stale, self.source_changed)
        _source_ranges(self.source_ranges, OccurrenceSourceRange)
        _timestamps(self.created_at, self.updated_at)


@dataclass(frozen=True, slots=True)
class SubjectOccurrenceLink:
    id: str
    candidate_source_id: str
    occurrence_id: str
    subject_id: str
    role: str
    subject_summary: str
    authority: Authority
    review_status: ReviewStatus
    source_type: SourceType
    stale: bool
    source_changed: bool
    source_ranges: tuple[SubjectOccurrenceLinkSourceRange, ...]
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _record_id(self.id)
        _candidate_source_id(self.candidate_source_id)
        _record_id(self.occurrence_id)
        _record_id(self.subject_id)
        _bounded_text(self.role, "link role", _MAX_ROLE)
        _bounded_text(
            self.subject_summary,
            "link subject summary",
            _MAX_SUBJECT_SUMMARY,
        )
        _model_record_contract(
            self.authority,
            self.review_status,
            self.source_type,
        )
        _status_flags(self.stale, self.source_changed)
        _source_ranges(
            self.source_ranges,
            SubjectOccurrenceLinkSourceRange,
        )
        _timestamps(self.created_at, self.updated_at)


def _validate_source_range(
    value: OccurrenceSourceRange | SubjectOccurrenceLinkSourceRange,
) -> None:
    _bounded_nonnegative_integer(value.ordinal, "source range ordinal", _MAX_ORDINAL)
    _record_id(value.source_chapter_id)
    _nonnegative_integer(value.source_revision, "source range revision")
    if not isinstance(value.source_hash, str) or _SHA256.fullmatch(
        value.source_hash
    ) is None:
        raise ValueError("occurrence source range hash is invalid")
    _bounded_text(
        value.semantic_window_source_id,
        "source range window ID",
        _MAX_WINDOW_SOURCE_ID,
    )
    _bounded_text(
        value.policy_version,
        "source range policy",
        _MAX_POLICY_VERSION,
    )
    _bounded_nonnegative_integer(
        value.source_start,
        "source range start",
        _MAX_SOURCE_CODEPOINTS,
    )
    if (
        isinstance(value.source_end, bool)
        or not isinstance(value.source_end, int)
        or value.source_end <= value.source_start
        or value.source_end > _MAX_SOURCE_CODEPOINTS
    ):
        raise ValueError("occurrence source range is invalid")


def _record_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("occurrence record ID is invalid")
    try:
        return validate_id(value)
    except ValueError:
        raise ValueError("occurrence record ID is invalid") from None


def _candidate_source_id(value: object) -> str:
    return _bounded_text(
        value,
        "candidate source",
        _MAX_CANDIDATE_SOURCE_ID,
    )


def _bounded_text(value: object, field: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > limit
    ):
        raise ValueError(f"occurrence {field} is invalid")
    return value


def _nonnegative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"occurrence {field} is invalid")
    return value


def _bounded_nonnegative_integer(value: object, field: str, limit: int) -> int:
    result = _nonnegative_integer(value, field)
    if result >= limit:
        raise ValueError(f"occurrence {field} is invalid")
    return result


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"occurrence {field} is invalid")
    return value


def _model_record_contract(
    authority: object,
    review_status: object,
    source_type: object,
) -> None:
    if (
        authority is not Authority.MODEL_EXTRACTED
        or source_type is not SourceType.MODEL
    ):
        raise ValueError("occurrence model review contract is invalid")
    if not isinstance(review_status, ReviewStatus):
        raise ValueError("occurrence review status is invalid")


def _status_flags(stale: object, source_changed: object) -> None:
    if not isinstance(stale, bool) or not isinstance(source_changed, bool):
        raise ValueError("occurrence status flags are invalid")


def _source_ranges(
    values: object,
    item_type: type[OccurrenceSourceRange]
    | type[SubjectOccurrenceLinkSourceRange],
) -> None:
    if (
        not isinstance(values, tuple)
        or not values
        or len(values) > _MAX_ORDINAL
        or any(
            not isinstance(item, item_type) or item.ordinal != ordinal
            for ordinal, item in enumerate(values)
        )
    ):
        raise ValueError("occurrence source ranges are invalid")
    first = values[0]
    envelope = (
        first.source_chapter_id,
        first.source_revision,
        first.source_hash,
        first.semantic_window_source_id,
        first.policy_version,
    )
    if any(
        (
            item.source_chapter_id,
            item.source_revision,
            item.source_hash,
            item.semantic_window_source_id,
            item.policy_version,
        )
        != envelope
        for item in values[1:]
    ):
        raise ValueError("occurrence source range envelope is invalid")


def _timestamps(created_at: object, updated_at: object) -> None:
    if not isinstance(created_at, datetime) or not isinstance(updated_at, datetime):
        raise ValueError("occurrence timestamps are invalid")
    try:
        if (
            created_at.utcoffset() is None
            or updated_at.utcoffset() is None
            or updated_at < created_at
        ):
            raise ValueError("occurrence timestamps are invalid")
    except (TypeError, ValueError, OverflowError):
        raise ValueError("occurrence timestamps are invalid") from None


__all__ = [
    "OCCURRENCE_TYPE_VOCABULARY_V1",
    "Occurrence",
    "OccurrenceSourceRange",
    "OccurrenceType",
    "SubjectOccurrenceLink",
    "SubjectOccurrenceLinkSourceRange",
]
