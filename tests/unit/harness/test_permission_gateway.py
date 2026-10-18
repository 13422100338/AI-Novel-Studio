from __future__ import annotations

import pytest

from ai_novel_studio.harness.permission_gateway import (
    GateContext,
    GateDecision,
    PermissionGateway,
    ToolCallDecision,
)
from ai_novel_studio.harness.run_state import RunStage
from ai_novel_studio.harness.tool_registry import (
    ToolDefinition,
    ToolRegistry,
    ToolRiskLevel,
    ToolScope,
    WriteEffect,
)


def _definition(
    tool_id: str = "manuscript.read",
    **overrides: object,
) -> ToolDefinition:
    fields: dict[str, object] = dict(
        id=tool_id,
        version=1,
        scope=ToolScope.PROJECT,
        risk_level=ToolRiskLevel.READ_ONLY,
        write_effect=WriteEffect.NONE,
        requires_approval=False,
        input_schema={},
        output_schema={},
    )
    fields.update(overrides)
    return ToolDefinition(**fields)


def _context(**overrides: object) -> GateContext:
    fields: dict[str, object] = dict(
        run_stage=RunStage.MODEL_RUNNING,
        expected_revision=None,
        idempotency_key=None,
        project_scope_enabled=True,
        run_scope_enabled=True,
    )
    fields.update(overrides)
    return GateContext(**fields)


def _evaluate(definition: ToolDefinition, **context: object) -> ToolCallDecision:
    registry = ToolRegistry()
    registry.register(definition)
    return PermissionGateway(registry).evaluate(definition.id, context=_context(**context))


def test_unregistered_tool_is_denied() -> None:
    gateway = PermissionGateway(ToolRegistry())
    decision = gateway.evaluate("subject.query", context=_context())
    assert decision.decision is GateDecision.DENIED
    assert decision.reason == "tool not registered"


def test_closed_run_stage_denies_tool_calls() -> None:
    decision = _evaluate(_definition(), run_stage=RunStage.CANCELLED)
    assert decision.decision is GateDecision.DENIED


def test_scope_flags_gate_project_and_run_tools() -> None:
    project_decision = _evaluate(_definition(), project_scope_enabled=False)
    assert project_decision.decision is GateDecision.DENIED
    run_decision = _evaluate(_definition(scope=ToolScope.RUN), run_scope_enabled=False)
    assert run_decision.decision is GateDecision.DENIED
    ok_decision = _evaluate(_definition(scope=ToolScope.RUN))
    assert ok_decision.decision is GateDecision.ALLOWED


def test_formal_write_requires_revision_key_and_approval() -> None:
    formal = _definition(
        tool_id="knowledge.propose_changeset", write_effect=WriteEffect.FORMAL_WRITE
    )
    missing_revision = _evaluate(formal, idempotency_key="key-1")
    assert missing_revision.decision is GateDecision.DENIED
    missing_key = _evaluate(formal, expected_revision=3)
    assert missing_key.decision is GateDecision.DENIED
    complete = _evaluate(formal, expected_revision=3, idempotency_key="key-1")
    assert complete.decision is GateDecision.REQUIRES_APPROVAL


def test_proposal_only_requires_key_and_honours_approval_flag() -> None:
    proposal = _definition(
        tool_id="subject.propose_merge", write_effect=WriteEffect.PROPOSAL_ONLY
    )
    missing_key = _evaluate(proposal)
    assert missing_key.decision is GateDecision.DENIED
    allowed = _evaluate(proposal, idempotency_key="key-1")
    assert allowed.decision is GateDecision.ALLOWED
    gated_definition = _definition(
        tool_id="subject.propose_merge",
        write_effect=WriteEffect.PROPOSAL_ONLY,
        requires_approval=True,
    )
    gated = _evaluate(gated_definition, idempotency_key="key-1")
    assert gated.decision is GateDecision.REQUIRES_APPROVAL


def test_read_only_tools_default_to_allowed() -> None:
    allowed = _evaluate(_definition())
    assert allowed.decision is GateDecision.ALLOWED
    gated = _evaluate(_definition(requires_approval=True))
    assert gated.decision is GateDecision.REQUIRES_APPROVAL


def test_gate_context_rejects_non_run_stage() -> None:
    with pytest.raises(ValueError):
        _context(run_stage="MODEL_RUNNING")
