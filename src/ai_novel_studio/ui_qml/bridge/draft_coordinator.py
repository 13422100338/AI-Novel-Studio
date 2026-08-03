"""Frontend-owned background coordinator for draft generation.

Frontend Wave F5 moves model streaming off the UI thread without importing the
legacy QWidget adapters (``ai_novel_studio.ui.qt``). The coordinator mirrors the
existing project pattern: a ``QThreadPool`` job consumes the prose stream and
emits signals back to the UI thread. Cancellation is cooperative through the
draft port's ``cancel`` (which sets the prose service cancellation token), so a
running job finishes quickly with a CANCELLED outcome.

The coordinator owns no persistence and no business rules; it only orchestrates
the framework-neutral ``DraftPort``.
"""

from __future__ import annotations

from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ai_novel_studio.ui_qml.bridge.draft_port import DraftPort

DRAFT_IDLE = "IDLE"
DRAFT_QUEUED = "QUEUED"
DRAFT_GENERATING = "GENERATING"
DRAFT_COMPLETED = "COMPLETED"
DRAFT_FAILED = "FAILED"
DRAFT_CANCELLED = "CANCELLED"


class _GenerateJob(QRunnable):
    def __init__(
        self,
        port: DraftPort,
        run_id: str,
        cancel_token: Event,
        coordinator: DraftCoordinator,
    ) -> None:
        super().__init__()
        self.port = port
        self.run_id = run_id
        self.cancel_token = cancel_token
        self.coordinator = coordinator

    def run(self) -> None:
        # Signals emitted from a pool thread are automatically queued to the
        # coordinator's thread (the UI thread) by Qt.
        self.coordinator.status_changed.emit(DRAFT_GENERATING)
        try:
            text, error = self.port.generate(self.run_id)
        except Exception as exc:  # noqa: BLE001 - surfaced as UI copy
            if self.cancel_token.is_set():
                self.coordinator.cancelled.emit("生成已取消")
                self.coordinator.status_changed.emit(DRAFT_CANCELLED)
            else:
                self.coordinator.draft_failed.emit(str(exc))
                self.coordinator.status_changed.emit(DRAFT_FAILED)
            return
        if self.cancel_token.is_set():
            self.coordinator.cancelled.emit("生成已取消，已保留收到的内容")
            self.coordinator.status_changed.emit(DRAFT_CANCELLED)
            return
        if error:
            self.coordinator.draft_failed.emit(error)
            self.coordinator.status_changed.emit(DRAFT_FAILED)
            return
        self.coordinator.draft_ready.emit(text)
        self.coordinator.status_changed.emit(DRAFT_COMPLETED)


class DraftCoordinator(QObject):
    """Run draft generation in a background thread with cooperative cancel."""

    status_changed = Signal(str)
    draft_ready = Signal(str)
    draft_failed = Signal(str)
    cancelled = Signal(str)

    def __init__(
        self,
        port: DraftPort | None,
        parent: QObject | None = None,
        *,
        pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)
        self.port = port
        self._pool = pool or QThreadPool.globalInstance()
        self._status = DRAFT_IDLE
        self._cancel_token: Event | None = None
        self._run_id: str | None = None
        self.status_changed.connect(self._set_status)

    @property
    def status(self) -> str:
        return self._status

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def is_running(self) -> bool:
        return self._status in {DRAFT_QUEUED, DRAFT_GENERATING}

    @Slot(str)
    def start_generate(self, run_id: str) -> None:
        if self.is_running:
            self.draft_failed.emit("已有生成任务正在进行")
            return
        if self.port is None:
            self.draft_failed.emit("模型生成端口未配置")
            self.status_changed.emit(DRAFT_FAILED)
            return
        self._run_id = run_id
        self._cancel_token = Event()
        self._status = DRAFT_QUEUED
        self.status_changed.emit(DRAFT_QUEUED)
        job = _GenerateJob(self.port, run_id, self._cancel_token, self)
        self._pool.start(job)

    @Slot()
    def cancel(self) -> None:
        if not self.is_running or self._run_id is None:
            return
        token = self._cancel_token
        if token is not None:
            token.set()
        if self.port is not None:
            self.port.cancel(self._run_id)

    @Slot(str)
    def _set_status(self, status: str) -> None:
        self._status = status
        if status in {DRAFT_COMPLETED, DRAFT_FAILED, DRAFT_CANCELLED}:
            self._run_id = None
            self._cancel_token = None
