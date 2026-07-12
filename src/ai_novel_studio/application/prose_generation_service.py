from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from threading import Event, Lock
from typing import Protocol

from ai_novel_studio.domain.generation import GenerationStatus
from ai_novel_studio.infrastructure.llm import (
    LLMMessage,
    LLMStreamEvent,
    LLMUsage,
    StreamEventKind,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.storage.checkpoint_repository import CheckpointRepository
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository


class ProseGateway(Protocol):
    def stream(
        self,
        purpose: TaskPurpose,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        *,
        temperature: float = 0.7,
    ) -> Iterator[LLMStreamEvent]: ...


class PreparedMessageProvider(Protocol):
    def messages_for(self, run_id: str) -> tuple[LLMMessage, ...]: ...


class ProseEventKind(StrEnum):
    DRAFT_CHUNK = "draft_chunk"
    REASONING = "reasoning"
    USAGE = "usage"
    RUN_CHANGED = "run_changed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProseGenerationEvent:
    kind: ProseEventKind
    text: str = ""
    usage: LLMUsage | None = None
    status: GenerationStatus | None = None
    message: str = ""


_SAFE_FAILURE = "正文生成失败，请检查连接与模型设置"
_SAFE_PARTIAL_FAILURE = "正文生成中断，已保留收到的内容"
_SAFE_CANCELLED = "正文生成已取消，已保留收到的内容"


class ProseGenerationService:
    def __init__(
        self,
        gateway: ProseGateway,
        messages: PreparedMessageProvider,
        runs: GenerationRepository,
        checkpoints: CheckpointRepository,
        *,
        checkpoint_characters: int = 2000,
    ) -> None:
        if checkpoint_characters <= 0:
            raise ValueError("检查点字符阈值必须大于零")
        self.gateway = gateway
        self.messages = messages
        self.runs = runs
        self.checkpoints = checkpoints
        self.checkpoint_characters = checkpoint_characters
        self._cancellations: dict[str, Event] = {}
        self._cancellation_lock = Lock()

    def cancel(self, run_id: str) -> None:
        with self._cancellation_lock:
            token = self._cancellations.setdefault(run_id, Event())
            token.set()

    def stream(self, run_id: str) -> Iterator[ProseGenerationEvent]:
        run = self.runs.get(run_id)
        messages = self.messages.messages_for(run_id)
        token = self._token(run_id)
        if token.is_set():
            failed = self.runs.transition(
                run.id,
                GenerationStatus.READY,
                GenerationStatus.FAILED,
                failure_code="USER_CANCELLED",
                failure_message="用户在请求开始前取消生成",
            )
            yield ProseGenerationEvent(
                ProseEventKind.RUN_CHANGED, status=failed.status
            )
            self._clear_token(run_id)
            return

        streaming = self.runs.transition(
            run.id, GenerationStatus.READY, GenerationStatus.STREAMING
        )
        yield ProseGenerationEvent(
            ProseEventKind.RUN_CHANGED, status=streaming.status
        )
        buffer = ""
        saved_length = 0
        usage: LLMUsage | None = None
        reached_terminal_event = False
        try:
            provider_events = self.gateway.stream(
                TaskPurpose.PROSE_GENERATION,
                messages,
                run.output_token_limit,
            )
            for event in provider_events:
                if token.is_set():
                    yield from self._interrupt(
                        run.id,
                        buffer,
                        saved_length,
                        usage,
                        code="USER_CANCELLED",
                        safe_message=_SAFE_CANCELLED,
                    )
                    reached_terminal_event = True
                    return
                if event.usage is not None:
                    usage = event.usage
                if event.kind == StreamEventKind.TEXT:
                    if not event.text:
                        continue
                    buffer += event.text
                    yield ProseGenerationEvent(
                        ProseEventKind.DRAFT_CHUNK, text=event.text
                    )
                    if len(buffer) - saved_length >= self.checkpoint_characters:
                        self.checkpoints.append(run.id, buffer)
                        saved_length = len(buffer)
                elif event.kind == StreamEventKind.REASONING:
                    if event.text:
                        yield ProseGenerationEvent(
                            ProseEventKind.REASONING, text=event.text
                        )
                elif event.kind == StreamEventKind.USAGE:
                    if usage is not None:
                        yield ProseGenerationEvent(ProseEventKind.USAGE, usage=usage)
                elif event.kind == StreamEventKind.PARTIAL_FAILURE:
                    yield from self._interrupt(
                        run.id,
                        buffer,
                        saved_length,
                        usage,
                        code="PARTIAL_FAILURE",
                        safe_message=_SAFE_PARTIAL_FAILURE,
                    )
                    reached_terminal_event = True
                    return
                elif event.kind == StreamEventKind.COMPLETED:
                    if not buffer:
                        yield from self._interrupt(
                            run.id,
                            buffer,
                            saved_length,
                            usage,
                            code="EMPTY_OUTPUT",
                            safe_message=_SAFE_FAILURE,
                        )
                        reached_terminal_event = True
                        return
                    if len(buffer) > saved_length:
                        self.checkpoints.append(run.id, buffer, finish_reason="completed")
                    completed = self.runs.transition(
                        run.id,
                        GenerationStatus.STREAMING,
                        GenerationStatus.COMPLETED,
                        **_usage_fields(usage),
                    )
                    yield ProseGenerationEvent(
                        ProseEventKind.RUN_CHANGED, status=completed.status
                    )
                    reached_terminal_event = True
                    return
            if not reached_terminal_event:
                yield from self._interrupt(
                    run.id,
                    buffer,
                    saved_length,
                    usage,
                    code="STREAM_ENDED",
                    safe_message=_SAFE_PARTIAL_FAILURE if buffer else _SAFE_FAILURE,
                )
        except Exception:
            yield from self._interrupt(
                run.id,
                buffer,
                saved_length,
                usage,
                code="STREAM_ERROR",
                safe_message=_SAFE_FAILURE,
            )
        finally:
            self._clear_token(run_id)

    def _interrupt(
        self,
        run_id: str,
        buffer: str,
        saved_length: int,
        usage: LLMUsage | None,
        *,
        code: str,
        safe_message: str,
    ) -> Iterator[ProseGenerationEvent]:
        durable_text = saved_length > 0
        if buffer and len(buffer) > saved_length:
            try:
                self.checkpoints.append(run_id, buffer, finish_reason=code.lower())
                durable_text = True
            except Exception:
                durable_text = saved_length > 0
        target = GenerationStatus.PARTIAL if durable_text else GenerationStatus.FAILED
        changed = self.runs.transition(
            run_id,
            GenerationStatus.STREAMING,
            target,
            failure_code=code,
            failure_message=safe_message,
            **_usage_fields(usage),
        )
        yield ProseGenerationEvent(ProseEventKind.RUN_CHANGED, status=changed.status)
        yield ProseGenerationEvent(ProseEventKind.FAILED, message=safe_message)

    def _token(self, run_id: str) -> Event:
        with self._cancellation_lock:
            return self._cancellations.setdefault(run_id, Event())

    def _clear_token(self, run_id: str) -> None:
        with self._cancellation_lock:
            self._cancellations.pop(run_id, None)


def _usage_fields(usage: LLMUsage | None) -> dict[str, object]:
    if usage is None:
        return {}
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
    }
