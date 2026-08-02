"""Frontend DTOs exposed to QML.

These are presentation-layer records, never persisted. They intentionally carry no
domain behavior so QML can consume them without touching repositories or services.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_novel_studio.ui_qml.bridge.text_utils import count_words


@dataclass(frozen=True, slots=True)
class ChapterDto:
    id: str
    title: str
    body: str
    status: str = "draft"
    revision: int = 1
    word_count: int = field(init=False)

    def __post_init__(self) -> None:
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
