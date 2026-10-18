from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approvals import ApprovalRequest, ApprovalStatus
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_state import RunEventType, RunStage


@dataclass(frozen=True, slots=True)
class CompletionCheckResult:
    run_id: str
    ok: bool
    failures: tuple[str, ...]


class CompletionChecker:
    """Program-side completion gate (design v0.3 §57).

    The deterministic half of completion checking: approvals, failed tool
    calls and stage consistency. The agent-side coverage review (request
    coverage, assumptions, knowledge boundaries) is a later ticket.
    """

    def __init__(self, store: HarnessEventStore, approvals: ApprovalRepository) -> None:
        self._store = store
        self._approvals = approvals

    def check(self, run_id: str) -> CompletionCheckResult:
        """Post-hoc audit: a COMPLETED run must carry no open obligations."""
        failures: list[str] = []
        run = self._store.get_run(run_id)
        pending = self._pending(run_id)
        failed_calls = [
            event
            for event in self._store.replay(run_id)
            if event.event_type is RunEventType.TOOL_CALL_FAILED
        ]
        if pending and run.stage is RunStage.COMPLETED:
            failures.append("run is COMPLETED with pending approvals")
        if run.stage is RunStage.WAITING_APPROVAL and not pending:
            failures.append("run is WAITING_APPROVAL without pending approvals")
        if run.stage is RunStage.COMPLETED and failed_calls:
            failures.append("run is COMPLETED with failed tool calls")
        return CompletionCheckResult(run_id=run_id, ok=not failures, failures=tuple(failures))

    def can_complete(self, run_id: str) -> CompletionCheckResult:
        """Gate for transitioning a run to COMPLETED."""
        failures: list[str] = []
        run = self._store.get_run(run_id)
        if run.stage in {RunStage.CANCELLED, RunStage.FAILED}:
            failures.append(f"run is closed at stage {run.stage.value}")
        if self._pending(run_id):
            failures.append("pending approvals must be resolved before COMPLETED")
        return CompletionCheckResult(run_id=run_id, ok=not failures, failures=tuple(failures))

    def _pending(self, run_id: str) -> tuple[ApprovalRequest, ...]:
        return tuple(
            request
            for request in self._approvals.list_for_run(run_id)
            if request.status is ApprovalStatus.PENDING
        )
