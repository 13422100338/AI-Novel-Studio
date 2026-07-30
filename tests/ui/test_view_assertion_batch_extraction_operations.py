from __future__ import annotations

from dataclasses import dataclass
from threading import Event

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from ai_novel_studio.application.memory_workspace_service import (
    MemoryWorkspaceRecord,
    MemoryWorkspaceService,
)
from ai_novel_studio.application.view_assertion_batch_extraction_service import (
    ViewAssertionBatchChapterResult,
    ViewAssertionBatchChapterStatus,
    ViewAssertionBatchExtractionReport,
    ViewAssertionBatchProgress,
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
class _BatchService:
    error: Exception | None = None
    report: ViewAssertionBatchExtractionReport | None = None

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def extract_chapters(self, chapter_ids, *, progress=None, should_cancel=None):  # type: ignore[no-untyped-def]
        self.calls.append(chapter_ids)
        if self.error is not None:
            raise self.error
        assert progress is not None
        progress(ViewAssertionBatchProgress(1, len(chapter_ids), chapter_ids[0], "Chapter one"))
        if self.report is not None:
            return self.report
        return ViewAssertionBatchExtractionReport(
            tuple(
                ViewAssertionBatchChapterResult(
                    chapter_id=chapter_id,
                    chapter_title=chapter_id,
                    status=ViewAssertionBatchChapterStatus.CREATED,
                    created_count=1,
                    message="safe",
                )
                for chapter_id in chapter_ids
            ),
            False,
        )


class _BlockingBatchService(_BatchService):
    def __post_init__(self) -> None:
        super().__post_init__()
        self.started = Event()
        self.release = Event()

    def extract_chapters(self, chapter_ids, *, progress=None, should_cancel=None):  # type: ignore[no-untyped-def]
        self.calls.append(chapter_ids)
        self.started.set()
        assert progress is not None
        progress(ViewAssertionBatchProgress(1, len(chapter_ids), chapter_ids[0], "Chapter one"))
        self.release.wait(timeout=2)
        assert should_cancel is not None
        return ViewAssertionBatchExtractionReport((), should_cancel())


_CHAPTERS = (("chapter-1", "Chapter one"), ("chapter-2", "Chapter two"))


def _bind(window: MemoryWindow, service: _BatchService | None, chapters=_CHAPTERS) -> None:
    window.bind(
        MemoryWorkspaceService(_WorkspaceGateway()),
        "chapter-1",
        view_assertion_batch_extraction_service=service,
        view_assertion_batch_chapters=chapters,
    )


def _check(window: MemoryWindow, index: int) -> None:
    window.view_assertion_batch_selector.item(index).setCheckState(
        Qt.CheckState.Checked
    )


def test_batch_extraction_is_disabled_without_a_bound_service(qtbot: QtBot) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    _bind(window, None)

    assert window.view_assertion_batch_start_button.isEnabled() is False


def test_batch_extraction_confirmation_cancel_does_not_call_model_service(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = _BatchService()
    _bind(window, service)
    _check(window, 0)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    qtbot.mouseClick(window.view_assertion_batch_start_button, Qt.MouseButton.LeftButton)

    assert service.calls == []


def test_batch_extraction_confirms_reports_progress_and_refreshes_review_list(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = _BatchService()
    _bind(window, service)
    _check(window, 0)
    _check(window, 1)
    refreshed: list[bool] = []
    window.view_assertion_review_changed.connect(lambda: refreshed.append(True))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(window.view_assertion_batch_start_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: refreshed == [True], timeout=3_000)
    assert service.calls == [("chapter-1", "chapter-2")]
    assert "2" in window.view_assertion_batch_status_label.text()
    assert window.view_assertion_batch_selector.isEnabled()


def test_batch_extraction_cancel_keeps_current_result_and_stops_future_work(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = _BlockingBatchService()
    _bind(window, service)
    _check(window, 0)
    _check(window, 1)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(window.view_assertion_batch_start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(service.started.is_set, timeout=3_000)
    assert window.view_assertion_batch_selector.isEnabled() is False
    assert window.view_assertion_batch_start_button.isEnabled() is False
    assert "1 / 2" in window.view_assertion_batch_status_label.text()
    qtbot.mouseClick(window.view_assertion_batch_cancel_button, Qt.MouseButton.LeftButton)
    service.release.set()

    qtbot.waitUntil(
        lambda: "已取消" in window.view_assertion_batch_status_label.text(),
        timeout=3_000,
    )
    assert service.calls == [("chapter-1", "chapter-2")]
    assert window.view_assertion_batch_selector.isEnabled()


def test_batch_extraction_failure_does_not_expose_raw_model_details(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    service = _BatchService(
        error=RuntimeError("sk-test-secret <chapter_text>raw model response</chapter_text>")
    )
    _bind(window, service)
    _check(window, 0)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(window.view_assertion_batch_start_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(
        lambda: "失败" in window.view_assertion_batch_status_label.text(),
        timeout=3_000,
    )
    status = window.view_assertion_batch_status_label.text()
    assert "sk-test-secret" not in status
    assert "raw model response" not in status


def test_batch_extraction_final_report_distinguishes_each_safe_outcome(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    report = ViewAssertionBatchExtractionReport(
        (
            ViewAssertionBatchChapterResult(
                "chapter-1",
                "Chapter one",
                ViewAssertionBatchChapterStatus.CREATED,
                2,
                "sk-test-secret <chapter_text>raw model response</chapter_text>",
            ),
            ViewAssertionBatchChapterResult(
                "chapter-2",
                "Chapter two",
                ViewAssertionBatchChapterStatus.SKIPPED,
                0,
                "sk-test-secret <chapter_text>raw model response</chapter_text>",
            ),
            ViewAssertionBatchChapterResult(
                "chapter-3",
                "Chapter three",
                ViewAssertionBatchChapterStatus.FAILED,
                0,
                "sk-test-secret <chapter_text>raw model response</chapter_text>",
            ),
        ),
        True,
    )
    _bind(window, _BatchService(report=report))
    _check(window, 0)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(window.view_assertion_batch_start_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(
        lambda: "已取消" in window.view_assertion_batch_status_label.text(),
        timeout=3_000,
    )
    status = window.view_assertion_batch_status_label.text()
    assert "2" in status
    assert "跳过 1" in status
    assert "失败 1" in status
    outcome_text = "\n".join(
        window.view_assertion_batch_outcome_list.item(index).text()
        for index in range(window.view_assertion_batch_outcome_list.count())
    )
    assert window.view_assertion_batch_outcome_list.count() == 4
    assert "Chapter one" in outcome_text
    assert "Chapter two" in outcome_text
    assert "Chapter three" in outcome_text
    assert "已取消" in outcome_text
    assert "sk-test-secret" not in outcome_text
    assert "raw model response" not in outcome_text


def test_batch_extraction_outcome_list_clears_on_normal_rebind(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    report = ViewAssertionBatchExtractionReport(
        (
            ViewAssertionBatchChapterResult(
                "chapter-1",
                "Chapter one",
                ViewAssertionBatchChapterStatus.CREATED,
                1,
                "safe",
            ),
        ),
        False,
    )
    service = _BatchService(report=report)
    _bind(window, service)
    _check(window, 0)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(window.view_assertion_batch_start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window.view_assertion_batch_outcome_list.count() == 1,
        timeout=3_000,
    )

    _bind(window, service)
    assert window.view_assertion_batch_outcome_list.count() == 0
    _bind(window, None)
    assert window.view_assertion_batch_outcome_list.count() == 0


def test_batch_extraction_refuses_an_eleventh_checked_chapter(qtbot: QtBot) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)
    chapters = tuple((f"chapter-{index}", f"Chapter {index}") for index in range(11))
    _bind(window, _BatchService(), chapters)

    for index in range(11):
        _check(window, index)

    checked = [
        item
        for index in range(window.view_assertion_batch_selector.count())
        if (item := window.view_assertion_batch_selector.item(index)).checkState()
        == Qt.CheckState.Checked
    ]
    assert len(checked) == 10
