from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from ai_novel_studio.harness.run_state import (
    CLOSED_STAGES,
    HarnessRun,
    RunEvent,
    RunEventType,
    RunStage,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _run(goal: str = "write the opening chapter") -> HarnessRun:
    now = _now()
    return HarnessRun(
        id="run-1",
        goal=goal,
        stage=RunStage.CREATED,
        active_chapter_id=None,
        failure_code=None,
        failure_message=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )


def _event(
    event_type: RunEventType = RunEventType.CONTEXT_COMPILED,
    *,
    sequence: int = 1,
    schema_version: int = 1,
    payload: dict[str, object] | None = None,
) -> RunEvent:
    return RunEvent(
        event_id="event-1",
        run_id="run-1",
        sequence=sequence,
        event_type=event_type,
        schema_version=schema_version,
        occurred_at=_now(),
        causation_id=None,
        correlation_id=None,
        payload=payload if payload is not None else {},
    )


def test_run_stage_vocabulary_matches_design() -> None:
    assert {stage.value for stage in RunStage} == {
        "CREATED",
        "TASK_ANALYZED",
        "CONTEXT_COMPILED",
        "PACKAGE_READY",
        "MODEL_RUNNING",
        "DRAFT_SAVED",
        "AUDIT_COMPLETED",
        "CHANGESET_READY",
        "WAITING_APPROVAL",
        "COMPLETED",
        "CANCELLED",
        "INTERRUPTED",
        "FAILED",
        "STALE",
    }


def test_closed_stages_are_terminal_but_interrupted_is_recoverable() -> None:
    assert CLOSED_STAGES == frozenset({RunStage.COMPLETED, RunStage.CANCELLED, RunStage.FAILED})
    assert RunStage.INTERRUPTED not in CLOSED_STAGES
    assert RunStage.STALE not in CLOSED_STAGES


def test_run_event_vocabulary_matches_design() -> None:
    assert {event.value for event in RunEventType} == {
        "RUN_CREATED",
        "RUN_STARTED",
        "RUN_CANCELLED",
        "RUN_INTERRUPTED",
        "RUN_FAILED",
        "RUN_COMPLETED",
        "CONTEXT_COMPILATION_STARTED",
        "CONTEXT_COMPILED",
        "CONTEXT_INVALIDATED",
        "CONTEXT_EXTENSION_REQUESTED",
        "CONTEXT_RECOMPILE_REQUESTED",
        "CONTEXT_HEALTH_CHANGED",
        "MANUAL_CONTEXT_PIN_ADDED",
        "MANUAL_CONTEXT_PIN_REMOVED",
        "COMPACTION_STARTED",
        "COMPACTION_COMPLETED",
        "SKILL_DISCOVERED",
        "SKILL_LOADED",
        "TOOL_SCHEMA_LOADED",
        "TOOL_CALL_STARTED",
        "TOOL_CALL_COMPLETED",
        "TOOL_CALL_FAILED",
        "GENERATION_PACKAGE_READY",
        "CHAPTER_STREAM_STARTED",
        "CHAPTER_STREAM_DELTA",
        "CHAPTER_STREAM_CHECKPOINT_SAVED",
        "CHAPTER_STREAM_COMPLETED",
        "AUDIT_STARTED",
        "AUDIT_COMPLETED",
        "CHANGESET_READY",
        "CHANGESET_REBASED",
        "CHANGESET_CONFLICTED",
        "APPROVAL_REQUESTED",
        "APPROVAL_RESOLVED",
        "APPROVAL_EXECUTION_FINALIZED",
    }


def test_harness_run_normalizes_text_fields() -> None:
    run = HarnessRun(
        id="  run-1  ",
        goal="  draft it  ",
        stage=RunStage.CREATED,
        active_chapter_id="  ",
        failure_code="  ",
        failure_message="  ",
        created_at=_now(),
        updated_at=_now(),
        completed_at=None,
    )
    assert run.id == "run-1"
    assert run.goal == "draft it"
    assert run.active_chapter_id is None
    assert run.failure_code is None
    assert run.failure_message is None


def test_harness_run_rejects_empty_goal() -> None:
    with pytest.raises(ValueError):
        _run(goal="   ")


def test_harness_run_rejects_non_stage_value() -> None:
    now = _now()
    with pytest.raises(ValueError):
        HarnessRun(
            id="run-1",
            goal="goal",
            stage="CREATED",
            active_chapter_id=None,
            failure_code=None,
            failure_message=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )


def test_run_event_rejects_negative_sequence() -> None:
    with pytest.raises(ValueError):
        _event(sequence=-1)


def test_run_event_rejects_non_positive_schema_version() -> None:
    with pytest.raises(ValueError):
        _event(schema_version=0)


def test_run_event_rejects_non_event_type() -> None:
    with pytest.raises(ValueError):
        RunEvent(
            event_id="event-1",
            run_id="run-1",
            sequence=1,
            event_type="CONTEXT_COMPILED",
            schema_version=1,
            occurred_at=_now(),
            causation_id=None,
            correlation_id=None,
            payload={},
        )


def test_run_event_rejects_non_json_payload() -> None:
    with pytest.raises(ValueError):
        _event(payload={"bad": object()})


def test_run_event_is_frozen() -> None:
    event = _event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.sequence = 99


def test_legacy_approval_resolved_v1_remains_decision_only() -> None:
    event = _event(
        RunEventType.APPROVAL_RESOLVED,
        schema_version=1,
        payload={"request_id": "approval-1", "approved": True},
    )

    assert event.payload == {"request_id": "approval-1", "approved": True}
    assert "disposition" not in event.payload
    assert event.schema_version == 1


def test_execution_finalized_is_a_separate_event_type() -> None:
    event = _event(
        RunEventType.APPROVAL_EXECUTION_FINALIZED,
        schema_version=1,
        payload={
            "request_id": "approval-1",
            "disposition": "FAILED",
            "receipt_revision": 2,
            "evidence_refs": [],
            "failure_class": "INTEGRITY",
            "failure_code": "MISSING_OUTCOME",
        },
    )

    assert event.event_type is RunEventType.APPROVAL_EXECUTION_FINALIZED
    assert event.payload["disposition"] == "FAILED"
