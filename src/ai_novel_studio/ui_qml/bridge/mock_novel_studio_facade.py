"""QML facade for the new frontend.

The facade is the only object QML talks to. By default it serves deterministic
mock data; since Frontend Wave F2 it can also open a real project through the
read-only application service ``ProjectWorkspaceService`` (volume tree, chapter
loading, summary). It never writes project files, never touches repositories or
the model gateway directly, and keeps the same presentation DTO shape for both
modes (see docs/frontend audit, section 8).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from ai_novel_studio.application.project_workspace_service import ProjectWorkspaceService
from ai_novel_studio.domain.generation import AuditPolicy, CreationMode
from ai_novel_studio.ui_qml.bridge.draft_coordinator import (
    DRAFT_FAILED,
    DRAFT_IDLE,
    DraftCoordinator,
)
from ai_novel_studio.ui_qml.bridge.draft_port import DraftPort, GenerationConfig
from ai_novel_studio.ui_qml.bridge.dtos import (
    ChapterDto,
    SuggestionDto,
    UsageDto,
    VolumeDto,
)
from ai_novel_studio.ui_qml.bridge.models.chapter_list_model import ChapterListModel
from ai_novel_studio.ui_qml.bridge.models.draft_diff_model import DraftDiffModel
from ai_novel_studio.ui_qml.bridge.models.readonly_list_models import (
    AuditListModel,
    CharacterJourneyListModel,
    CharacterListModel,
    MemoryListModel,
)
from ai_novel_studio.ui_qml.bridge.models.suggestion_list_model import SuggestionListModel
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

_NAV_IDS = ("writing", "characters", "memory", "clues", "audit", "settings")


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

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        draft_port: DraftPort | None = None,
        draft_coordinator: DraftCoordinator | None = None,
    ) -> None:
        super().__init__(parent)
        self._draft_port = draft_port
        self._generation_config = GenerationConfig()
        self._usage = UsageDto()
        self._overview = OverviewCounts()
        self._readonly_views = ReadonlyViews()
        self._characters_model = CharacterListModel(self)
        self._journey_model = CharacterJourneyListModel(self)
        self._memories_model = MemoryListModel(self)
        self._audits_model = AuditListModel(self)
        self._selected_character: CharacterViewDto | None = None
        self._selected_memory: MemoryViewDto | None = None
        self._draft_diff_model = DraftDiffModel(self)
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
        self._volumes = _mock_volumes()
        self._chapters_model = ChapterListModel(self._volumes, self)
        self._suggestions_model = SuggestionListModel(self)
        self._chapters = tuple(
            chapter for volume in self._volumes for chapter in volume.chapters
        )
        self._current_index = 0
        self._body_text = self._chapters[0].body
        self._saved_body = self._body_text
        self._revision = self._chapters[0].revision
        self._editor_state = "CLEAN"
        self._save_status = "已载入 · 暂无未保存更改"
        self._workspace: ProjectWorkspaceService | None = None
        self._ai_drawer_open = False
        self._active_nav = "writing"
        self._reduce_motion = False

    # -- project -------------------------------------------------------------

    @Property(str, notify=project_changed)
    def projectTitle(self) -> str:
        if self._workspace is not None:
            return self._workspace.summary().title
        return "雾港来信"

    @Property(str, notify=project_changed)
    def projectPath(self) -> str:
        if self._workspace is not None:
            return str(self._workspace.summary().root)
        return "C:\\Users\\demo\\Novels\\雾港来信"

    @Property(str, notify=project_changed)
    def projectSource(self) -> str:
        return "project" if self._workspace is not None else "mock"

    @Property(int, notify=project_changed)
    def chapterCount(self) -> int:
        return len(self._chapters)

    @Property(QObject, notify=project_changed)
    def chapters(self) -> ChapterListModel:
        return self._chapters_model

    @Property(QObject, constant=True)
    def suggestions(self) -> SuggestionListModel:
        return self._suggestions_model

    @Property(str, notify=chapter_changed)
    def currentChapterId(self) -> str:
        return self._chapters[self._current_index].id

    @Property(str, notify=chapter_changed)
    def currentChapterTitle(self) -> str:
        return self._chapters[self._current_index].title

    @Property(str, notify=chapter_changed)
    def currentChapterBody(self) -> str:
        return self._body_text

    @Property(int, notify=chapter_changed)
    def currentChapterWordCount(self) -> int:
        return count_words(self._body_text)

    @Property(str, notify=chapter_changed)
    def currentWordCountText(self) -> str:
        return format_word_count(count_words(self._body_text))

    @Property(str, notify=chapter_changed)
    def currentVolumeTitle(self) -> str:
        chapter_id = self._chapters[self._current_index].id
        volume = next(
            (v for v in self._volumes if chapter_id in {c.id for c in v.chapters}),
            None,
        )
        return volume.title if volume is not None else ""

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
        return self._generation_config.mode.value

    @Property(str, notify=generation_config_changed)
    def generationAuditPolicy(self) -> str:
        return self._generation_config.audit_policy.value

    @Property(str, notify=usage_changed)
    def usageInputOutputText(self) -> str:
        input_text = self._token_text(self._usage.input_tokens)
        output_text = self._token_text(self._usage.output_tokens)
        return f"{input_text} / {output_text}"

    @Property(str, notify=usage_changed)
    def usageCostText(self) -> str:
        if self._usage.cost is None or (
            self._usage.call_count == 0 and self._usage.cost == 0
        ):
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
        chapter = self._chapters_model.chapter_at_row(row)
        if chapter is None:
            return
        self._current_index = next(
            index
            for index, candidate in enumerate(self._chapters)
            if candidate.id == chapter.id
        )
        self._load_current_chapter_document()
        self.chapter_changed.emit()
        self.editor_state_changed.emit()

    @Slot(str)
    def editorTextChanged(self, text: str) -> None:
        if self._editor_state == "CONFLICT":
            self._body_text = text
            self.chapter_changed.emit()
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
        self._editor_state = "DIRTY"
        self._save_status = "有未保存更改"
        self.editor_state_changed.emit()
        self.chapter_changed.emit()

    @Slot()
    def requestSave(self) -> None:
        if self._workspace is not None:
            if self._editor_state == "CLEAN":
                self._save_status = f"已保存 · 修订 {self._revision}"
                self.editor_state_changed.emit()
                return
            chapter_id = self._chapters[self._current_index].id
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
        self.editor_state_changed.emit()

    @Slot()
    def requestDraft(self) -> None:
        if self._workspace is not None:
            self._request_project_draft()
            return
        chapter_title = self._chapters[self._current_index].title
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
        if nav_id not in _NAV_IDS or nav_id == self._active_nav:
            return
        self._active_nav = nav_id
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
        try:
            mode = CreationMode(value)
        except ValueError:
            return
        if mode == self._generation_config.mode:
            return
        self._generation_config = GenerationConfig(
            target_words=self._generation_config.target_words,
            output_token_limit=self._generation_config.output_token_limit,
            mode=mode,
            audit_policy=self._generation_config.audit_policy,
        )
        self.generation_config_changed.emit()

    @Slot(str)
    def setGenerationAuditPolicy(self, value: str) -> None:
        try:
            policy = AuditPolicy(value)
        except ValueError:
            return
        if policy == self._generation_config.audit_policy:
            return
        self._generation_config = GenerationConfig(
            target_words=self._generation_config.target_words,
            output_token_limit=self._generation_config.output_token_limit,
            mode=self._generation_config.mode,
            audit_policy=policy,
        )
        self.generation_config_changed.emit()

    @Slot(str)
    def setChapterFilter(self, query: str) -> None:
        self._chapters_model.set_filter(query)

    @Slot(str, result=str)
    def openProject(self, root: str) -> str:
        """Open a real project read-only. Returns an error message or empty."""
        try:
            workspace = ProjectWorkspaceService()
            workspace.open_project(Path(root))
        except Exception as exc:  # noqa: BLE001 - surfaced as UI copy, logged by caller if needed
            return f"打开项目失败：{exc}"
        if self._workspace is not None:
            self._workspace.close_project()
        self._workspace = workspace
        self._volumes = self._volumes_from_workspace()
        self._chapters = tuple(
            chapter for volume in self._volumes for chapter in volume.chapters
        )
        self._chapters_model.set_volumes(self._volumes)
        if self._chapters:
            self._current_index = 0
            self._load_current_chapter_document()
        self.project_changed.emit()
        self.chapter_changed.emit()
        self.editor_state_changed.emit()
        return ""

    @Slot(QUrl, result=str)
    def openProjectFromUrl(self, url: QUrl | str) -> str:
        """FolderDialog helper: convert a QML URL to a local path."""
        local_path = url.toLocalFile() if isinstance(url, QUrl) else url
        return self.openProject(local_path)

    @Slot()
    def closeProject(self) -> None:
        if self._workspace is not None:
            self._workspace.close_project()
            self._workspace = None
        self._volumes = _mock_volumes()
        self._chapters = tuple(
            chapter for volume in self._volumes for chapter in volume.chapters
        )
        self._chapters_model.set_volumes(self._volumes)
        self._current_index = 0
        self._load_current_chapter_document()
        self._refresh_overview()
        self.project_changed.emit()
        self.chapter_changed.emit()
        self.editor_state_changed.emit()

    def _load_current_chapter_document(self) -> None:
        self._clear_draft_review_state()
        self._selected_character = None
        self._journey_model.set_items(())
        self.character_detail_changed.emit()
        self._selected_memory = None
        self.memory_detail_changed.emit()
        chapter = self._chapters[self._current_index]
        if self._workspace is not None:
            workspace = self._workspace.load_chapter(chapter.id)
            self._body_text = workspace.content
            self._revision = workspace.revision
            self._refresh_overview()
        else:
            self._body_text = chapter.body
            self._revision = chapter.revision
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
        self._overview = readonly_overview_counts(
            self._workspace.project,
            self._chapters[self._current_index].id,
        )
        self._readonly_views = readonly_views(
            self._workspace.project,
            self._chapters[self._current_index].id,
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
        self.editor_state_changed.emit()
        self.chapter_changed.emit()

    def _rebuild_draft_diff(self) -> None:
        visible = tuple(
            block
            for block in self._diff_blocks
            if block.block_id not in self._diff_ignored
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
