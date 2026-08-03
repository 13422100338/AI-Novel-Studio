import threading

from PySide6.QtCore import QObject

from ai_novel_studio.application.project_generation_session import AcceptedGeneration
from ai_novel_studio.ui_qml.bridge.draft_port import GenerationConfig
from ai_novel_studio.ui_qml.bridge.dtos import UsageDto
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.models.draft_diff_model import (
    ROLE_BLOCK_ID,
    ROLE_KIND,
)
from ai_novel_studio.ui_qml.bridge.models.suggestion_list_model import ROLE_LABEL

from .test_project_wiring import create_temp_project


class FakeDraftPort:
    """Deterministic draft port for facade orchestration tests."""

    def __init__(
        self,
        *,
        draft_text: str = "AI 生成的草稿正文。",
        accept_failure: str | None = None,
        generate_error: str | None = None,
        block_on_generate: bool = False,
    ) -> None:
        self.draft_text = draft_text
        self.accept_failure = accept_failure
        self.generate_error = generate_error
        self.block_on_generate = block_on_generate
        self._generate_block = threading.Event()
        self.prepared: list[tuple[str, int, GenerationConfig]] = []
        self.accepted = False
        self.discarded = False
        self.cancel_called = False
        self.next_revision = 7
        self.usage = UsageDto(
            input_tokens=1200,
            output_tokens=800,
            cached_input_tokens=600,
            cost=0.018,
            call_count=1,
            failed_call_count=0,
            cache_known=True,
        )

    def prepare(
        self,
        chapter_id: str,
        revision: int,
        config: GenerationConfig,
    ) -> str:
        self.prepared.append((chapter_id, revision, config))
        return "run-fake"

    def generate(self, run_id: str) -> tuple[str, str]:
        if self.block_on_generate:
            self._generate_block.wait(timeout=10)
        if self.cancel_called:
            return self.draft_text, "正文生成已取消，已保留收到的内容"
        if self.generate_error is not None:
            return self.draft_text, self.generate_error
        return self.draft_text, ""

    def cancel(self, run_id: str) -> None:
        self.cancel_called = True
        self._generate_block.set()

    def usage_snapshot(self) -> UsageDto:
        return self.usage

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


def test_project_draft_request_uses_port_and_opens_drawer(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort()
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))

    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("suggestions").rowCount() == 1,
        timeout=5000,
    )

    assert facade.property("aiDrawerOpen") is True
    suggestions = facade.property("suggestions")
    assert suggestions.rowCount() == 1
    assert port.prepared[0][0] == facade.property("currentChapterId")
    assert port.prepared[0][1] == facade.property("currentRevision")
    assert facade.property("draftStatus") == "COMPLETED"


def test_project_draft_accept_applies_generated_text(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort()
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("suggestions").rowCount() == 1,
        timeout=5000,
    )

    facade.acceptSuggestion(0)

    assert facade.property("currentChapterBody") == port.draft_text
    assert facade.property("currentRevision") == 7
    assert facade.property("editorState") == "CLEAN"
    assert facade.property("suggestions").rowCount() == 0
    assert port.accepted is True


def test_project_draft_discard_keeps_body(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort()
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    body_before = facade.property("currentChapterBody")
    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("suggestions").rowCount() == 1,
        timeout=5000,
    )

    facade.discardSuggestion(0)

    assert facade.property("currentChapterBody") == body_before
    assert facade.property("suggestions").rowCount() == 0
    assert port.discarded is True


def test_project_draft_without_port_reports_missing_gateway(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))

    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("draftStatus") == "FAILED",
        timeout=5000,
    )

    assert "端口未配置" in facade.property("saveStatusText")
    assert facade.property("suggestions").rowCount() == 0
    assert facade.property("aiDrawerOpen") is False


def test_project_draft_accept_failure_keeps_candidate(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(accept_failure="采用失败：测试错误")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    body_before = facade.property("currentChapterBody")
    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("suggestions").rowCount() == 1,
        timeout=5000,
    )

    facade.acceptSuggestion(0)

    assert "采用草稿失败" in facade.property("saveStatusText")
    assert facade.property("suggestions").rowCount() == 1
    assert facade.property("currentChapterBody") == body_before


