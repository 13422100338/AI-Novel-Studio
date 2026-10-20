"""QML facade for the new frontend.

The facade is the only object QML talks to. By default it serves deterministic
mock data; since Frontend Wave F2 it can also open a real project through the
read-only application service ``ProjectWorkspaceService`` (volume tree, chapter
loading, summary). It never writes project files, never touches repositories or
the model gateway directly, and keeps the same presentation DTO shape for both
modes (see docs/frontend audit, section 8).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from ai_novel_studio.application.novel_read_service import NovelEditorSnapshot
from ai_novel_studio.application.selection_patch import (
    SelectionPatchCapture,
    capture_selection_range,
)
from ai_novel_studio.ui_qml.bridge.backend_availability import BACKEND_AVAILABLE
from ai_novel_studio.ui_qml.bridge.codex_session_bridge import CodexSessionController
from ai_novel_studio.ui_qml.bridge.draft_coordinator import (
    DRAFT_FAILED,
    DRAFT_IDLE,
    DraftCoordinator,
)
from ai_novel_studio.ui_qml.bridge.draft_port import DraftPort, GenerationConfig
from ai_novel_studio.ui_qml.bridge.dtos import (
    AgentTimelineItemDto,
    ChapterDto,
    DiscussionMessageDto,
    SuggestionDto,
    UsageDto,
    VolumeDto,
)
from ai_novel_studio.ui_qml.bridge.harness_agent_bridge import (
    HarnessAgentCoordinator,
    HarnessAgentTimelineController,
)
from ai_novel_studio.ui_qml.bridge.models.agent_timeline_model import (
    AgentTimelineModel,
)
from ai_novel_studio.ui_qml.bridge.models.chapter_list_model import ChapterListModel
from ai_novel_studio.ui_qml.bridge.models.discussion_message_list_model import (
    DiscussionMessageListModel,
)
from ai_novel_studio.ui_qml.bridge.models.draft_diff_model import DraftDiffModel
from ai_novel_studio.ui_qml.bridge.models.readonly_list_models import (
    AuditListModel,
    CharacterJourneyListModel,
    CharacterListModel,
    MemoryListModel,
)
from ai_novel_studio.ui_qml.bridge.models.suggestion_list_model import SuggestionListModel
from ai_novel_studio.ui_qml.bridge.outline_bridge import OutlineBridge
from ai_novel_studio.ui_qml.bridge.overview_counts import (
    OverviewCounts,
    readonly_overview_counts,
)
from ai_novel_studio.ui_qml.bridge.paragraph_diff import (
    ParagraphDiffBlock,
    apply_diff_blocks,
    diff_paragraphs,
)
from ai_novel_studio.ui_qml.bridge.readonly_views import (
    CharacterViewDto,
    MemoryViewDto,
    ReadonlyViews,
    readonly_views,
)
from ai_novel_studio.ui_qml.bridge.text_utils import count_words, format_word_count

_NAV_IDS = ("writing", "outline", "library", "advanced", "settings")
_NAV_ALIASES = {
    "characters": "library",
    "memory": "library",
    "clues": "advanced",
    "audit": "advanced",
}
_CREATION_MODES = ("BASIC", "STANDARD", "STRICT")
_AUDIT_POLICIES = ("MINIMAL", "STANDARD", "DEEP")
_SELECTION_QUICK_COMMANDS = frozenset({"重写", "润色", "精简", "扩写"})

_AGENT_KINDS = {
    "user_text",
    "assistant_text",
    "run_status",
    "tool_call",
    "tool_result",
    "choice_card",
    "text_diff",
    "confirmation",
    "form_card",
    "change_set",
    "warning",
    "error",
}


def _mock_volumes() -> tuple[VolumeDto, ...]:
    return (
        VolumeDto(
            id="volume-1",
            title="第一卷 · 雾港来信",
            chapters=(
                ChapterDto(
                    id="chapter-1",
                    title="第一章 雾港的清晨",
                    status="draft",
                    revision=3,
                    body=(
                        "清晨的雾港还浸在灰蓝色的光线里。渡轮靠岸时，甲板上的水汽"
                        "把远处灯塔的光晕揉成一团模糊的暖色。\n\n"
                        "林默把最后一封信塞进外套内袋，沿着湿漉漉的栈桥走进镇子。"
                        "他没想到，二十年后回到这里的第一个清晨，会先听见钟声。"
                    ),
                ),
                ChapterDto(
                    id="chapter-2",
                    title="第二章 潮汐声",
                    status="draft",
                    revision=1,
                    body=(
                        "傍晚的潮水涌过防波堤，声音像有人一遍遍翻动旧书页。"
                        "旅馆老板娘说，灯塔已经三年没有亮过。\n\n"
                        "林默在窗边坐下，把那封信摊开。信纸的边缘已经发脆。"
                    ),
                ),
                ChapterDto(
                    id="chapter-3",
                    title="第三章 灯塔看守人",
                    status="draft",
                    revision=1,
                    body=(
                        "看守人的小屋锁着，但门缝里夹着一支没有点燃的蜡烛。"
                        "林默站在台阶前，听见屋里传来走动声。\n\n"
                        "他敲了三下门。脚步声停了。"
                    ),
                ),
            ),
        ),
        VolumeDto(
            id="volume-2",
            title="第二卷 · 旧信与火",
            chapters=(
                ChapterDto(
                    id="chapter-4",
                    title="第四章 尘封的信",
                    status="draft",
                    revision=1,
                    body=(
                        "抽屉最底层压着十二封信，按日期捆成一扎。"
                        "最早的一封写于二十年前，墨水已经褪成浅褐色。\n\n"
                        "林默没有立刻拆开。他想先弄清楚，写信的人究竟是谁。"
                    ),
                ),
                ChapterDto(
                    id="chapter-5",
                    title="第五章 燃烧的码头",
                    status="draft",
                    revision=1,
                    body=(
                        "火光从码头仓库的窗口蹿出来时，林默正站在五十米外的人群里。"
                        "他摸到外套内袋里的信，纸张已经有些烫。\n\n"
                        "人群中有个声音说：'这次，他总该回来了。'"
                    ),
                ),
            ),
        ),
    )


class MockNovelStudioFacade(QObject):
    """QML singleton facade with mock project, editor, and AI drawer state."""

    project_changed = Signal()
    chapter_changed = Signal()
    chapterChanged = Signal()
    editor_state_changed = Signal()
    ai_drawer_changed = Signal()
    active_nav_changed = Signal()
    reduce_motion_changed = Signal()
    draft_status_changed = Signal()
    generation_config_changed = Signal()
    draft_view_changed = Signal()
    usage_changed = Signal()
    overview_changed = Signal()
    readonly_views_changed = Signal()
    character_detail_changed = Signal()
    memory_detail_changed = Signal()
    evidenceRevealRequested = Signal(str, int, int)
    web_word_count_changed = Signal()
    draftAcceptedToEditor = Signal(str)
    editorRevisionChanged = Signal(int)
    discussion_changed = Signal()
    agent_timeline_changed = Signal()
    agent_busy_changed = Signal()
    codex_status_changed = Signal()
    codex_controls_changed = Signal()
    selection_reference_changed = Signal()
    model_status_changed = Signal()
    advanced_data_changed = Signal()
    trajectory_changed = Signal()
    cognition_changed = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        draft_port: DraftPort | None = None,
        draft_coordinator: DraftCoordinator | None = None,
        agent_coordinator: HarnessAgentCoordinator | None = None,
        codex_controller: CodexSessionController | None = None,
        demo_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self._draft_port = draft_port
        self._generation_config = GenerationConfig()
        self._usage = UsageDto()
        self._web_word_count: int | None = None
        self._overview = OverviewCounts()
        self._readonly_views = ReadonlyViews()
        self._characters_model = CharacterListModel(self)
        self._journey_model = CharacterJourneyListModel(self)
        self._memories_model = MemoryListModel(self)
        self._audits_model = AuditListModel(self)
        self._selected_character: CharacterViewDto | None = None
        self._selected_memory: MemoryViewDto | None = None
        self._draft_diff_model = DraftDiffModel(self)
        self._discussion_model = DiscussionMessageListModel(self)
        self._discussion_busy = False
        self._agent_timeline_model = AgentTimelineModel(self)
        self._real_agent: HarnessAgentTimelineController | None = None
        if agent_coordinator is not None and codex_controller is None:
            self._real_agent = HarnessAgentTimelineController(agent_coordinator, self)
            self._agent_timeline_model = self._real_agent.model
            self._real_agent.timeline_changed.connect(self.agent_timeline_changed)
            self._real_agent.busy_changed.connect(self.agent_busy_changed)
        self._codex = codex_controller
        if self._codex is not None:
            self._codex.bind_model(self._agent_timeline_model)
            self._codex.writer_status_changed.connect(self._on_draft_status)
            self._codex.busy_changed.connect(self.agent_busy_changed)
            self._codex.status_changed.connect(self.codex_status_changed)
            self._codex.controls_changed.connect(self.codex_controls_changed)
        self._agent_busy = False
        self._agent_step = 0
        # Stream identity reservation: every Mock Agent turn gets one run_id and
        # monotonic sequence numbers so real streaming events can be matched and
        # stale chunks dropped after cancel/chapter switch (ideal-UI spec 10.4).
        self._active_agent_run_id: str | None = None
        self._agent_sequence = 0
        self._agent_timer: QTimer | None = None
        self._selection_reference: SelectionPatchCapture | None = None
        self._chat_selection: NovelEditorSnapshot | None = None
        self._draft_view = "draft"
        self._draft_base_body = ""
        self._draft_text = ""
        self._diff_blocks: tuple[ParagraphDiffBlock, ...] = ()
        self._diff_accepted: set[int] = set()
        self._diff_ignored: set[int] = set()
        self._active_run_id: str | None = None
        self._draft_status = DRAFT_IDLE
        self._draft_coordinator = draft_coordinator
        if self._draft_coordinator is None and draft_port is not None:
            self._draft_coordinator = DraftCoordinator(draft_port, self)
        if self._draft_coordinator is not None:
            self._draft_coordinator.status_changed.connect(self._on_draft_status)
            self._draft_coordinator.draft_ready.connect(self._on_draft_ready)
            self._draft_coordinator.draft_failed.connect(self._on_draft_failed)
            self._draft_coordinator.cancelled.connect(self._on_draft_cancelled)
        self._volumes = _mock_volumes() if demo_mode else ()
        self._demo_mode = demo_mode
        self._chapters = tuple(chapter for volume in self._volumes for chapter in volume.chapters)
        self._chapters_model = ChapterListModel(self._volumes, self)
        self._target_volume_id = self._volumes[0].id if self._volumes else ""
        self._suggestions_model = SuggestionListModel(self)
        self._current_index = 0
        first_chapter = self._chapters[0] if self._chapters else None
        self._body_text = first_chapter.body if first_chapter else ""
        self._saved_body = self._body_text
        self._revision = first_chapter.revision if first_chapter else 0
        self._editor_state = "CLEAN"
        self._save_status = "已载入 · 暂无未保存更改"
        self._workspace: Any | None = None
        self._outline = OutlineBridge(self, chapter_opener=self._open_outline_chapter)
        self.project_changed.connect(self._bind_outline_project)
        self._ai_drawer_open = False
        self._active_nav = "writing"
        self._reduce_motion = False
        self._advanced_clues: list[dict[str, Any]] = []
        self._advanced_plan: dict[str, Any] = {}
        self._advanced_state = "NO_PROJECT"
        self._trajectory_index: list[dict[str, Any]] = []
        self._trajectory_detail: dict[str, Any] = {}
        self._trajectory_evidence: list[dict[str, Any]] = []
        self._trajectory_evidence_outcome = ""
        self._trajectory_state = "NO_PROJECT"
        self._cognition_rows: list[dict[str, Any]] = []
        self._cognition_state = "NO_PROJECT"
        self._advanced_reads_cache: Any | None = None
        self.editor_state_changed.connect(self._sync_codex_editor)
        self.chapter_changed.connect(self._sync_codex_editor)
        self.selection_reference_changed.connect(self._sync_codex_editor)

    # -- project -------------------------------------------------------------

    @Property(QObject, constant=True)
    def outline(self) -> OutlineBridge:
        return self._outline

    def _bind_outline_project(self) -> None:
        self._outline.bind_project(self._workspace.project if self._workspace else None)

    def _open_outline_chapter(self, chapter_id: str) -> bool:
        if self._editor_state != "CLEAN":
            self.requestSave()
            if self._editor_state != "CLEAN":
                return False
        for row in self._chapters_model.chapter_rows():
            chapter = self._chapters_model.chapter_at_row(row)
            if chapter is not None and chapter.id == chapter_id:
                self.selectChapter(row)
                current = self._current_chapter()
                if current is not None and current.id == chapter_id:
                    self.setActiveNav("writing")
                    return self._active_nav == "writing"
                return False
        return False

    @Property(str, notify=project_changed)
    def projectTitle(self) -> str:
        if self._workspace is not None:
            return str(self._workspace.summary().title)
        if self._demo_mode:
            return "雾港来信"
        return "未打开项目"

    @Property(str, notify=project_changed)
    def projectPath(self) -> str:
        if self._workspace is not None:
            return str(self._workspace.summary().root)
        if self._demo_mode:
            return "C:\\Users\\demo\\Novels\\雾港来信"
        return ""

    @Property(str, notify=project_changed)
    def projectSource(self) -> str:
        if self._workspace is not None:
            return "project"
        return "mock" if self._demo_mode else "empty"

    @Property(str, notify=model_status_changed)
    def modelStatusText(self) -> str:
        """QP-1: honest placeholder; QP-2 wires the real config state."""
        return "未配置"

    @Property("QVariantList", notify=advanced_data_changed)  # type: ignore[arg-type]
    def advancedClues(self) -> list[dict[str, Any]]:
        return self._advanced_clues

    @Property("QVariantMap", notify=advanced_data_changed)  # type: ignore[arg-type]
    def advancedPlan(self) -> dict[str, Any]:
        return self._advanced_plan

    @Property(str, notify=advanced_data_changed)
    def advancedState(self) -> str:
        return self._advanced_state

    @Property("QVariantList", notify=trajectory_changed)  # type: ignore[arg-type]
    def trajectoryIndex(self) -> list[dict[str, Any]]:
        return self._trajectory_index

    @Property("QVariantMap", notify=trajectory_changed)  # type: ignore[arg-type]
    def trajectoryDetail(self) -> dict[str, Any]:
        return self._trajectory_detail

    @Property("QVariantList", notify=trajectory_changed)  # type: ignore[arg-type]
    def trajectoryEvidence(self) -> list[dict[str, Any]]:
        return self._trajectory_evidence

    @Property(str, notify=trajectory_changed)
    def trajectoryState(self) -> str:
        return self._trajectory_state

    @Property("QVariantList", notify=cognition_changed)  # type: ignore[arg-type]
    def cognitionRows(self) -> list[dict[str, Any]]:
        return self._cognition_rows

    @Property(str, notify=cognition_changed)
    def cognitionState(self) -> str:
        return self._cognition_state

    @Property(int, notify=project_changed)
    def chapterCount(self) -> int:
        return len(self._chapters)

    @Property(QObject, notify=project_changed)
    def chapters(self) -> ChapterListModel:
        return self._chapters_model

    @Property(QObject, constant=True)
    def suggestions(self) -> SuggestionListModel:
        return self._suggestions_model

    def _current_chapter(self) -> ChapterDto | None:
        if 0 <= self._current_index < len(self._chapters):
            return self._chapters[self._current_index]
        return None

    @Property(str, notify=chapter_changed)
    def currentChapterId(self) -> str:
        chapter = self._current_chapter()
        return chapter.id if chapter is not None else ""

    @Property(str, notify=chapter_changed)
    def currentChapterTitle(self) -> str:
        chapter = self._current_chapter()
        return chapter.title if chapter is not None else ""

    @Property(str, notify=chapter_changed)
    def currentChapterBody(self) -> str:
        return self._body_text

    @Property(int, notify=chapter_changed)
    def currentChapterWordCount(self) -> int:
        return count_words(self._body_text)

    @Property(str, notify=chapter_changed)
    def currentWordCountText(self) -> str:
        return format_word_count(count_words(self._body_text))

    @Property(str, notify=web_word_count_changed)
    def webEngineWordCountText(self) -> str:
        if self._web_word_count is None:
            return format_word_count(count_words(self._body_text))
        return format_word_count(self._web_word_count)

    @Property(str, notify=chapter_changed)
    def currentVolumeTitle(self) -> str:
        chapter = self._current_chapter()
        if chapter is None:
            return ""
        volume = next(
            (v for v in self._volumes if chapter.id in {c.id for c in v.chapters}),
            None,
        )
        return volume.title if volume is not None else ""

    @Property(QObject, constant=True)
    def discussionMessages(self) -> DiscussionMessageListModel:
        return self._discussion_model

    @Property(bool, notify=discussion_changed)
    def discussionBusy(self) -> bool:
        return self._discussion_busy

    @Property(int, notify=chapter_changed)
    def currentRevision(self) -> int:
        return self._revision

    @Property(str, notify=editor_state_changed)
    def editorState(self) -> str:
        return self._editor_state

    @Property(str, notify=editor_state_changed)
    def saveStatusText(self) -> str:
        return self._save_status

    @Property(bool, notify=ai_drawer_changed)
    def aiDrawerOpen(self) -> bool:
        return self._ai_drawer_open

    @Property(str, notify=active_nav_changed)
    def activeNav(self) -> str:
        return self._active_nav

    @Property(bool, notify=reduce_motion_changed)
    def reduceMotion(self) -> bool:
        return self._reduce_motion

    @Property(str, notify=draft_status_changed)
    def draftStatus(self) -> str:
        return self._draft_status

    @Property(bool, notify=draft_view_changed)
    def draftViewEnabled(self) -> bool:
        return bool(self._draft_text) and self._workspace is not None

    @Property(str, notify=draft_view_changed)
    def draftView(self) -> str:
        return self._draft_view

    @Property(str, notify=draft_view_changed)
    def draftBaseText(self) -> str:
        return self._draft_base_body

    @Property(str, notify=draft_view_changed)
    def draftText(self) -> str:
        return self._draft_text

    @Property(QObject, constant=True)
    def draftDiff(self) -> DraftDiffModel:
        return self._draft_diff_model

    @Property(QObject, constant=True)
    def characterViews(self) -> CharacterListModel:
        return self._characters_model

    @Property(QObject, constant=True)
    def characterJourney(self) -> CharacterJourneyListModel:
        return self._journey_model

    @Property(bool, notify=character_detail_changed)
    def characterDetailVisible(self) -> bool:
        return self._selected_character is not None

    @Property(str, notify=character_detail_changed)
    def characterDetailName(self) -> str:
        return self._selected_character.name if self._selected_character else ""

    @Property(str, notify=character_detail_changed)
    def characterDetailProfile(self) -> str:
        return self._selected_character.profile if self._selected_character else ""

    @Property(str, notify=character_detail_changed)
    def characterDetailMotivation(self) -> str:
        return self._selected_character.motivation if self._selected_character else ""

    @Property(str, notify=character_detail_changed)
    def characterDetailPsychology(self) -> str:
        return self._selected_character.psychology if self._selected_character else ""

    @Property(str, notify=character_detail_changed)
    def characterDetailGoal(self) -> str:
        return self._selected_character.goal if self._selected_character else ""

    @Property(str, notify=character_detail_changed)
    def characterDetailRelationships(self) -> str:
        return self._selected_character.relationships if self._selected_character else ""

    @Property(str, notify=character_detail_changed)
    def characterDetailRecent(self) -> str:
        return self._selected_character.recent if self._selected_character else ""

    @Property(str, notify=character_detail_changed)
    def characterDetailLocation(self) -> str:
        return self._selected_character.location if self._selected_character else ""

    @Property(str, notify=character_detail_changed)
    def characterDetailInjury(self) -> str:
        return self._selected_character.injury_status if self._selected_character else ""

    @Property(bool, notify=memory_detail_changed)
    def memoryDetailVisible(self) -> bool:
        return self._selected_memory is not None

    @Property(str, notify=memory_detail_changed)
    def memoryDetailTitle(self) -> str:
        return self._selected_memory.title if self._selected_memory else ""

    @Property(str, notify=memory_detail_changed)
    def memoryDetailCategory(self) -> str:
        return self._selected_memory.category if self._selected_memory else ""

    @Property(str, notify=memory_detail_changed)
    def memoryDetailContent(self) -> str:
        return self._selected_memory.content if self._selected_memory else ""

    @Property(str, notify=memory_detail_changed)
    def memoryDetailSourceType(self) -> str:
        return self._selected_memory.source_type if self._selected_memory else ""

    @Property(str, notify=memory_detail_changed)
    def memoryDetailAuthority(self) -> str:
        return str(self._selected_memory.authority) if self._selected_memory else ""

    @Property(str, notify=memory_detail_changed)
    def memoryDetailReview(self) -> str:
        return str(self._selected_memory.review_status) if self._selected_memory else ""

    @Property(str, notify=memory_detail_changed)
    def memoryDetailStatus(self) -> str:
        return str(self._selected_memory.status) if self._selected_memory else ""

    @Property(int, notify=memory_detail_changed)
    def memoryDetailRevision(self) -> int:
        return self._selected_memory.revision if self._selected_memory else 0

    @Property(QObject, constant=True)
    def memoryViews(self) -> MemoryListModel:
        return self._memories_model

    @Property(QObject, constant=True)
    def auditViews(self) -> AuditListModel:
        return self._audits_model

    @Property(int, notify=generation_config_changed)
    def generationTargetWords(self) -> int:
        return self._generation_config.target_words

    @Property(int, notify=generation_config_changed)
    def generationOutputTokenLimit(self) -> int:
        return self._generation_config.output_token_limit

    @Property(str, notify=generation_config_changed)
    def generationMode(self) -> str:
        return self._generation_config.mode

    @Property(str, notify=generation_config_changed)
    def generationAuditPolicy(self) -> str:
        return self._generation_config.audit_policy

    @Property(str, notify=usage_changed)
    def usageInputOutputText(self) -> str:
        input_text = self._token_text(self._usage.input_tokens)
        output_text = self._token_text(self._usage.output_tokens)
        return f"{input_text} / {output_text}"

    @Property(str, notify=usage_changed)
    def usageCostText(self) -> str:
        if self._usage.cost is None or (self._usage.call_count == 0 and self._usage.cost == 0):
            return "未估算"
        return f"¥{self._usage.cost:.3f}"

    @Property(str, notify=usage_changed)
    def usageCacheText(self) -> str:
        if not self._usage.cache_known:
            return "缓存 未知"
        return f"缓存 {self._token_text(self._usage.cached_input_tokens)}"

    @Property(str, notify=usage_changed)
    def usageCallsText(self) -> str:
        if self._usage.call_count == 0:
            return "0 次调用"
        failed = f" · {self._usage.failed_call_count} 失败" if self._usage.failed_call_count else ""
        return f"{self._usage.call_count} 次调用{failed}"

    @Property(str, notify=overview_changed)
    def characterCountText(self) -> str:
        return self._count_text(self._overview.character_count, "人")

    @Property(str, notify=overview_changed)
    def memoryCountText(self) -> str:
        return self._count_text(self._overview.memory_count, "条")

    @Property(str, notify=overview_changed)
    def auditCountText(self) -> str:
        return self._count_text(self._overview.audit_count, "项")

    # -- commands ------------------------------------------------------------

    @Slot(int)
    def selectChapter(self, row: int) -> None:
        if self._real_agent is not None and self._real_agent.is_busy:
            self._real_agent.warn("Harness 运行期间不能切换章节")
            return
        chapter = self._chapters_model.chapter_at_row(row)
        if chapter is None:
            return
        self._current_index = next(
            index for index, candidate in enumerate(self._chapters) if candidate.id == chapter.id
        )
        self._target_volume_id = self._volume_id_for_chapter(chapter.id)
        self._load_current_chapter_document()
        self.chapter_changed.emit()
        self.chapterChanged.emit()
        self.editor_state_changed.emit()
        self.setActiveNav("writing")

    @Slot(str)
    def editorTextChanged(self, text: str) -> None:
        if self._editor_state == "CONFLICT":
            self._body_text = text
            self.chapter_changed.emit()
            self.chapterChanged.emit()
            return
        if text == self._body_text:
            if self._editor_state == "CLEAN":
                return
            self._editor_state = "CLEAN" if text == self._saved_body else "DIRTY"
            self._save_status = (
                "已保存 · 暂无未保存更改" if self._editor_state == "CLEAN" else "有未保存更改"
            )
            self.editor_state_changed.emit()
            return
        self._body_text = text
        self.clearSelectionReference()
        self._editor_state = "DIRTY"
        self._save_status = "有未保存更改"
        self.editor_state_changed.emit()
        self.chapter_changed.emit()
        self.chapterChanged.emit()

    @Slot()
    def requestSave(self) -> None:
        if self._workspace is not None:
            if self._editor_state == "CLEAN":
                self._save_status = f"已保存 · 修订 {self._revision}"
                self.editor_state_changed.emit()
                return
            current = self._current_chapter()
            if current is None:
                self._save_status = "未打开项目，无法保存"
                self.editor_state_changed.emit()
                return
            chapter_id = current.id
            self._editor_state = "SAVING"
            self.editor_state_changed.emit()
            try:
                result = self._workspace.save_chapter(
                    chapter_id,
                    self._body_text,
                    expected_revision=self._revision,
                )
            except RuntimeError as exc:
                message = str(exc)
                if "revision is stale" in message:
                    self._editor_state = "CONFLICT"
                    self._save_status = (
                        "正文已在其他位置修改（修订冲突）· 未覆盖任何内容，请重新载入"
                    )
                else:
                    self._editor_state = "DIRTY"
                    self._save_status = f"保存失败：{message}"
                self.editor_state_changed.emit()
                return
            self._saved_body = self._body_text
            self._revision = result.revision
            self._editor_state = "CLEAN"
            self._save_status = f"已保存 · 修订 {self._revision}"
            self.editor_state_changed.emit()
            self.chapter_changed.emit()
            self.chapterChanged.emit()
            return
        if self._editor_state == "CLEAN":
            self._save_status = f"已保存 · 修订 {self._revision}"
            self.editor_state_changed.emit()
            return
        self._editor_state = "SAVING"
        self.editor_state_changed.emit()
        self._saved_body = self._body_text
        self._revision += 1
        self._editor_state = "CLEAN"
        self._save_status = f"已保存 · 修订 {self._revision}"
        self.editor_state_changed.emit()

    @Slot()
    def reloadChapter(self) -> None:
        """Discard local edits and reload the current chapter from disk.

        Only available after a revision conflict; this is an explicit user
        recovery action, never automatic.
        """
        if self._workspace is None or self._editor_state != "CONFLICT":
            return
        self._load_current_chapter_document()
        self._save_status = "已重新载入 · 放弃了冲突前的本地未保存修改"
        self.chapter_changed.emit()
        self.chapterChanged.emit()
        self.editor_state_changed.emit()

    @Slot(str, int, str)
    def saveFromEditor(
        self,
        chapter_id: str,
        expected_revision: int,
        markdown: str,
    ) -> None:
        """Persist a chapter payload coming from the WebEngine editor.

        The bridge validates hash/size before this slot; the facade still
        verifies the chapter matches the current editor and uses the F3
        expected-revision save path (stale revisions become CONFLICT).
        """
        if self._workspace is None:
            self._save_status = "未打开项目，无法保存"
            self.editor_state_changed.emit()
            return
        current = self._current_chapter()
        if current is None or chapter_id != current.id:
            self._save_status = "编辑器章节与当前章节不一致，拒绝保存"
            self.editor_state_changed.emit()
            return
        if expected_revision != self._revision:
            self._editor_state = "CONFLICT"
            self._save_status = "编辑器保存修订已过期 · 未覆盖任何内容，请重新载入"
            self.editor_state_changed.emit()
            return
        self._body_text = markdown
        self._editor_state = "SAVING"
        self.editor_state_changed.emit()
        try:
            result = self._workspace.save_chapter(
                chapter_id,
                markdown,
                expected_revision=expected_revision,
            )
        except RuntimeError as exc:
            message = str(exc)
            if "revision is stale" in message:
                self._editor_state = "CONFLICT"
                self._save_status = "正文已在其他位置修改（修订冲突）· 未覆盖任何内容，请重新载入"
            else:
                self._editor_state = "DIRTY"
                self._save_status = f"保存失败：{message}"
            self.editor_state_changed.emit()
            return
        self._saved_body = markdown
        self._revision = result.revision
        self._editor_state = "CLEAN"
        self._save_status = f"已保存 · 修订 {result.revision}"
        if self._chat_selection and self._chat_selection.content == markdown:
            from dataclasses import replace

            self._chat_selection = replace(self._chat_selection, revision=result.revision)
            self.selection_reference_changed.emit()
        self.editorRevisionChanged.emit(result.revision)
        self.editor_state_changed.emit()
        self.chapter_changed.emit()

    @Slot(str)
    def setSaveStatusText(self, message: str) -> None:
        """Surface bridge/editor errors in the status bar."""
        self._save_status = message
        self.editor_state_changed.emit()

    @Slot(int)
    def setWebEngineWordCount(self, count: int) -> None:
        self._web_word_count = max(0, count)
        self.web_word_count_changed.emit()
        self.chapterChanged.emit()

    @Slot()
    def requestDraft(self) -> None:
        if self._codex is not None:
            self.toggleAiDrawer(True)
            self.startAssistantChat("/生成草稿")
            return
        if self._workspace is not None:
            self._request_project_draft()
            return
        chapter = self._current_chapter()
        if chapter is None:
            return
        chapter_title = chapter.title
        suggestion = SuggestionDto(
            id=str(uuid4()),
            label="段落润色建议",
            kind="polish",
            body=(
                f"针对《{chapter_title}》的 Mock 润色建议：把动作和光线写得更有层次，"
                "让时间线更清楚；该建议仅演示「候选层」流程，不直接修改正式正文，"
                "确认后才会进入编辑器缓冲区。"
            ),
        )
        self._suggestions_model.add_item(suggestion)
        self._ai_drawer_open = True
        self.ai_drawer_changed.emit()

    @Slot(int)
    def acceptSuggestion(self, row: int) -> None:
        item = self._suggestions_model.item_at_row(row)
        if item is None:
            return
        if self._workspace is not None and item.kind == "draft":
            self._accept_project_draft(row)
            return
        prefix = "" if not self._body_text.strip() else "\n\n"
        self._body_text = self._body_text + prefix + item.body
        self._suggestions_model.remove_item(row)
        self._editor_state = "DIRTY"
        self._save_status = "有未保存更改（已采用建议）"
        self.editor_state_changed.emit()
        self.chapter_changed.emit()
        self.chapterChanged.emit()

    @Slot(int)
    def discardSuggestion(self, row: int) -> None:
        item = self._suggestions_model.item_at_row(row)
        if self._workspace is not None and item is not None and item.kind == "draft":
            if self._draft_port is not None:
                try:
                    self._draft_port.discard_current()
                except (KeyError, RuntimeError, ValueError) as exc:
                    self._save_status = f"放弃草稿失败：{exc}"
                    self.editor_state_changed.emit()
                    return
            self._active_run_id = None
            self._suggestions_model.remove_item(row)
            self._save_status = "AI 草稿已放弃"
            self._clear_draft_review_state()
            self.editor_state_changed.emit()
            return
        self._suggestions_model.remove_item(row)

    @Slot(bool)
    def toggleAiDrawer(self, open_: bool) -> None:
        if self._ai_drawer_open == open_:
            return
        self._ai_drawer_open = open_
        self.ai_drawer_changed.emit()

    @Slot(str)
    def setActiveNav(self, nav_id: str) -> None:
        normalized = _NAV_ALIASES.get(nav_id, nav_id)
        if normalized not in _NAV_IDS or normalized == self._active_nav:
            return
        if self._active_nav == "outline" and not self._outline.flush():
            return
        self._active_nav = normalized
        self.active_nav_changed.emit()

    @Slot(int)
    def selectCharacter(self, row: int) -> None:
        character = self._characters_model.character_at_row(row)
        if character is None:
            return
        self._selected_character = character
        self._journey_model.set_items(character.journey)
        self.character_detail_changed.emit()

    @Slot()
    def closeCharacterDetail(self) -> None:
        if self._selected_character is None:
            return
        self._selected_character = None
        self._journey_model.set_items(())
        self.character_detail_changed.emit()

    @Slot(int)
    def selectMemory(self, row: int) -> None:
        memory = self._memories_model.memory_at_row(row)
        if memory is None:
            return
        self._selected_memory = memory
        self.memory_detail_changed.emit()

    @Slot()
    def closeMemoryDetail(self) -> None:
        if self._selected_memory is None:
            return
        self._selected_memory = None
        self.memory_detail_changed.emit()

    @Slot(int)
    def revealAuditEvidence(self, row: int) -> None:
        """Locate an audit finding's evidence in the current chapter body."""
        finding = self._audits_model.audit_at_row(row)
        if finding is None:
            return
        position = self._body_text.find(finding.evidence)
        if position < 0:
            self._save_status = "审校证据在当前正文中未找到（正文可能已修改）"
            self.editor_state_changed.emit()
            return
        self.setActiveNav("writing")
        self.evidenceRevealRequested.emit(
            finding.evidence,
            position,
            len(finding.evidence),
        )

    @Slot(int, str)
    def updateAuditFindingStatus(self, row: int, status: str) -> None:
        """Persist an ignore/false-positive decision through the audit service."""
        if self._codex is not None:
            self._save_status = "旧审校记录仅供查看"
            self.editor_state_changed.emit()
            return
        finding = self._audits_model.audit_at_row(row)
        if finding is None:
            return
        if self._workspace is None or self._workspace.project is None:
            self._save_status = "未打开项目，无法更新审校状态"
            self.editor_state_changed.emit()
            return
        try:
            if not BACKEND_AVAILABLE:
                self._save_status = "后端不可用：独立前端仓库无法持久化审校状态"
                self.editor_state_changed.emit()
                return
            from ai_novel_studio.application.project_audit_service import (
                ProjectAuditService,
            )
            from ai_novel_studio.domain.audit import AuditFindingStatus

            ProjectAuditService(self._workspace.project).update_finding_status(
                finding.id, AuditFindingStatus(status)
            )
        except (KeyError, LookupError, RuntimeError, ValueError) as exc:
            self._save_status = f"更新审校状态失败：{exc}"
            self.editor_state_changed.emit()
            return
        self._refresh_overview()
        self._save_status = "审校状态已更新"
        self.editor_state_changed.emit()

    @Slot(bool)
    def setReduceMotion(self, enabled: bool) -> None:
        if self._reduce_motion == enabled:
            return
        self._reduce_motion = enabled
        self.reduce_motion_changed.emit()

    @Slot(str)
    def setDraftView(self, value: str) -> None:
        if value not in {"current", "draft", "diff"} or value == self._draft_view:
            return
        self._draft_view = value
        self.draft_view_changed.emit()

    @Slot(int)
    def acceptDiffBlock(self, block_id: int) -> None:
        if self._workspace is None or not self._draft_text:
            return
        block = next(
            (item for item in self._diff_blocks if item.block_id == block_id),
            None,
        )
        if block is None or block_id in self._diff_accepted:
            return
        self._diff_accepted.add(block_id)
        self._diff_ignored.add(block_id)
        self._body_text = apply_diff_blocks(
            self._draft_base_body,
            self._diff_blocks,
            self._diff_accepted,
        )
        self._editor_state = "DIRTY"
        self._save_status = "已采用段落修改 · 待保存"
        self._rebuild_draft_diff()
        self.editor_state_changed.emit()
        self.chapter_changed.emit()
        self.chapterChanged.emit()
        self.draft_view_changed.emit()

    @Slot(int)
    def rejectDiffBlock(self, block_id: int) -> None:
        if self._workspace is None or not self._draft_text:
            return
        block = next(
            (item for item in self._diff_blocks if item.block_id == block_id),
            None,
        )
        if block is None or block_id in self._diff_ignored:
            return
        self._diff_ignored.add(block_id)
        self._save_status = "已忽略该段修改"
        self._rebuild_draft_diff()
        self.editor_state_changed.emit()
        self.draft_view_changed.emit()

    @Slot(int, str)
    def editAndAcceptDiffBlock(self, block_id: int, edited_text: str) -> None:
        """Accept a diff block using a user-edited replacement text."""
        if self._workspace is None or not self._draft_text:
            return
        block = next(
            (item for item in self._diff_blocks if item.block_id == block_id),
            None,
        )
        if block is None or block_id in self._diff_accepted or block.kind == "unchanged":
            return
        normalized = edited_text.strip()
        if not normalized:
            self._save_status = "编辑后的文本不能为空"
            self.editor_state_changed.emit()
            return
        edited_block = replace(block, draft_text=normalized)
        self._diff_blocks = tuple(
            edited_block if item.block_id == block_id else item for item in self._diff_blocks
        )
        self._diff_accepted.add(block_id)
        self._diff_ignored.add(block_id)
        self._body_text = apply_diff_blocks(
            self._draft_base_body,
            self._diff_blocks,
            self._diff_accepted,
        )
        self._editor_state = "DIRTY"
        self._save_status = "已采用编辑后的段落 · 待保存"
        self._rebuild_draft_diff()
        self.editor_state_changed.emit()
        self.chapter_changed.emit()
        self.chapterChanged.emit()
        self.draft_view_changed.emit()

    @Slot(int)
    def setGenerationTargetWords(self, value: int) -> None:
        target = max(100, min(value, 100_000))
        if target == self._generation_config.target_words:
            return
        self._generation_config = GenerationConfig(
            target_words=target,
            output_token_limit=self._generation_config.output_token_limit,
            mode=self._generation_config.mode,
            audit_policy=self._generation_config.audit_policy,
        )
        self.generation_config_changed.emit()

    @Slot(int)
    def setGenerationOutputTokenLimit(self, value: int) -> None:
        limit = max(256, min(value, 32_768))
        if limit == self._generation_config.output_token_limit:
            return
        self._generation_config = GenerationConfig(
            target_words=self._generation_config.target_words,
            output_token_limit=limit,
            mode=self._generation_config.mode,
            audit_policy=self._generation_config.audit_policy,
        )
        self.generation_config_changed.emit()

    @Slot(str)
    def setGenerationMode(self, value: str) -> None:
        if value not in _CREATION_MODES:
            return
        if value == self._generation_config.mode:
            return
        self._generation_config = GenerationConfig(
            target_words=self._generation_config.target_words,
            output_token_limit=self._generation_config.output_token_limit,
            mode=value,
            audit_policy=self._generation_config.audit_policy,
        )
        self.generation_config_changed.emit()

    @Slot(str)
    def setGenerationAuditPolicy(self, value: str) -> None:
        if value not in _AUDIT_POLICIES:
            return
        if value == self._generation_config.audit_policy:
            return
        self._generation_config = GenerationConfig(
            target_words=self._generation_config.target_words,
            output_token_limit=self._generation_config.output_token_limit,
            mode=self._generation_config.mode,
            audit_policy=value,
        )
        self.generation_config_changed.emit()

    @Slot(str)
    def setChapterFilter(self, query: str) -> None:
        self._chapters_model.set_filter(query)

    @Slot(str)
    def sendDiscussion(self, text: str) -> None:
        """DEPRECATED (C1.1): legacy plot-discussion path, no longer rendered.

        Kept only for compatibility with the deprecated DiscussionPanel; the
        default AI surface is the Agent timeline via ``startAgentTurn``.
        """
        normalized = text.strip()
        if not normalized or self._discussion_busy:
            return
        self._discussion_model.add_message(
            DiscussionMessageDto(id=str(uuid4()), role="user", text=normalized)
        )
        self._discussion_busy = True
        self.discussion_changed.emit()
        reply = (
            f"（Mock 剧情商讨）针对当前章节《{self.currentChapterTitle}》，"
            f"可以考虑：{normalized[:40]}。这条回复由前端 mock 生成，"
            "后端模型端口接线后将成为真实讨论。"
        )
        self._discussion_model.add_message(
            DiscussionMessageDto(id=str(uuid4()), role="assistant", text=reply)
        )
        self._discussion_busy = False
        self.discussion_changed.emit()

    @Slot()
    def clearDiscussion(self) -> None:
        """DEPRECATED (C1.1): see ``sendDiscussion``."""
        self._discussion_model.clear()
        self.discussion_changed.emit()

    @Property(QObject, constant=True)
    def agentTimeline(self) -> AgentTimelineModel:
        return self._agent_timeline_model

    @Property(bool, notify=agent_busy_changed)
    def agentBusy(self) -> bool:
        if self._codex is not None and self._codex.is_busy:
            return True
        if self._real_agent is not None:
            return self._real_agent.is_busy
        return self._agent_busy

    @Property(bool, constant=True)
    def codexEnabled(self) -> bool:
        return self._codex is not None

    @Property(str, notify=codex_status_changed)
    def codexStatusText(self) -> str:
        return self._codex.status_text if self._codex is not None else ""

    @Property("QVariantList", notify=codex_controls_changed)  # type: ignore[arg-type]
    def codexSessions(self) -> list[dict[str, str]]:
        return self._codex.sessions if self._codex else []

    @Property(int, notify=codex_controls_changed)
    def codexSessionIndex(self) -> int:
        return self._codex.session_index if self._codex else -1

    @Property("QVariantList", notify=codex_controls_changed)  # type: ignore[arg-type]
    def codexAttachments(self) -> list[dict[str, str]]:
        return self._codex.attachments if self._codex else []

    @Property(bool, notify=codex_controls_changed)
    def codexCanSteer(self) -> bool:
        return bool(self._codex and self._codex.can_steer)

    @Property(bool, notify=codex_controls_changed)
    def codexCanManageCurrent(self) -> bool:
        return bool(self._codex and self._codex.can_manage_current)

    @Property(str, notify=codex_controls_changed)
    def codexUsageText(self) -> str:
        return self._codex.usage_text if self._codex else ""

    @Property(str, notify=codex_controls_changed)
    def codexNovelText(self) -> str:
        return self._codex.novel_text if self._codex else ""

    @Slot(str, str)
    def manageCodexSession(self, operation: str, thread_id: str) -> None:
        if self._codex and not self.agentBusy:
            self._codex.manage_session(operation, thread_id)

    @Slot(QUrl)
    def addCodexAttachment(self, url: QUrl) -> None:
        if self._codex and not self.agentBusy and url.isLocalFile():
            self._codex.add_attachment(Path(url.toLocalFile()))

    @Slot(int)
    def removeCodexAttachment(self, index: int) -> None:
        if self._codex:
            self._codex.remove_attachment(index)

    def _sync_codex_editor(self) -> None:
        if self._codex is None:
            return
        chapter = self._current_chapter()
        selection = self._selection_reference
        selected = ""
        capture = None
        if (
            selection
            and chapter
            and selection.chapter_id == chapter.id
            and selection.base_revision == self._revision
            and selection.base_source_hash == hashlib.sha256(self._body_text.encode()).hexdigest()
        ):
            selected = selection.selection.text
            capture = selection
        if (
            capture is None
            and self._chat_selection
            and chapter
            and self._chat_selection.chapter_id == chapter.id
            and self._chat_selection.revision == self._revision
            and self._chat_selection.content == self._body_text
        ):
            selected = self._chat_selection.selection
        self._codex.update_editor(
            NovelEditorSnapshot(
                chapter_id=chapter.id if chapter else None,
                title=chapter.title if chapter else "",
                revision=self._revision if chapter else 0,
                content=self._body_text if chapter else "",
                dirty=bool(chapter and self._editor_state != "CLEAN"),
                selection=selected,
                selection_capture=capture,
            )
        )

    @Slot(int, int)
    def setPlainTextSelection(self, start: int, end: int) -> None:
        """TextArea reports UTF-16 offsets; persist exact Python codepoint spans."""
        chapter = self._current_chapter()
        if chapter is None or self._editor_state == "CONFLICT":
            return
        try:
            encoded = self._body_text.encode("utf-16-le")
            if (
                type(start) is not int
                or type(end) is not int
                or not 0 <= start < end <= len(encoded) // 2
            ):
                raise ValueError
            first = len(encoded[: start * 2].decode("utf-16-le"))
            last = len(encoded[: end * 2].decode("utf-16-le"))
            capture = capture_selection_range(
                chapter.id, self._revision, self._body_text, first, last
            )
        except (UnicodeError, ValueError):
            self.clearSelectionReference()
            return
        self._chat_selection = None
        self._selection_reference = capture
        self.selection_reference_changed.emit()

    @Property(bool, notify=selection_reference_changed)
    def hasSelectionReference(self) -> bool:
        return (
            bool(self._chat_selection and self._chat_selection.selection)
            or self._selection_reference is not None
        )

    @Property(str, notify=selection_reference_changed)
    def selectionReferenceLabel(self) -> str:
        chat_ref = self._chat_selection
        if chat_ref and chat_ref.selection and chat_ref.chapter_id:
            return f"{self._chapter_title(chat_ref.chapter_id)} · {len(chat_ref.selection)} 字"
        if self._selection_reference is None:
            return ""
        ref = self._selection_reference
        title = self._chapter_title(ref.chapter_id)
        return f"{title} · {len(ref.selection.text)} 字"

    @Property(str, notify=selection_reference_changed)
    def selectionReferencePreview(self) -> str:
        if self._chat_selection and self._chat_selection.selection:
            preview = " ".join(self._chat_selection.selection.split())
            return preview[:160] + ("…" if len(preview) > 160 else "")
        if self._selection_reference is None:
            return ""
        # Collapse whitespace/newlines to a single space: a cross-paragraph
        # selection would otherwise render as multiple lines inside the chip
        # and overflow its fixed height (the QML elide only applies on one
        # line). The quote shown is a preview, not the authoritative text.
        preview = " ".join(self._selection_reference.selection.text.split())
        return preview[:80] + ("…" if len(preview) > 80 else "")

    @Slot(str)
    def setChatSelectionJson(self, payload_json: str) -> None:
        from ai_novel_studio.ui_qml.bridge.models.chat_selection import parse_chat_selection

        snapshot = parse_chat_selection(payload_json)
        chapter = self._current_chapter()
        if snapshot is None:
            self.clearSelectionReference()
            return
        if not chapter or snapshot.chapter_id != chapter.id or snapshot.revision != self._revision:
            return
        if self._editor_state == "CONFLICT":
            return
        # Read the live buffer without saving it. ProseMirror's serialization
        # can differ from imported Markdown, so a quote is not a patch capture.
        self.editorTextChanged(snapshot.content)
        self._chat_selection = snapshot
        self.selection_reference_changed.emit()

    @Slot(str)
    def setSelectionReferenceJson(self, payload_json: str) -> None:
        from ai_novel_studio.ui_qml.bridge.models.selection_reference import (
            parse_selection_reference,
        )

        if payload_json.strip() == "":
            self._selection_reference = None
            self.selection_reference_changed.emit()
            return
        reference = parse_selection_reference(payload_json)
        if reference is None:
            self._selection_reference = None
            self._save_status = "选区引用数据无效，已清除"
            self.editor_state_changed.emit()
            self.selection_reference_changed.emit()
            return
        current_chapter = self._current_chapter()
        current_chapter_id = current_chapter.id if current_chapter is not None else ""
        if (
            current_chapter is None
            or reference.chapter_id != current_chapter_id
            or reference.base_revision != self._revision
            or reference.base_source_hash
            != hashlib.sha256(self._body_text.encode("utf-8")).hexdigest()
        ):
            # Stale selection: the editor may still hold a previous chapter or
            # revision. Reject and clear so the AI panel never acts on it.
            self._selection_reference = None
            self._save_status = "选区引用已过期（章节或修订已变化），已清除"
            self.editor_state_changed.emit()
            self.selection_reference_changed.emit()
            return
        self._selection_reference = reference
        self.selection_reference_changed.emit()

    @Slot()
    def clearSelectionReference(self) -> None:
        if self._selection_reference is None and self._chat_selection is None:
            return
        self._chat_selection = None
        self._selection_reference = None
        self.selection_reference_changed.emit()

    @Slot(str)
    def startAgentTurn(self, text: str) -> None:
        """Generate a replacement candidate for the current chapter."""
        if self._codex is not None:
            self.toggleAiDrawer(True)
            self.startAssistantChat(text)
            return
        normalized = text.strip()
        if not normalized or self.agentBusy:
            return
        chapter = self._current_chapter()
        if chapter is None:
            if self._real_agent is not None:
                self._real_agent.warn(
                    "未打开项目，无法运行 Agent"
                    if self._workspace is None
                    else "当前项目还没有章节，请先新建章节"
                )
            return
        if self._real_agent is not None:
            if normalized in _SELECTION_QUICK_COMMANDS and self._selection_reference is None:
                self._real_agent.warn("请先选择要修改的正文")
                return
            self._real_agent.start(
                normalized,
                chapter.id,
                self._body_text,
                editor_clean=self._workspace is None or self._editor_state == "CLEAN",
                selection_patch=self._selection_reference,
            )
            return
        self._active_agent_run_id = str(uuid4())
        self._agent_sequence = 0
        self._agent_timeline_model.append_item(
            AgentTimelineItemDto(
                id=str(uuid4()),
                kind="user_text",
                text=normalized,
                run_id=self._active_agent_run_id,
                sequence_number=self._agent_sequence,
            )
        )
        self._agent_sequence = 1
        self._agent_busy = True
        self._agent_step = 0
        self.agent_busy_changed.emit()
        self.agent_timeline_changed.emit()
        self._schedule_agent_step()

    @Slot(str)
    def startAssistantChat(self, text: str) -> None:
        """Start a read-only assistant conversation, never a chapter diff."""
        normalized = (text or "").strip()
        if not normalized:
            return
        if self._codex is not None:
            from ai_novel_studio.application.novel_writing_commands import writing_request

            display_text = normalized
            try:
                operation, normalized = writing_request(normalized)
            except ValueError as exc:
                self._codex.warn(str(exc))
                return
            if operation and self.agentBusy:
                self._codex.warn("请等待当前任务完成后再调用写作技能；也可以直接输入文字追加要求。")
                return
            if (
                operation in {"重写", "润色", "精简", "扩写"}
                and not self.hasSelectionReference
                and "作者补充：无" in normalized
            ):
                self._codex.warn("请先选择要修改的正文；如需处理整章，可在指令后输入“整章”。")
                return
            if self._codex.can_steer:
                self._codex.steer(normalized)
            elif not self.agentBusy:
                if not self._outline.flush():
                    self._codex.warn("大纲尚未保存，未发送创作任务；请先处理保存冲突或导出副本。")
                    return
                self._sync_codex_editor()
                self._codex.start(display_text, request_text=normalized)
            return
        if self.agentBusy:
            return
        chapter = self._current_chapter()
        if chapter is None:
            if self._real_agent is not None:
                self._real_agent.warn(
                    "未打开项目，无法使用 AI 助手"
                    if self._workspace is None
                    else "当前项目还没有章节，请先新建章节"
                )
            return
        if self._real_agent is not None:
            self._real_agent.start_chat(
                normalized,
                chapter.id,
                self._body_text,
            )
            return
        self._append_agent_text("当前运行环境没有连接真实 AI 对话服务。")

    @Slot()
    def stopAgentTurn(self) -> None:
        if not self.agentBusy:
            return
        if self._codex is not None and self._codex.is_busy:
            self._codex.stop()
            return
        if self._real_agent is not None:
            self._real_agent.stop()
            return
        self._stop_agent_timer()
        self._agent_busy = False
        run_id = self._active_agent_run_id or ""
        self._agent_timeline_model.append_item(
            AgentTimelineItemDto(
                id=str(uuid4()),
                kind="warning",
                text="已停止 Mock 任务（真实 Agent 接入后支持中断恢复）",
                run_id=run_id,
                sequence_number=self._agent_sequence,
            )
        )
        self._active_agent_run_id = None
        self.agent_busy_changed.emit()
        self.agent_timeline_changed.emit()

    @Slot(int)
    def agentReplyChoice(self, choice: int) -> None:
        options = ("方案 A：保持悬念，下一章揭示", "方案 B：本章末尾点破", "方案 C：由读者自行推理")
        if 0 <= choice < len(options):
            self._append_agent_text(
                f"你选择了：{options[choice]}（Mock 分支，真实决策需 Agent 后端）"
            )

    @Slot(str)
    def approveAgentItem(self, item_id: str) -> None:
        """Approve exactly one proposal identified by ``item_id``."""
        if self._real_agent is not None and self._real_agent.handles_pending_item(item_id):
            if self._real_agent.resolve_pending(item_id, approved=True):
                self._load_current_chapter_document()
                self.draftAcceptedToEditor.emit(self._body_text)
                self.editorRevisionChanged.emit(self._revision)
                self.chapter_changed.emit()
                self.chapterChanged.emit()
                self.editor_state_changed.emit()
            return
        self._replace_agent_item(item_id, state="APPLIED")
        self._append_agent_text(
            "已确认该修改方案。真实替换将在后续 Wave 接入（修订与哈希校验协议已预留）。"
        )

    @Slot(str)
    def retryAgentItem(self, item_id: str) -> None:
        """Retry exactly one proposal identified by ``item_id``."""
        if self._real_agent is not None and self._real_agent.handles_pending_item(item_id):
            self._real_agent.notify_action_unavailable(
                item_id,
                "请在输入框补充修改要求后重新生成；当前候选稿保持待确认。",
            )
            return
        self._replace_agent_item(item_id, state="RUNNING")
        self._append_agent_text("已收到再次修改请求，正在按新要求生成（Mock 分支）。")

    @Slot(str)
    def discardAgentItem(self, item_id: str) -> None:
        """Discard exactly one proposal identified by ``item_id``."""
        if self._real_agent is not None and self._real_agent.handles_pending_item(item_id):
            self._real_agent.resolve_pending(item_id, approved=False)
            return
        self._replace_agent_item(item_id, state="DISCARDED")
        self._append_agent_text("已放弃该修改方案，正文保持不变。")

    @Slot(str)
    def cancelAgentItem(self, item_id: str) -> None:
        """Cancel a pending confirmation or form without applying anything."""
        if self._real_agent is not None and self._real_agent.handles_pending_item(item_id):
            self._real_agent.resolve_pending(item_id, approved=False)
            return
        self._replace_agent_item(item_id, state="CANCELLED")
        self._append_agent_text("已取消确认，未执行任何修改。")

    @Slot(str, str)
    def submitAgentForm(self, item_id: str, values_json: str) -> None:
        """Record a mock form submission; nothing is persisted in C1."""
        self._replace_agent_item(item_id, state="APPLIED")
        preview = values_json[:120]
        self._append_agent_text(f"已保存表单 {preview}（Mock 保存，未写入项目）")

    @Slot(str)
    def skipAgentForm(self, item_id: str) -> None:
        self._replace_agent_item(item_id, state="DISCARDED")
        self._append_agent_text("已跳过该表单。")

    @Slot(str)
    def editAgentChangeSet(self, item_id: str) -> None:
        self._replace_agent_item(item_id, state="RUNNING")
        self._append_agent_text("编辑模式将在真实 Agent 接线后启用，当前保留 Mock 提案。")

    @Slot()
    def jumpToMemorySource(self) -> None:
        """Return to the writing page from a memory detail (source chapter)."""
        self.setActiveNav("writing")

    def _schedule_agent_step(self) -> None:
        self._stop_agent_timer()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(120)
        timer.timeout.connect(self._advance_agent)
        self._agent_timer = timer
        timer.start()

    def _advance_agent(self) -> None:
        if not self._agent_busy:
            return

        def step(**fields: Any) -> AgentTimelineItemDto:
            item = AgentTimelineItemDto(
                id=str(uuid4()),
                run_id=self._active_agent_run_id or "",
                sequence_number=self._agent_sequence,
                **fields,
            )
            self._agent_sequence += 1
            return item

        steps: list[AgentTimelineItemDto] = []
        if self._agent_step == 0:
            steps.append(
                step(
                    kind="run_status",
                    label="正在读取当前章节和选区",
                    busy=True,
                    status="RUNNING",
                    state="RUNNING",
                )
            )
        elif self._agent_step == 1:
            steps.append(
                step(
                    kind="tool_call",
                    label="read_selection",
                    text="读取正文选区与章节修订",
                    state="COMPLETED",
                )
            )
        elif self._agent_step == 2:
            ref = self._selection_reference
            steps.append(
                step(
                    kind="tool_result",
                    label="read_selection",
                    text=(
                        f"已读取 {self.currentChapterTitle} "
                        f"{len(ref.selection.text) if ref else 0} 字"
                    ),
                    state="COMPLETED",
                )
            )
        elif self._agent_step == 3:
            steps.append(
                step(
                    kind="run_status",
                    label="正在生成修改稿",
                    busy=False,
                    status="DONE",
                    state="COMPLETED",
                )
            )
        elif self._agent_step == 4:
            current = (
                self._selection_reference.selection.text
                if self._selection_reference
                else self._body_text[:120]
            )
            steps.append(
                step(
                    kind="text_diff",
                    label="修改对比",
                    current_text=current,
                    draft_text=("（Mock 修改稿）" + current[:40] + "…请人工确认后再替换。"),
                    state="PENDING",
                )
            )
        elif self._agent_step == 5:
            steps.append(
                step(
                    kind="confirmation",
                    label="确认操作",
                    text="替换选区 / 再次修改 / 放弃",
                    state="PENDING",
                )
            )
        elif self._agent_step == 6:
            steps.append(
                step(
                    kind="form_card",
                    label="补充设定",
                    text="请补充人物关系设定（Mock 表单，不写入项目）",
                    field_labels=("人物名", "关系", "备注"),
                    field_values=("林默", "旧友", "待确认"),
                    state="PENDING",
                )
            )
        elif self._agent_step == 7:
            steps.append(
                step(
                    kind="change_set",
                    label="变更提案",
                    target="人物 · 林默",
                    operation="更新",
                    before_text="码头工人",
                    after_text="退役水手",
                    risk="低",
                    reason="Mock 提案：人物设定与第一章背景冲突",
                    state="PENDING",
                )
            )
        else:
            self._agent_busy = False
            self._active_agent_run_id = None
            self.agent_busy_changed.emit()
            self.agent_timeline_changed.emit()
            return
        for item in steps:
            self._agent_timeline_model.append_item(item)
        self._agent_step += 1
        self.agent_timeline_changed.emit()
        if self._agent_step <= 7:
            self._schedule_agent_step()
        else:
            self._agent_busy = False
            self._active_agent_run_id = None
            self.agent_busy_changed.emit()

    def _replace_agent_item(self, item_id: str, **changes: Any) -> None:
        """Precisely update one timeline item via ``dataChanged`` (spec 18.6)."""
        if self._agent_timeline_model.update_item(item_id, **changes):
            self.agent_timeline_changed.emit()

    def _append_agent_text(self, text: str) -> None:
        run_id = self._active_agent_run_id or ""
        self._agent_timeline_model.append_item(
            AgentTimelineItemDto(
                id=str(uuid4()),
                kind="assistant_text",
                text=text,
                run_id=run_id,
                sequence_number=self._agent_sequence,
            )
        )
        self._agent_sequence += 1
        self.agent_timeline_changed.emit()

    def _stop_agent_timer(self) -> None:
        if self._agent_timer is not None:
            self._agent_timer.stop()
            self._agent_timer.deleteLater()
            self._agent_timer = None

    def _chapter_title(self, chapter_id: str) -> str:
        for volume in self._volumes:
            for chapter in volume.chapters:
                if chapter.id == chapter_id:
                    return chapter.title
        return "当前章节"

    @Slot(str, result=str)
    def openProject(self, root: str) -> str:
        """Open a real project read-only. Returns an error message or empty."""
        if not self._outline.flush():
            return "大纲尚未保存，请先处理保存冲突或导出副本"
        if self._real_agent is not None and self._real_agent.is_busy:
            return "Harness 正在运行，完成前不能切换项目"
        try:
            if not BACKEND_AVAILABLE:
                return "后端不可用：独立前端仓库需在主仓库运行时才能打开项目"
            from ai_novel_studio.application.project_workspace_service import (
                ProjectWorkspaceService,
            )

            workspace = ProjectWorkspaceService()
            workspace.open_project(Path(root))
        except Exception as exc:  # noqa: BLE001 - surfaced as UI copy, logged by caller if needed
            return f"打开项目失败：{exc}"
        if self._workspace is not None:
            self._workspace.close_project()
        self._workspace = workspace
        if self._real_agent is not None:
            self._real_agent.bind_project(workspace.project)
        if self._codex is not None:
            project = workspace.project
            self._codex.bind_project(project.project.id if project is not None else None, project)
        self._volumes = self._volumes_from_workspace()
        self._chapters = tuple(chapter for volume in self._volumes for chapter in volume.chapters)
        self._target_volume_id = (
            self._volume_id_for_chapter(self._chapters[0].id)
            if self._chapters
            else (self._volumes[0].id if self._volumes else "")
        )
        self._chapters_model.set_volumes(self._volumes)
        self._reset_advanced_secondary()
        if self._chapters:
            self._current_index = 0
            self._load_current_chapter_document()
        self.setActiveNav("writing")
        self.project_changed.emit()
        self.chapter_changed.emit()
        self.chapterChanged.emit()
        self.editor_state_changed.emit()
        return ""

    @Slot(QUrl, result=str)
    def openProjectFromUrl(self, url: QUrl | str) -> str:
        """FolderDialog helper: convert a QML URL to a local path."""
        local_path = url.toLocalFile() if isinstance(url, QUrl) else url
        return self.openProject(local_path)

    @Slot()
    def closeProject(self) -> None:
        if not self._outline.flush():
            return
        if self._real_agent is not None and self._real_agent.is_busy:
            self._real_agent.warn("Harness 运行期间不能关闭项目")
            return
        if self._real_agent is not None:
            self._real_agent.bind_project(None)
        if self._codex is not None:
            self._codex.bind_project(None)
        if self._workspace is not None:
            self._workspace.close_project()
            self._workspace = None
        self._volumes = ()
        self._chapters = ()
        self._target_volume_id = ""
        self._current_index = 0
        self._chapters_model.set_volumes(self._volumes)
        self._load_current_chapter_document()
        self._reset_advanced_secondary()
        self._refresh_overview()
        self.project_changed.emit()
        self.chapter_changed.emit()
        self.chapterChanged.emit()
        self.editor_state_changed.emit()

    @Slot(str, str, result=str)
    def createProject(self, parent_dir: str, title: str) -> str:
        """Create a real project at ``parent_dir/title`` (fail closed).

        Returns an error message, or empty on success. The target directory
        must not exist: the canonical workspace service owns creation, and
        this facade never overwrites existing files.
        """
        normalized_parent = (parent_dir or "").strip()
        if not normalized_parent:
            return "请填写父目录"
        return self._create_project_at(Path(normalized_parent), title)

    @Slot(QUrl, str, result=str)
    def createProjectFromUrl(self, parent_url: QUrl, title: str) -> str:
        """QML FolderDialog boundary: accept the selected folder as QUrl.

        Non-local URLs (or empty ones) fail closed; local URLs are converted
        via ``toLocalFile()`` exactly like ``openProjectFromUrl``.
        """
        if parent_url is None or not isinstance(parent_url, QUrl):
            return "请选择有效的父目录"
        if not parent_url.isLocalFile():
            return "父目录必须是本地文件夹"
        local = parent_url.toLocalFile()
        if not local:
            return "请选择有效的父目录"
        return self._create_project_at(Path(local), title)

    def _create_project_at(self, parent: Path, title: str) -> str:
        if not self._outline.flush():
            return "大纲尚未保存，请先处理保存冲突或导出副本"
        if self._real_agent is not None and self._real_agent.is_busy:
            return "Harness 正在运行，完成前不能新建项目"
        normalized_title = (title or "").strip()
        if not normalized_title:
            return "请填写项目名称"
        if any(character in normalized_title for character in '\\/:*?"<>|'):
            return "项目名称不能包含文件系统保留字符"
        target = parent / normalized_title
        if target.exists():
            return "目标目录已存在，未创建任何文件"
        try:
            if not BACKEND_AVAILABLE:
                return "后端不可用：独立前端仓库需在主仓库运行时才能新建项目"
            from ai_novel_studio.application.project_workspace_service import (
                ProjectWorkspaceService,
            )

            workspace = ProjectWorkspaceService()
            workspace.create_project(target, normalized_title)
        except Exception:  # noqa: BLE001 - fixed sanitized copy, never raw payloads
            return "新建项目失败：请检查目录权限后重试（未创建任何文件）"
        if self._workspace is not None:
            self._workspace.close_project()
        self._workspace = workspace
        if self._real_agent is not None:
            self._real_agent.bind_project(workspace.project)
        if self._codex is not None:
            project = workspace.project
            self._codex.bind_project(project.project.id if project is not None else None, project)
        self._volumes = self._volumes_from_workspace()
        self._chapters = tuple(chapter for volume in self._volumes for chapter in volume.chapters)
        self._target_volume_id = self._volumes[0].id if self._volumes else ""
        self._chapters_model.set_volumes(self._volumes)
        self._current_index = 0
        self._reset_advanced_secondary()
        self._load_current_chapter_document()
        self.setActiveNav("writing")
        self.project_changed.emit()
        self.chapter_changed.emit()
        self.chapterChanged.emit()
        self.editor_state_changed.emit()
        return ""

    @Slot(str, result=str)
    def createVolume(self, title: str) -> str:
        normalized = (title or "").strip()
        if self._real_agent is not None and self._real_agent.is_busy:
            return "Harness 正在运行，完成前不能修改项目结构"
        if self._workspace is None or self._workspace.project is None:
            return "请先新建或打开项目"
        if not normalized:
            return "请输入卷名"
        try:
            created = self._workspace.create_volume(normalized)
        except Exception:  # noqa: BLE001 - fixed UI copy, never raw storage data
            return "新建卷失败，请检查卷名后重试"
        self._reload_project_structure()
        self._target_volume_id = created.id
        self.project_changed.emit()
        return ""

    @Slot(str, str, result=str)
    def createChapter(self, title: str, declared_number: str = "") -> str:
        normalized_title = (title or "").strip()
        normalized_number = (declared_number or "").strip()
        if self._real_agent is not None and self._real_agent.is_busy:
            return "Harness 正在运行，完成前不能修改项目结构"
        if self._workspace is None or self._workspace.project is None:
            return "请先新建或打开项目"
        if not normalized_title:
            return "请输入章节标题"
        volume_id = self._target_volume_id
        if not volume_id and self._volumes:
            volume_id = self._volumes[0].id
        if not volume_id:
            return "当前项目没有可用卷"
        try:
            created = self._workspace.create_chapter(
                volume_id,
                normalized_title,
                normalized_number,
            )
        except Exception:  # noqa: BLE001 - fixed UI copy, never raw storage data
            return "新建章节失败，请检查标题后重试"
        self._reload_project_structure(select_chapter_id=created.id)
        self._load_current_chapter_document()
        self.project_changed.emit()
        self.chapter_changed.emit()
        self.chapterChanged.emit()
        self.editor_state_changed.emit()
        return ""

    @Slot(QUrl, result=str)
    def importManuscriptFromUrl(self, source_url: QUrl) -> str:
        if self._real_agent is not None and self._real_agent.is_busy:
            return "Harness 正在运行，完成前不能导入稿件"
        if self._workspace is None or self._workspace.project is None:
            return "请先新建或打开项目"
        if not isinstance(source_url, QUrl) or not source_url.isLocalFile():
            return "请选择本地 Markdown 或 TXT 文件"
        source = Path(source_url.toLocalFile())
        if source.suffix.lower() not in {".md", ".txt"} or not source.is_file():
            return "请选择本地 Markdown 或 TXT 文件"
        try:
            if source.stat().st_size > 20_000_000:
                return "稿件文件超过 20MB 上限"
            from ai_novel_studio.application.manuscript_import_service import (
                ManuscriptImportService,
            )

            report = ManuscriptImportService().import_file(
                self._workspace.project,
                source,
            )
        except Exception:  # noqa: BLE001 - fixed UI copy, never raw source data
            self._reload_project_structure()
            return "导入失败，请检查文件格式后重试"
        self._reload_project_structure(select_chapter_id=report.first_chapter_id)
        self._load_current_chapter_document()
        self.project_changed.emit()
        self.chapter_changed.emit()
        self.chapterChanged.emit()
        self.editor_state_changed.emit()
        self._save_status = f"导入完成 · {report.imported_chapters} 章"
        self.editor_state_changed.emit()
        return ""

    @Slot(result=int)
    def emptyChapterCount(self) -> int:
        if self._workspace is None or self._workspace.project is None:
            return 0
        try:
            return len(self._empty_chapter_ids())
        except Exception:  # noqa: BLE001 - count degrades closed at the UI boundary
            return 0

    @Slot(result=str)
    def deleteEmptyChapters(self) -> str:
        if self._real_agent is not None and self._real_agent.is_busy:
            return "Harness 正在运行，完成前不能删除章节"
        if self._workspace is None or self._workspace.project is None:
            return "请先新建或打开项目"
        if self._editor_state != "CLEAN":
            return "请先保存当前章节，再清理空章"
        try:
            chapter_ids = self._empty_chapter_ids()
            for chapter_id in chapter_ids:
                self._workspace.delete_chapter(chapter_id)
        except Exception:  # noqa: BLE001 - fixed UI copy, never raw storage data
            self._reload_project_structure()
            return "清理空章未完成，请重新载入项目后检查"
        self._reload_project_structure()
        if self._chapters:
            self._current_index = 0
            self._target_volume_id = self._volume_id_for_chapter(self._chapters[0].id)
        self._load_current_chapter_document()
        self.project_changed.emit()
        self.chapter_changed.emit()
        self.chapterChanged.emit()
        self.editor_state_changed.emit()
        self._save_status = f"已清理 {len(chapter_ids)} 个空白章节"
        self.editor_state_changed.emit()
        return ""

    def _empty_chapter_ids(self) -> tuple[str, ...]:
        if self._workspace is None:
            return ()
        return tuple(
            chapter.id
            for volume in self._workspace.volume_tree()
            for chapter in volume.chapters
            if not self._workspace.load_chapter(chapter.id).content.strip()
        )

    def _volume_id_for_chapter(self, chapter_id: str) -> str:
        for volume in self._volumes:
            if any(chapter.id == chapter_id for chapter in volume.chapters):
                return volume.id
        return ""

    def _reload_project_structure(
        self,
        *,
        select_chapter_id: str | None = None,
    ) -> None:
        self._volumes = self._volumes_from_workspace()
        self._chapters = tuple(chapter for volume in self._volumes for chapter in volume.chapters)
        self._chapters_model.set_volumes(self._volumes)
        if select_chapter_id is not None:
            for index, chapter in enumerate(self._chapters):
                if chapter.id == select_chapter_id:
                    self._current_index = index
                    self._target_volume_id = self._volume_id_for_chapter(chapter.id)
                    break
        elif self._chapters:
            self._current_index = min(self._current_index, len(self._chapters) - 1)
            self._target_volume_id = self._volume_id_for_chapter(
                self._chapters[self._current_index].id
            )
        elif self._volumes and not self._target_volume_id:
            self._target_volume_id = self._volumes[0].id

    def _advanced_reads(self) -> Any:
        """RC-4: application-layer owner of all advanced reads."""
        from ai_novel_studio.application.advanced_creation_read_service import (
            AdvancedCreationReadService,
        )

        if self._advanced_reads_cache is None:
            self._advanced_reads_cache = AdvancedCreationReadService(
                self._workspace.project  # type: ignore[union-attr]
            )
        return self._advanced_reads_cache

    def _current_sequence(self) -> int:
        current = self._current_chapter()
        if current is None or self._workspace is None:
            return 0
        try:
            sequence: int = int(self._advanced_reads().current_sequence(current.id))
            return sequence
        except KeyError:
            return 0

    @Slot(int, result=str)
    def characterIdAt(self, row: int) -> str:
        item = self._characters_model.character_at_row(row)
        return item.id if item is not None else ""

    @Slot(str)
    def loadAdvancedForSubject(self, subject_id: str) -> None:
        """QP-3B: load trajectory INDEX + cognition rows for one character."""
        self.loadTrajectory(subject_id)
        self.loadCognition(subject_id)

    @Slot(str)
    def loadTrajectory(self, subject_id: str) -> None:
        """QP-3B: Level-1 INDEX for one character (read-only)."""
        if self._workspace is None or self._workspace.project is None:
            self._trajectory_state = "NO_PROJECT"
            self.trajectory_changed.emit()
            return
        normalized = (subject_id or "").strip()
        if not normalized:
            self._trajectory_state = "NO_SUBJECT"
            self.trajectory_changed.emit()
            return
        try:
            items = self._advanced_reads().trajectory_index(normalized)
        except (KeyError, RuntimeError, ValueError):
            self._trajectory_index = []
            self._trajectory_detail = {}
            self._trajectory_state = "ERROR"
            self.trajectory_changed.emit()
            return
        self._trajectory_state = "READY"
        self._trajectory_detail = {}
        self._trajectory_evidence = []
        self._trajectory_evidence_outcome = ""
        self._trajectory_index = [
            {
                "occurrenceId": item.occurrence_id,
                "title": item.title,
                "type": item.occurrence_type.value,
                "sequence": item.narrative_sequence,
                "role": item.role,
                "summary": item.subject_summary,
                "status": item.review_status.value,
            }
            for item in items
        ]
        self.trajectory_changed.emit()

    @Slot(str)
    def openTrajectoryDetail(self, occurrence_id: str) -> None:
        if self._workspace is None or self._workspace.project is None:
            return
        try:
            detail = self._advanced_reads().trajectory_detail(occurrence_id)
        except (KeyError, RuntimeError, ValueError):
            self.setSaveStatusText("事件详情不可用（可能已失效或未审核）")
            self.trajectory_changed.emit()
            return
        self._trajectory_detail = {
            "occurrenceId": detail.occurrence_id,
            "title": detail.title,
            "type": detail.occurrence_type.value,
            "sequence": detail.narrative_sequence,
            "summary": detail.summary,
            "status": detail.review_status.value,
            "participants": [
                {
                    "subjectId": p.subject_id,
                    "role": p.role,
                    "summary": p.subject_summary,
                }
                for p in detail.participants
            ],
            "rangeCount": len(detail.source_ranges),
        }
        self.trajectory_changed.emit()

    @Slot(str)
    def loadTrajectoryEvidence(self, occurrence_id: str) -> None:
        """Explicit Level-3 evidence call through the R3b-Q1 boundary."""
        if self._workspace is None or self._workspace.project is None:
            return
        current = self._current_chapter()
        if current is None:
            self.setSaveStatusText("未打开章节，无法回源证据")
            return
        try:
            evidence_set = self._advanced_reads().trajectory_evidence(
                occurrence_id,
                target_chapter_id=current.id,
            )
        except (KeyError, RuntimeError, ValueError):
            self.setSaveStatusText("证据回源失败（来源可能已失效）")
            self.trajectory_changed.emit()
            return
        self._trajectory_evidence_outcome = evidence_set.outcome.value
        self._trajectory_evidence = [
            {
                "chapterId": hit.chapter_id,
                "start": hit.source_start,
                "end": hit.source_end,
                "text": hit.text[:400],
                "truncated": len(hit.text) > 400,
            }
            for hit in evidence_set.hits
        ]
        self.trajectory_changed.emit()

    @Slot(str)
    def loadCognition(self, viewer_subject_id: str) -> None:
        """QP-3B: read-only visible View assertions for one viewer."""
        if self._workspace is None or self._workspace.project is None:
            self._cognition_state = "NO_PROJECT"
            self.cognition_changed.emit()
            return
        viewer = (viewer_subject_id or "").strip() or None
        if viewer is None:
            self._cognition_state = "NO_SUBJECT"
            self._cognition_rows = []
            self.cognition_changed.emit()
            return
        try:
            rows = self._advanced_reads().cognition_rows(
                viewer_subject_id=viewer,
                narrative_sequence=self._current_sequence(),
            )
        except (KeyError, RuntimeError, ValueError):
            self._cognition_rows = []
            self._cognition_state = "ERROR"
            self.cognition_changed.emit()
            return
        self._cognition_state = "READY"
        self._cognition_rows = [
            {
                "viewType": row.view_type,
                "targetName": row.target_name,
                "viewerName": row.viewer_name or "",
                "epistemicStatus": row.epistemic_status or "",
                "content": row.content,
                "contentTruncated": row.content_truncated,
            }
            for row in rows
        ]
        self.cognition_changed.emit()

    @Slot()
    def refreshAdvancedReads(self) -> None:
        """QP-3C: re-run the read-only projections for the current chapter."""
        self._refresh_overview()
        self._refresh_advanced()

    def _reset_advanced_secondary(self) -> None:
        """Clear trajectory/cognition state on project switch/close."""
        self._trajectory_index = []
        self._trajectory_detail = {}
        self._trajectory_evidence = []
        self._trajectory_evidence_outcome = ""
        self._trajectory_state = "NO_PROJECT" if self._workspace is None else "NO_SUBJECT"
        self._cognition_rows = []
        self._cognition_state = "NO_PROJECT" if self._workspace is None else "NO_SUBJECT"
        self._advanced_reads_cache = None
        self.trajectory_changed.emit()
        self.cognition_changed.emit()

    def _refresh_advanced(self) -> None:
        """QP-3A: bounded read-only clue ledger + chapter plan projection."""
        current = self._current_chapter()
        if self._workspace is None or self._workspace.project is None:
            self._advanced_state = "NO_PROJECT"
        elif current is None:
            self._advanced_state = "NO_CHAPTER"
        else:
            self._advanced_state = "READY"
            try:
                clues = self._advanced_reads().clues_before(current.id)
                self._advanced_clues = [
                    {
                        "clueId": item.clue_id,
                        "title": item.title,
                        "clueType": item.clue_type,
                        "eventCount": item.event_count,
                        "lastAction": item.last_action,
                        "summary": item.summary,
                        "summaryTruncated": item.summary_truncated,
                        "chapterIds": list(item.chapter_ids),
                    }
                    for item in clues
                ]
                plan = self._advanced_reads().plan(current.id)
                requirement = plan.requirement
                self._advanced_plan = {
                    "domainKind": plan.domain_kind,
                    "requirementText": (requirement.content if requirement is not None else ""),
                    "requirementLocked": (
                        requirement.is_locked if requirement is not None else False
                    ),
                    "requirementTruncated": plan.requirement_truncated,
                    "guidanceText": plan.guidance_text,
                    "guidanceTruncated": plan.guidance_truncated,
                }
            except (KeyError, RuntimeError, ValueError):
                self._advanced_clues = []
                self._advanced_plan = {}
                self._advanced_state = "ERROR"
        self.advanced_data_changed.emit()

    def _load_current_chapter_document(self) -> None:
        self._clear_draft_review_state()
        if self._selection_reference is not None or self._chat_selection is not None:
            self._chat_selection = None
            self._selection_reference = None
            self.selection_reference_changed.emit()
        self._selected_character = None
        self._journey_model.set_items(())
        self.character_detail_changed.emit()
        self._selected_memory = None
        self.memory_detail_changed.emit()
        chapter = self._current_chapter()
        if chapter is None:
            self._body_text = ""
            self._saved_body = ""
            self._revision = 0
            self._editor_state = "CLEAN"
            self._save_status = "未打开项目 · 空状态"
            self._refresh_advanced()
            return
        if self._workspace is not None:
            workspace = self._workspace.load_chapter(chapter.id)
            self._body_text = workspace.content
            self._revision = workspace.revision
            self._refresh_overview()
        else:
            self._body_text = chapter.body
            self._revision = chapter.revision
        self._refresh_advanced()
        self._saved_body = self._body_text
        self._editor_state = "CLEAN"
        self._save_status = "已载入 · 暂无未保存更改"

    def _refresh_overview(self) -> None:
        if self._workspace is None or self._workspace.project is None:
            self._overview = OverviewCounts()
            self._readonly_views = ReadonlyViews()
            self._characters_model.set_items(())
            self._memories_model.set_items(())
            self._audits_model.set_items(())
            self.overview_changed.emit()
            self.readonly_views_changed.emit()
            return
        current = self._current_chapter()
        self._overview = readonly_overview_counts(
            self._workspace.project,
            current.id if current is not None else "",
        )
        self._readonly_views = readonly_views(
            self._workspace.project,
            current.id if current is not None else "",
        )
        self._characters_model.set_items(self._readonly_views.characters)
        self._memories_model.set_items(self._readonly_views.memories)
        self._audits_model.set_items(self._readonly_views.audits)
        self.overview_changed.emit()
        self.readonly_views_changed.emit()

    @staticmethod
    def _count_text(value: int | None, unit: str) -> str:
        return "—" if value is None else f"{value} {unit}"

    def _request_project_draft(self) -> None:
        if self._draft_port is None:
            self._save_status = "模型生成端口未配置，无法生成草稿（F4 接线点）"
            self._draft_status = DRAFT_FAILED
            self.draft_status_changed.emit()
            self.editor_state_changed.emit()
            return
        if self._draft_coordinator is None:
            self._save_status = "生成协调器未配置，无法生成草稿"
            self._draft_status = DRAFT_FAILED
            self.draft_status_changed.emit()
            self.editor_state_changed.emit()
            return
        chapter_id = self._chapters[self._current_index].id
        try:
            run_id = self._draft_port.prepare(
                chapter_id,
                self._revision,
                self._generation_config,
            )
        except (KeyError, RuntimeError, ValueError) as exc:
            self._save_status = f"生成草稿失败：{exc}"
            self.editor_state_changed.emit()
            return
        self._draft_coordinator.start_generate(run_id)

    def _on_draft_status(self, status: str) -> None:
        if status == self._draft_status:
            return
        self._draft_status = status
        self.draft_status_changed.emit()

    def _on_draft_ready(self, draft_text: str) -> None:
        if not draft_text.strip():
            self._save_status = "生成草稿为空，请重试"
            self.editor_state_changed.emit()
            return
        self._refresh_usage()
        self._active_run_id = self._draft_coordinator.run_id if self._draft_coordinator else None
        self._draft_base_body = self._body_text
        self._draft_text = draft_text
        self._diff_blocks = diff_paragraphs(self._draft_base_body, draft_text)
        self._diff_accepted = set()
        self._diff_ignored = set()
        self._draft_view = "draft"
        self._rebuild_draft_diff()
        self._suggestions_model.add_item(
            SuggestionDto(
                id=str(uuid4()),
                label="AI 草稿",
                kind="draft",
                body=draft_text,
            )
        )
        self._ai_drawer_open = True
        self.ai_drawer_changed.emit()
        self.draft_view_changed.emit()

    def _on_draft_failed(self, message: str) -> None:
        self._refresh_usage()
        self._save_status = f"生成草稿失败：{message}"
        self.editor_state_changed.emit()

    def _on_draft_cancelled(self, message: str) -> None:
        self._refresh_usage()
        self._save_status = message
        self.editor_state_changed.emit()

    def _refresh_usage(self) -> None:
        if self._draft_port is None:
            return
        try:
            self._usage = self._draft_port.usage_snapshot()
        except (KeyError, RuntimeError, ValueError):
            return
        self.usage_changed.emit()

    @staticmethod
    def _token_text(value: int) -> str:
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return str(value)

    @Slot()
    def cancelDraft(self) -> None:
        if self._draft_coordinator is not None:
            self._draft_coordinator.cancel()

    @Slot(str)
    def copyWriterDraft(self, item_id: str) -> None:
        if self._codex is not None:
            self._codex.copy_draft(item_id)

    @Slot()
    def stopWriterDraft(self) -> None:
        if self._codex is not None:
            self._codex.cancel_writer()

    @Slot(str, result="QVariantMap")
    def writerInputPreview(self, item_id: str) -> dict[str, Any]:
        return self._codex.preview_writer_input(item_id) if self._codex else {}

    @Slot(str, result=bool)
    def confirmWriterInput(self, item_id: str) -> bool:
        if self._codex is None:
            return False
        if not self._outline.flush():
            self._codex.warn("大纲尚未保存，请先处理冲突；正文模型未启动。")
            return False
        self._sync_codex_editor()
        return self._codex.confirm_writer_input(item_id)

    @Slot(str, result=bool)
    def rejectWriterInput(self, item_id: str) -> bool:
        return self._codex.reject_writer_input(item_id) if self._codex else False

    @Slot(result=bool)
    def restoreWriterDrafts(self) -> bool:
        return self._codex.restore_writer_drafts() if self._codex else False

    @Slot(str, result=bool)
    def discardWriterDraft(self, item_id: str) -> bool:
        return self._codex.discard_writer_draft(item_id) if self._codex else False

    @Slot(str, bool, result=bool)
    def adoptWriterDraft(self, item_id: str, allow_partial: bool = False) -> bool:
        if self._codex is None:
            return False
        if self._editor_state == "CONFLICT":
            self._codex.warn("正文存在修订冲突，请先重新载入检查。")
            return False
        # Do not save first: adoption checks the original formal revision and
        # the exact frozen editor buffer, including any then-unsaved edits.
        self._sync_codex_editor()
        result = self._codex.adopt_writer_draft(item_id, allow_partial=allow_partial)
        if not result:
            return False
        self._body_text = result["text"]
        self._saved_body = result["text"]
        self._revision = result["revision"]
        self._editor_state = "CLEAN"
        self._save_status = f"已采用候选 · 修订 {self._revision}"
        if result.get("maintenance_pending"):
            self._save_status += " · 检索索引待修复"
        self.clearSelectionReference()
        self._clear_draft_review_state()
        try:
            self._reload_project_structure(select_chapter_id=result["chapter_id"])
        except (KeyError, OSError, RuntimeError, ValueError):
            self._save_status += " · 章节列表待刷新"
        self.draftAcceptedToEditor.emit(self._body_text)
        self.editorRevisionChanged.emit(self._revision)
        self.editor_state_changed.emit()
        self.chapter_changed.emit()
        self.chapterChanged.emit()
        self.project_changed.emit()
        return True

    def _accept_project_draft(self, row: int) -> None:
        if self._draft_port is None or self._active_run_id is None:
            self._save_status = "当前没有可采用的 AI 草稿"
            self.editor_state_changed.emit()
            return
        try:
            accepted = self._draft_port.accept_current()
        except (KeyError, RuntimeError, ValueError) as exc:
            self._save_status = f"采用草稿失败：{exc}"
            self.editor_state_changed.emit()
            return
        self._body_text = accepted.text
        self._saved_body = accepted.text
        self._revision = accepted.chapter_revision
        self._editor_state = "CLEAN"
        self._save_status = f"已采用 AI 草稿 · 修订 {accepted.chapter_revision}"
        self._active_run_id = None
        self._suggestions_model.remove_item(row)
        self._clear_draft_review_state()
        self.draftAcceptedToEditor.emit(accepted.text)
        self.editorRevisionChanged.emit(self._revision)
        self.editor_state_changed.emit()
        self.chapter_changed.emit()
        self.chapterChanged.emit()

    def _rebuild_draft_diff(self) -> None:
        visible = tuple(
            block for block in self._diff_blocks if block.block_id not in self._diff_ignored
        )
        self._draft_diff_model.set_blocks(visible)

    def _clear_draft_review_state(self) -> None:
        self._draft_base_body = ""
        self._draft_text = ""
        self._diff_blocks = ()
        self._diff_accepted = set()
        self._diff_ignored = set()
        self._draft_diff_model.set_blocks(())
        self._draft_view = "draft"
        self.draft_view_changed.emit()

    def _volumes_from_workspace(self) -> tuple[VolumeDto, ...]:
        if self._workspace is None:
            return ()
        return tuple(
            VolumeDto(
                id=volume.id,
                title=volume.title,
                chapters=tuple(
                    ChapterDto(
                        id=chapter.id,
                        title=chapter.title,
                        status="draft",
                        revision=chapter.revision,
                        declared_number=chapter.declared_number,
                        word_count=chapter.word_count,
                    )
                    for chapter in volume.chapters
                ),
            )
            for volume in self._workspace.volume_tree()
        )

    def volumes(self) -> Sequence[VolumeDto]:
        return self._volumes
