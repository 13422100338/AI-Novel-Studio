from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

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

OCCURRENCE_ID = "00000000-0000-0000-0000-000000000001"
LINK_ID = "00000000-0000-0000-0000-000000000002"
SUBJECT_ID = "00000000-0000-0000-0000-000000000003"
CHAPTER_ID = "00000000-0000-0000-0000-000000000004"
NOW = datetime(2026, 8, 13, tzinfo=UTC)


def _occurrence_range() -> OccurrenceSourceRange:
    return OccurrenceSourceRange(
        ordinal=0,
        source_chapter_id=CHAPTER_ID,
        source_revision=7,
        source_hash="a" * 64,
        semantic_window_source_id="SEMANTIC_WINDOW:source",
        policy_version="semantic-window-v1",
        source_start=4,
        source_end=12,
    )


def _link_range() -> SubjectOccurrenceLinkSourceRange:
    return SubjectOccurrenceLinkSourceRange(
        ordinal=0,
        source_chapter_id=CHAPTER_ID,
        source_revision=7,
        source_hash="a" * 64,
        semantic_window_source_id="SEMANTIC_WINDOW:source",
        policy_version="semantic-window-v1",
        source_start=4,
        source_end=12,
    )


def _occurrence(**changes: object) -> Occurrence:
    values: dict[str, object] = {
        "id": OCCURRENCE_ID,
        "candidate_source_id": "semantic-window:occurrence:0",
        "type_code": OccurrenceType.DISCOVERY,
        "vocabulary_version": OCCURRENCE_TYPE_VOCABULARY_V1,
        "title": "The sealed room opens",
        "summary": "The group discovers the missing ledger.",
        "narrative_sequence": 3,
        "authority": Authority.MODEL_EXTRACTED,
        "review_status": ReviewStatus.REVIEW,
        "source_type": SourceType.MODEL,
        "stale": False,
        "source_changed": False,
        "source_ranges": (_occurrence_range(),),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return Occurrence(**values)  # type: ignore[arg-type]


def _link(**changes: object) -> SubjectOccurrenceLink:
    values: dict[str, object] = {
        "id": LINK_ID,
        "candidate_source_id": "semantic-window:participant-link:0",
        "occurrence_id": OCCURRENCE_ID,
        "subject_id": SUBJECT_ID,
        "role": "witness",
        "subject_summary": "Witnesses the discovery and secures the ledger.",
        "authority": Authority.MODEL_EXTRACTED,
        "review_status": ReviewStatus.REVIEW,
        "source_type": SourceType.MODEL,
        "stale": False,
        "source_changed": False,
        "source_ranges": (_link_range(),),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return SubjectOccurrenceLink(**values)  # type: ignore[arg-type]


def test_occurrence_domain_is_immutable_and_uses_versioned_closed_vocabulary() -> None:
    occurrence = _occurrence()
    link = _link()

    assert tuple(item.value for item in OccurrenceType) == (
        "ACTION",
        "CONVERSATION",
        "CONFLICT",
        "DISCOVERY",
        "DECISION",
        "REVELATION",
        "TRANSITION",
        "RELATIONSHIP_CHANGE",
        "OTHER",
    )
    assert occurrence.vocabulary_version == "occurrence-type-v1"
    assert occurrence.source_ranges[0].source_start == 4
    assert link.subject_id == SUBJECT_ID
    with pytest.raises(AttributeError):
        occurrence.title = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"type_code": "DISCOVERY"}, "occurrence type"),
        ({"vocabulary_version": "occurrence-type-v2"}, "vocabulary"),
        ({"narrative_sequence": True}, "narrative sequence"),
        ({"title": " "}, "title"),
        ({"summary": "x" * 4_001}, "summary"),
        ({"candidate_source_id": "x" * 513}, "candidate source"),
        ({"authority": Authority.USER_CONFIRMED}, "model review"),
        ({"review_status": "REVIEW"}, "review status"),
        ({"source_type": SourceType.HUMAN}, "model review"),
        ({"stale": 1}, "status flags"),
        ({"source_ranges": ()}, "source ranges"),
    ],
)
def test_occurrence_rejects_invalid_or_non_review_model_contract(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _occurrence(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"subject_id": "not-a-uuid"},
        {"role": ""},
        {"role": "x" * 101},
        {"subject_summary": "x" * 2_001},
        {"authority": Authority.AUDITED},
        {"review_status": "REVIEW"},
        {"source_type": SourceType.SYSTEM},
        {"source_changed": 1},
        {"source_ranges": ()},
    ],
)
def test_subject_link_rejects_invalid_or_non_review_model_contract(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="occurrence"):
        _link(**changes)


