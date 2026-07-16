from dataclasses import replace
from threading import Event
from time import perf_counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from ai_novel_studio.application.chapter_context_pin_service import (
    ChapterContextPinService,
)
from ai_novel_studio.application.memory_workspace_service import (
    MemoryWorkspaceField,
    MemoryWorkspaceRecord,
    MemoryWorkspaceService,
)
from ai_novel_studio.application.project_guidance_service import ProjectGuidanceService
from ai_novel_studio.application.project_memory_workspace_gateway import (
    ProjectMemoryWorkspaceGateway,
)
from ai_novel_studio.domain.memory import (
    Authority,
    MemoryStatus,
    ReviewStatus,
    SummaryLevel,
)
from ai_novel_studio.infrastructure.storage.chapter_context_pin_repository import (
    ChapterContextPinRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
    ProjectGuidanceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository
from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.pages.memory_window import MemoryWindow


class UiGateway:
    def __init__(self) -> None:
        self.record = MemoryWorkspaceRecord(
            id="summary-1",
            category="压缩前文",
            title="第一章摘要",
            content="模型候选摘要",
            source_type="SUMMARY",
            source_chapter_id="chapter-1",
            source_revision=4,
            source_hash="source-hash",
            authority=Authority.MODEL_EXTRACTED,
            review_status=ReviewStatus.REVIEW,
            status=MemoryStatus.REVIEW,
            revision=1,
            editable=True,
            promotable=True,
        )
        self.saved_content = ""
        self.promote_count = 0
        self.retry_count = 0

    def load_before(self, chapter_id: str) -> tuple[MemoryWorkspaceRecord, ...]:
        assert chapter_id == "chapter-2"
        return (self.record,)

    def update_content(
        self, record_id: str, content: str, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        assert (record_id, expected_revision) == ("summary-1", 1)
        self.saved_content = content
        self.record = replace(self.record, content=content, revision=2)
        return self.record

    def promote(self, record_id: str, expected_revision: int) -> MemoryWorkspaceRecord:
        assert (record_id, expected_revision) == ("summary-1", 2)
        self.promote_count += 1
        self.record = replace(
            self.record,
            review_status=ReviewStatus.APPROVED,
            status=MemoryStatus.CURRENT,
            revision=3,
            promotable=False,
        )
        return self.record

    def request_model_retry(
        self, record_id: str, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        assert (record_id, expected_revision) == ("summary-1", 3)
        self.retry_count += 1
        self.record = replace(
            self.record,
            source_type="SUMMARY_FALLBACK",
            review_status=ReviewStatus.REVIEW,
            status=MemoryStatus.REVIEW,
            revision=4,
            promotable=False,
        )
        return self.record

    def update_fields(
        self,
        record_id: str,
        source_type: str,
        fields: dict[str, str],
        expected_revision: int,
    ) -> MemoryWorkspaceRecord:
        raise AssertionError("summary test must not use structured editing")


class StructuredUiGateway(UiGateway):
    def __init__(self) -> None:
        super().__init__()
        self.record = replace(
            self.record,
            id="state-1",
            category="人物状态",
            title="人物状态：林默",
            content="心理：警惕",
            source_type="CHARACTER_STATE",
            revision=0,
            fields=(MemoryWorkspaceField("psychology", "心理状态", "警惕", multiline=True),),
        )
        self.saved_fields: dict[str, str] = {}

    def update_fields(
        self,
        record_id: str,
        source_type: str,
        fields: dict[str, str],
        expected_revision: int,
    ) -> MemoryWorkspaceRecord:
        assert (record_id, source_type, expected_revision) == (
            "state-1",
            "CHARACTER_STATE",
            0,
        )
        self.saved_fields = fields
        self.record = replace(
            self.record,
            content=f"心理：{fields['psychology']}",
            review_status=ReviewStatus.APPROVED,
            promotable=False,
            fields=(
                MemoryWorkspaceField(
                    "psychology", "心理状态", fields["psychology"], multiline=True
                ),
            ),
        )
        return self.record


class BlockingUiGateway(UiGateway):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def promote(self, record_id: str, expected_revision: int) -> MemoryWorkspaceRecord:
        self.started.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("test release timeout")
        return super().promote(record_id, expected_revision)


class CanonUiGateway(UiGateway):
    _GROUP_TITLES = {
        "WORLD": "世界观",
        "CHARACTER_IDENTITY": "人物身份背景",
        "ITEM_ABILITY": "重要物品、能力与兵器",
        "ORGANIZATION": "组织、团队与成员",
    }

    def __init__(self) -> None:
        super().__init__()
        base = replace(
            self.record,
            category="正典事实",
            source_type="CANON",
            source_chapter_id=None,
            source_revision=None,
            revision=0,
            promotable=False,
            fields=(
                MemoryWorkspaceField(
                    "category",
                    "所属正典卡片",
                    "世界观",
                    choices=tuple(self._GROUP_TITLES.values()),
                ),
            ),
        )
        self.records = (
            replace(
                base,
                id="canon-world",
                title="正典：旧港地理",
                content="旧港位于王国南部。",
                group_key="WORLD",
            ),
            replace(
                base,
                id="canon-character",
                title="正典：林默身份",
                content="林默是档案员。",
                group_key="CHARACTER_IDENTITY",
            ),
            replace(
                base,
                id="canon-item",
                title="正典：潮汐钥匙",
                content="潮汐钥匙能够开启旧港密室。",
                group_key="ITEM_ABILITY",
            ),
            replace(
                base,
                id="canon-organization",
                title="正典：守潮会",
                content="守潮会负责看守旧港。",
                group_key="ORGANIZATION",
            ),
        )

    def load_before(self, chapter_id: str) -> tuple[MemoryWorkspaceRecord, ...]:
        assert chapter_id == "chapter-2"
        return self.records

    def update_fields(
        self,
        record_id: str,
        source_type: str,
        fields: dict[str, str],
        expected_revision: int,
    ) -> MemoryWorkspaceRecord:
        assert source_type == "CANON"
        assert expected_revision == 0
        group_key = next(
            key for key, title in self._GROUP_TITLES.items() if title == fields["category"]
        )
        current = next(record for record in self.records if record.id == record_id)
        updated = replace(
            current,
            group_key=group_key,
            fields=(replace(current.fields[0], value=fields["category"]),),
        )
        self.records = tuple(
            updated if record.id == record_id else record for record in self.records
        )
        return updated


def test_memory_window_binds_metadata_edit_and_explicit_promotion(qtbot: QtBot) -> None:
    gateway = UiGateway()
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    window.bind(MemoryWorkspaceService(gateway), "chapter-2")

    assert window.tabs.tabText(0) == "小说最高提示"
    assert window.tabs.tabText(1) == "压缩前文"
    window.tabs.setCurrentIndex(1)
    assert window.editors["压缩前文"].toPlainText() == "模型候选摘要"
    assert "chapter-1" in window.metadata_label.text()
    assert "REVIEW" in window.metadata_label.text()
    window.editors["压缩前文"].setPlainText("人工修订摘要")
    qtbot.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.promote_button, Qt.MouseButton.LeftButton)

    assert gateway.saved_content == "人工修订摘要"
    assert gateway.promote_count == 1
    assert "APPROVED" in window.metadata_label.text()
    assert window.promote_button.isEnabled() is False


def test_memory_window_groups_canon_facts_into_four_cards(qtbot: QtBot) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    window.bind(MemoryWorkspaceService(CanonUiGateway()), "chapter-2")

    groups = window.group_selectors["正典事实"]
    assert [groups.itemText(index) for index in range(groups.count())] == [
        "世界观",
        "人物身份背景",
        "重要物品、能力与兵器",
        "组织、团队与成员",
    ]
    groups.setCurrentText("重要物品、能力与兵器")

    selector = window.selectors["正典事实"]
    assert selector.count() == 1
    assert selector.currentData() == "canon-item"
    assert window.editors["正典事实"].toPlainText() == "潮汐钥匙能够开启旧港密室。"


def test_memory_window_moves_canon_fact_after_manual_category_save(qtbot: QtBot) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    window.bind(MemoryWorkspaceService(CanonUiGateway()), "chapter-2")

    category = window.field_widgets["正典事实"]["category"]
    category.setCurrentText("重要物品、能力与兵器")  # type: ignore[attr-defined]
    qtbot.mouseClick(window.save_button, Qt.MouseButton.LeftButton)

    groups = window.group_selectors["正典事实"]
    assert groups.currentData() == "ITEM_ABILITY"
    assert window.selectors["正典事实"].currentData() == "canon-world"


def test_memory_window_edits_highest_system_prompt_only_by_explicit_manual_save(
    qtbot: QtBot, tmp_path
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Guidance UI")
    guidance_service = ProjectGuidanceService(ProjectGuidanceRepository(project))
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    window.bind(
        MemoryWorkspaceService(UiGateway()),
        "chapter-2",
        guidance_service=guidance_service,
    )
    window.tabs.setCurrentIndex(0)

    assert window.guidance_editor.toPlainText() == ""
    assert window.guidance_save_button.isEnabled() is False
    window.guidance_editor.setPlainText("核心目的：写人物如何承担选择的代价。")
    assert window.guidance_save_button.isEnabled() is True
    window.guidance_save_button.click()

    assert guidance_service.read_highest_system_prompt() == "核心目的：写人物如何承担选择的代价。"
    assert window.guidance_save_button.isEnabled() is False
    assert "人工保存" in window.guidance_status_label.text()


def test_memory_window_preserves_unsaved_guidance_during_same_project_rebind(
    qtbot: QtBot, tmp_path
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Guidance Draft")
    guidance_service = ProjectGuidanceService(ProjectGuidanceRepository(project))
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = MemoryWorkspaceService(UiGateway())
    window.bind(service, "chapter-2", guidance_service=guidance_service)
    window.tabs.setCurrentIndex(0)

    window.guidance_editor.insertPlainText("尚未保存的最高提示")
    assert window.guidance_editor.document().isModified()

    window.bind(service, "chapter-2", guidance_service=guidance_service)

    assert window.guidance_editor.toPlainText() == "尚未保存的最高提示"
    assert window.guidance_save_button.isEnabled()
    assert "保留" in window.guidance_status_label.text()


def test_memory_window_can_undo_model_summary_promotion_for_retry(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    gateway = UiGateway()
    gateway.record = replace(
        gateway.record,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
        revision=3,
        promotable=False,
    )
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    window.bind(MemoryWorkspaceService(gateway), "chapter-2")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    assert window.retry_button.isEnabled() is True
    qtbot.mouseClick(window.retry_button, Qt.MouseButton.LeftButton)

    assert gateway.retry_count == 1
    assert window.retry_button.text() == "本章已等待重新整理"
    assert window.retry_button.isEnabled() is False
    assert "正常章节不会重新调用模型" in window.metadata_label.text()


def test_memory_window_can_add_and_remove_reviewed_memory_for_current_chapter(
    qtbot: QtBot, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "Opening", "1", "body")
    target = chapters.create_chapter(volume.id, "Target", "2")
    SummaryRepository(project).add_human_summary(
        SummaryLevel.CHAPTER,
        first.id,
        "Reviewed summary",
        (first.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    window.bind(
        MemoryWorkspaceService(ProjectMemoryWorkspaceGateway(project)),
        "__all__",
        pin_service=ChapterContextPinService(ChapterContextPinRepository(project)),
        target_chapter_id=target.id,
    )

    qtbot.mouseClick(window.pin_button, Qt.MouseButton.LeftButton)
    assert "已强制加入" in window.pin_button.text()
    assert "已加入当前章" in window.metadata_label.text()

    qtbot.mouseClick(window.pin_button, Qt.MouseButton.LeftButton)
    assert window.pin_button.text().startswith("＋")
    assert "移除" in window.metadata_label.text()


def test_memory_window_saves_structured_character_fields(qtbot: QtBot) -> None:
    gateway = StructuredUiGateway()
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    window.bind(MemoryWorkspaceService(gateway), "chapter-2")

    psychology = window.field_widgets["人物状态"]["psychology"]
    psychology.setPlainText("警惕但坚定")  # type: ignore[attr-defined]
    qtbot.mouseClick(window.save_button, Qt.MouseButton.LeftButton)

    assert gateway.saved_fields == {"psychology": "警惕但坚定"}
    assert "APPROVED" in window.metadata_label.text()


def test_memory_window_can_confirm_and_promote_all_candidates(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    gateway = UiGateway()
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    window.bind(MemoryWorkspaceService(gateway), "chapter-2")
    window.editors["压缩前文"].setPlainText("人工修订摘要")
    qtbot.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(window.promote_all_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: gateway.promote_count == 1)
    qtbot.waitUntil(lambda: not window._bulk_promotion_running())
    assert window.promote_all_button.isEnabled() is False
    assert "成功晋升 1 条" in window.metadata_label.text()


def test_bulk_promotion_runs_off_the_ui_thread(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    gateway = BlockingUiGateway()
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    window.bind(MemoryWorkspaceService(gateway), "chapter-2")
    window.editors["压缩前文"].setPlainText("人工修订摘要")
    qtbot.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    started_at = perf_counter()
    qtbot.mouseClick(window.promote_all_button, Qt.MouseButton.LeftButton)
    elapsed = perf_counter() - started_at

    assert elapsed < 1
    qtbot.waitUntil(gateway.started.is_set)
    assert window.tabs.isEnabled() is False
    gateway.release.set()
    qtbot.waitUntil(lambda: gateway.promote_count == 1)
    qtbot.waitUntil(lambda: window.tabs.isEnabled())
