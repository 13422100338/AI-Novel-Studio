from __future__ import annotations

from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.run_state import (
    CLOSED_STAGES,
    HarnessRun,
    RunEvent,
    RunEventType,
    RunStage,
    validate_transition,
)


class HarnessRunClosedError(RuntimeError):
    """The run is closed and rejects further events or stage changes."""


class HarnessEventIdempotencyError(ValueError):
    """A caller-supplied event_id collides with a different persisted event."""


class HarnessEventStore:
    """Harness-owned policy boundary over the append-only run event repository.

    This is the only writer of run lifecycle facts (design v0.3 §52-§57): it
    reserves the RUN_CREATED event for start_run, rejects late events once a
    run reaches a closed stage, keeps caller-supplied event ids idempotent, and
    guarantees strict per-run sequence ordering through replay.
    """

    def __init__(self, repository: HarnessEventRepository) -> None:
        self._repository = repository

    def start_run(
        self, *, goal: str, active_chapter_id: str | None = None
    ) -> tuple[HarnessRun, RunEvent]:
        return self._repository.start_run(goal=goal, active_chapter_id=active_chapter_id)

    def get_run(self, run_id: str) -> HarnessRun:
        return self._repository.get_run(run_id)
    def list_runs(self) -> tuple[HarnessRun, ...]:
        return self._repository.list_runs()


    def transition(
        self,
        run_id: str,
        stage: RunStage,
        *,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> HarnessRun:
        run = self._repository.get_run(run_id)
        if run.stage in CLOSED_STAGES:
            if stage is run.stage:
                return run
            raise HarnessRunClosedError(
                f"run {run_id} is closed at stage {run.stage.value}; "
                f"cannot move to {stage.value}"
            )
        validate_transition(run.stage, stage)
        return self._repository.set_stage(
            run_id,
            stage,
            failure_code=failure_code,
            failure_message=failure_message,
        )

    def append(
        self,
        run_id: str,
        event_type: RunEventType,
        payload: dict[str, object] | None = None,
        *,
        schema_version: int = 1,
        causation_id: str | None = None,
        correlation_id: str | None = None,
        event_id: str | None = None,
    ) -> RunEvent:
        if event_type is RunEventType.RUN_CREATED:
            raise ValueError("RUN_CREATED events are reserved for start_run")
        run = self._repository.get_run(run_id)
        if run.stage in CLOSED_STAGES:
            raise HarnessRunClosedError(
                f"run {run_id} is closed at stage {run.stage.value}; "
                "late events are rejected"
            )
        if event_id is not None:
            try:
                existing = self._repository.get_event(event_id)
            except KeyError:
                pass
            else:
                if existing.run_id != run_id or existing.event_type is not event_type:
                    raise HarnessEventIdempotencyError(
                        f"event_id {event_id} is already bound to a different event"
                    )
                return existing
        return self._repository.insert_event(
            run_id,
            event_type,
            payload if payload is not None else {},
            schema_version=schema_version,
            causation_id=causation_id,
            correlation_id=correlation_id,
            event_id=event_id,
        )

    def replay(self, run_id: str) -> tuple[RunEvent, ...]:
        return self._repository.list_events(run_id)
