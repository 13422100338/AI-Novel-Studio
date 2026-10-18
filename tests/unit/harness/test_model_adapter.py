from __future__ import annotations

from collections.abc import Iterator

import pytest

from ai_novel_studio.harness.model_adapter import (
    HarnessModelAdapter,
    UnboundModelRoleError,
)
from ai_novel_studio.harness.model_roles import ModelRole, ModelRoleBinding
from ai_novel_studio.infrastructure.llm.contract_runner import (
    JsonField,
    JsonObjectContract,
)
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
    StreamEventKind,
    TaskPurpose,
)


class _FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[TaskPurpose, tuple[LLMMessage, ...], int]] = []
        self.stream_calls: list[tuple[TaskPurpose, tuple[LLMMessage, ...], int]] = []

    def complete(
        self,
        purpose: TaskPurpose,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        *,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> LLMResponse:
        self.calls.append((purpose, messages, output_token_limit))
        return LLMResponse(
            text='{"answer": "yes"}',
            model_id="model-x",
            usage=LLMUsage(input_tokens=10, output_tokens=5),
        )

    def stream(
        self,
        purpose: TaskPurpose,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        *,
        temperature: float = 0.7,
    ) -> Iterator[LLMStreamEvent]:
        self.stream_calls.append((purpose, messages, output_token_limit))
        yield LLMStreamEvent(kind=StreamEventKind.TEXT, text="hello")


def _bindings() -> tuple[ModelRoleBinding, ...]:
    return (
        ModelRoleBinding(ModelRole.AGENT, TaskPurpose.PLOT_DISCUSSION, "p", "agent-model"),
        ModelRoleBinding(
            ModelRole.CHAPTER_DRAFT, TaskPurpose.PROSE_GENERATION, "p", "draft-model"
        ),
        ModelRoleBinding(
            ModelRole.COMPACTION, TaskPurpose.AGENT_ASSISTANT, "p", "compaction-model"
        ),
    )


def _messages() -> tuple[LLMMessage, ...]:
    return (LLMMessage("user", "draft the scene"),)


def test_adapter_routes_complete_by_role() -> None:
    gateway = _FakeGateway()
    adapter = HarnessModelAdapter("run-1", _bindings(), gateway)

    adapter.complete(ModelRole.AGENT, _messages(), 500)
    adapter.complete(ModelRole.CHAPTER_DRAFT, _messages(), 500)

    assert gateway.calls[0][0] is TaskPurpose.PLOT_DISCUSSION
    assert gateway.calls[1][0] is TaskPurpose.PROSE_GENERATION


def test_adapter_stream_routes_by_role() -> None:
    gateway = _FakeGateway()
    adapter = HarnessModelAdapter("run-1", _bindings(), gateway)

    events = list(adapter.stream(ModelRole.COMPACTION, _messages(), 500))

    assert gateway.stream_calls[0][0] is TaskPurpose.AGENT_ASSISTANT
    assert [event.text for event in events] == ["hello"]


def test_adapter_complete_json_parses_and_validates() -> None:
    gateway = _FakeGateway()
    adapter = HarnessModelAdapter("run-1", _bindings(), gateway)
    contract = JsonObjectContract(fields=(JsonField(name="answer", expected_type=str),))

    payload = adapter.complete_json(ModelRole.AGENT, _messages(), 500, contract)

    assert payload == {"answer": "yes"}
    assert gateway.calls[0][0] is TaskPurpose.PLOT_DISCUSSION


def test_adapter_rejects_unbound_role() -> None:
    gateway = _FakeGateway()
    adapter = HarnessModelAdapter(
        "run-1",
        (ModelRoleBinding(ModelRole.AGENT, TaskPurpose.AGENT_ASSISTANT, "p", "m"),),
        gateway,
    )

    with pytest.raises(UnboundModelRoleError):
        adapter.complete(ModelRole.CHAPTER_DRAFT, _messages(), 500)


def test_adapter_rejects_duplicate_role_bindings_and_empty_run_id() -> None:
    gateway = _FakeGateway()
    binding = ModelRoleBinding(ModelRole.AGENT, TaskPurpose.AGENT_ASSISTANT, "p", "m")

    with pytest.raises(ValueError):
        HarnessModelAdapter("run-1", (binding, binding), gateway)
    with pytest.raises(ValueError):
        HarnessModelAdapter("  ", (binding,), gateway)
