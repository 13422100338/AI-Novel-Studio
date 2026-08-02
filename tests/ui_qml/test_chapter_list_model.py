from PySide6.QtCore import Qt

from ai_novel_studio.ui_qml.bridge.dtos import ChapterDto, VolumeDto
from ai_novel_studio.ui_qml.bridge.models.chapter_list_model import (
    ROLE_CHAPTER_ID,
    ROLE_KIND,
    ROLE_TITLE,
    ROLE_WORD_COUNT_TEXT,
    ChapterListModel,
)


def _sample_volumes() -> tuple[VolumeDto, ...]:
    return (
        VolumeDto(
            id="v1",
            title="第一卷",
            chapters=(
                ChapterDto(id="c1", title="第一章 雾港", body="清晨的雾港。"),
                ChapterDto(id="c2", title="第二章 灯塔", body="灯塔的灯光。"),
            ),
        ),
        VolumeDto(
            id="v2",
            title="第二卷",
            chapters=(ChapterDto(id="c3", title="第三章 码头", body="码头。"),),
        ),
    )


def test_rows_are_flat_volume_then_chapters() -> None:
    model = ChapterListModel(_sample_volumes())
    assert model.rowCount() == 5
    assert model.data(model.index(0), ROLE_KIND) == "volume"
    assert model.data(model.index(0), ROLE_TITLE) == "第一卷"
    assert model.data(model.index(1), ROLE_KIND) == "chapter"
    assert model.data(model.index(1), ROLE_CHAPTER_ID) == "c1"


def test_role_names_are_exposed() -> None:
    model = ChapterListModel(_sample_volumes())
    names = model.roleNames()
    assert names[ROLE_CHAPTER_ID] == b"chapterId"
    assert names[ROLE_TITLE] == b"title"
    assert names[ROLE_KIND] == b"kind"
    assert names[ROLE_WORD_COUNT_TEXT] == b"wordCountText"


def test_word_count_role_formats() -> None:
    model = ChapterListModel(_sample_volumes())
    assert model.data(model.index(1), ROLE_WORD_COUNT_TEXT) == "5"


def test_set_volumes_resets_rows() -> None:
    model = ChapterListModel(_sample_volumes())
    model.set_volumes((_sample_volumes()[0],))
    assert model.rowCount() == 3


def test_chapter_at_row_and_rows() -> None:
    model = ChapterListModel(_sample_volumes())
    assert model.chapter_at_row(0) is None
    assert model.chapter_at_row(1) is not None
    assert model.chapter_at_row(1).id == "c1"
    assert model.chapter_rows() == [1, 2, 4]
    assert model.chapter_at_row(99) is None


def test_set_filter_hides_unmatched_chapters_and_volumes() -> None:
    model = ChapterListModel(_sample_volumes())
    model.set_filter("灯塔")
    assert model.rowCount() == 2
    assert model.data(model.index(0), ROLE_KIND) == "volume"
    assert model.data(model.index(1), ROLE_CHAPTER_ID) == "c2"
    model.set_filter("")
    assert model.rowCount() == 5


def test_filter_is_case_insensitive() -> None:
    model = ChapterListModel(
        (VolumeDto(id="v1", title="V", chapters=(ChapterDto(id="c1", title="ABC", body="x"),)),)
    )
    model.set_filter("abc")
    assert model.rowCount() == 2


def test_display_role_returns_none_for_valid_index() -> None:
    model = ChapterListModel(_sample_volumes())
    assert model.data(model.index(0), Qt.ItemDataRole.DisplayRole) is None
