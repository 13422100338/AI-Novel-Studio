from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approvals import ApprovalStatus
from ai_novel_studio.harness.artifacts import Artifact, ArtifactKind, ArtifactStore
from ai_novel_studio.harness.conversation_summary import ConversationSummary, SummaryRevision
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_state import RunEventType, RunStage


@dataclass(frozen=True, slots=True)
class CompactionDecision:
    run_id: str
    allowed: bool
    reason: str | None = None


class CompactionGate:
    """Forbidden-state guard for conversation compaction (design §19).

    Compaction must never run while the model is streaming, approvals are
    unstable, or the run is closed; the trigger conditions (budget pressure,
    stage end, topic switch, author request, idle) are caller-side.
    """

    def __init__(self, store: HarnessEventStore, approvals: ApprovalRepository) -> None:
        self._store = store
        self._approvals = approvals

    def evaluate(self, run_id: str) -> CompactionDecision:
        run = self._store.get_run(run_id)
        if run.stage is RunStage.MODEL_RUNNING:
            return CompactionDecision(run_id, False, "model is streaming")
        if self._open_tool_call(run_id):
            return CompactionDecision(run_id, False, "a tool call is still open")
        pending = any(
            request.status is ApprovalStatus.PENDING
            for request in self._approvals.list_for_run(run_id)
        )
        if pending:
            return CompactionDecision(run_id, False, "approvals are pending")
        if self._commit_may_be_in_flight(run_id, run.stage):
            return CompactionDecision(run_id, False, "a backend commit may be in flight")
        if run.stage in {RunStage.COMPLETED, RunStage.CANCELLED, RunStage.FAILED}:
            return CompactionDecision(run_id, False, f"run is closed at {run.stage.value}")
        return CompactionDecision(run_id, True)

    def _open_tool_call(self, run_id: str) -> bool:
        started = 0
        finished = 0
        for event in self._store.replay(run_id):
            if event.event_type is RunEventType.TOOL_CALL_STARTED:
                started += 1
            elif event.event_type in {
                RunEventType.TOOL_CALL_COMPLETED,
                RunEventType.TOOL_CALL_FAILED,
            }:
                finished += 1
        return started > finished

    def _commit_may_be_in_flight(self, run_id: str, stage: RunStage) -> bool:
        if stage in {RunStage.COMPLETED, RunStage.CANCELLED, RunStage.FAILED}:
            return False
        for event in reversed(self._store.replay(run_id)):
            if event.event_type is RunEventType.APPROVAL_RESOLVED:
                return bool(event.payload.get("approved"))
        return False


def build_program_skeleton(
    approvals: ApprovalRepository, run_id: str
) -> ConversationSummary:
    """Program-extracted non-lossy summary fields (design §18).

    The deterministic half of compaction: resolved approval summaries become
    confirmed decisions / rejected options and author notes become rationale.
    Fields without a deterministic source stay empty; the main agent fills
    the natural-language parts later.
    """
    confirmed: list[str] = []
    rejected: list[str] = []
    rationale: list[str] = []
    for request in approvals.list_for_run(run_id):
        if request.status is ApprovalStatus.APPROVED:
            confirmed.append(request.summary)
        elif request.status is ApprovalStatus.REJECTED:
            rejected.append(request.summary)
        if request.resolution_note:
            rationale.append(request.resolution_note)
    return ConversationSummary(
        confirmed_decisions=tuple(confirmed),
        rejected_options=tuple(rejected),
        important_rationale=tuple(rationale),
    )


def persist_summary_revision(
    artifacts: ArtifactStore,
    run_id: str,
    revision: SummaryRevision,
) -> Artifact:
    """Store one summary revision as a content-addressed artifact."""
    return artifacts.put(
        ArtifactKind.SUMMARY_REVISION,
        run_id,
        revision.summary.to_json().encode("utf-8"),
        content_type="application/json",
    )
