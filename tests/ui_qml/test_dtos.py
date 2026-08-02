from dataclasses import FrozenInstanceError

import pytest

from ai_novel_studio.ui_qml.bridge.dtos import ChapterDto, SuggestionDto, VolumeDto


def test_chapter_dto_computes_word_count() -> None:
    chapter = ChapterDto(id="c1", title="第一章", body="清晨的雾港。Hello 世界。")
    assert chapter.word_count == 8


def test_chapter_dto_is_frozen() -> None:
    chapter = ChapterDto(id="c1", title="第一章", body="正文")
    with pytest.raises(FrozenInstanceError):
        chapter.title = "改名"  # type: ignore[misc]


def test_volume_dto_holds_chapters() -> None:
    chapter = ChapterDto(id="c1", title="第一章", body="正文")
    volume = VolumeDto(id="v1", title="第一卷", chapters=(chapter,))
    assert volume.chapters[0].id == "c1"


def test_suggestion_dto_defaults() -> None:
    suggestion = SuggestionDto(id="s1", label="润色", body="建议")
    assert suggestion.kind == "polish"
