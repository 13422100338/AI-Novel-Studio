from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from ai_novel_studio.domain.agent import AgentToolName, AgentToolResult


class AgentToolValidationError(ValueError):
    pass


class AgentToolBudgetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AgentToolRequest:
    tool_name: AgentToolName
    arguments: dict[str, object]
    run_id: str
    chapter_id: str | None
    max_result_chars: int


class AgentTool(Protocol):
    name: AgentToolName
    required_arguments: tuple[str, ...]

    def execute(self, request: AgentToolRequest) -> AgentToolResult: ...


FORBIDDEN_TOOL_NAMES = {
    "WRITE_CHAPTER",
    "SAVE_MEMORY",
    "PROMOTE_MEMORY",
    "APPLY_REPAIR",
    "DELETE_RECORD",
    "CHANGE_SETTINGS",
    "EXPORT_MANUSCRIPT",
}


class AgentToolRegistry:
    def __init__(self, tools: tuple[AgentTool, ...]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    @property
    def tool_names(self) -> tuple[AgentToolName, ...]:
        return tuple(self._tools)

    def execute(
        self,
        tool_name: AgentToolName | str,
        arguments: dict[str, object],
        *,
        run_id: str,
        chapter_id: str | None,
        max_result_chars: int,
    ) -> AgentToolResult:
        if max_result_chars <= 0:
            raise AgentToolBudgetError("max_result_chars must be positive")
        if isinstance(tool_name, str) and tool_name in FORBIDDEN_TOOL_NAMES:
            raise AgentToolValidationError(f"forbidden agent tool: {tool_name}")
        try:
            normalized = (
                tool_name
                if isinstance(tool_name, AgentToolName)
                else AgentToolName(tool_name)
            )
        except ValueError as exc:
            raise AgentToolValidationError(f"unknown agent tool: {tool_name}") from exc
        tool = self._tools.get(normalized)
        if tool is None:
            raise AgentToolValidationError(f"unknown agent tool: {normalized.value}")
        missing = [name for name in tool.required_arguments if name not in arguments]
        if missing:
            raise AgentToolValidationError(f"missing required argument: {', '.join(missing)}")
        result = tool.execute(
            AgentToolRequest(normalized, arguments, run_id, chapter_id, max_result_chars)
        )
        if len(result.content) <= max_result_chars:
            return result
        content = result.content[:max_result_chars]
        omitted = (*result.omitted, f"tool result truncated to {max_result_chars} characters")
        return AgentToolResult(
            result.tool_name,
            content,
            result.source_refs,
            omitted,
            hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
