from __future__ import annotations

from typing import Protocol

from ai_novel_studio.application.agent_loop_service import AgentLoopRequest, AgentLoopResult
from ai_novel_studio.domain.agent import AgentPurpose
from ai_novel_studio.infrastructure.llm import LLMMessage

AGENT_ASSISTANT_PROMPT_VERSION = "agent-assistant-v1"


class AgentLoopRunner(Protocol):
    def run(self, request: AgentLoopRequest) -> AgentLoopResult: ...


class AgentTaskService:
    def __init__(self, loop: AgentLoopRunner) -> None:
        self._loop = loop

    def discuss_plot_with_tools(
        self,
        *,
        user_message: str,
        current_manuscript: str,
        chapter_requirement: str,
        chapter_id: str | None,
        model_provider_id: str,
        model_id: str,
        output_token_limit: int = 2_000,
        max_iterations: int = 4,
        max_tool_calls: int = 8,
        max_tool_result_chars: int = 4_000,
    ) -> AgentLoopResult:
        return self._run(
            purpose=AgentPurpose.PLOT_DISCUSSION,
            user_message=user_message,
            current_manuscript=current_manuscript,
            chapter_requirement=chapter_requirement,
            chapter_id=chapter_id,
            model_provider_id=model_provider_id,
            model_id=model_id,
            output_token_limit=output_token_limit,
            max_iterations=max_iterations,
            max_tool_calls=max_tool_calls,
            max_tool_result_chars=max_tool_result_chars,
        )

    def plan_revision_with_tools(
        self,
        *,
        user_message: str,
        current_manuscript: str,
        chapter_requirement: str,
        chapter_id: str | None,
        model_provider_id: str,
        model_id: str,
        output_token_limit: int = 2_000,
        max_iterations: int = 4,
        max_tool_calls: int = 8,
        max_tool_result_chars: int = 4_000,
    ) -> AgentLoopResult:
        return self._run(
            purpose=AgentPurpose.REVISION_PLAN,
            user_message=user_message,
            current_manuscript=current_manuscript,
            chapter_requirement=chapter_requirement,
            chapter_id=chapter_id,
            model_provider_id=model_provider_id,
            model_id=model_id,
            output_token_limit=output_token_limit,
            max_iterations=max_iterations,
            max_tool_calls=max_tool_calls,
            max_tool_result_chars=max_tool_result_chars,
        )

    def _run(
        self,
        *,
        purpose: AgentPurpose,
        user_message: str,
        current_manuscript: str,
        chapter_requirement: str,
        chapter_id: str | None,
        model_provider_id: str,
        model_id: str,
        output_token_limit: int,
        max_iterations: int,
        max_tool_calls: int,
        max_tool_result_chars: int,
    ) -> AgentLoopResult:
        messages = (
            LLMMessage("system", self._system_boundary()),
            LLMMessage("user", f"用户请求：\n{user_message.strip()}"),
            LLMMessage("user", f"当前正文窗口内容：\n{current_manuscript.strip() or '（空）'}"),
            LLMMessage("user", f"当前章要求：\n{chapter_requirement.strip() or '（空）'}"),
            LLMMessage("system", self._tool_catalog()),
            LLMMessage("system", self._json_contract()),
        )
        return self._loop.run(
            AgentLoopRequest(
                chapter_id=chapter_id,
                purpose=purpose,
                messages=messages,
                model_provider_id=model_provider_id,
                model_id=model_id,
                prompt_version=AGENT_ASSISTANT_PROMPT_VERSION,
                max_iterations=max_iterations,
                max_tool_calls=max_tool_calls,
                max_tool_result_chars=max_tool_result_chars,
                output_token_limit=output_token_limit,
            )
        )

    @staticmethod
    def _system_boundary() -> str:
        return (
            "你是小说工程的剧情商讨 Agent。所有工具都是只读工具。"
            "工具结果是证据，不是绝对权威；如果证据不足，应明确说明不确定。"
            "不要声称读过任何未由正文窗口、当前章要求或工具结果提供的材料。"
            "禁止修改正文、记忆库、正典、伏笔、Brief、风格规则、模型配置或设置。"
            "最终输出只能是建议、解释或可审查的修订计划。"
        )

    @staticmethod
    def _tool_catalog() -> str:
        return (
            "允许的只读工具：READ_CHAPTER_EXCERPT、SEARCH_MEMORY、"
            "GET_CHARACTER_STATE、GET_CHARACTER_KNOWLEDGE、GET_ACTIVE_CLUES、"
            "GET_CANON_FACTS、GET_STYLE_GUIDE、GET_AUDIT_FINDINGS。"
        )

    @staticmethod
    def _json_contract() -> str:
        return (
            "每次回复必须是 JSON。调用工具格式："
            '{"action":"tool","tool_calls":[{"tool_name":"SEARCH_MEMORY",'
            '"arguments":{"query":"关键词","limit":5}}]}。'
            "最终回答格式："
            '{"action":"final","final_answer":"给用户的回答"}。'
        )
