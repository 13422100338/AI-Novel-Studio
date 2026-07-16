from collections.abc import Iterator

from ai_novel_studio.application.model_tasks import (
    ChatSummaryResult,
    ModelTaskService,
    NormalizedBrief,
    StyleAuditFinding,
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


def test_chat_summary_preserves_long_term_decisions_in_validated_json() -> None:
    gateway = FakeGateway(
        ['{"summary":"已确认主角前往旧港；寄信人身份仍未解决。"}']
    )
    service = ModelTaskService(gateway)  # type: ignore[arg-type]

    result = service.summarize_chat(
        "已确认保留来信。",
        "user: 下一章去旧港\nassistant: 可以，但不要揭晓寄信人",
        2000,
    )

    assert result == ChatSummaryResult("已确认主角前往旧港；寄信人身份仍未解决。")
    purpose, messages, limit, kwargs = gateway.calls[0]
    assert purpose == TaskPurpose.PLOT_DISCUSSION
    assert limit == 2000
    assert kwargs["json_mode"] is True
    assert "不得把建议写成既定事实" in messages[0].content


def test_requirement_draft_uses_plot_route_and_returns_nonempty_formal_instruction() -> None:
    gateway = FakeGateway(
        [
            '{"chapter_goal":"让主角开始怀疑信件来源",'
            '"hard_events":["发现信封封口被替换"],'
            '"character_psychology":["主角警惕但保持克制"],'
            '"forbidden_changes":["不能确认幕后人"],'
            '"creative_freedom":["环境细节"]}'
        ]
    )
    service = ModelTaskService(gateway)  # type: ignore[arg-type]

    result = service.draft_chapter_requirement(
        (LLMMessage("user", "讨论记录"),),
        "正文片段",
        2000,
    )

    assert result.startswith("## 当前章目标")
    assert "- 发现信封封口被替换" in result
    assert "## 禁止改变\n- 不能确认幕后人" in result
    purpose, messages, _, kwargs = gateway.calls[0]
    assert purpose == TaskPurpose.CHAPTER_REQUIREMENT
    assert "不得写小说正文" in messages[-1].content
    assert kwargs["json_mode"] is True


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


def test_brief_normalization_accepts_safe_scalar_list_shape_variants() -> None:
    gateway = FakeGateway(
        [
            """{"dramatic_function":["制造怀疑","推动调查"],
            "hard_events":"发现封口","soft_goals":["保持克制"],
            "forbidden_changes":"不能确认凶手","creative_freedom":"环境细节"}"""
        ]
    )
    service = ModelTaskService(gateway)  # type: ignore[arg-type]

    result = service.normalize_brief("未经整理的 Brief", 4000)

    assert result.dramatic_function == "制造怀疑；推动调查"
    assert result.hard_events == ("发现封口",)
    assert result.forbidden_changes == ("不能确认凶手",)
    assert result.creative_freedom == ("环境细节",)


def test_brief_normalization_accepts_known_aliases_and_missing_sections() -> None:
    gateway = FakeGateway(
        ['{"戏剧功能":"推动调查","必须事件":"发现封口"}']
    )
    service = ModelTaskService(gateway)  # type: ignore[arg-type]

    result = service.normalize_brief("未经整理的 Brief", 4000)

    assert result == NormalizedBrief(
        dramatic_function="推动调查",
        hard_events=("发现封口",),
        soft_goals=(),
        forbidden_changes=(),
        creative_freedom=(),
    )


def test_brief_normalization_retries_unrecognized_payload_with_exact_schema() -> None:
    gateway = FakeGateway(
        [
            '{"content":"推动调查"}',
            '{"dramatic_function":"推动调查","hard_events":[],"soft_goals":[],'
            '"forbidden_changes":[],"creative_freedom":[]}',
        ]
    )
    service = ModelTaskService(gateway)  # type: ignore[arg-type]

    result = service.normalize_brief("未经整理的 Brief", 4000)

    assert result.dramatic_function == "推动调查"
    assert len(gateway.calls) == 2
    correction = gateway.calls[1][1][-1].content
    assert "合同字段" in correction
    assert "dramatic_function" in correction
    assert "hard_events" in correction


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
    assert result.findings[0].category == "STYLE"
    assert result.findings[0].severity == "WARNING"
    assert result.findings[0].evidence == "两人用词相同"
    assert gateway.calls[0][0] == TaskPurpose.STYLE_AUDIT


def test_style_audit_accepts_nested_aliases_and_missing_summary() -> None:
    gateway = FakeGateway(
        [
            '{"findings":[{"category":"STYLE","problem":"声音区分不足",'
            '"quote":"两人用词相同","level":"WARNING"}]}'
        ]
    )
    service = ModelTaskService(gateway)  # type: ignore[arg-type]

    result = service.audit_style("原始正文", (), 4000)

    assert result.summary == ""
    assert result.findings == (
        StyleAuditFinding("STYLE", "声音区分不足", "两人用词相同", "WARNING"),
    )


def test_style_audit_retries_when_nested_finding_is_incomplete() -> None:
    gateway = FakeGateway(
        [
            '{"summary":"发现问题","findings":[{"category":"STYLE"}]}',
            '{"summary":"发现问题","findings":[{"category":"STYLE",'
            '"issue":"声音区分不足","evidence":"两人用词相同",'
            '"severity":"WARNING"}]}',
        ]
    )
    service = ModelTaskService(gateway)  # type: ignore[arg-type]

    result = service.audit_style("原始正文", (), 4000)

    assert result.findings[0].issue == "声音区分不足"
    assert len(gateway.calls) == 2
    assert "findings[0]" in gateway.calls[1][1][-1].content
