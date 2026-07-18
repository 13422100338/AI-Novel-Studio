from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType


class ViewType(StrEnum):
    WORLD_TRUTH = "WORLD_TRUTH"
    CHARACTER_VIEW = "CHARACTER_VIEW"
    READER_VIEW = "READER_VIEW"
    AUTHOR_PLAN = "AUTHOR_PLAN"


class EpistemicStatus(StrEnum):
    KNOWS = "KNOWS"
    BELIEVES = "BELIEVES"
    SUSPECTS = "SUSPECTS"
    MISBELIEVES = "MISBELIEVES"
    UNAWARE = "UNAWARE"


def _optional_text(value: str | None, field: str, limit: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be blank")
    if len(normalized) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return normalized


def _sequence(value: int | None, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class ViewAssertionDraft:
    subject_id: str
    view_type: ViewType
    content: str
    viewer_subject_id: str | None = None
    epistemic_status: EpistemicStatus | None = None
    valid_from_sequence: int | None = None
    valid_to_sequence: int | None = None
    story_time_label: str | None = None
    narrative_visible_from_sequence: int | None = None
    narrative_visible_to_sequence: int | None = None

    def __post_init__(self) -> None:
        subject_id = _optional_text(self.subject_id, "subject_id", 200)
        content = _optional_text(self.content, "content", 20_000)
        viewer_id = _optional_text(self.viewer_subject_id, "viewer_subject_id", 200)
        story_time = _optional_text(self.story_time_label, "story_time_label", 500)
        valid_from = _sequence(self.valid_from_sequence, "valid_from_sequence")
        valid_to = _sequence(self.valid_to_sequence, "valid_to_sequence")
        visible_from = _sequence(
            self.narrative_visible_from_sequence,
            "narrative_visible_from_sequence",
        )
        visible_to = _sequence(
            self.narrative_visible_to_sequence,
            "narrative_visible_to_sequence",
        )
        if valid_from is not None and valid_to is not None and valid_from > valid_to:
            raise ValueError("valid sequence range is inverted")
        if (
            visible_from is not None
            and visible_to is not None
            and visible_from > visible_to
        ):
            raise ValueError("narrative visibility range is inverted")
        if self.view_type == ViewType.CHARACTER_VIEW:
            if viewer_id is None or self.epistemic_status is None:
                raise ValueError(
                    "CHARACTER_VIEW requires viewer_subject_id and epistemic_status"
                )
        elif viewer_id is not None or self.epistemic_status is not None:
            raise ValueError(
                "viewer_subject_id and epistemic_status belong only to CHARACTER_VIEW"
            )
        if self.view_type == ViewType.READER_VIEW and visible_from is None:
            raise ValueError(
                "READER_VIEW requires narrative_visible_from_sequence"
            )
        object.__setattr__(self, "subject_id", subject_id)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "viewer_subject_id", viewer_id)
        object.__setattr__(self, "story_time_label", story_time)


@dataclass(frozen=True, slots=True)
class ViewAssertion:
    id: str
    subject_id: str
    view_type: ViewType
    content: str
    viewer_subject_id: str | None
    epistemic_status: EpistemicStatus | None
    valid_from_sequence: int | None
    valid_to_sequence: int | None
    story_time_label: str | None
    narrative_visible_from_sequence: int | None
    narrative_visible_to_sequence: int | None
    authority: Authority
    review_status: ReviewStatus
    source_type: SourceType
    source_id: str
    source_revision: int
    stale: bool
    source_changed: bool
    created_at: datetime
    updated_at: datetime
