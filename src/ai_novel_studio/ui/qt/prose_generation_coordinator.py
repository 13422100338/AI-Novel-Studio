from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Protocol

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ai_novel_studio.application.prose_generation_service import (
    ProseEventKind,
    ProseGenerationEvent,
)


class ProseGenerationPort(Protocol):
    def stream(self, run_id: str) -> Iterator[ProseGenerationEvent]: ...

    def cancel(self, run_id: str) -> None: ...


class _ProseJob(QRunnable):
    def __init__(
        self,
        events: Callable[[], Iterator[ProseGenerationEvent]],
        event_callback: Callable[[ProseGenerationEvent], None],
        completed: Callable[[], None],
        failure: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.events = events
        self.event_callback = event_callback
        self.completed = completed
        self.failure = failure

    @Slot()
    def run(self) -> None:
        try:
            for event in self.events():
                self.event_callback(event)
        except BaseException:
            self.failure("正文生成失败，请检查连接与模型设置")
        finally:
            self.completed()


class ProseGenerationCoordinator(QObject):
    draft_chunk = Signal(str)
    reasoning_chunk = Signal(str)
    usage_changed = Signal(object)
    run_changed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        service: ProseGenerationPort,
        parent: QObject | None = None,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.thread_pool = thread_pool or QThreadPool.globalInstance()

    def start(self, run_id: str) -> None:
        self.thread_pool.start(
            _ProseJob(
                lambda: self.service.stream(run_id),
                self._forward,
                self.finished.emit,
                self.failed.emit,
            )
        )

    def cancel(self, run_id: str) -> None:
        self.service.cancel(run_id)

    def _forward(self, event: ProseGenerationEvent) -> None:
        if event.kind == ProseEventKind.DRAFT_CHUNK:
            self.draft_chunk.emit(event.text)
        elif event.kind == ProseEventKind.REASONING:
            self.reasoning_chunk.emit(event.text)
        elif event.kind == ProseEventKind.USAGE and event.usage is not None:
            self.usage_changed.emit(event.usage)
        elif event.kind == ProseEventKind.RUN_CHANGED and event.status is not None:
            self.run_changed.emit(event.status)
        elif event.kind == ProseEventKind.FAILED:
            self.failed.emit(event.message)
