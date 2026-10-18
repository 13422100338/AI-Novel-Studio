from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RunStage(StrEnum):
    """Lifecycle stages of a Harness AgentRun (design v0.3 §52)."""

    CREATED = "CREATED"
    TASK_ANALYZED = "TASK_ANALYZED"
    CONTEXT_COMPILED = "CONTEXT_COMPILED"
    PACKAGE_READY = "PACKAGE_READY"
    MODEL_RUNNING = "MODEL_RUNNING"
    DRAFT_SAVED = "DRAFT_SAVED"
    AUDIT_COMPLETED = "AUDIT_COMPLETED"
    CHANGESET_READY = "CHANGESET_READY"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"
    STALE = "STALE"


# Stages after which the run entry is closed: no further events may be appended
# and the stage can no longer change (design v0.3 §54). INTERRUPTED and STALE
# stay open so recovery can continue the run (design v0.3 §55).
CLOSED_STAGES = frozenset({RunStage.COMPLETED, RunStage.CANCELLED, RunStage.FAILED})

# Legal open-stage transitions (design v0.3 §52). CREATED is the queue-gated
# entry and may jump straight into any task stage; the chain stages advance
# linearly or abort; INTERRUPTED/STALE stay open for recovery and re-enter
# the chain from the top (design §55). Closed stages are terminal and only
# re-enter themselves (enforced by the event store).
_ABORT_TARGETS = frozenset(
    {
        RunStage.CANCELLED,
        RunStage.INTERRUPTED,
        RunStage.STALE,
        RunStage.FAILED,
    }
)

LEGAL_TRANSITIONS: dict[RunStage, frozenset[RunStage]] = {
    RunStage.CREATED: frozenset(RunStage) - frozenset({RunStage.CREATED}),
    RunStage.TASK_ANALYZED: frozenset({RunStage.CONTEXT_COMPILED, RunStage.WAITING_APPROVAL})
    | _ABORT_TARGETS,
    RunStage.CONTEXT_COMPILED: frozenset({RunStage.PACKAGE_READY, RunStage.WAITING_APPROVAL})
    | _ABORT_TARGETS,
    RunStage.PACKAGE_READY: frozenset({RunStage.MODEL_RUNNING, RunStage.WAITING_APPROVAL})
    | _ABORT_TARGETS,
    RunStage.MODEL_RUNNING: frozenset({RunStage.DRAFT_SAVED}) | _ABORT_TARGETS,
    RunStage.DRAFT_SAVED: frozenset({RunStage.AUDIT_COMPLETED, RunStage.WAITING_APPROVAL})
    | _ABORT_TARGETS,
    RunStage.AUDIT_COMPLETED: frozenset({RunStage.CHANGESET_READY, RunStage.WAITING_APPROVAL})
    | _ABORT_TARGETS,
    RunStage.CHANGESET_READY: frozenset({RunStage.WAITING_APPROVAL}) | _ABORT_TARGETS,
    RunStage.WAITING_APPROVAL: frozenset(
        {
            RunStage.COMPLETED,
            RunStage.CANCELLED,
            RunStage.INTERRUPTED,
            RunStage.STALE,
            RunStage.FAILED,
        }
    ),
    RunStage.INTERRUPTED: frozenset(
        {
            RunStage.TASK_ANALYZED,
            RunStage.CONTEXT_COMPILED,
            RunStage.WAITING_APPROVAL,
            RunStage.CANCELLED,
            RunStage.FAILED,
        }
    ),
    RunStage.STALE: frozenset(
        {
            RunStage.TASK_ANALYZED,
            RunStage.CONTEXT_COMPILED,
            RunStage.WAITING_APPROVAL,
            RunStage.CANCELLED,
            RunStage.FAILED,
        }
    ),
}


def validate_transition(current: RunStage, target: RunStage) -> None:
    """Deterministic state-machine edge check (design §52)."""
    if not isinstance(current, RunStage) or not isinstance(target, RunStage):
        raise ValueError("stages must be RunStage values")
    if current is target:
        return
    if target not in LEGAL_TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"illegal stage transition: {current.value} -> {target.value}")


