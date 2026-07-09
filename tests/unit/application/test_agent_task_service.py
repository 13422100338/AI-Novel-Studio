from ai_novel_studio.application.agent_loop_service import AgentLoopRequest, AgentLoopResult
from ai_novel_studio.application.agent_task_service import (
    AGENT_ASSISTANT_PROMPT_VERSION,
    AgentTaskService,
)
from ai_novel_studio.domain.agent import AgentPurpose, AgentRunStatus


class CapturingLoop:
    def __init__(self) -> None:
        self.request: AgentLoopRequest | None = None

    def run(self, request: AgentLoopRequest) -> AgentLoopResult:
        self.request = request
        return AgentLoopResult("run-1", AgentRunStatus.COMPLETED, "ok")


def test_plot_agent_prompt_order_and_boundaries() -> None:
    loop = CapturingLoop()
    service = AgentTaskService(loop)

    service.discuss_plot_with_tools(
        user_message="这一章要不要回收旧信？",
        current_manuscript="旧信被发现。",
        chapter_requirement="本章要求：推进调查。",
        chapter_id="chapter-2",
        model_provider_id="provider",
        model_id="model",
        output_token_limit=900,
    )

    assert loop.request is not None
    messages = loop.request.messages
    assert loop.request.purpose == AgentPurpose.PLOT_DISCUSSION
    assert loop.request.prompt_version == AGENT_ASSISTANT_PROMPT_VERSION
    assert messages[0].role == "system"
    assert "只读" in messages[0].content
    assert "不要声称读过" in messages[0].content
    assert "这一章要不要回收旧信" in messages[1].content
    assert "旧信被发现" in messages[2].content
    assert "本章要求" in messages[3].content
    assert "READ_CHAPTER_EXCERPT" in messages[4].content
    assert "JSON" in messages[5].content
    assert loop.request.output_token_limit == 900


def test_revision_agent_uses_revision_purpose() -> None:
    loop = CapturingLoop()
    service = AgentTaskService(loop)

    service.plan_revision_with_tools(
        user_message="修一下人物动机",
        current_manuscript="文本",
        chapter_requirement="要求",
        chapter_id="chapter-2",
        model_provider_id="provider",
        model_id="model",
    )

    assert loop.request is not None
    assert loop.request.purpose == AgentPurpose.REVISION_PLAN
