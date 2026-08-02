from PySide6.QtCore import QObject

from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.models.suggestion_list_model import ROLE_LABEL


def test_initial_project_state() -> None:
    facade = MockNovelStudioFacade()
    assert facade.property("projectTitle") == "雾港来信"
    assert facade.property("chapterCount") == 5
    assert facade.property("currentChapterId") == "chapter-1"
    assert facade.property("currentChapterTitle") == "第一章 雾港的清晨"
    assert facade.property("currentRevision") == 3
    assert facade.property("editorState") == "CLEAN"
    assert facade.property("aiDrawerOpen") is False
    assert facade.property("activeNav") == "writing"


def test_facade_is_qobject() -> None:
    assert isinstance(MockNovelStudioFacade(), QObject)


def test_editor_text_change_tracks_dirty_state() -> None:
    facade = MockNovelStudioFacade()
    facade.editorTextChanged("全新的正文")
    assert facade.property("editorState") == "DIRTY"
    assert facade.property("currentWordCountText") == "5"


def test_save_bumps_revision_and_clears_dirty() -> None:
    facade = MockNovelStudioFacade()
    facade.editorTextChanged("全新的正文")
    facade.requestSave()
    assert facade.property("editorState") == "CLEAN"
    assert facade.property("currentRevision") == 4
    assert facade.property("saveStatusText") == "已保存 · 修订 4"


def test_save_without_changes_keeps_revision() -> None:
    facade = MockNovelStudioFacade()
    facade.requestSave()
    assert facade.property("currentRevision") == 3


def test_select_chapter_loads_clean_document() -> None:
    facade = MockNovelStudioFacade()
    facade.editorTextChanged("脏内容")
    facade.selectChapter(3)
    assert facade.property("currentChapterId") == "chapter-3"
    assert facade.property("editorState") == "CLEAN"
    assert "看守人" in facade.property("currentChapterBody")


def test_select_chapter_ignores_non_chapter_row() -> None:
    facade = MockNovelStudioFacade()
    facade.selectChapter(0)
    assert facade.property("currentChapterId") == "chapter-1"


def test_request_draft_opens_drawer_and_adds_suggestion() -> None:
    facade = MockNovelStudioFacade()
    facade.requestDraft()
    assert facade.property("aiDrawerOpen") is True
    suggestions = facade.property("suggestions")
    assert suggestions.rowCount() == 1
    assert "润色" in suggestions.data(suggestions.index(0), ROLE_LABEL)


def test_accept_suggestion_appends_body_and_removes_item() -> None:
    facade = MockNovelStudioFacade()
    facade.requestDraft()
    body_before = facade.property("currentChapterBody")
    facade.acceptSuggestion(0)
    body_after = facade.property("currentChapterBody")
    assert body_after.startswith(body_before)
    assert body_after != body_before
    assert facade.property("editorState") == "DIRTY"
    assert facade.property("suggestions").rowCount() == 0


def test_discard_suggestion_keeps_body() -> None:
    facade = MockNovelStudioFacade()
    facade.requestDraft()
    body_before = facade.property("currentChapterBody")
    facade.discardSuggestion(0)
    assert facade.property("currentChapterBody") == body_before
    assert facade.property("suggestions").rowCount() == 0


def test_drawer_toggle() -> None:
    facade = MockNovelStudioFacade()
    facade.toggleAiDrawer(True)
    assert facade.property("aiDrawerOpen") is True
    facade.toggleAiDrawer(True)
    assert facade.property("aiDrawerOpen") is True
    facade.toggleAiDrawer(False)
    assert facade.property("aiDrawerOpen") is False


def test_active_nav_validation() -> None:
    facade = MockNovelStudioFacade()
    facade.setActiveNav("memory")
    assert facade.property("activeNav") == "memory"
    facade.setActiveNav("unknown")
    assert facade.property("activeNav") == "memory"


def test_reduce_motion_toggle() -> None:
    facade = MockNovelStudioFacade()
    assert facade.property("reduceMotion") is False
    facade.setReduceMotion(True)
    assert facade.property("reduceMotion") is True


def test_chapter_filter_updates_model() -> None:
    facade = MockNovelStudioFacade()
    facade.setChapterFilter("灯塔")
    model = facade.property("chapters")
    assert model.rowCount() == 2
    facade.setChapterFilter("")
    assert model.rowCount() == 7


def test_volumes_snapshot() -> None:
    facade = MockNovelStudioFacade()
    assert len(facade.volumes()) == 2
    assert len(facade.volumes()[0].chapters) == 3
