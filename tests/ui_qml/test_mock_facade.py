from PySide6.QtCore import QObject

from ai_novel_studio.application.project_generation_session import AcceptedGeneration
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.models.suggestion_list_model import ROLE_LABEL

from .test_project_wiring import create_temp_project


class FakeDraftPort:
    """Deterministic draft port for facade orchestration tests."""

    def __init__(
        self,
        *,
        draft_text: str = "AI 生成的草稿正文。",
        accept_failure: str | None = None,
    ) -> None:
        self.draft_text = draft_text
        self.accept_failure = accept_failure
        self.prepared: list[tuple[str, int, int]] = []
        self.accepted = False
        self.discarded = False
        self.next_revision = 7

    def prepare(self, chapter_id: str, revision: int, target_words: int) -> str:
        self.prepared.append((chapter_id, revision, target_words))
        return "run-fake"

    def generate(self, run_id: str) -> tuple[str, str]:
        return self.draft_text, ""

    def accept_current(self) -> AcceptedGeneration:
        if self.accept_failure is not None:
            raise RuntimeError(self.accept_failure)
        self.accepted = True
        return AcceptedGeneration(self.draft_text, self.next_revision)

    def discard_current(self) -> bool:
        self.discarded = True
        return True


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


def test_project_draft_request_uses_port_and_opens_drawer(tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort()
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))

    facade.requestDraft()

    assert facade.property("aiDrawerOpen") is True
    suggestions = facade.property("suggestions")
    assert suggestions.rowCount() == 1
    assert port.prepared[0][0] == facade.property("currentChapterId")
    assert port.prepared[0][1] == facade.property("currentRevision")


def test_project_draft_accept_applies_generated_text(tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort()
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    facade.requestDraft()

    facade.acceptSuggestion(0)

    assert facade.property("currentChapterBody") == port.draft_text
    assert facade.property("currentRevision") == 7
    assert facade.property("editorState") == "CLEAN"
    assert facade.property("suggestions").rowCount() == 0
    assert port.accepted is True


def test_project_draft_discard_keeps_body(tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort()
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    body_before = facade.property("currentChapterBody")
    facade.requestDraft()

    facade.discardSuggestion(0)

    assert facade.property("currentChapterBody") == body_before
    assert facade.property("suggestions").rowCount() == 0
    assert port.discarded is True


def test_project_draft_without_port_reports_missing_gateway(tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))

    facade.requestDraft()

    assert "端口未配置" in facade.property("saveStatusText")
    assert facade.property("suggestions").rowCount() == 0
    assert facade.property("aiDrawerOpen") is False


def test_project_draft_accept_failure_keeps_candidate(tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(accept_failure="采用失败：测试错误")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    body_before = facade.property("currentChapterBody")
    facade.requestDraft()

    facade.acceptSuggestion(0)

    assert "采用草稿失败" in facade.property("saveStatusText")
    assert facade.property("suggestions").rowCount() == 1
    assert facade.property("currentChapterBody") == body_before