@pytest.mark.parametrize("review_status", tuple(ReviewStatus))
def test_all_review_lifecycle_states_are_valid_domain_records(
    review_status: ReviewStatus,
) -> None:
    assert _occurrence(review_status=review_status).review_status is review_status
    assert _link(review_status=review_status).review_status is review_status


@pytest.mark.parametrize(
    "identity_change",
    [
        {"source_chapter_id": "00000000-0000-0000-0000-000000000099"},
        {"source_revision": 8},
        {"source_hash": "b" * 64},
        {"semantic_window_source_id": "SEMANTIC_WINDOW:other"},
        {"policy_version": "semantic-window-v2"},
    ],
)
@pytest.mark.parametrize("target", ["occurrence", "link"])
def test_model_record_ranges_must_share_one_semantic_window_envelope(
    identity_change: dict[str, object],
    target: str,
) -> None:
    first = _occurrence_range()
    second = replace(first, ordinal=1, **identity_change)

    with pytest.raises(
        ValueError,
        match="occurrence source range envelope is invalid",
    ) as captured:
        if target == "occurrence":
            _occurrence(source_ranges=(first, second))
        else:
            first_link = _link_range()
            second_link = replace(first_link, ordinal=1, **identity_change)
            _link(source_ranges=(first_link, second_link))

    message = str(captured.value)
    assert "SEMANTIC_WINDOW" not in message
    assert "a" * 64 not in message
    assert "b" * 64 not in message


@pytest.mark.parametrize(
    ("created_at", "updated_at"),
    [
        (datetime(2026, 8, 13), datetime(2026, 8, 13)),
        (datetime(2026, 8, 13), NOW),
        (NOW, datetime(2026, 8, 13)),
        (NOW, NOW - timedelta(seconds=1)),
    ],
)
@pytest.mark.parametrize("target", ["occurrence", "link"])
def test_timestamps_require_aware_ordered_datetimes_with_fixed_errors(
    created_at: datetime,
    updated_at: datetime,
    target: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="^occurrence timestamps are invalid$",
    ) as captured:
        if target == "occurrence":
            _occurrence(created_at=created_at, updated_at=updated_at)
        else:
            _link(created_at=created_at, updated_at=updated_at)

    assert str(created_at) not in str(captured.value)
    assert str(updated_at) not in str(captured.value)


def test_timezone_aware_timestamps_compare_by_absolute_time() -> None:
    same_instant = datetime(
        2026,
        8,
        13,
        8,
        tzinfo=timezone(timedelta(hours=8)),
    )

    assert _occurrence(created_at=NOW, updated_at=same_instant).updated_at == same_instant


@pytest.mark.parametrize(
    "changes",
    [
        {"ordinal": True},
        {"ordinal": 10_000},
        {"source_revision": True},
        {"source_revision": -1},
        {"source_hash": "secret manuscript hash"},
        {"semantic_window_source_id": ""},
        {"semantic_window_source_id": "x" * 513},
        {"policy_version": " "},
        {"policy_version": "x" * 101},
        {"source_start": True},
        {"source_start": -1},
        {"source_end": 4},
        {"source_end": 20_000_001},
    ],
)
def test_source_ranges_fail_closed_with_sanitized_errors(
    changes: dict[str, object],
) -> None:
    source_range = _occurrence_range()

    with pytest.raises(ValueError) as captured:
        replace(source_range, **changes)

    message = str(captured.value)
    assert "secret manuscript hash" not in message
    assert "a" * 64 not in message


def test_domain_has_no_body_quote_score_or_event_subject_contract() -> None:
    occurrence_fields = {item.name for item in fields(Occurrence)}
    link_fields = {item.name for item in fields(SubjectOccurrenceLink)}
    range_fields = {item.name for item in fields(OccurrenceSourceRange)}

    assert {"body", "content", "quote", "importance", "confidence"}.isdisjoint(
        occurrence_fields | link_fields | range_fields
    )
    assert tuple(SubjectType) == (SubjectType.CHARACTER,)
