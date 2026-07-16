from __future__ import annotations

from collections.abc import Callable, Iterator

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ai_novel_studio.application.model_task_port import ModelTaskPort
from ai_novel_studio.infrastructure.llm import (
    ContractValidationError,
    LLMMessage,
    LLMStreamEvent,
    MissingCredentialError,
    MissingModelRouteError,
    ProviderError,
    StreamEventKind,
)


class _ResultJob(QRunnable):
    def __init__(
        self,
        function: Callable[[], object],
        success: Callable[[object], None],
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


class _ChatJob(QRunnable):
    def __init__(
        self,
        events: Callable[[], Iterator[LLMStreamEvent]],
        chunk: Callable[[str], None],
        completed: Callable[[], None],
        failure: Callable[[BaseException], None],
    ) -> None:
        super().__init__()
        self.events = events
        self.chunk = chunk
        self.completed = completed
        self.failure = failure

    @Slot()
    def run(self) -> None:
        try:
            for event in self.events():
                if event.kind == StreamEventKind.TEXT:
                    self.chunk(event.text)
                elif event.kind == StreamEventKind.PARTIAL_FAILURE:
                    self.failure(RuntimeError(event.error))
            self.completed()
        except BaseException as error:
            self.failure(error)


class ModelTaskCoordinator(QObject):
    chat_chunk = Signal(str)
    chat_finished = Signal()
    requirement_ready = Signal(str)
    brief_ready = Signal(object)
    audit_ready = Signal(object)
    chat_summary_ready = Signal(object)
    task_failed = Signal(str)
    usage_changed = Signal(object)

    def __init__(
        self,
        service: ModelTaskPort,
        parent: QObject | None = None,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.thread_pool = thread_pool or QThreadPool.globalInstance()

    def start_chat(
        self,
        conversation: tuple[LLMMessage, ...],
        manuscript: str,
        output_token_limit: int,
    ) -> None:
        self.thread_pool.start(
            _ChatJob(
                lambda: self.service.stream_chat(
                    conversation, manuscript, output_token_limit
                ),
                self.chat_chunk.emit,
                self._finish_chat,
                self._emit_failure,
            )
        )

    def start_requirement(
        self,
        conversation: tuple[LLMMessage, ...],
        manuscript: str,
        output_token_limit: int,
    ) -> None:
        self._start_result(
            lambda: self.service.draft_chapter_requirement(
                conversation, manuscript, output_token_limit
            ),
            lambda value: self._emit_result(self.requirement_ready.emit, str(value)),
        )

    def start_brief(self, source: str, output_token_limit: int) -> None:
        self._start_result(
            lambda: self.service.normalize_brief(source, output_token_limit),
            lambda value: self._emit_result(self.brief_ready.emit, value),
        )

    def start_audit(
        self,
        manuscript: str,
        rules: tuple[str, ...],
        output_token_limit: int,
    ) -> None:
        self._start_result(
            lambda: self.service.audit_style(manuscript, rules, output_token_limit),
            lambda value: self._emit_result(self.audit_ready.emit, value),
        )

    def start_chat_summary(
        self,
        existing_summary: str,
        transcript: str,
        output_token_limit: int,
    ) -> None:
        self._start_result(
            lambda: self.service.summarize_chat(
                existing_summary, transcript, output_token_limit
            ),
            lambda value: self._emit_result(self.chat_summary_ready.emit, value),
        )

    def _start_result(
        self,
        function: Callable[[], object],
        success: Callable[[object], None],
    ) -> None:
        self.thread_pool.start(_ResultJob(function, success, self._emit_failure))

    def _emit_failure(self, error: BaseException) -> None:
        safe_types = (
            ContractValidationError,
            MissingCredentialError,
            MissingModelRouteError,
            ProviderError,
        )
        if isinstance(error, safe_types):
            self.task_failed.emit(str(error))
        else:
            self.task_failed.emit("模型任务失败，请检查连接与模型设置")

    def _finish_chat(self) -> None:
        self.chat_finished.emit()
        self._emit_usage()

    def _emit_result(self, emitter: Callable[[object], None], value: object) -> None:
        emitter(value)
        self._emit_usage()

    def _emit_usage(self) -> None:
        snapshot_method = getattr(self.service, "usage_snapshot", None)
        if callable(snapshot_method):
            self.usage_changed.emit(snapshot_method())
