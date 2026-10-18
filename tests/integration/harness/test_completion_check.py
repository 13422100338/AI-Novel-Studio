from __future__ import annotations

from pathlib import Path

from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approval_service import ApprovalService
from ai_novel_studio.harness.approvals import ApprovalKind
from ai_novel_studio.harness.completion_check import CompletionChecker
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _checker(tmp_path: Path) -> tuple[HarnessEventStore, ApprovalService, CompletionChecker]:
    project = ProjectRepository.create(tmp_path / "novel", "Completion Test")
    store = HarnessEventStore(HarnessEventRepository(project))
    approvals = ApprovalService(store, ApprovalRepository(project))
    checker = CompletionChecker(store, ApprovalRepository(project))
    return store, approvals, checker


def test_clean_completed_run_passes_check(tmp_path: Path) -> None:
    store, _approvals, checker = _checker(tmp_path)
    run, _ = store.start_run(goal="clean run")
    store.transition(run.id, RunStage.COMPLETED)

    result = checker.check(run.id)
    assert result.ok is True
    assert checker.can_complete(run.id).ok is True


def test_completed_with_pending_approval_fails(tmp_path: Path) -> None:
    store, approvals, checker = _checker(tmp_path)
    run, _ = store.start_run(goal="pending approval")
    approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.CHANGESET,
        summary="replace scene",
        idempotency_key="key-1",
    )
    store.transition(run.id, RunStage.COMPLETED)

    result = checker.check(run.id)
    assert result.ok is False
    assert "pending approvals" in result.failures[0]


def test_orphan_waiting_approval_fails(tmp_path: Path) -> None:
    store, _approvals, checker = _checker(tmp_path)
    run, _ = store.start_run(goal="orphan wait")
    store.transition(run.id, RunStage.WAITING_APPROVAL)

    result = checker.check(run.id)
    assert result.ok is False
    assert "WAITING_APPROVAL without pending approvals" in result.failures[0]


def test_completed_with_failed_tool_call_fails(tmp_path: Path) -> None:
    store, _approvals, checker = _checker(tmp_path)
    run, _ = store.start_run(goal="failed tool")
    store.append(run.id, RunEventType.TOOL_CALL_FAILED, {"tool_id": "subject.query"})
    store.transition(run.id, RunStage.COMPLETED)

    result = checker.check(run.id)
    assert result.ok is False
    assert "failed tool calls" in result.failures[0]


def test_can_complete_gates_on_pending_and_closed_runs(tmp_path: Path) -> None:
    store, approvals, checker = _checker(tmp_path)
    run, _ = store.start_run(goal="gate")
    assert checker.can_complete(run.id).ok is True

    approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.PROMPT_CHANGE,
        summary="tweak system prompt",
        idempotency_key="key-1",
    )
    gated = checker.can_complete(run.id)
    assert gated.ok is False
    assert "pending approvals" in gated.failures[0]

    store.transition(run.id, RunStage.CANCELLED)
    closed = checker.can_complete(run.id)
    assert closed.ok is False
    assert "closed" in closed.failures[0]