def test_project_draft_cancel_keeps_body_and_reports_cancelled(
    qtbot, tmp_path
) -> None:
    from ai_novel_studio.ui_qml.bridge.draft_coordinator import DRAFT_GENERATING

    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(block_on_generate=True)
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    body_before = facade.property("currentChapterBody")

    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("draftStatus") == DRAFT_GENERATING,
        timeout=5000,
    )
    facade.cancelDraft()
    qtbot.waitUntil(
        lambda: facade.property("draftStatus") == "CANCELLED",
        timeout=5000,
    )

    assert facade.property("currentChapterBody") == body_before
    assert facade.property("suggestions").rowCount() == 0
    assert "已取消" in facade.property("saveStatusText")
    assert port.cancel_called is True


def test_generation_config_defaults() -> None:
    facade = MockNovelStudioFacade()
    assert facade.property("generationTargetWords") == 800
    assert facade.property("generationOutputTokenLimit") == 8192
    assert facade.property("generationMode") == "BASIC"
    assert facade.property("generationAuditPolicy") == "MINIMAL"


def test_generation_config_setters_validate_and_persist() -> None:
    facade = MockNovelStudioFacade()

    facade.setGenerationTargetWords(2000)
    facade.setGenerationOutputTokenLimit(4096)
    facade.setGenerationMode("STRICT")
    facade.setGenerationAuditPolicy("DEEP")

    assert facade.property("generationTargetWords") == 2000
    assert facade.property("generationOutputTokenLimit") == 4096
    assert facade.property("generationMode") == "STRICT"
    assert facade.property("generationAuditPolicy") == "DEEP"

    # Out-of-range values are clamped, not rejected.
    facade.setGenerationTargetWords(10)
    facade.setGenerationOutputTokenLimit(1_000_000)
    assert facade.property("generationTargetWords") == 100
    assert facade.property("generationOutputTokenLimit") == 32768

    # Unknown enum values are ignored.
    facade.setGenerationMode("EXPERIMENTAL")
    facade.setGenerationAuditPolicy("NONE")
    assert facade.property("generationMode") == "STRICT"
    assert facade.property("generationAuditPolicy") == "DEEP"


def test_project_draft_forwards_generation_config(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort()
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    facade.setGenerationTargetWords(3000)
    facade.setGenerationMode("STANDARD")
    facade.setGenerationAuditPolicy("STANDARD")

    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("suggestions").rowCount() == 1,
        timeout=5000,
    )

    _, revision, config = port.prepared[0]
    assert revision == facade.property("currentRevision")
    assert config.target_words == 3000
    assert config.mode.value == "STANDARD"
    assert config.audit_policy.value == "STANDARD"
    assert config.output_token_limit == 8192


def _generate_draft(qtbot, facade) -> None:
    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("suggestions").rowCount() == 1,
        timeout=5000,
    )


def test_draft_view_enabled_after_generation(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(draft_text="这是测试正文。\n\nAI 新增的段落。")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))

    _generate_draft(qtbot, facade)

    assert facade.property("draftViewEnabled") is True
    assert facade.property("draftView") == "draft"
    assert "这是测试正文" in facade.property("draftBaseText")
    assert "AI 新增的段落" in facade.property("draftText")
    diff_model = facade.property("draftDiff")
    assert diff_model.rowCount() >= 2


