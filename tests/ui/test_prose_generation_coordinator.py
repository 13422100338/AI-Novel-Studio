from collections.abc import Iterator

from ai_novel_studio.application.prose_generation_coordinator import (
    ProseGenerationCoordinator,
)
from ai_novel_studio.application.prose_generation_service import (
    ProseEventKind,
    ProseGenerationEvent,
)
from ai_novel_studio.domain.generation import GenerationStatus
from ai_novel_studio.infrastructure.llm import LLMUsage


class FakeProseService:
    def __init__(self, events: tuple[ProseGenerationEvent, ...]) -> None:
        self.events = events
        self.calls: list[str] = []
        self.cancelled: list[str] = []

    def stream(self, run_id: str) -> Iterator[ProseGenerationEvent]:
        self.calls.append(run_id)
        yield from self.events

    def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)


def test_coordinator_runs_in_background_and_forwards_signals(qtbot) -> None:  # type: ignore[no-untyped-def]
    usage = LLMUsage(input_tokens=100, output_tokens=50)
    service = FakeProseService(
        (
            ProseGenerationEvent(ProseEventKind.DRAFT_CHUNK, text="正文片段"),
            ProseGenerationEvent(ProseEventKind.USAGE, usage=usage),
            ProseGenerationEvent(
                ProseEventKind.RUN_CHANGED, status=GenerationStatus.COMPLETED
            ),
        )
    )
    coordinator = ProseGenerationCoordinator(service)
    chunks: list[str] = []
    usages: list[object] = []
    statuses: list[object] = []
    coordinator.draft_chunk.connect(chunks.append)
    coordinator.usage_changed.connect(usages.append)
    coordinator.run_changed.connect(statuses.append)

    with qtbot.waitSignal(coordinator.finished, timeout=2000):
        coordinator.start("run-1")

    assert service.calls == ["run-1"]
    assert chunks == ["正文片段"]
    assert usages == [usage]
    assert statuses == [GenerationStatus.COMPLETED]


def test_coordinator_forwards_safe_failure_and_cancel(qtbot) -> None:  # type: ignore[no-untyped-def]
    service = FakeProseService(
        (
            ProseGenerationEvent(
                ProseEventKind.FAILED,
                message="正文生成失败，请检查连接与模型设置",
            ),
        )
    )
    coordinator = ProseGenerationCoordinator(service)

    with qtbot.waitSignal(coordinator.failed, timeout=2000) as signal:
        coordinator.start("run-2")

    assert signal.args == ["正文生成失败，请检查连接与模型设置"]
    coordinator.cancel("run-2")
    assert service.cancelled == ["run-2"]
