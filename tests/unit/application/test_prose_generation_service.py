from collections.abc import Callable, Iterator
from pathlib import Path

from ai_novel_studio.application.prose_generation_service import (
    ProseEventKind,
    ProseGenerationService,
)
from ai_novel_studio.core.context.context_manifest import (
    ContextManifest,
    ContextManifestRepository,
    create_manifest_id,
    utc_now,
)
from ai_novel_studio.domain.generation import CreationMode, GenerationStatus
from ai_novel_studio.infrastructure.llm import (
    LLMMessage,
    LLMStreamEvent,
    LLMUsage,
    StreamEventKind,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.llm.provider_adapter import ProviderRequestError
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.checkpoint_repository import CheckpointRepository
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class MessageProvider:
    def __init__(self, messages: tuple[LLMMessage, ...]) -> None:
        self.messages = messages
        self.requested: list[str] = []

    def messages_for(self, run_id: str) -> tuple[LLMMessage, ...]:
        self.requested.append(run_id)
        return self.messages


class FakeGateway:
    def __init__(
        self,
        events: tuple[LLMStreamEvent, ...] = (),
        *,
        error: BaseException | None = None,
        after_event: Callable[[int], None] | None = None,
    ) -> None:
        self.events = events
        self.error = error
        self.after_event = after_event
        self.calls: list[tuple[TaskPurpose, tuple[LLMMessage, ...], int]] = []

    def stream(
        self,
        purpose: TaskPurpose,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        *,
        temperature: float = 0.7,
    ) -> Iterator[LLMStreamEvent]:
        self.calls.append((purpose, messages, output_token_limit))
        for index, event in enumerate(self.events):
            yield event
            if self.after_event is not None:
                self.after_event(index)
        if self.error is not None:
            raise self.error


def _ready_run(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "正文流测试")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(volume.id, "当前章", "1")
    runs = GenerationRepository(project)
    run = runs.create_preparing(
        chapter_id=chapter.id,
        mode=CreationMode.BASIC,
        brief_id=None,
        brief_revision=None,
        model_provider_id="provider-1",
        model_id="writer-1",
        output_token_limit=32_000,
        prompt_version="prose-v1",
    )
    manifest = ContextManifest(
        create_manifest_id(),
        chapter.id,
        run.id,
        90_000,
        run.output_token_limit,
        1000,
        (),
        (),
        (),
        utc_now(),
    )
    ContextManifestRepository(project).save(manifest)
    run = runs.mark_ready(run.id, manifest.id)
    checkpoints = CheckpointRepository(project, runs)
    messages = (
        LLMMessage("system", "只写正文"),
        LLMMessage("user", "写出雨夜相认"),
    )
    provider = MessageProvider(messages)
    return project, run, runs, checkpoints, messages, provider


def test_stream_forwards_exact_prompt_and_limit_once_and_separates_reasoning(
    tmp_path: Path,
) -> None:
    _, run, runs, checkpoints, messages, provider = _ready_run(tmp_path)
    usage = LLMUsage(1200, 800, 600, 100)
    gateway = FakeGateway(
        (
            LLMStreamEvent(StreamEventKind.REASONING, text="先安排冲突"),
            LLMStreamEvent(StreamEventKind.TEXT, text="第一段"),
            LLMStreamEvent(StreamEventKind.TEXT, text="第二段"),
            LLMStreamEvent(StreamEventKind.USAGE, usage=usage),
            LLMStreamEvent(StreamEventKind.COMPLETED),
        )
    )
    service = ProseGenerationService(
        gateway, provider, runs, checkpoints, checkpoint_characters=5
    )

    events = tuple(service.stream(run.id))

    assert gateway.calls == [(TaskPurpose.PROSE_GENERATION, messages, 32_000)]
    assert provider.requested == [run.id]
    assert [event.text for event in events if event.kind == ProseEventKind.DRAFT_CHUNK] == [
        "第一段",
        "第二段",
    ]
    assert [event.text for event in events if event.kind == ProseEventKind.REASONING] == [
        "先安排冲突"
    ]
    completed = runs.get(run.id)
    assert completed.status == GenerationStatus.COMPLETED
    assert completed.input_tokens == 1200
    assert completed.cached_input_tokens == 600
    latest = checkpoints.latest(run.id)
    assert latest is not None
    assert checkpoints.read(latest.id) == "第一段第二段"


def test_partial_failure_with_text_preserves_draft_but_without_text_fails(
    tmp_path: Path,
) -> None:
    _, run, runs, checkpoints, _, provider = _ready_run(tmp_path / "with-text")
    gateway = FakeGateway(
        (
            LLMStreamEvent(StreamEventKind.TEXT, text="已经收到的正文"),
            LLMStreamEvent(StreamEventKind.PARTIAL_FAILURE, error="sk-secret-detail"),
        )
    )
    service = ProseGenerationService(gateway, provider, runs, checkpoints)

    events = tuple(service.stream(run.id))

    partial = runs.get(run.id)
    assert partial.status == GenerationStatus.PARTIAL
    assert "secret" not in (partial.failure_message or "")
    latest = checkpoints.latest(run.id)
    assert latest is not None
    assert checkpoints.read(latest.id) == "已经收到的正文"
    assert any(event.kind == ProseEventKind.FAILED for event in events)

    _, empty_run, empty_runs, empty_checkpoints, _, empty_provider = _ready_run(
        tmp_path / "without-text"
    )
    empty_service = ProseGenerationService(
        FakeGateway((LLMStreamEvent(StreamEventKind.PARTIAL_FAILURE, error="raw"),)),
        empty_provider,
        empty_runs,
        empty_checkpoints,
    )
    tuple(empty_service.stream(empty_run.id))
    assert empty_runs.get(empty_run.id).status == GenerationStatus.FAILED
    assert empty_checkpoints.latest(empty_run.id) is None


def test_provider_exception_is_sanitized_and_never_retried_by_service(
    tmp_path: Path,
) -> None:
    _, run, runs, checkpoints, _, provider = _ready_run(tmp_path)
    gateway = FakeGateway(error=ProviderRequestError("sk-live-sensitive"))
    service = ProseGenerationService(gateway, provider, runs, checkpoints)

    events = tuple(service.stream(run.id))

    failed = runs.get(run.id)
    assert failed.status == GenerationStatus.FAILED
    assert len(gateway.calls) == 1
    assert "sensitive" not in (failed.failure_message or "")
    assert [event.message for event in events if event.kind == ProseEventKind.FAILED] == [
        "正文生成失败，请检查连接与模型设置"
    ]


def test_cancellation_keeps_received_text_and_starts_no_second_request(
    tmp_path: Path,
) -> None:
    _, run, runs, checkpoints, _, provider = _ready_run(tmp_path)
    service: ProseGenerationService

    def cancel_after_first(index: int) -> None:
        if index == 0:
            service.cancel(run.id)

    gateway = FakeGateway(
        (
            LLMStreamEvent(StreamEventKind.TEXT, text="保留这一段"),
            LLMStreamEvent(StreamEventKind.TEXT, text="不应处理"),
        ),
        after_event=cancel_after_first,
    )
    service = ProseGenerationService(gateway, provider, runs, checkpoints)

    tuple(service.stream(run.id))

    assert len(gateway.calls) == 1
    assert runs.get(run.id).status == GenerationStatus.PARTIAL
    latest = checkpoints.latest(run.id)
    assert latest is not None
    assert checkpoints.read(latest.id) == "保留这一段"
