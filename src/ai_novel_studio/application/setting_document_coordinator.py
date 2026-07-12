from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Job(QRunnable):
    def __init__(
        self,
        function: Callable[[], object],
        success: Callable[[object], None],
        failure: Callable[[BaseException], None],
    ) -> None:
        super().__init__()
        self._function = function
        self._success = success
        self._failure = failure

    @Slot()
    def run(self) -> None:
        try:
            self._success(self._function())
        except BaseException as error:
            self._failure(error)


class SettingDocumentCoordinator(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, function: Callable[[], object]) -> None:
        if self._running:
            raise RuntimeError("设定资料整理任务已经在运行")
        self._running = True
        QThreadPool.globalInstance().start(_Job(function, self._complete, self._fail))

    def _complete(self, result: object) -> None:
        self._running = False
        self.completed.emit(result)

    def _fail(self, error: BaseException) -> None:
        self._running = False
        self.failed.emit((str(error).strip() or type(error).__name__)[:500])
