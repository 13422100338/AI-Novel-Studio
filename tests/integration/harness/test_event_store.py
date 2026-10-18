from pathlib import Path

import pytest

from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import (
    HarnessEventIdempotencyError,
    HarnessEventStore,
    HarnessRunClosedError,
)
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _store(tmp_path: Path) -> HarnessEventStore:
    project = ProjectRepository.create(tmp_path / "novel", "Harness Event Store")
    return HarnessEventStore(HarnessEventRepository(project))


def test_start_run_creates_run_and_reserved_initial_event(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, created = store.start_run(goal="draft chapter three")

    assert run.stage is RunStage.CREATED
    assert run.goal == "draft chapter three"
    assert created.sequence == 0
    assert created.event_type is RunEventType.RUN_CREATED
    assert store.replay(run.id) == (created,)


def test_append_assigns_strict_sequences_and_replays_in_order(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, created = store.start_run(goal="plan the scene")

    first = store.append(run.id, RunEventType.CONTEXT_COMPILATION_STARTED, {"chapter_id": "c1"})
    second = store.append(run.id, RunEventType.CONTEXT_COMPILED, {"manifest_id": "m1"})

    assert (created.sequence, first.sequence, second.sequence) == (0, 1, 2)
    assert store.replay(run.id) == (created, first, second)
    assert second.payload == {"manifest_id": "m1"}


def test_events_survive_repository_recreation(tmp_path: Path) -> None:
    root = tmp_path / "novel"
    project = ProjectRepository.create(root, "Harness Event Store")
    store = HarnessEventStore(HarnessEventRepository(project))
    run, _ = store.start_run(goal="recover me")
    store.append(run.id, RunEventType.CONTEXT_COMPILED, {"manifest_id": "m1"})

    reopened = HarnessEventStore(HarnessEventRepository(ProjectRepository.open(root)))
    assert reopened.replay(run.id) == store.replay(run.id)
    assert reopened.get_run(run.id).stage is RunStage.CREATED


def test_append_with_supplied_event_id_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="idempotent append")

    event = store.append(run.id, RunEventType.CONTEXT_COMPILED, event_id="fixed-event")
    again = store.append(run.id, RunEventType.CONTEXT_COMPILED, event_id="fixed-event")

    assert again == event
    assert store.replay(run.id)[-1].sequence == 1


def test_append_rejects_event_id_reuse_for_other_run_or_type(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run_a, _ = store.start_run(goal="first")
    run_b, _ = store.start_run(goal="second")
    store.append(run_a.id, RunEventType.CONTEXT_COMPILED, event_id="dup")

    with pytest.raises(HarnessEventIdempotencyError):
        store.append(run_b.id, RunEventType.CONTEXT_COMPILED, event_id="dup")
    with pytest.raises(HarnessEventIdempotencyError):
        store.append(run_a.id, RunEventType.AUDIT_STARTED, event_id="dup")


def test_append_rejected_after_run_is_cancelled(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="cancel me")
    store.transition(run.id, RunStage.CANCELLED)

    with pytest.raises(HarnessRunClosedError):
        store.append(run.id, RunEventType.CONTEXT_COMPILED)


def test_interrupted_run_accepts_events_and_can_resume(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="resume me")
    store.transition(run.id, RunStage.INTERRUPTED)
    store.append(run.id, RunEventType.CONTEXT_RECOMPILE_REQUESTED)

    resumed = store.transition(run.id, RunStage.CONTEXT_COMPILED)
    assert resumed.stage is RunStage.CONTEXT_COMPILED


def test_cancelled_run_cannot_leave_closed_stage(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="no resurrection")
    store.transition(run.id, RunStage.CANCELLED)

    with pytest.raises(HarnessRunClosedError):
        store.transition(run.id, RunStage.MODEL_RUNNING)
    # no-op transition to the same closed stage is allowed
    assert store.transition(run.id, RunStage.CANCELLED).stage is RunStage.CANCELLED


def test_terminal_transition_stamps_completed_at_and_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="fail me")

    failed = store.transition(
        run.id, RunStage.FAILED, failure_code="PROVIDER_ERROR", failure_message="boom"
    )
    assert failed.completed_at is not None
    assert failed.failure_code == "PROVIDER_ERROR"
    assert failed.failure_message == "boom"


def test_run_created_event_type_is_reserved(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="reserved event")

    with pytest.raises(ValueError):
        store.append(run.id, RunEventType.RUN_CREATED)


def test_unknown_run_raises_key_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(KeyError):
        store.append("missing-run", RunEventType.CONTEXT_COMPILED)


def test_illegal_open_transition_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="illegal edge")
    store.transition(run.id, RunStage.MODEL_RUNNING)

    with pytest.raises(ValueError, match="illegal stage transition"):
        store.transition(run.id, RunStage.AUDIT_COMPLETED)
    assert store.get_run(run.id).stage is RunStage.MODEL_RUNNING
    store.transition(run.id, RunStage.DRAFT_SAVED)


def test_stale_run_can_recompile(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="stale recovery")
    store.transition(run.id, RunStage.STALE)

    assert store.transition(run.id, RunStage.CONTEXT_COMPILED).stage is (RunStage.CONTEXT_COMPILED)


def test_replay_preserves_legacy_decision_and_separate_execution_event(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="replay approval evidence")
    decision = store.append(
        run.id,
        RunEventType.APPROVAL_RESOLVED,
        {"request_id": "approval-1", "approved": True},
        schema_version=1,
        correlation_id="approval-1",
        event_id="decision-event-1",
    )
    execution = store.append(
        run.id,
        RunEventType.APPROVAL_EXECUTION_FINALIZED,
        {
            "request_id": "approval-1",
            "disposition": "FAILED",
            "receipt_revision": 2,
            "evidence_refs": [],
            "failure_class": "INTEGRITY",
            "failure_code": "MISSING_OUTCOME",
        },
        schema_version=1,
        causation_id=decision.event_id,
        correlation_id="approval-1",
        event_id="execution-event-1",
    )

    replayed = store.replay(run.id)
    assert replayed[-2:] == (decision, execution)
    assert replayed[-2].payload == {"request_id": "approval-1", "approved": True}
    assert "disposition" not in replayed[-2].payload
    assert replayed[-1].event_type is RunEventType.APPROVAL_EXECUTION_FINALIZED
