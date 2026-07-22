from dataclasses import dataclass
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from ai_novel_studio.application.memory_workspace_service import (
    MemoryWorkspaceRecord,
    MemoryWorkspaceService,
)
from ai_novel_studio.application.view_assertion_service import (
    LegacyReaderViewCandidate,
)
from ai_novel_studio.domain.memory import KnowledgeState
from ai_novel_studio.domain.view import ViewAssertion
from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.pages.memory_window import MemoryWindow


class _WorkspaceGateway:
    def load_before(self, chapter_id: str) -> tuple[MemoryWorkspaceRecord, ...]:
        assert chapter_id == "chapter-2"
        return ()

    def update_content(
        self, record_id: str, content: str, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        raise AssertionError("Reader View tests do not edit memory records")

    def promote(self, record_id: str, expected_revision: int) -> MemoryWorkspaceRecord:
        raise AssertionError("Reader View tests do not promote memory records")

    def request_model_retry(
        self, record_id: str, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        raise AssertionError("Reader View tests do not retry memory records")

    def update_fields(
        self,
        record_id: str,
        source_type: str,
        fields: dict[str, str],
        expected_revision: int,
    ) -> MemoryWorkspaceRecord:
        raise AssertionError("Reader View tests do not edit structured records")


@dataclass
class _ReaderViewService:
    candidates: tuple[LegacyReaderViewCandidate, ...]
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def list_legacy_reader_view_candidates(
        self,
    ) -> tuple[LegacyReaderViewCandidate, ...]:
        return self.candidates

    def replace_legacy_reader_event(
        self,
        *,
        legacy_event_id: str,
        subject_id: str,
        content: str,
        confirmed_by_user: bool,
    ) -> ViewAssertion:
        self.calls.append(
            {
                "legacy_event_id": legacy_event_id,
                "subject_id": subject_id,
                "content": content,
                "confirmed_by_user": confirmed_by_user,
            }
        )
        if self.error is not None:
            raise self.error
        self.candidates = ()
        return cast(ViewAssertion, object())


def _candidate() -> LegacyReaderViewCandidate:
    return LegacyReaderViewCandidate(
        event_id="reader-event-1",
        title="匿名来信",
        detail="读者看见守夜人投递匿名来信。",
        state=KnowledgeState.KNOWN,
        source_chapter_id="chapter-1",
        source_chapter_title="开篇",
        narrative_visible_from_sequence=2,
    )


def _bind(window: MemoryWindow, service: _ReaderViewService) -> None:
    window.bind(
        MemoryWorkspaceService(_WorkspaceGateway()),
        "chapter-2",
        reader_view_service=service,
        reader_view_subjects=(("character-1", "艾瑞克"),),
    )


def test_reader_view_operation_binds_one_candidate_and_active_character(
    qtbot: QtBot,
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    _bind(window, _ReaderViewService((_candidate(),)))

    assert window.reader_view_candidate_selector.count() == 1
    assert "匿名来信" in window.reader_view_candidate_selector.currentText()
    assert window.reader_view_subject_selector.currentData() == "character-1"
    assert "开篇" in window.reader_view_source_label.text()
    assert window.reader_view_content_editor.toPlainText() == "读者看见守夜人投递匿名来信。"
    assert window.reader_view_convert_button.isEnabled()


def test_reader_view_operation_does_not_write_when_confirmation_is_cancelled(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = _ReaderViewService((_candidate(),))
    _bind(window, service)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    qtbot.mouseClick(window.reader_view_convert_button, Qt.MouseButton.LeftButton)

    assert service.calls == []


def test_reader_view_operation_confirms_one_write_and_refreshes_candidates(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = _ReaderViewService((_candidate(),))
    _bind(window, service)
    window.reader_view_content_editor.setPlainText("用户修订后的读者可见信息。")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(window.reader_view_convert_button, Qt.MouseButton.LeftButton)

    assert service.calls == [
        {
            "legacy_event_id": "reader-event-1",
            "subject_id": "character-1",
            "content": "用户修订后的读者可见信息。",
            "confirmed_by_user": True,
        }
    ]
    assert window.reader_view_candidate_selector.count() == 0
    assert window.reader_view_convert_button.isEnabled() is False


def test_reader_view_operation_disables_empty_states_and_shows_service_errors(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    _bind(window, _ReaderViewService(()))

    assert window.reader_view_convert_button.isEnabled() is False
    assert "没有" in window.reader_view_status_label.text()

    service = _ReaderViewService((_candidate(),), error=ValueError("旧知识已被接管"))
    _bind(window, service)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    qtbot.mouseClick(window.reader_view_convert_button, Qt.MouseButton.LeftButton)

    assert "旧知识已被接管" in window.reader_view_status_label.text()
