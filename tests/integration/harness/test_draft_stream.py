from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.harness.artifacts import ArtifactKind, ArtifactStore, FileArtifactBackend
from ai_novel_studio.harness.cancel_token import CancellationError
from ai_novel_studio.harness.draft_stream import (
    ChapterDraftStreamService,
    DraftCandidateResult,
    DraftStreamFailureError,
)
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.model_adapter import HarnessModelAdapter
from ai_novel_studio.harness.model_roles import ModelRole, ModelRoleBinding
from ai_novel_studio.harness.run_engine import HarnessRunEngine, RunCancelledError
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMMessage,
    LLMStreamEvent,
    LLMUsage,
    StreamEventKind,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_MESSAGES = (LLMMessage("system", "写正文"), LLMMessage("user", "写第一章"))


class _FakeGateway:
    def __init__(self, events: tuple[LLMStreamEvent, ...]) -> None:
        self._events = events
        self.purpose: TaskPurpose | None = None
        self.output_token_limit: int | None = None

    def complete(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError("complete is not exercised by the draft stream")

    def stream(
        self,
        purpose: TaskPurpose,
        messages: object,
        output_token_limit: int,
        **kwargs: object,
    ):
        self.purpose = purpose
        self.output_token_limit = output_token_limit
        yield from self._events


def _engine(
    tmp_path: Path,
    gateway: _FakeGateway,
    *,
    checkpoint_chars: int = 4,
) -> HarnessRunEngine:
    project = ProjectRepository.create(tmp_path / "novel", "Draft stream")
    store = HarnessEventStore(HarnessEventRepository(project))
    artifacts = ArtifactStore(FileArtifactBackend(tmp_path))
    binding = ModelRoleBinding(
        ModelRole.CHAPTER_DRAFT, TaskPurpose.PROSE_GENERATION, "provider-1", "model-1"
    )
    adapter = HarnessModelAdapter("run-local", (binding,), gateway)
    service = ChapterDraftStreamService(
        store, artifacts, adapter, checkpoint_chars=checkpoint_chars
    )
    return HarnessRunEngine(project, draft_stream=service)


def _usage() -> LLMUsage:
    return LLMUsage(input_tokens=120, output_tokens=45)


def _stream_events() -> tuple[LLMStreamEvent, ...]:
    return (
        LLMStreamEvent(StreamEventKind.TEXT, text="abc"),
        LLMStreamEvent(StreamEventKind.REASONING, text="内部思考"),
        LLMStreamEvent(StreamEventKind.TEXT, text="defg"),
        LLMStreamEvent(StreamEventKind.TEXT, text="hi"),
        LLMStreamEvent(StreamEventKind.USAGE, usage=_usage()),
        LLMStreamEvent(StreamEventKind.COMPLETED, usage=_usage()),
    )


def test_stream_records_events_checkpoints_and_candidate(tmp_path: Path) -> None:
    gateway = _FakeGateway(_stream_events())
    engine = _engine(tmp_path, gateway)
    run, _ = engine.start("生成候选稿")

    result = engine.stream_draft(run.id, _MESSAGES, 1024)

    assert isinstance(result, DraftCandidateResult)
    assert result.text == "abcdefghi"
    assert result.usage == _usage()
    assert gateway.purpose is TaskPurpose.PROSE_GENERATION
    assert gateway.output_token_limit == 1024
    assert result.artifact.kind is ArtifactKind.DRAFT_CANDIDATE
    assert result.artifact.content.decode("utf-8") == "abcdefghi"
    assert engine.run_stage(run.id) is RunStage.DRAFT_SAVED

    events = engine.store.replay(run.id)
    assert [event.event_type for event in events] == [
        RunEventType.RUN_CREATED,
        RunEventType.CHAPTER_STREAM_STARTED,
        RunEventType.CHAPTER_STREAM_DELTA,
        RunEventType.CHAPTER_STREAM_DELTA,
        RunEventType.CHAPTER_STREAM_CHECKPOINT_SAVED,
        RunEventType.CHAPTER_STREAM_DELTA,
        RunEventType.CHAPTER_STREAM_COMPLETED,
    ]
    started = events[1]
    assert started.payload["output_token_limit"] == 1024
    assert started.payload["message_count"] == 2
    assert events[2].payload == {"delta_length": 3, "cumulative_chars": 3}
    assert events[3].payload == {"delta_length": 4, "cumulative_chars": 7}
    assert events[5].payload == {"delta_length": 2, "cumulative_chars": 9}
    assert all(
        event.schema_version == 2
        for event in events
        if event.event_type is RunEventType.CHAPTER_STREAM_DELTA
    )
    checkpoint = events[4]
    assert checkpoint.payload["character_count"] == 7
    checkpoint_artifact = ArtifactStore(FileArtifactBackend(tmp_path)).get(
        str(checkpoint.payload["artifact_id"])
    )
    assert checkpoint_artifact.kind is ArtifactKind.DRAFT_CHECKPOINT
    completed = events[6]
    assert completed.payload["artifact_id"] == result.artifact.artifact_id
    assert completed.payload["character_count"] == 9
    assert completed.payload["input_tokens"] == 120
    assert completed.payload["output_tokens"] == 45
    assert all(
        "内部思考" not in str(event.payload) for event in events
    )


def test_cancel_saves_partial_and_rejects_late_events(tmp_path: Path) -> None:
    class _CancellingGateway(_FakeGateway):
        def __init__(self, canceller: object) -> None:
            super().__init__(())
            self._canceller = canceller

        def stream(
            self,
            purpose: TaskPurpose,
            messages: object,
            output_token_limit: int,
            **kwargs: object,
        ):
            yield LLMStreamEvent(StreamEventKind.TEXT, text="abc")
            self._canceller()  # type: ignore[operator]
            yield LLMStreamEvent(StreamEventKind.TEXT, text="def")

    cancelled: list[None] = []

    def cancel_now() -> None:
        engine.cancel(run_id)
        cancelled.append(None)

    gateway = _CancellingGateway(cancel_now)
    engine = _engine(tmp_path, gateway)
    run, _ = engine.start("要取消的生成")
    run_id = run.id

    with pytest.raises(CancellationError):
        engine.stream_draft(run_id, _MESSAGES, 1024)

    assert cancelled
    assert engine.run_stage(run_id) is RunStage.CANCELLED
    events = engine.store.replay(run_id)
    assert [event.event_type for event in events] == [
        RunEventType.RUN_CREATED,
        RunEventType.CHAPTER_STREAM_STARTED,
        RunEventType.CHAPTER_STREAM_DELTA,
    ]
    partial_id = "sha256:" + hashlib.sha256(b"abc").hexdigest()
    partial = ArtifactStore(FileArtifactBackend(tmp_path)).get(partial_id)
    assert partial.kind is ArtifactKind.PARTIAL_DRAFT
    assert partial.content.decode("utf-8") == "abc"


def test_partial_failure_saves_partial_and_raises(tmp_path: Path) -> None:
    gateway = _FakeGateway(
        (
            LLMStreamEvent(StreamEventKind.TEXT, text="部分正文"),
            LLMStreamEvent(StreamEventKind.PARTIAL_FAILURE, error="连接中断"),
        )
    )
    engine = _engine(tmp_path, gateway, checkpoint_chars=8)
    run, _ = engine.start("会失败的生成")

    with pytest.raises(DraftStreamFailureError, match="连接中断"):
        engine.stream_draft(run.id, _MESSAGES, 1024)

    assert engine.run_stage(run.id) is RunStage.CREATED
    events = engine.store.replay(run.id)
    assert [event.event_type for event in events] == [
        RunEventType.RUN_CREATED,
        RunEventType.CHAPTER_STREAM_STARTED,
        RunEventType.CHAPTER_STREAM_DELTA,
    ]
    partial_id = "sha256:" + hashlib.sha256("部分正文".encode()).hexdigest()
    partial = ArtifactStore(FileArtifactBackend(tmp_path)).get(partial_id)
    assert partial.kind is ArtifactKind.PARTIAL_DRAFT
    assert partial.content.decode("utf-8") == "部分正文"


def test_empty_stream_raises_and_saves_nothing(tmp_path: Path) -> None:
    gateway = _FakeGateway(())
    engine = _engine(tmp_path, gateway)
    run, _ = engine.start("空流")

    with pytest.raises(DraftStreamFailureError, match="no prose"):
        engine.stream_draft(run.id, _MESSAGES, 1024)

    artifacts_dir = tmp_path / "artifacts"
    assert not any(artifacts_dir.glob("*.bin")) or not artifacts_dir.exists()


def test_checkpoint_identical_to_final_shares_artifact_id(tmp_path: Path) -> None:
    gateway = _FakeGateway(
        (
            LLMStreamEvent(StreamEventKind.TEXT, text="abc"),
            LLMStreamEvent(StreamEventKind.TEXT, text="def"),
            LLMStreamEvent(StreamEventKind.COMPLETED),
        )
    )
    engine = _engine(tmp_path, gateway, checkpoint_chars=6)
    run, _ = engine.start("检查点撞终点")

    result = engine.stream_draft(run.id, _MESSAGES, 1024)

    assert result.text == "abcdef"
    events = engine.store.replay(run.id)
    checkpoint = next(
        event
        for event in events
        if event.event_type is RunEventType.CHAPTER_STREAM_CHECKPOINT_SAVED
    )
    completed = next(
        event
        for event in events
        if event.event_type is RunEventType.CHAPTER_STREAM_COMPLETED
    )
    assert checkpoint.payload["artifact_id"] == completed.payload["artifact_id"]
    assert result.artifact.artifact_id == checkpoint.payload["artifact_id"]


def test_orphan_run_rejected_by_engine(tmp_path: Path) -> None:
    project_path = tmp_path / "novel"
    engine = _engine(tmp_path, _FakeGateway(()))
    run, _ = engine.start("孤儿测试")

    project = ProjectRepository.open(project_path)
    reopened = HarnessRunEngine(
        project,
        draft_stream=ChapterDraftStreamService(
            HarnessEventStore(HarnessEventRepository(project)),
            ArtifactStore(FileArtifactBackend(tmp_path / "reopened")),
            HarnessModelAdapter(
                "run-local",
                (
                    ModelRoleBinding(
                        ModelRole.CHAPTER_DRAFT,
                        TaskPurpose.PROSE_GENERATION,
                        "provider-1",
                        "model-1",
                    ),
                ),
                _FakeGateway(()),
            ),
        ),
    )

    with pytest.raises(RunCancelledError):
        reopened.stream_draft(run.id, _MESSAGES, 1024)
