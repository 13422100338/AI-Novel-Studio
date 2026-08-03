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
from ai_novel_studio.ui_qml.bridge.dtos import ChapterDto, SuggestionDto, VolumeDto
from ai_novel_studio.ui_qml.bridge.models.chapter_list_model import ChapterListModel
from ai_novel_studio.ui_qml.bridge.models.suggestion_list_model import SuggestionListModel
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

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
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
        prefix = "" if not self._body_text.strip() else "\n\n"
        self._body_text = self._body_text + prefix + item.body
        self._suggestions_model.remove_item(row)
        self._editor_state = "DIRTY"
        self._save_status = "有未保存更改（已采用建议）"
        self.editor_state_changed.emit()
        self.chapter_changed.emit()

    @Slot(int)
    def discardSuggestion(self, row: int) -> None:
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

    @Slot(bool)
    def setReduceMotion(self, enabled: bool) -> None:
        if self._reduce_motion == enabled:
            return
        self._reduce_motion = enabled
        self.reduce_motion_changed.emit()

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
        self.project_changed.emit()
        self.chapter_changed.emit()
        self.editor_state_changed.emit()

    def _load_current_chapter_document(self) -> None:
        chapter = self._chapters[self._current_index]
        if self._workspace is not None:
            workspace = self._workspace.load_chapter(chapter.id)
            self._body_text = workspace.content
            self._revision = workspace.revision
        else:
            self._body_text = chapter.body
            self._revision = chapter.revision
        self._saved_body = self._body_text
        self._editor_state = "CLEAN"
        self._save_status = "已载入 · 暂无未保存更改"

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
