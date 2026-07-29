from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from ai_novel_studio.application.memory_workspace_service import (
    MemoryWorkspaceRecord,
    MemoryWorkspaceService,
)
from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.pages.memory_window import MemoryWindow


class _WorkspaceGateway:
    def load_before(self, chapter_id: str) -> tuple[MemoryWorkspaceRecord, ...]:
        return ()

    def update_content(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError

    def promote(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError

    def request_model_retry(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError

    def update_fields(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError


@dataclass
class _ExtractionService:
    result_count: int = 2
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.calls: list[str] = []

    def extract_current_chapter(self, chapter_id: str) -> tuple[object, ...]:
        self.calls.append(chapter_id)
        if self.error is not None:
            raise self.error
        return tuple(object() for _ in range(self.result_count))


def _bind(window: MemoryWindow, service: _ExtractionService | None) -> None:
    window.bind(
        MemoryWorkspaceService(_WorkspaceGateway()),
        "chapter-1",
        target_chapter_id="chapter-1",
        view_assertion_extraction_service=service,
    )


def test_view_assertion_extraction_is_disabled_without_service(qtbot: QtBot) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    _bind(window, None)

    assert window.view_assertion_extract_button.isEnabled() is False


def test_view_assertion_extraction_cancel_does_not_call_service(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = _ExtractionService()
    _bind(window, service)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    qtbot.mouseClick(window.view_assertion_extract_button, Qt.MouseButton.LeftButton)

    assert service.calls == []


def test_view_assertion_extraction_confirms_refreshes_and_shows_count(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = _ExtractionService()
    _bind(window, service)
    changed: list[bool] = []
    window.view_assertion_review_changed.connect(lambda: changed.append(True))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(window.view_assertion_extract_button, Qt.MouseButton.LeftButton)

    assert service.calls == ["chapter-1"]
    assert changed == [True]
    assert "2" in window.view_assertion_extract_status_label.text()


def test_view_assertion_extraction_shows_bounded_error(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = _ExtractionService(error=ValueError("invalid candidate"))
    _bind(window, service)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(window.view_assertion_extract_button, Qt.MouseButton.LeftButton)

    assert "提取失败" in window.view_assertion_extract_status_label.text()
    assert "invalid candidate" not in window.view_assertion_extract_status_label.text()


def test_view_assertion_extraction_error_does_not_expose_model_details(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = _ExtractionService(
        error=ValueError("sk-test-secret <chapter_text>raw model response</chapter_text>")
    )
    _bind(window, service)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(window.view_assertion_extract_button, Qt.MouseButton.LeftButton)

    status = window.view_assertion_extract_status_label.text()
    assert "sk-test-secret" not in status
    assert "raw model response" not in status
