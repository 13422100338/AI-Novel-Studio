from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ai_novel_studio.application.memory_workspace_service import (
    MemoryBulkPromotionResult,
    MemoryWorkspaceService,
)


class _PromotionJob(QRunnable):
    def __init__(
        self,
        function: Callable[[], MemoryBulkPromotionResult],
        success: Callable[[MemoryBulkPromotionResult], None],
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


class MemoryPromotionCoordinator(QObject):
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: MemoryWorkspaceService,
        parent: QObject | None = None,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.thread_pool = thread_pool or QThreadPool.globalInstance()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            raise RuntimeError("批量晋升任务已经在运行")
        self._running = True
        self.thread_pool.start(
            _PromotionJob(
                lambda: self.service.promote_all(progress=self.progress_changed.emit),
                self._complete,
                self._fail,
            )
        )

    def _complete(self, result: MemoryBulkPromotionResult) -> None:
        self._running = False
        self.completed.emit(result)

    def _fail(self, error: BaseException) -> None:
        self._running = False
        self.failed.emit((str(error).strip() or type(error).__name__)[:500])
