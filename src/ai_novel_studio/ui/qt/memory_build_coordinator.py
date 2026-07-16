from __future__ import annotations

from collections.abc import Callable
from threading import Event
from typing import Protocol

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ai_novel_studio.application.manuscript_memory_build_service import (
    ManuscriptMemoryBuildReport,
    MemoryBuildProgress,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class MemoryBuildPort(Protocol):
    def build_all(
        self,
        project: ProjectRepository,
        *,
        progress: Callable[[MemoryBuildProgress], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ManuscriptMemoryBuildReport: ...


class _MemoryBuildJob(QRunnable):
    def __init__(
        self,
        function: Callable[[], ManuscriptMemoryBuildReport],
        success: Callable[[ManuscriptMemoryBuildReport], None],
        failure: Callable[[BaseException], None],
    ) -> None:
        super().__init__()
        self.function = function
        self.success = success
        self.failure = failure

    @Slot()
    def run(self) -> None:
        try:
            self.success(self.function())
        except BaseException as error:
            self.failure(error)


class MemoryBuildCoordinator(QObject):
    progress_changed = Signal(object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: MemoryBuildPort,
        parent: QObject | None = None,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.thread_pool = thread_pool or QThreadPool.globalInstance()
        self._cancel = Event()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, project: ProjectRepository) -> None:
        if self._running:
            raise RuntimeError("记忆整理任务已经在运行")
        self._cancel.clear()
        self._running = True
        self.thread_pool.start(
            _MemoryBuildJob(
                lambda: self.service.build_all(
                    project,
                    progress=self.progress_changed.emit,
                    should_cancel=self._cancel.is_set,
                ),
                self._complete,
                self._fail,
            )
        )

    def cancel(self) -> None:
        self._cancel.set()

    def _complete(self, report: ManuscriptMemoryBuildReport) -> None:
        self._running = False
        self.completed.emit(report)

    def _fail(self, error: BaseException) -> None:
        self._running = False
        message = (str(error).strip() or type(error).__name__)[:500]
        self.failed.emit(message)
