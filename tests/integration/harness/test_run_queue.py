from __future__ import annotations

from pathlib import Path

from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_queue import QueueDecision, RunQueueGate
from ai_novel_studio.harness.run_state import RunStage
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _store(tmp_path: Path) -> HarnessEventStore:
    project = ProjectRepository.create(tmp_path / "novel", "Queue Test")
    return HarnessEventStore(HarnessEventRepository(project))


def test_empty_project_allows_start(tmp_path: Path) -> None:
    gate = RunQueueGate(_store(tmp_path))
    result = gate.evaluate()
    assert result.decision is QueueDecision.START
    assert result.executing_run_count == 0


def test_one_executing_run_queues_next(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="drafting now")
    store.transition(run.id, RunStage.MODEL_RUNNING)

    result = RunQueueGate(store).evaluate()
    assert result.decision is QueueDecision.QUEUE
    assert result.executing_run_count == 1


def test_terminal_runs_do_not_block(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for stage in (
        RunStage.COMPLETED,
        RunStage.CANCELLED,
        RunStage.FAILED,
        RunStage.CREATED,
    ):
        run, _ = store.start_run(goal=f"stage {stage.value}")
        store.transition(run.id, stage)

    result = RunQueueGate(store).evaluate()
    assert result.decision is QueueDecision.START
    assert result.executing_run_count == 0


def test_waiting_approval_counts_as_executing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="waiting for the author")
    store.transition(run.id, RunStage.WAITING_APPROVAL)

    result = RunQueueGate(store).evaluate()
    assert result.decision is QueueDecision.QUEUE


def test_interrupted_run_releases_the_queue(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="interrupted")
    store.transition(run.id, RunStage.INTERRUPTED)

    result = RunQueueGate(store).evaluate()
    assert result.decision is QueueDecision.START
