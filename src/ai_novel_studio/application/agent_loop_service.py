from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from ai_novel_studio.application.agent_tools import (
    AgentToolRegistry,
    AgentToolValidationError,
)
from ai_novel_studio.domain.agent import (
    AgentPurpose,
    AgentRunStatus,
    AgentSourceRef,
    AgentToolCallStatus,
    AgentTurnRole,
)
from ai_novel_studio.infrastructure.llm import LLMMessage
from ai_novel_studio.infrastructure.storage.agent_repository import AgentRepository


class AgentModelPort(Protocol):
    def complete_json(
        self,
        messages: tuple[LLMMessage, ...],
        *,
        output_token_limit: int,
    ) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class AgentLoopRequest:
    chapter_id: str | None
    purpose: AgentPurpose
    messages: tuple[LLMMessage, ...]
    model_provider_id: str
    model_id: str
    prompt_version: str
    max_iterations: int = 4
    max_tool_calls: int = 8
    max_tool_result_chars: int = 4_000
    output_token_limit: int = 2_000


@dataclass(frozen=True, slots=True)
class AgentLoopResult:
    run_id: str
    status: AgentRunStatus
    final_answer: str
    failure_code: str | None = None
    failure_message: str | None = None


class AgentLoopService:
    def __init__(
        self,
        repository: AgentRepository,
        tools: AgentToolRegistry,
        model: AgentModelPort,
    ) -> None:
        self._repository = repository
        self._tools = tools
        self._model = model

    def run(self, request: AgentLoopRequest) -> AgentLoopResult:
        run = self._repository.create_run(
            chapter_id=request.chapter_id,
            purpose=request.purpose,
            status=AgentRunStatus.PREPARING,
            model_provider_id=request.model_provider_id,
            model_id=request.model_id,
            prompt_version=request.prompt_version,
            max_iterations=request.max_iterations,
            max_tool_calls=request.max_tool_calls,
            max_tool_result_chars=request.max_tool_result_chars,
        )
        messages = list(request.messages)
        for message in messages:
            self._repository.add_turn(
                run.id,
                self._role_from_message(message),
                message.content,
            )

        used_tool_calls = 0
        for _ in range(request.max_iterations):
            self._repository.increment_usage(run.id, used_iterations_delta=1)
            self._repository.update_run_status(run.id, AgentRunStatus.WAITING_FOR_MODEL)
            try:
                response = self._model.complete_json(
                    tuple(messages),
                    output_token_limit=request.output_token_limit,
                )
                action = self._required_string(response, "action")
            except (TypeError, ValueError) as exc:
                return self._fail(run.id, "INVALID_JSON", str(exc))

            if action == "final":
                final_answer = self._required_string(response, "final_answer")
                self._repository.add_turn(run.id, AgentTurnRole.ASSISTANT, final_answer)
                self._repository.update_run_status(run.id, AgentRunStatus.COMPLETED)
                return AgentLoopResult(run.id, AgentRunStatus.COMPLETED, final_answer)

            if action != "tool":
                return self._fail(run.id, "INVALID_ACTION", action)

            calls = response.get("tool_calls")
            if not isinstance(calls, list) or not calls:
                return self._fail(
                    run.id,
                    "INVALID_TOOL_CALLS",
                    "tool_calls must be a non-empty list",
                )
            self._repository.update_run_status(run.id, AgentRunStatus.WAITING_FOR_TOOL)

            for raw_call in calls:
                if used_tool_calls >= request.max_tool_calls:
                    return self._fail(
                        run.id,
                        "MAX_TOOL_CALLS",
                        "agent exceeded tool call budget",
                    )
                if not isinstance(raw_call, dict):
                    return self._fail(
                        run.id,
                        "INVALID_TOOL_CALL",
                        "tool call must be an object",
                    )
                tool_name = self._required_string(raw_call, "tool_name")
                arguments = raw_call.get("arguments", {})
                if not isinstance(arguments, dict):
                    return self._fail(
                        run.id,
                        "INVALID_ARGUMENTS",
                        "arguments must be an object",
                    )
                call = self._repository.add_tool_call(
                    run.id,
                    tool_name,
                    json.dumps(arguments, ensure_ascii=False, sort_keys=True),
                )
                try:
                    result = self._tools.execute(
                        tool_name,
                        dict(arguments),
                        run_id=run.id,
                        chapter_id=request.chapter_id,
                        max_result_chars=request.max_tool_result_chars,
                    )
                except AgentToolValidationError as exc:
                    self._repository.complete_tool_call(
                        call.id,
                        AgentToolCallStatus.REJECTED,
                        "{}",
                        0,
                        "[]",
                        failure_code="TOOL_REJECTED",
                        failure_message=str(exc),
                    )
                    return self._fail(run.id, "TOOL_REJECTED", str(exc))
                used_tool_calls += 1
                self._repository.increment_usage(run.id, used_tool_calls_delta=1)
                source_refs_json = json.dumps(
                    [self._source_ref_to_json(ref) for ref in result.source_refs],
                    ensure_ascii=False,
                    sort_keys=True,
                )
                result_json = json.dumps(
                    {"content": result.content, "omitted": list(result.omitted)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                self._repository.complete_tool_call(
                    call.id,
                    AgentToolCallStatus.EXECUTED,
                    result_json,
                    len(result.content),
                    source_refs_json,
                )
                tool_content = self._tool_message(tool_name, result.content, result.omitted)
                self._repository.add_turn(run.id, AgentTurnRole.TOOL, tool_content)
                messages.append(LLMMessage("tool", tool_content))

        return self._fail(run.id, "MAX_ITERATIONS", "agent exceeded iteration budget")

    def _fail(
        self,
        run_id: str,
        failure_code: str,
        failure_message: str,
    ) -> AgentLoopResult:
        self._repository.update_run_status(
            run_id,
            AgentRunStatus.FAILED,
            failure_code=failure_code,
            failure_message=failure_message,
        )
        return AgentLoopResult(
            run_id,
            AgentRunStatus.FAILED,
            "",
            failure_code,
            failure_message,
        )

    @staticmethod
    def _required_string(data: dict[str, object], field: str) -> str:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _role_from_message(message: LLMMessage) -> AgentTurnRole:
        return {
            "system": AgentTurnRole.SYSTEM,
            "user": AgentTurnRole.USER,
            "assistant": AgentTurnRole.ASSISTANT,
            "tool": AgentTurnRole.TOOL,
        }[message.role]

    @staticmethod
    def _source_ref_to_json(ref: AgentSourceRef) -> dict[str, object]:
        return {
            "source_type": ref.source_type,
            "source_id": ref.source_id,
            "source_revision": ref.source_revision,
            "source_hash": ref.source_hash,
        }

    @staticmethod
    def _tool_message(tool_name: str, content: str, omitted: tuple[str, ...]) -> str:
        payload = {"tool_name": tool_name, "content": content, "omitted": list(omitted)}
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
