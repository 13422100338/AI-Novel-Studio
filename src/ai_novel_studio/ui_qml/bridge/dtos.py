"""Frontend DTOs exposed to QML.

These are presentation-layer records, never persisted. They intentionally carry no
domain behavior so QML can consume them without touching repositories or services.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.ui_qml.bridge.text_utils import count_words


@dataclass(frozen=True, slots=True)
class ChapterDto:
    id: str
    title: str
    body: str = ""
    status: str = "draft"
    revision: int = 1
    declared_number: str = ""
    word_count: int = 0

    def __post_init__(self) -> None:
        if self.body and self.word_count <= 0:
            object.__setattr__(self, "word_count", count_words(self.body))


@dataclass(frozen=True, slots=True)
class VolumeDto:
    id: str
    title: str
    chapters: tuple[ChapterDto, ...] = ()


@dataclass(frozen=True, slots=True)
class SuggestionDto:
    id: str
    label: str
    body: str
    kind: str = "polish"


@dataclass(frozen=True, slots=True)
class UsageDto:
    """Presentation DTO mirroring ``UsageSnapshot`` semantics for the status bar."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost: float | None = None
    call_count: int = 0
    failed_call_count: int = 0
    cache_known: bool = False


@dataclass(frozen=True, slots=True)
class DiscussionMessageDto:
    """DEPRECATED (C1.1): legacy plot-discussion record.

    Retained only for the deprecated DiscussionPanel compatibility path; new
    AI interactions use ``AgentTimelineItemDto``.
    """

    id: str
    role: str  # user | assistant
    text: str


@dataclass(frozen=True, slots=True)
class AgentTimelineItemDto:
    """One structured Agent timeline event (C1)."""

    id: str
    kind: str  # user_text|assistant_text|run_status|tool_call|tool_result|
    # choice_card|text_diff|confirmation|form_card|change_set|warning|error
    # Stream identity: reserved so late events from an old run can be dropped
    # after cancel/chapter switch (ideal-UI spec 10.4).
    run_id: str = ""
    sequence_number: int = 0
    text: str = ""
    label: str = ""
    busy: bool = False
    status: str = ""
    # PENDING|RUNNING|COMPLETED|FAILED|CANCELLED|APPLIED|DISCARDED
    state: str = ""
    options: tuple[str, ...] = ()
    current_text: str = ""
    draft_text: str = ""
    field_labels: tuple[str, ...] = ()
    field_values: tuple[str, ...] = ()
    target: str = ""
    operation: str = ""
    before_text: str = ""
    after_text: str = ""
    risk: str = ""
    reason: str = ""
    data: str = ""  # JSON-safe extra payload string


@dataclass(frozen=True, slots=True)
class SelectionReferenceDto:
    """Validated selection reference from the WebEngine editor (C1)."""

    chapter_id: str
    base_revision: int
    from_pos: int
    to_pos: int
    selected_text: str
    selected_text_hash: str
