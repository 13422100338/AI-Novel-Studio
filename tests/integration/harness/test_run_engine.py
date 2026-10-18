from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalStatus
from ai_novel_studio.harness.run_engine import (
    HarnessRunEngine,
    RunCancelledError,
    RunQueuedError,
)
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _engine(tmp_path: Path) -> HarnessRunEngine:
    project = ProjectRepository.create(tmp_path / "novel", "Run engine")
    return HarnessRunEngine(project)


def test_start_records_run_and_token(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run, created = engine.start("写第三章")

    assert run.stage is RunStage.CREATED
    assert created.event_type is RunEventType.RUN_CREATED
    assert engine.cancelled(run.id) is False
    assert engine.run_stage(run.id) is RunStage.CREATED


def test_queue_gate_blocks_second_run(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run, _ = engine.start("第一个")
    engine.transition(run.id, RunStage.MODEL_RUNNING)

    with pytest.raises(RunQueuedError):
        engine.start("第二个")


def test_cancel_closes_run_and_rejects_actions(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run, _ = engine.start("要取消的任务")
    engine.cancel(run.id)

    assert engine.run_stage(run.id) is RunStage.CANCELLED
    assert engine.cancelled(run.id) is True


def test_approval_flow_through_engine(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run, _ = engine.start("提交变更")
    request = engine.request_approval(
        run.id,
        ApprovalKind.CHANGESET,
        "替换开场",
        idempotency_key="key-1",
    )

    assert engine.run_stage(run.id) is RunStage.WAITING_APPROVAL
    # pending approval means a healthy WAITING state; completion must be gated
    assert engine.can_complete(run.id).ok is False

    resolved = engine.resolve_approval(request.request_id, approved=True)
    assert resolved.status is ApprovalStatus.APPROVED


def test_completion_gate_and_projections(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run, _ = engine.start("干净完成")

    assert engine.can_complete(run.id).ok is True
    engine.transition(run.id, RunStage.COMPLETED)
    assert engine.check_completion(run.id).ok is True
    assert engine.projections.status(run.id).stage is RunStage.COMPLETED


def test_compile_step_is_optional_and_callable(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run, _ = engine.start("编译")
    with pytest.raises(RuntimeError):
        engine.compile_step(run.id)

    seen: list[str] = []

    def step(run: object) -> object:
        seen.append(run.id)
        return {"ok": True}

    project = ProjectRepository.open(tmp_path / "novel")
    wired = HarnessRunEngine(project, compile_step=step)
    wired_run, _ = wired.start("编译2")
    result = wired.compile_step(wired_run.id)
    assert result == {"ok": True}
    assert seen == [wired_run.id]


def test_recover_open_runs_reattaches_cancel_tokens(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Run engine")
    engine = HarnessRunEngine(project)
    run, _ = engine.start("重启前的任务")
    engine.transition(run.id, RunStage.MODEL_RUNNING)

    reopened = HarnessRunEngine(ProjectRepository.open(tmp_path / "novel"))
    with pytest.raises(RunCancelledError):
        reopened.cancel(run.id)

    recovered = reopened.recover_open_runs()
    assert [item.id for item in recovered] == [run.id]
    assert reopened.cancel(run.id).stage is RunStage.CANCELLED
    assert reopened.cancelled(run.id) is True


def test_recover_open_runs_skips_closed_runs(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Run engine")
    engine = HarnessRunEngine(project)
    run, _ = engine.start("已完成的任务")
    engine.transition(run.id, RunStage.COMPLETED)

    reopened = HarnessRunEngine(ProjectRepository.open(tmp_path / "novel"))

    assert reopened.recover_open_runs() == ()
    with pytest.raises(RunCancelledError):
        reopened.cancel(run.id)
