from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.harness.cancel_token import (
    CancellationError,
    CancelToken,
    cancel_run,
)
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import (
    HarnessEventStore,
    HarnessRunClosedError,
)
from ai_novel_studio.harness.permission_gateway import GateContext, GateDecision, PermissionGateway
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.harness.tool_registry import (
    ToolDefinition,
    ToolRegistry,
    ToolRiskLevel,
    ToolScope,
    WriteEffect,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def test_token_is_one_way_and_raises_after_request() -> None:
    token = CancelToken()
    assert not token.cancelled

    token.request()
    assert token.cancelled
    with pytest.raises(CancellationError):
        token.raise_if_cancelled()

    token.request()
    assert token.cancelled


def test_cancel_run_closes_run_and_rejects_late_events(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Cancel Test")
    store = HarnessEventStore(HarnessEventRepository(project))
    run, _ = store.start_run(goal="cancel me")

    cancelled = cancel_run(store, run.id, CancelToken())

    assert cancelled.stage is RunStage.CANCELLED
    with pytest.raises(HarnessRunClosedError):
        store.append(run.id, RunEventType.CONTEXT_COMPILED)
    # 幂等:再次取消已取消的 run 不抛错
    again = cancel_run(store, run.id, CancelToken())
    assert again.stage is RunStage.CANCELLED


def test_cancelled_run_denied_by_permission_gateway(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Cancel Gate Test")
    store = HarnessEventStore(HarnessEventRepository(project))
    run, _ = store.start_run(goal="cancel gate")
    token = CancelToken()
    cancel_run(store, run.id, token)

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            id="manuscript.read",
            version=1,
            scope=ToolScope.PROJECT,
            risk_level=ToolRiskLevel.READ_ONLY,
            write_effect=WriteEffect.NONE,
            requires_approval=False,
            input_schema={},
            output_schema={},
        )
    )
    gateway = PermissionGateway(registry)
    decision = gateway.evaluate(
        "manuscript.read",
        context=GateContext(
            run_stage=store.get_run(run.id).stage,
                expected_revision=None,
            idempotency_key=None,
            project_scope_enabled=True,
            run_scope_enabled=True,
        ),
    )

    assert decision.decision is GateDecision.DENIED
