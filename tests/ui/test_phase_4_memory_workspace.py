from dataclasses import replace
from threading import Event
from time import perf_counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from ai_novel_studio.application.memory_workspace_service import (
    MemoryWorkspaceField,
    MemoryWorkspaceRecord,
    MemoryWorkspaceService,
)
from ai_novel_studio.domain.memory import Authority, MemoryStatus, ReviewStatus
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


def test_memory_window_binds_metadata_edit_and_explicit_promotion(qtbot: QtBot) -> None:
    gateway = UiGateway()
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    window.bind(MemoryWorkspaceService(gateway), "chapter-2")

    assert window.tabs.tabText(0) == "压缩前文"
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
