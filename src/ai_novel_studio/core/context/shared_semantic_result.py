from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ai_novel_studio.core.context.semantic_windowing import SemanticWindow
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.domain.memory import Authority, ReviewStatus
from ai_novel_studio.domain.view import EpistemicStatus, ViewType

SHARED_SEMANTIC_RESULT_V1 = "shared-semantic-result-v1"
_MAX_MENTIONS = 100
_MAX_ALIASES = 100
_MAX_OCCURRENCES = 100
_MAX_LINKS = 500
_MAX_STATES = 100
_MAX_VIEWS = 100
_MAX_CANDIDATES = 1_000
_MAX_TEXT = 4_000
_MAX_QUOTE = 2_000
_MAX_TOTAL_TEXT = 32_000
_MAX_SPANS = 32
_MAX_CANDIDATE_ID = 512


class SemanticCandidateKind(StrEnum):
    SUBJECT_MENTION = "subject-mention"
    ALIAS = "alias"
    OCCURRENCE = "occurrence"
    PARTICIPANT_LINK = "participant-link"
    STATE_CHANGE = "state-change"
    VIEW_DIFFERENCE = "view-difference"
    WINDOW_SUMMARY = "window-summary"


def candidate_source_id(
    window: SemanticWindow,
    kind: str | SemanticCandidateKind,
    ordinal: int,
) -> str:
    if not isinstance(window, SemanticWindow):
        raise ValueError("semantic result window is invalid")
    if isinstance(kind, SemanticCandidateKind):
        kind_value = kind.value
    elif isinstance(kind, str):
        try:
            kind_value = SemanticCandidateKind(kind).value
        except ValueError:
            raise ValueError("semantic result candidate kind is invalid") from None
    else:
        raise ValueError("semantic result candidate kind is invalid")
    if (
        isinstance(ordinal, bool)
        or not isinstance(ordinal, int)
        or not 0 <= ordinal < 10_000
    ):
        raise ValueError("semantic result candidate ordinal is invalid")
    source_id = f"{window.source_id}:{kind_value}:{ordinal}"
    if len(source_id) > _MAX_CANDIDATE_ID:
        raise ValueError("semantic result candidate ID is invalid")
    return source_id


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start: int
    end: int
    quote: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.start, bool)
            or isinstance(self.end, bool)
            or not isinstance(self.start, int)
            or not isinstance(self.end, int)
            or self.start < 0
            or self.end <= self.start
            or not isinstance(self.quote, str)
            or len(self.quote) != self.end - self.start
            or len(self.quote) > _MAX_QUOTE
        ):
            raise ValueError("semantic result span is invalid")


@dataclass(frozen=True, slots=True)
class ResolvedSubjectReference:
    subject_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject_id, str):
            raise ValueError("semantic result subject reference is invalid")
        try:
            object.__setattr__(self, "subject_id", validate_id(self.subject_id))
        except ValueError:
            raise ValueError("semantic result subject reference is invalid") from None


@dataclass(frozen=True, slots=True)
class SubjectMentionCandidate:
    candidate_id: str
    mention: str
    spans: tuple[SourceSpan, ...]


@dataclass(frozen=True, slots=True)
class AliasCandidate:
    candidate_id: str
    alias: str
    spans: tuple[SourceSpan, ...]
    resolved_subject: ResolvedSubjectReference | None = None


@dataclass(frozen=True, slots=True)
class OccurrenceCandidate:
    candidate_id: str
    occurrence_type: str
    title: str
    summary: str
    spans: tuple[SourceSpan, ...]


@dataclass(frozen=True, slots=True)
class ParticipantLinkCandidate:
    candidate_id: str
    subject: ResolvedSubjectReference | None
    role: str
    subject_summary: str
    spans: tuple[SourceSpan, ...]
    occurrence_candidate_id: str | None = None
    subject_mention_candidate_id: str | None = None


@dataclass(frozen=True, slots=True)
class StateChangeCandidate:
    candidate_id: str
    subject: ResolvedSubjectReference | None
    change_type: str
    detail: str
    spans: tuple[SourceSpan, ...]
    occurrence_candidate_id: str | None = None
    subject_mention_candidate_id: str | None = None


@dataclass(frozen=True, slots=True)
class ViewDifferenceCandidate:
    candidate_id: str
    view_type: ViewType
    observer: ResolvedSubjectReference | None
    target: ResolvedSubjectReference | None
    epistemic_status: EpistemicStatus | None
    content: str
    spans: tuple[SourceSpan, ...]
    occurrence_candidate_id: str | None = None
    observer_mention_candidate_id: str | None = None
    target_mention_candidate_id: str | None = None


