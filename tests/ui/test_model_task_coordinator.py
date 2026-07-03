from collections.abc import Iterator

from pytestqt.qtbot import QtBot

from ai_novel_studio.application.model_task_coordinator import ModelTaskCoordinator
from ai_novel_studio.application.model_tasks import NormalizedBrief, StyleAuditResult
from ai_novel_studio.infrastructure.llm import LLMMessage, LLMStreamEvent, StreamEventKind


class FakeTaskService:
    def stream_chat(self, conversation, manuscript, limit) -> Iterator[LLMStreamEvent]:  # type: ignore[no-untyped-def]
        yield LLMStreamEvent(StreamEventKind.TEXT, text="甲")
        yield LLMStreamEvent(StreamEventKind.TEXT, text="乙")
        yield LLMStreamEvent(StreamEventKind.COMPLETED)

    def draft_chapter_requirement(self, conversation, manuscript, limit):  # type: ignore[no-untyped-def]
        return "正式要求"

    def normalize_brief(self, source, limit):  # type: ignore[no-untyped-def]
        return NormalizedBrief("功能", (), (), (), ())

    def audit_style(self, manuscript, rules, limit):  # type: ignore[no-untyped-def]
        return StyleAuditResult("通过", ())


def test_coordinator_emits_stream_chunks_in_order_without_blocking_ui(qtbot: QtBot) -> None:
    coordinator = ModelTaskCoordinator(FakeTaskService())  # type: ignore[arg-type]
    chunks: list[str] = []
    coordinator.chat_chunk.connect(chunks.append)

    with qtbot.waitSignal(coordinator.chat_finished, timeout=2000):
        coordinator.start_chat((LLMMessage("user", "讨论"),), "正文", 1000)

    assert chunks == ["甲", "乙"]


def test_coordinator_returns_requirement_result(qtbot: QtBot) -> None:
    coordinator = ModelTaskCoordinator(FakeTaskService())  # type: ignore[arg-type]

    with qtbot.waitSignal(coordinator.requirement_ready, timeout=2000) as signal:
        coordinator.start_requirement((LLMMessage("user", "讨论"),), "正文", 1000)

    assert signal.args == ["正式要求"]


class FailingTaskService(FakeTaskService):
    def draft_chapter_requirement(self, conversation, manuscript, limit):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider echoed sk-private-value")


def test_coordinator_sanitizes_unexpected_worker_errors(qtbot: QtBot) -> None:
    coordinator = ModelTaskCoordinator(FailingTaskService())  # type: ignore[arg-type]

    with qtbot.waitSignal(coordinator.task_failed, timeout=2000) as signal:
        coordinator.start_requirement((LLMMessage("user", "讨论"),), "正文", 1000)

    assert "sk-private-value" not in signal.args[0]
    assert "模型任务失败" in signal.args[0]

