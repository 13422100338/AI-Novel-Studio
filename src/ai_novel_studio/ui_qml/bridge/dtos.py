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
    id: str
    role: str  # user | assistant
    text: str