@dataclass(frozen=True, slots=True)
class WindowSummaryCandidate:
    candidate_id: str
    content: str
    spans: tuple[SourceSpan, ...]


@dataclass(frozen=True, slots=True)
class SharedSemanticResult:
    window: SemanticWindow
    subject_mentions: tuple[SubjectMentionCandidate, ...] = ()
    aliases: tuple[AliasCandidate, ...] = ()
    occurrences: tuple[OccurrenceCandidate, ...] = ()
    participant_links: tuple[ParticipantLinkCandidate, ...] = ()
    state_changes: tuple[StateChangeCandidate, ...] = ()
    view_differences: tuple[ViewDifferenceCandidate, ...] = ()
    summary: WindowSummaryCandidate | None = None
    schema_version: str = SHARED_SEMANTIC_RESULT_V1
    authority: Authority = Authority.MODEL_EXTRACTED
    review_status: ReviewStatus = ReviewStatus.REVIEW

    def __post_init__(self) -> None:
        if (
            not isinstance(self.window, SemanticWindow)
            or self.schema_version != SHARED_SEMANTIC_RESULT_V1
            or self.authority is not Authority.MODEL_EXTRACTED
            or self.review_status is not ReviewStatus.REVIEW
        ):
            raise ValueError("semantic result metadata is invalid")
        collections = (
            (
                self.subject_mentions,
                SemanticCandidateKind.SUBJECT_MENTION,
                _MAX_MENTIONS,
                SubjectMentionCandidate,
            ),
            (self.aliases, SemanticCandidateKind.ALIAS, _MAX_ALIASES, AliasCandidate),
            (
                self.occurrences,
                SemanticCandidateKind.OCCURRENCE,
                _MAX_OCCURRENCES,
                OccurrenceCandidate,
            ),
            (
                self.participant_links,
                SemanticCandidateKind.PARTICIPANT_LINK,
                _MAX_LINKS,
                ParticipantLinkCandidate,
            ),
            (
                self.state_changes,
                SemanticCandidateKind.STATE_CHANGE,
                _MAX_STATES,
                StateChangeCandidate,
            ),
            (
                self.view_differences,
                SemanticCandidateKind.VIEW_DIFFERENCE,
                _MAX_VIEWS,
                ViewDifferenceCandidate,
            ),
        )
        total = sum(len(values) for values, _, _, _ in collections) + (
            1 if self.summary else 0
        )
        if total > _MAX_CANDIDATES:
            raise ValueError("semantic result candidate limit exceeded")
        known_ids: set[str] = set()
        occurrence_ids: set[str] = set()
        total_text = 0
        for values, kind, limit, candidate_type in collections:
            if not isinstance(values, tuple) or len(values) > limit:
                raise ValueError("semantic result candidate collection is invalid")
            ids, text_size = _validate_collection(
                values,
                kind,
                candidate_type,
                self.window,
                known_ids,
            )
            known_ids.update(ids)
            total_text += text_size
            if kind is SemanticCandidateKind.OCCURRENCE:
                occurrence_ids.update(ids)
        if self.summary is not None:
            if self.summary.candidate_id != candidate_source_id(
                self.window, SemanticCandidateKind.WINDOW_SUMMARY, 0
            ):
                raise ValueError("semantic result summary identity is invalid")
            known_ids.add(self.summary.candidate_id)
            total_text += _validate_candidate(self.summary, self.window)
        if total_text > _MAX_TOTAL_TEXT:
            raise ValueError("semantic result text limit exceeded")
        mention_ids = {item.candidate_id for item in self.subject_mentions}
        for candidate_link in self.participant_links:
            _validate_child_references(
                candidate_link.occurrence_candidate_id,
                candidate_link.subject_mention_candidate_id,
                occurrence_ids,
                mention_ids,
            )
        for candidate_state in self.state_changes:
            _validate_child_references(
                candidate_state.occurrence_candidate_id,
                candidate_state.subject_mention_candidate_id,
                occurrence_ids,
                mention_ids,
            )
        for candidate_view in self.view_differences:
            _validate_child_references(
                candidate_view.occurrence_candidate_id,
                candidate_view.observer_mention_candidate_id,
                occurrence_ids,
                mention_ids,
            )
            _validate_child_references(
                None,
                candidate_view.target_mention_candidate_id,
                occurrence_ids,
                mention_ids,
            )


def _validate_child_references(
    occurrence_id: str | None,
    mention_id: str | None,
    occurrence_ids: set[str],
    mention_ids: set[str],
) -> None:
    if occurrence_id is not None and occurrence_id not in occurrence_ids:
        raise ValueError("semantic result occurrence reference is invalid")
    if mention_id is not None and mention_id not in mention_ids:
        raise ValueError("semantic result mention reference is invalid")


