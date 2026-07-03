from collections.abc import Iterator

from ai_novel_studio.application.model_tasks import (
    ModelTaskService,
    NormalizedBrief,
    StyleAuditResult,
)
from ai_novel_studio.infrastructure.llm import (
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    StreamEventKind,
    TaskPurpose,
)


class FakeGateway:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls = []
        self.stream_calls = []

    def complete(self, purpose, messages, output_token_limit, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append((purpose, messages, output_token_limit, kwargs))
        return LLMResponse(self.responses.pop(0), "model")

    def stream(self, purpose, messages, output_token_limit, **kwargs) -> Iterator[LLMStreamEvent]:  # type: ignore[no-untyped-def]
        self.stream_calls.append((purpose, messages, output_token_limit, kwargs))
        yield LLMStreamEvent(StreamEventKind.TEXT, text="第一段")
        yield LLMStreamEvent(StreamEventKind.TEXT, text="第二段")
        yield LLMStreamEvent(StreamEventKind.COMPLETED)


def test_plot_chat_prompt_keeps_rules_first_and_user_turn_last() -> None:
    gateway = FakeGateway()
    service = ModelTaskService(gateway)  # type: ignore[arg-type]
    conversation = (
        LLMMessage("assistant", "你想讨论什么？"),
        LLMMessage("user", "让主角在这里产生怀疑。"),
    )

    events = tuple(service.stream_chat(conversation, "当前正文片段", 4096))

    purpose, messages, limit, _ = gateway.stream_calls[0]
    assert purpose == TaskPurpose.PLOT_DISCUSSION
    assert limit == 4096
    assert messages[0].role == "system"
    assert "剧情导演" in messages[0].content
    assert "当前正文片段" in messages[-2].content
    assert messages[-1] == conversation[-1]
    assert events[-1].kind == StreamEventKind.COMPLETED


def test_requirement_draft_uses_plot_route_and_returns_nonempty_formal_instruction() -> None:
    gateway = FakeGateway(["本章必须让主角发现信封封口被替换，但不能确认幕后人。"])
    service = ModelTaskService(gateway)  # type: ignore[arg-type]

    result = service.draft_chapter_requirement(
        (LLMMessage("user", "讨论记录"),),
        "正文片段",
        2000,
    )

    assert result.startswith("本章必须")
    purpose, messages, _, _ = gateway.calls[0]
    assert purpose == TaskPurpose.CHAPTER_REQUIREMENT
    assert "正式当前章要求" in messages[-1].content


def test_brief_normalization_uses_json_contract_and_typed_result() -> None:
    gateway = FakeGateway(
        [
            """{"dramatic_function":"制造怀疑","hard_events":["发现封口"],
            "soft_goals":["保持克制"],"forbidden_changes":["确认凶手"],
            "creative_freedom":["环境细节"]}"""
        ]
    )
    service = ModelTaskService(gateway)  # type: ignore[arg-type]

    result = service.normalize_brief("未经整理的 Brief", 4000)

    assert result == NormalizedBrief(
        dramatic_function="制造怀疑",
        hard_events=("发现封口",),
        soft_goals=("保持克制",),
        forbidden_changes=("确认凶手",),
        creative_freedom=("环境细节",),
    )
    assert gateway.calls[0][0] == TaskPurpose.BRIEF_NORMALIZATION
    assert gateway.calls[0][3]["json_mode"] is True


def test_style_audit_returns_findings_without_modifying_manuscript() -> None:
    gateway = FakeGateway(
        [
            """{"summary":"人物声音略显一致","findings":[
            {"category":"声音","issue":"区分不足","evidence":"两人用词相同","severity":"中"}
            ]}"""
        ]
    )
    service = ModelTaskService(gateway)  # type: ignore[arg-type]

    result = service.audit_style("原始正文", ("避免解释情绪",), 4000)

    assert isinstance(result, StyleAuditResult)
    assert result.summary == "人物声音略显一致"
    assert result.findings[0].evidence == "两人用词相同"
    assert gateway.calls[0][0] == TaskPurpose.STYLE_AUDIT

