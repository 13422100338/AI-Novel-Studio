from __future__ import annotations

from threading import Event

import pytest
from PySide6.QtCore import QThread
from pytestqt.qtbot import QtBot

from ai_novel_studio.application.view_assertion_batch_extraction_service import (
    ViewAssertionBatchExtractionReport,
    ViewAssertionBatchProgress,
)
from ai_novel_studio.ui.qt.view_assertion_batch_extraction_coordinator import (
    ViewAssertionBatchExtractionCoordinator,
)


class _BatchService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def extract_chapters(self, chapter_ids, *, progress=None, should_cancel=None):  # type: ignore[no-untyped-def]
        self.calls.append(chapter_ids)
        assert progress is not None
        progress(ViewAssertionBatchProgress(1, 1, chapter_ids[0], "Chapter one"))
        return ViewAssertionBatchExtractionReport((), False)


class _BlockingBatchService:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.cancel_observed = False

    def extract_chapters(self, chapter_ids, *, progress=None, should_cancel=None):  # type: ignore[no-untyped-def]
        self.started.set()
        assert should_cancel is not None
        self.release.wait(timeout=2)
        self.cancel_observed = should_cancel()
        return ViewAssertionBatchExtractionReport((), self.cancel_observed)


class _FailingBatchService:
    def extract_chapters(self, chapter_ids, *, progress=None, should_cancel=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("model failure")


class _ThreadRecordingCoordinator(ViewAssertionBatchExtractionCoordinator):
    def __init__(self, service) -> None:  # type: ignore[no-untyped-def]
        self.completed_on_coordinator_thread: bool | None = None
        self.failed_on_coordinator_thread: bool | None = None
        super().__init__(service)

    def _complete(self, report: ViewAssertionBatchExtractionReport) -> None:
        self.completed_on_coordinator_thread = QThread.currentThread() == self.thread()
        super()._complete(report)

    def _fail(self) -> None:
        self.failed_on_coordinator_thread = QThread.currentThread() == self.thread()
        super()._fail()


def test_batch_coordinator_runs_off_ui_thread_and_forwards_chapter_progress(
    qtbot: QtBot,
) -> None:
    service = _BatchService()
    coordinator = ViewAssertionBatchExtractionCoordinator(service)  # type: ignore[arg-type]
    progress: list[ViewAssertionBatchProgress] = []
    reports: list[ViewAssertionBatchExtractionReport] = []
    coordinator.progress_changed.connect(progress.append)
    coordinator.completed.connect(reports.append)

    coordinator.start(("chapter-1",))

    qtbot.waitUntil(lambda: bool(reports), timeout=3_000)
    assert service.calls == [("chapter-1",)]
    assert progress == [ViewAssertionBatchProgress(1, 1, "chapter-1", "Chapter one")]
    assert coordinator.is_running is False


def test_batch_coordinator_rejects_duplicate_start_and_cancels_cooperatively(
    qtbot: QtBot,
) -> None:
    service = _BlockingBatchService()
    coordinator = ViewAssertionBatchExtractionCoordinator(service)  # type: ignore[arg-type]
    reports: list[ViewAssertionBatchExtractionReport] = []
    coordinator.completed.connect(reports.append)

    coordinator.start(("chapter-1", "chapter-2"))
    qtbot.waitUntil(service.started.is_set, timeout=3_000)
    with pytest.raises(RuntimeError):
        coordinator.start(("chapter-1",))
    coordinator.cancel()
    service.release.set()

    qtbot.waitUntil(lambda: bool(reports), timeout=3_000)
    assert service.cancel_observed is True
    assert reports[0].cancelled is True
    assert coordinator.is_running is False


def test_batch_coordinator_handles_completion_and_failure_on_its_qt_thread(
    qtbot: QtBot,
) -> None:
    completed = _ThreadRecordingCoordinator(_BatchService())  # type: ignore[arg-type]
    reports: list[ViewAssertionBatchExtractionReport] = []
    completed.completed.connect(reports.append)

    completed.start(("chapter-1",))

    qtbot.waitUntil(lambda: bool(reports), timeout=3_000)
    assert completed.completed_on_coordinator_thread is True

    failed = _ThreadRecordingCoordinator(_FailingBatchService())  # type: ignore[arg-type]
    failures: list[str] = []
    failed.failed.connect(failures.append)

    failed.start(("chapter-1",))

    qtbot.waitUntil(lambda: bool(failures), timeout=3_000)
    assert failed.failed_on_coordinator_thread is True
    assert failed.is_running is False
