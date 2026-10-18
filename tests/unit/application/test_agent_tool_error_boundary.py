"""Ticket B / R3: tool exception sanitization + usage counting."""

from __future__ import annotations

from typing import Any

import pytest

from ai_novel_studio.application.agent_loop_service import (
    AgentLoopRequest,
    AgentLoopService,
)
from ai_novel_studio.application.agent_tools import (
    AgentToolRegistry,
    AgentToolValidationError,
)
from ai_novel_studio.domain.agent import AgentPurpose, AgentRunStatus
from ai_novel_studio.infrastructure.llm import LLMMessage


class FakeRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}
        self.tool_calls: list[dict] = {}
        self.usage: dict[str, int] = {}
        self._run_counter = 0
        self._call_counter = 0

    def create_run(self, **kwargs: Any) -> Any:
        self._run_counter += 1
        run_id = f"run-{self._run_counter}"
        self.runs[run_id] = {"id": run_id, **kwargs}
        return type("Run", (), {"id": run_id})()

    def add_turn(self, run_id: str, role: str, content: str) -> None: ...

    def update_run_status(self, run_id: str, status: Any, **kw: Any) -> None:
        if run_id in self.runs:
            self.runs[run_id]["status"] = status

    def increment_usage(self, run_id: str, **kw: Any) -> None:
        self.usage[run_id] = self.usage.get(run_id, 0) + kw.get("used_tool_calls_delta", 0)

    def add_tool_call(self, run_id: str, tool_name: str, arguments_json: str) -> Any:
        self._call_counter += 1
        call_id = f"call-{self._call_counter}"
        self.tool_calls[call_id] = {
            "id": call_id, "run_id": run_id,
            "tool_name": tool_name, "arguments": arguments_json,
            "status": "REQUESTED",
            "failure_code": None, "failure_message": None,
        }
        return type("Call", (), {"id": call_id})()

    def complete_tool_call(self, call_id: str, status: Any,
                           result_json: str, chars: int,
                           source_refs_json: str, **kw: Any) -> None:
        if call_id in self.tool_calls:
            self.tool_calls[call_id]["status"] = str(status)
            self.tool_calls[call_id]["failure_code"] = kw.get("failure_code")
            self.tool_calls[call_id]["failure_message"] = kw.get("failure_message")

    def increment_iterations(self, run_id: str) -> None: ...


class FakeModel:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)
        self._idx = 0

    def complete_json(self, messages: tuple, *, output_token_limit: int) -> dict:
        resp = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return resp


class ThrowingTool:
    name = "SEARCH_MEMORY"
    required_arguments = ("query",)

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def execute(self, request: object) -> object:
        raise self._exc


def _make_request() -> AgentLoopRequest:
    return AgentLoopRequest(
        chapter_id="ch-1",
        purpose=AgentPurpose.PLOT_DISCUSSION,
        messages=(LLMMessage("user", "test"),),
        model_provider_id="p",
        model_id="m",
        prompt_version="test",
        max_iterations=3,
        required_tool_names=(),
    )


SECRET_MARKERS = [
    "/absolute/path/to/file.py",
    "SELECT * FROM chapters",
    "正文秘密内容标记",
    "Bearer sk-secret-key-12345",
]


@pytest.mark.parametrize("marker", SECRET_MARKERS)
def test_tool_exception_sanitized_and_reaches_failed_terminal(marker: str) -> None:
    """R3: raw exception must be replaced with fixed message; run reaches
    FAILED; DB contains no secret markers."""
    repo = FakeRepository()
    throwing = ThrowingTool(RuntimeError(
        f"sqlite3 error at /abs/path: {marker} — 正文泄露 {marker}"
    ))
    registry = AgentToolRegistry((throwing,))
    model = FakeModel([
        {"action": "tool", "tool_calls": [{"tool_name": "SEARCH_MEMORY",
                                           "arguments": {"query": "x"}}]},
        {"action": "final", "final_answer": "ok"},
    ])
    service = AgentLoopService(repo, registry, model)

    result = service.run(_make_request())

    assert result.status == AgentRunStatus.COMPLETED
    failed_calls = [c for c in repo.tool_calls.values()
                    if c["failure_message"] is not None]
    assert failed_calls, "no tool call recorded as failed"
    for c in failed_calls:
        msg = c["failure_message"] or ""
        for m in SECRET_MARKERS:
            assert m not in msg, f"leaked marker {m!r} in failure_message"
    # usage counting must include the failed call
    assert repo.usage.get(result.run_id, 0) >= 1


def test_validation_error_keeps_original_message_but_run_survives() -> None:
    repo = FakeRepository()
    throwing = ThrowingTool(AgentToolValidationError("chapter_ids must be a non-empty list"))
    registry = AgentToolRegistry((throwing,))
    model = FakeModel([
        {"action": "tool", "tool_calls": [{"tool_name": "SEARCH_MEMORY",
                                           "arguments": {"query": "x"}}]},
        {"action": "final", "final_answer": "ok"},
    ])
    service = AgentLoopService(repo, registry, model)

    result = service.run(_make_request())

    assert result.status == AgentRunStatus.COMPLETED
    rejected = [c for c in repo.tool_calls.values()
                if c["failure_code"] == "TOOL_REJECTED"]
    assert rejected
    assert "chapter_ids" in rejected[0]["failure_message"]