def _validate_collection(
    values: tuple[object, ...],
    kind: SemanticCandidateKind,
    candidate_type: type[object],
    window: SemanticWindow,
    known_ids: set[str],
) -> tuple[tuple[str, ...], int]:
    ids: list[str] = []
    text_size = 0
    for ordinal, candidate in enumerate(values):
        expected = candidate_source_id(window, kind, ordinal)
        candidate_id = getattr(candidate, "candidate_id", None)
        if not isinstance(candidate, candidate_type):
            raise ValueError("semantic result candidate collection is invalid")
        if candidate_id != expected or candidate_id in known_ids or candidate_id in ids:
            raise ValueError("semantic result candidate identity is invalid")
        ids.append(expected)
        text_size += _validate_candidate(candidate, window)
    return tuple(ids), text_size


def _validate_candidate(candidate: object, window: SemanticWindow) -> int:
    candidate_id = getattr(candidate, "candidate_id", None)
    if (
        not isinstance(candidate_id, str)
        or not candidate_id
        or len(candidate_id) > _MAX_CANDIDATE_ID
    ):
        raise ValueError("semantic result candidate is invalid")
    spans = getattr(candidate, "spans", ())
    if not isinstance(spans, tuple) or not 1 <= len(spans) <= _MAX_SPANS:
        raise ValueError("semantic result spans are invalid")
    total = 0
    for span in spans:
        if (
            not isinstance(span, SourceSpan)
            or span.end > len(window.text)
            or span.quote != window.text[span.start : span.end]
        ):
            raise ValueError("semantic result span is invalid")
        total += len(span.quote)
    if isinstance(candidate, (SubjectMentionCandidate, AliasCandidate)):
        source_text = (
            candidate.mention
            if isinstance(candidate, SubjectMentionCandidate)
            else candidate.alias
        )
        if source_text != spans[0].quote:
            raise ValueError("semantic result mention is invalid")
        if isinstance(candidate, AliasCandidate):
            if candidate.resolved_subject is not None and not isinstance(
                candidate.resolved_subject, ResolvedSubjectReference
            ):
                raise ValueError("semantic result subject reference is invalid")
    text_fields = (
        "mention",
        "alias",
        "occurrence_type",
        "title",
        "summary",
        "role",
        "subject_summary",
        "change_type",
        "detail",
        "content",
    )
    for field in text_fields:
        value = getattr(candidate, field, None)
        if value is not None:
            if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT:
                raise ValueError("semantic result candidate text is invalid")
            total += len(value)
    view_type = getattr(candidate, "view_type", None)
    if isinstance(candidate, (ParticipantLinkCandidate, StateChangeCandidate)):
        subject = candidate.subject
        mention_id = candidate.subject_mention_candidate_id
        if subject is not None and not isinstance(subject, ResolvedSubjectReference):
            raise ValueError("semantic result subject reference is invalid")
        if (subject is None) == (mention_id is None):
            raise ValueError("semantic result subject reference is invalid")
    if view_type is not None:
        if not isinstance(candidate, ViewDifferenceCandidate) or not isinstance(
            candidate.view_type, ViewType
        ):
            raise ValueError("semantic result view shape is invalid")
        if candidate.observer is not None and not isinstance(
            candidate.observer, ResolvedSubjectReference
        ):
            raise ValueError("semantic result subject reference is invalid")
        if candidate.target is not None and not isinstance(
            candidate.target, ResolvedSubjectReference
        ):
            raise ValueError("semantic result subject reference is invalid")
        if candidate.epistemic_status is not None and not isinstance(
            candidate.epistemic_status, EpistemicStatus
        ):
            raise ValueError("semantic result view shape is invalid")
        if view_type is ViewType.CHARACTER_VIEW:
            observer = candidate.observer
            observer_mention = candidate.observer_mention_candidate_id
            target = candidate.target
            target_mention = candidate.target_mention_candidate_id
            if (
                (observer is None) == (observer_mention is None)
            ) or (
                (target is None) == (target_mention is None)
            ) or (
                candidate.epistemic_status is None
            ):
                raise ValueError("semantic result view shape is invalid")
            if (
                observer is not None and target is not None and observer == target
            ):
                raise ValueError("semantic result view shape is invalid")
        elif view_type is ViewType.READER_VIEW:
            if (
                candidate.observer is not None
                or candidate.observer_mention_candidate_id is not None
                or candidate.epistemic_status is not None
                or (
                    (candidate.target is None)
                    == (candidate.target_mention_candidate_id is None)
                )
            ):
                raise ValueError("semantic result view shape is invalid")
        else:
            raise ValueError("semantic result view shape is invalid")
    return total
