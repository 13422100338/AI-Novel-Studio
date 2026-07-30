from __future__ import annotations

from collections.abc import Callable
from threading import Event
from typing import Protocol

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from ai_novel_studio.application.view_assertion_batch_extraction_service import (
    ViewAssertionBatchExtractionReport,
    ViewAssertionBatchProgress,
)


class ViewAssertionBatchExtractionPort(Protocol):
    def extract_chapters(
        self,
        chapter_ids: tuple[str, ...],
        *,
        progress: Callable[[ViewAssertionBatchProgress], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ViewAssertionBatchExtractionReport: ...


class _BatchExtractionJob(QRunnable):
    def __init__(
        self,
        function: Callable[[], ViewAssertionBatchExtractionReport],
        success: Callable[[ViewAssertionBatchExtractionReport], None],
        failure: Callable[[], None],
    ) -> None:
        super().__init__()
        self._function = function
        self._success = success
        self._failure = failure

    @Slot()
    def run(self) -> None:
        try:
            self._success(self._function())
        except BaseException:
            self._failure()


class ViewAssertionBatchExtractionCoordinator(QObject):
    progress_changed = Signal(object)
    completed = Signal(object)
    failed = Signal(str)
    _job_progressed = Signal(object)
    _job_completed = Signal(object)
    _job_failed = Signal()

    def __init__(
        self,
        service: ViewAssertionBatchExtractionPort,
        parent: QObject | None = None,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._cancel = Event()
        self._running = False
        self._job_progressed.connect(
            self._forward_progress,
            Qt.ConnectionType.QueuedConnection,
        )
        self._job_completed.connect(
            self._complete,
            Qt.ConnectionType.QueuedConnection,
        )
        self._job_failed.connect(
            self._fail,
            Qt.ConnectionType.QueuedConnection,
        )

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, chapter_ids: tuple[str, ...]) -> None:
        if self._running:
            raise RuntimeError("批量 View Assertion 提取任务正在运行")
        self._cancel.clear()
        self._running = True
        self._thread_pool.start(
            _BatchExtractionJob(
                lambda: self._service.extract_chapters(
                    chapter_ids,
                    progress=self._job_progressed.emit,
                    should_cancel=self._cancel.is_set,
                ),
                self._job_completed.emit,
                self._job_failed.emit,
            )
        )

    def cancel(self) -> None:
        self._cancel.set()

    def _forward_progress(self, progress: ViewAssertionBatchProgress) -> None:
        self.progress_changed.emit(progress)

    def _complete(self, report: ViewAssertionBatchExtractionReport) -> None:
        self._running = False
        self.completed.emit(report)

    def _fail(self) -> None:
        self._running = False
        self.failed.emit("批量 View Assertion 候选提取失败，请重试。")