def test_draft_view_switch_and_validation(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(draft_text="草稿正文")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    _generate_draft(qtbot, facade)

    facade.setDraftView("current")
    assert facade.property("draftView") == "current"
    facade.setDraftView("diff")
    assert facade.property("draftView") == "diff"
    facade.setDraftView("invalid")
    assert facade.property("draftView") == "diff"


def test_accept_diff_block_applies_paragraph_and_marks_dirty(
    qtbot, tmp_path
) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(
        draft_text="这是测试正文。\n\nAI 重写的第二段。",
    )
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    _generate_draft(qtbot, facade)
    diff_model = facade.property("draftDiff")
    replaced = next(
        row
        for row in range(diff_model.rowCount())
        if diff_model.data(diff_model.index(row), ROLE_KIND) == "replaced"
    )
    block_id = diff_model.data(diff_model.index(replaced), ROLE_BLOCK_ID)
    before_count = diff_model.rowCount()

    facade.acceptDiffBlock(block_id)

    body = facade.property("currentChapterBody")
    assert "AI 重写的第二段" in body
    assert "\n\n第二段。" not in body
    assert facade.property("editorState") == "DIRTY"
    assert "待保存" in facade.property("saveStatusText")
    assert diff_model.rowCount() == before_count - 1


def test_reject_diff_block_keeps_body(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(draft_text="这是测试正文。\n\nAI 重写的第二段。")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    body_before = facade.property("currentChapterBody")
    _generate_draft(qtbot, facade)
    diff_model = facade.property("draftDiff")
    replaced = next(
        row
        for row in range(diff_model.rowCount())
        if diff_model.data(diff_model.index(row), ROLE_KIND) == "replaced"
    )
    block_id = diff_model.data(diff_model.index(replaced), ROLE_BLOCK_ID)
    before_count = diff_model.rowCount()

    facade.rejectDiffBlock(block_id)

    assert facade.property("currentChapterBody") == body_before
    assert facade.property("editorState") == "CLEAN"
    assert "已忽略" in facade.property("saveStatusText")
    assert diff_model.rowCount() == before_count - 1


def test_accept_all_diff_blocks_produces_draft_text(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(
        draft_text="这是测试正文。\n\nAI 重写的第二段。\n\nAI 新增的第三段。",
    )
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    _generate_draft(qtbot, facade)
    diff_model = facade.property("draftDiff")

    while diff_model.rowCount() > 0:
        block_id = diff_model.data(diff_model.index(0), ROLE_BLOCK_ID)
        facade.acceptDiffBlock(block_id)

    assert facade.property("currentChapterBody") == facade.property("draftText")
    assert facade.property("editorState") == "DIRTY"


def test_edit_and_accept_diff_block_applies_edited_text(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(
        draft_text="这是测试正文。\n\nAI 重写的第二段。",
    )
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    _generate_draft(qtbot, facade)
    diff_model = facade.property("draftDiff")
    replaced = next(
        row
        for row in range(diff_model.rowCount())
        if diff_model.data(diff_model.index(row), ROLE_KIND) == "replaced"
    )
    block_id = diff_model.data(diff_model.index(replaced), ROLE_BLOCK_ID)
    before_count = diff_model.rowCount()

    facade.editAndAcceptDiffBlock(block_id, "自定义的第二段。")

    body = facade.property("currentChapterBody")
    assert "自定义的第二段" in body
    assert "AI 重写的第二段" not in body
    assert "\n\n第二段。" not in body
    assert facade.property("editorState") == "DIRTY"
    assert "已采用编辑后的段落" in facade.property("saveStatusText")
    assert diff_model.rowCount() == before_count - 1


def test_edit_and_accept_empty_text_is_rejected(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(
        draft_text="这是测试正文。\n\nAI 重写的第二段。",
    )
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    body_before = facade.property("currentChapterBody")
    _generate_draft(qtbot, facade)
    diff_model = facade.property("draftDiff")
    replaced = next(
        row
        for row in range(diff_model.rowCount())
        if diff_model.data(diff_model.index(row), ROLE_KIND) == "replaced"
    )
    block_id = diff_model.data(diff_model.index(replaced), ROLE_BLOCK_ID)

    facade.editAndAcceptDiffBlock(block_id, "   ")

    assert facade.property("currentChapterBody") == body_before
    assert "不能为空" in facade.property("saveStatusText")
    assert diff_model.rowCount() > 0


def test_accept_full_draft_clears_diff_state(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(draft_text="AI 生成的草稿正文。")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    _generate_draft(qtbot, facade)
    assert facade.property("draftViewEnabled") is True

    facade.acceptSuggestion(0)

    assert facade.property("draftViewEnabled") is False
    assert facade.property("draftDiff").rowCount() == 0


def test_usage_properties_update_after_generation(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(draft_text="草稿正文")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))

    assert facade.property("usageInputOutputText") == "0 / 0"
    assert facade.property("usageCostText") == "未估算"
    assert facade.property("usageCacheText") == "缓存 未知"

    _generate_draft(qtbot, facade)

    assert facade.property("usageInputOutputText") == "1.2K / 800"
    assert facade.property("usageCostText") == "¥0.018"
    assert facade.property("usageCacheText") == "缓存 600"
    assert facade.property("usageCallsText") == "1 次调用"


def test_usage_updates_on_generation_failure(qtbot, tmp_path) -> None:
    root = create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(generate_error="模型超时")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))

    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("draftStatus") == "FAILED",
        timeout=5000,
    )

    assert facade.property("usageInputOutputText") == "1.2K / 800"
    assert facade.property("draftStatus") == "FAILED"


def test_usage_stays_zero_without_port() -> None:
    facade = MockNovelStudioFacade()
    assert facade.property("usageInputOutputText") == "0 / 0"
    assert facade.property("usageCostText") == "未估算"