class RunEventType(StrEnum):
    """Immutable Harness event vocabulary (design v0.3 §63)."""

    RUN_CREATED = "RUN_CREATED"
    RUN_STARTED = "RUN_STARTED"
    RUN_CANCELLED = "RUN_CANCELLED"
    RUN_INTERRUPTED = "RUN_INTERRUPTED"
    RUN_FAILED = "RUN_FAILED"
    RUN_COMPLETED = "RUN_COMPLETED"
    CONTEXT_COMPILATION_STARTED = "CONTEXT_COMPILATION_STARTED"
    CONTEXT_COMPILED = "CONTEXT_COMPILED"
    CONTEXT_INVALIDATED = "CONTEXT_INVALIDATED"
    CONTEXT_EXTENSION_REQUESTED = "CONTEXT_EXTENSION_REQUESTED"
    CONTEXT_RECOMPILE_REQUESTED = "CONTEXT_RECOMPILE_REQUESTED"
    CONTEXT_HEALTH_CHANGED = "CONTEXT_HEALTH_CHANGED"
    MANUAL_CONTEXT_PIN_ADDED = "MANUAL_CONTEXT_PIN_ADDED"
    MANUAL_CONTEXT_PIN_REMOVED = "MANUAL_CONTEXT_PIN_REMOVED"
    COMPACTION_STARTED = "COMPACTION_STARTED"
    COMPACTION_COMPLETED = "COMPACTION_COMPLETED"
    SKILL_DISCOVERED = "SKILL_DISCOVERED"
    SKILL_LOADED = "SKILL_LOADED"
    TOOL_SCHEMA_LOADED = "TOOL_SCHEMA_LOADED"
    TOOL_CALL_STARTED = "TOOL_CALL_STARTED"
    TOOL_CALL_COMPLETED = "TOOL_CALL_COMPLETED"
    TOOL_CALL_FAILED = "TOOL_CALL_FAILED"
    GENERATION_PACKAGE_READY = "GENERATION_PACKAGE_READY"
    CHAPTER_STREAM_STARTED = "CHAPTER_STREAM_STARTED"
    CHAPTER_STREAM_DELTA = "CHAPTER_STREAM_DELTA"
    CHAPTER_STREAM_CHECKPOINT_SAVED = "CHAPTER_STREAM_CHECKPOINT_SAVED"
    CHAPTER_STREAM_COMPLETED = "CHAPTER_STREAM_COMPLETED"
    AUDIT_STARTED = "AUDIT_STARTED"
    AUDIT_COMPLETED = "AUDIT_COMPLETED"
    CHANGESET_READY = "CHANGESET_READY"
    CHANGESET_REBASED = "CHANGESET_REBASED"
    CHANGESET_CONFLICTED = "CHANGESET_CONFLICTED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_RESOLVED = "APPROVAL_RESOLVED"
    APPROVAL_EXECUTION_FINALIZED = "APPROVAL_EXECUTION_FINALIZED"


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _non_negative(value: int, field: str) -> int:
    if value < 0:
        raise ValueError(f"{field} cannot be negative")
    return value


def _positive(value: int, field: str) -> int:
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _validate_payload(value: dict[str, object]) -> dict[str, object]:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must be JSON-serializable") from exc
    return value


@dataclass(frozen=True, slots=True)
class HarnessRun:
    """A Harness-owned orchestration run (design v0.3 §14, §52).

    Unlike the legacy Phase-7 AgentRun (bounded read-only tool loop), this
    record owns the full generation pipeline lifecycle. It never holds domain
    truth; the backend owns novel facts, plans, and states.
    """

    id: str
    goal: str
    stage: RunStage
    active_chapter_id: str | None
    failure_code: str | None
    failure_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required(self.id, "id"))
        object.__setattr__(self, "goal", _required(self.goal, "goal"))
        if not isinstance(self.stage, RunStage):
            raise ValueError("stage must be a RunStage")
        object.__setattr__(self, "active_chapter_id", _optional_text(self.active_chapter_id))
        object.__setattr__(self, "failure_code", _optional_text(self.failure_code))
        object.__setattr__(self, "failure_message", _optional_text(self.failure_message))


@dataclass(frozen=True, slots=True)
class RunEvent:
    """Immutable append-only event on a Harness run (design v0.3 §63, §64)."""

    event_id: str
    run_id: str
    sequence: int
    event_type: RunEventType
    schema_version: int
    occurred_at: datetime
    causation_id: str | None
    correlation_id: str | None
    payload: dict[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _required(self.event_id, "event_id"))
        object.__setattr__(self, "run_id", _required(self.run_id, "run_id"))
        object.__setattr__(self, "sequence", _non_negative(self.sequence, "sequence"))
        if not isinstance(self.event_type, RunEventType):
            raise ValueError("event_type must be a RunEventType")
        object.__setattr__(self, "schema_version", _positive(self.schema_version, "schema_version"))
        object.__setattr__(self, "causation_id", _optional_text(self.causation_id))
        object.__setattr__(self, "correlation_id", _optional_text(self.correlation_id))
        object.__setattr__(self, "payload", _validate_payload(self.payload))
