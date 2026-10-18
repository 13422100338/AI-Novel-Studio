from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_state import RunStage


class QueueDecision(StrEnum):
    START = "START"
    QUEUE = "QUEUE"


# Stages that count as "a formal model/tool run executing" (design v0.3 §58).
_EXECUTION_STAGES = frozenset(
    {
        RunStage.TASK_ANALYZED,
        RunStage.CONTEXT_COMPILED,
        RunStage.PACKAGE_READY,
        RunStage.MODEL_RUNNING,
        RunStage.DRAFT_SAVED,
        RunStage.AUDIT_COMPLETED,
        RunStage.CHANGESET_READY,
        RunStage.WAITING_APPROVAL,
    }
)


@dataclass(frozen=True, slots=True)
class QueueResult:
    decision: QueueDecision
    executing_run_count: int


class RunQueueGate:
    """V1 concurrency rule: at most one formal run executes (design v0.3 §58).

    Ordinary chat and background maintenance may continue; a new formal run
    starts only when no other run is in an execution stage. The gate is the
    deterministic revalidation before starting or resuming a queued run.
    """

    def __init__(self, store: HarnessEventStore) -> None:
        self._store = store

    def evaluate(self) -> QueueResult:
        executing = [
            run
            for run in self._store.list_runs()
            if run.stage in _EXECUTION_STAGES
        ]
        decision = QueueDecision.QUEUE if executing else QueueDecision.START
        return QueueResult(decision=decision, executing_run_count=len(executing))
