from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Protocol

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ai_novel_studio.application.model_tasks import (
    NormalizedBrief,
    StyleAuditResult,
)
from ai_novel_studio.infrastructure.llm import (
    ContractValidationError,
    LLMMessage,
    LLMStreamEvent,
    MissingCredentialError,
    MissingModelRouteError,
    ProviderError,
    StreamEventKind,
)


class ModelTaskPort(Protocol):
    def stream_chat(
        self,
        conversation: tuple[LLMMessage, ...],
        manuscript_excerpt: str,
        output_token_limit: int,
    ) -> Iterator[LLMStreamEvent]: ...

    def draft_chapter_requirement(
        self,
        conversation: tuple[LLMMessage, ...],
        manuscript_excerpt: str,
        output_token_limit: int,
    ) -> str: ...

    def normalize_brief(self, source: str, output_token_limit: int) -> NormalizedBrief: ...

    def audit_style(
        self,
        manuscript: str,
        rules: tuple[str, ...],
        output_token_limit: int,
    ) -> StyleAuditResult: ...


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
    task_failed = Signal(str)

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
                self.chat_finished.emit,
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
            lambda value: self.requirement_ready.emit(str(value)),
        )

    def start_brief(self, source: str, output_token_limit: int) -> None:
        self._start_result(
            lambda: self.service.normalize_brief(source, output_token_limit),
            self.brief_ready.emit,
        )

    def start_audit(
        self,
        manuscript: str,
        rules: tuple[str, ...],
        output_token_limit: int,
    ) -> None:
        self._start_result(
            lambda: self.service.audit_style(manuscript, rules, output_token_limit),
            self.audit_ready.emit,
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
