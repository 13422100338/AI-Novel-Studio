from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ai_novel_studio.harness.run_state import CLOSED_STAGES, RunStage
from ai_novel_studio.harness.tool_registry import (
    ToolRegistry,
    ToolScope,
    WriteEffect,
)


class GateDecision(StrEnum):
    ALLOWED = "ALLOWED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    DENIED = "DENIED"


@dataclass(frozen=True, slots=True)
class GateContext:
    """Facts the deterministic gateway checks for one tool call (design §31)."""

    run_stage: RunStage
    expected_revision: int | None
    idempotency_key: str | None
    project_scope_enabled: bool
    run_scope_enabled: bool

    def __post_init__(self) -> None:
        if not isinstance(self.run_stage, RunStage):
            raise ValueError("run_stage must be a RunStage")


@dataclass(frozen=True, slots=True)
class ToolCallDecision:
    decision: GateDecision
    tool_id: str
    tool_version: int
    reason: str | None = None


class PermissionGateway:
    """Deterministic pre-execution checks for every tool call (design §31).

    Prompts and skills cannot bypass this gateway: it decides from the frozen
    ToolDefinition and the run facts alone. A3 provides the decision skeleton;
    approval persistence and the approval resolver arrive with A8.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def evaluate(
        self,
        tool_id: str,
        *,
        version: int | None = None,
        context: GateContext,
    ) -> ToolCallDecision:
        try:
            definition = self._registry.resolve(tool_id, version)
        except KeyError:
            return ToolCallDecision(GateDecision.DENIED, tool_id, 0, "tool not registered")

        if context.run_stage in CLOSED_STAGES:
            return ToolCallDecision(
                GateDecision.DENIED,
                tool_id,
                definition.version,
                f"run is closed at stage {context.run_stage.value}",
            )
        if definition.scope is ToolScope.PROJECT and not context.project_scope_enabled:
            return ToolCallDecision(
                GateDecision.DENIED, tool_id, definition.version, "project scope not enabled"
            )
        if definition.scope is ToolScope.RUN and not context.run_scope_enabled:
            return ToolCallDecision(
                GateDecision.DENIED, tool_id, definition.version, "run scope not enabled"
            )
        if definition.write_effect is WriteEffect.FORMAL_WRITE:
            if context.expected_revision is None:
                return ToolCallDecision(
                    GateDecision.DENIED,
                    tool_id,
                    definition.version,
                    "FORMAL_WRITE requires expected_revision",
                )
            if not context.idempotency_key:
                return ToolCallDecision(
                    GateDecision.DENIED,
                    tool_id,
                    definition.version,
                    "FORMAL_WRITE requires idempotency_key",
                )
            return ToolCallDecision(
                GateDecision.REQUIRES_APPROVAL,
                tool_id,
                definition.version,
                "formal writes always require author approval",
            )
        if definition.write_effect is WriteEffect.PROPOSAL_ONLY and not context.idempotency_key:
            return ToolCallDecision(
                GateDecision.DENIED,
                tool_id,
                definition.version,
                "PROPOSAL_ONLY tools require idempotency_key",
            )
        if definition.requires_approval:
            return ToolCallDecision(GateDecision.REQUIRES_APPROVAL, tool_id, definition.version)
        return ToolCallDecision(GateDecision.ALLOWED, tool_id, definition.version)
