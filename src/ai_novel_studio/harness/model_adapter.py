from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Protocol

from ai_novel_studio.harness.model_roles import ModelRole, ModelRoleBinding
from ai_novel_studio.infrastructure.llm.contract_runner import (
    CompletionGateway,
    JsonObjectContract,
    LLMContractRunner,
)
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    TaskPurpose,
)


class StreamingGateway(CompletionGateway, Protocol):
    """Gateway surface used by the harness adapter (complete + stream)."""

    def stream(
        self,
        purpose: TaskPurpose,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        *,
        temperature: float = 0.7,
    ) -> Iterator[LLMStreamEvent]: ...


class UnboundModelRoleError(LookupError):
    pass


class HarnessModelAdapter:
    """Run-frozen binding layer over the existing LLM gateway (design v0.3 §35).

    One adapter per run. It routes each logical model role through its frozen
    ModelRoleBinding, so the same provider/model may serve several roles while
    records stay separated by role. It adds no second model layer, no retry
    policy, and no cost logic of its own.
    """

    def __init__(
        self,
        run_id: str,
        bindings: tuple[ModelRoleBinding, ...],
        gateway: StreamingGateway,
    ) -> None:
        if not run_id.strip():
            raise ValueError("run_id cannot be empty")
        roles = [binding.role for binding in bindings]
        if len(set(roles)) != len(roles):
            raise ValueError("bindings must be unique per role")
        self.run_id = run_id
        self._bindings = {binding.role: binding for binding in bindings}
        self._gateway = gateway
        self._contract_runners: dict[ModelRole, LLMContractRunner] = {}

    def _binding(self, role: ModelRole) -> ModelRoleBinding:
        binding = self._bindings.get(role)
        if binding is None:
            raise UnboundModelRoleError(
                f"run {self.run_id} has no binding for role {role.value}"
            )
        return binding

    def complete(
        self,
        role: ModelRole,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        *,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> LLMResponse:
        binding = self._binding(role)
        return self._gateway.complete(
            binding.purpose,
            messages,
            output_token_limit,
            temperature=temperature,
            json_mode=json_mode,
        )

    def complete_json(
        self,
        role: ModelRole,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        contract: JsonObjectContract,
        validator: Callable[[dict[str, object]], dict[str, object]] | None = None,
    ) -> dict[str, object]:
        binding = self._binding(role)
        runner = self._contract_runners.setdefault(role, LLMContractRunner(self._gateway))
        return runner.run_json(
            binding.purpose, messages, output_token_limit, contract, validator
        )

    def stream(
        self,
        role: ModelRole,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        *,
        temperature: float = 0.7,
    ) -> Iterator[LLMStreamEvent]:
        binding = self._binding(role)
        yield from self._gateway.stream(
            binding.purpose, messages, output_token_limit, temperature=temperature
        )
