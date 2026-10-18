from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approvals import ApprovalRequest, ApprovalStatus
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_state import HarnessRun, RunEvent, RunEventType, RunStage
from ai_novel_studio.harness.state_capsule import (
    AgentStateCapsule,
    ContextHealth,
    OptimizationStatus,
)
from ai_novel_studio.harness.usage_meter import HarnessUsageMeter, RoleUsage


@dataclass(frozen=True, slots=True)
class RunStatusProjection:
    """Read-only run status for the UI (design v0.3 §64)."""

    run_id: str
    goal: str
    stage: RunStage
    active_chapter_id: str | None
    failure_code: str | None
    failure_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    event_count: int
    last_sequence: int | None


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """One ordered event summary without sensitive payloads (design §64, §64.1)."""

    sequence: int
    event_type: RunEventType
    schema_version: int
    occurred_at: datetime
    causation_id: str | None
    correlation_id: str | None


@dataclass(frozen=True, slots=True)
class ProcessTimelineProjection:
    run_id: str
    entries: tuple[TimelineEntry, ...]


@dataclass(frozen=True, slots=True)
class UsageProjection:
    """Per-role usage figures with measurement labels (design v0.3 §66)."""

    run_id: str
    roles: tuple[RoleUsage, ...]


@dataclass(frozen=True, slots=True)
class RecoveryProjection:
    """What the recovery center needs to offer for one run (design v0.3 §55)."""

    run_id: str
    stage: RunStage
    resumable: bool
    recommended_actions: tuple[str, ...]
    event_count: int


@dataclass(frozen=True, slots=True)
class AgentContextStatusProjection:
    """Context status-bar view derived from run facts only (design §14, §64).

    The frontend renders this bar; it never infers domain state from chat
    text. All fields come from the run record, the event log, the approval
    repository and the usage meter.
    """

    run_id: str
    goal: str
    stage: RunStage
    active_chapter_id: str | None
    context_manifest_id: str | None
    context_health: ContextHealth
    optimization_status: OptimizationStatus
    context_budget: int | None
    evidence_hit_count: int | None
    included_categories: tuple[tuple[str, int], ...]
    draft_artifact_id: str | None
    draft_character_count: int | None
    draft_checkpoint_count: int
    pending_approvals: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    usage_roles: tuple[RoleUsage, ...]


def _latest(events: tuple[RunEvent, ...], event_type: RunEventType) -> RunEvent | None:
    for event in reversed(events):
        if event.event_type is event_type:
            return event
    return None


def _payload_text(event: RunEvent | None, key: str) -> str | None:
    if event is None:
        return None
    value = event.payload.get(key)
    return str(value) if isinstance(value, str) and value.strip() else None


def _payload_int(event: RunEvent | None, key: str) -> int | None:
    if event is None:
        return None
    value = event.payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _payload_texts(
    events: tuple[RunEvent, ...], event_type: RunEventType, key: str
) -> tuple[str, ...]:
    values: list[str] = []
    for event in events:
        if event.event_type is event_type:
            value = _payload_text(event, key)
            if value is not None and value not in values:
                values.append(value)
    return tuple(values)


def _payload_categories(
    event: RunEvent | None,
) -> tuple[tuple[str, int], ...]:
    if event is None:
        return ()
    raw = event.payload.get("included_categories")
    if not isinstance(raw, list):
        return ()
    categories: list[tuple[str, int]] = []
    for item in raw:
        if (
            isinstance(item, list)
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], int)
            and not isinstance(item[1], bool)
        ):
            categories.append((item[0], item[1]))
    return tuple(categories)


_RECOVERY_ACTIONS: dict[RunStage, tuple[str, ...]] = {
    RunStage.INTERRUPTED: ("RESUME_RUN",),
    RunStage.STALE: ("RECOMPILE_CONTEXT",),
    RunStage.WAITING_APPROVAL: ("RESTORE_APPROVAL_VIEW",),
}


class HarnessProjectionService:
    """Deterministic read-only projections over run facts (design §64).

    Projections are derived from the event log, the run record and the usage
    meter only - the frontend never infers domain state from chat text.
    """

    def __init__(
        self,
        store: HarnessEventStore,
        meter: HarnessUsageMeter | None = None,
        approvals: ApprovalRepository | None = None,
    ) -> None:
        self._store = store
        self._meter = meter
        self._approvals = approvals

    def status(self, run_id: str) -> RunStatusProjection:
        run = self._store.get_run(run_id)
        events = self._store.replay(run_id)
        return RunStatusProjection(
            run_id=run.id,
            goal=run.goal,
            stage=run.stage,
            active_chapter_id=run.active_chapter_id,
            failure_code=run.failure_code,
            failure_message=run.failure_message,
            created_at=run.created_at,
            updated_at=run.updated_at,
            completed_at=run.completed_at,
            event_count=len(events),
            last_sequence=events[-1].sequence if events else None,
        )

    def timeline(self, run_id: str) -> ProcessTimelineProjection:
        entries = tuple(
            TimelineEntry(
                sequence=event.sequence,
                event_type=event.event_type,
                schema_version=event.schema_version,
                occurred_at=event.occurred_at,
                causation_id=event.causation_id,
                correlation_id=event.correlation_id,
            )
            for event in self._store.replay(run_id)
        )
        return ProcessTimelineProjection(run_id=run_id, entries=entries)

    def usage(self, run_id: str) -> UsageProjection:
        roles = self._meter.snapshot() if self._meter is not None else ()
        return UsageProjection(run_id=run_id, roles=roles)

    def recovery(self, run_id: str) -> RecoveryProjection:
        run = self._store.get_run(run_id)
        events = self._store.replay(run_id)
        actions = _RECOVERY_ACTIONS.get(run.stage, ())
        return RecoveryProjection(
            run_id=run_id,
            stage=run.stage,
            resumable=bool(actions),
            recommended_actions=actions,
            event_count=len(events),
        )

    def recoverable_runs(self) -> tuple[RecoveryProjection, ...]:
        """Recovery-center data loop (design v0.3 §55): all resumable runs."""
        return tuple(
            projection
            for projection in (
                self.recovery(run.id) for run in self._store.list_runs()
            )
            if projection.resumable
        )

    def approvals(self, run_id: str) -> tuple[ApprovalRequest, ...]:
        """Approval-card data for the recovery center (design v0.3 §55)."""
        if self._approvals is None:
            return ()
        return self._approvals.list_for_run(run_id)

    def capsule(self, run_id: str) -> AgentStateCapsule:
        """Deterministic AgentStateCapsule from run facts (design v0.3 §14).

        The capsule is a derived snapshot, never persisted and never a second
        source of truth. Fields without an event producer yet stay None or
        empty rather than being invented.
        """
        run = self._store.get_run(run_id)
        events = self._store.replay(run_id)
        compiled = _latest(events, RunEventType.CONTEXT_COMPILED)
        package_ready = _latest(events, RunEventType.GENERATION_PACKAGE_READY)
        context_health = self._context_health(run, compiled)
        pending = (
            tuple(
                request.request_id
                for request in self._approvals.list_for_run(run_id)
                if request.status is ApprovalStatus.PENDING
            )
            if self._approvals is not None
            else ()
        )
        loaded_skills = _payload_texts(
            events, RunEventType.SKILL_LOADED, "skill_id"
        )
        loaded_tools = _payload_texts(
            events, RunEventType.TOOL_SCHEMA_LOADED, "tool_id"
        )
        return AgentStateCapsule(
            run_id=run.id,
            goal=run.goal,
            stage=run.stage,
            active_chapter_id=run.active_chapter_id,
            editor_snapshot_revision=_payload_int(
                package_ready, "editor_snapshot_revision"
            ),
            formal_revision=_payload_int(package_ready, "formal_revision"),
            context_manifest_id=_payload_text(compiled, "manifest_id"),
            conversation_summary_revision=None,
            last_model_request_manifest_id=None,
            context_health=context_health,
            optimization_status=self._optimization_status(run, compiled),
            pending_approvals=pending,
            loaded_skills=loaded_skills,
            loaded_tools=loaded_tools,
            context_budget=_payload_int(compiled, "estimated_input_tokens"),
        )

    def context_status(self, run_id: str) -> AgentContextStatusProjection:
        """Context status-bar projection: capsule plus manifest/draft/usage
        figures from the event log (design v0.3 §64, §66)."""
        capsule = self.capsule(run_id)
        events = self._store.replay(run_id)
        compiled = _latest(events, RunEventType.CONTEXT_COMPILED)
        completed = _latest(events, RunEventType.CHAPTER_STREAM_COMPLETED)
        checkpoints = sum(
            1
            for event in events
            if event.event_type is RunEventType.CHAPTER_STREAM_CHECKPOINT_SAVED
        )
        roles = self._meter.snapshot() if self._meter is not None else ()
        return AgentContextStatusProjection(
            run_id=capsule.run_id,
            goal=capsule.goal,
            stage=capsule.stage,
            active_chapter_id=capsule.active_chapter_id,
            context_manifest_id=capsule.context_manifest_id,
            context_health=capsule.context_health,
            optimization_status=capsule.optimization_status,
            context_budget=capsule.context_budget,
            evidence_hit_count=_payload_int(compiled, "evidence_hit_count"),
            included_categories=_payload_categories(compiled),
            draft_artifact_id=_payload_text(completed, "artifact_id"),
            draft_character_count=_payload_int(completed, "character_count"),
            draft_checkpoint_count=checkpoints,
            pending_approvals=capsule.pending_approvals,
            unresolved_questions=capsule.unresolved_questions,
            usage_roles=roles,
        )

    @staticmethod
    def _context_health(
        run: HarnessRun, compiled: RunEvent | None
    ) -> ContextHealth:
        if run.stage is RunStage.STALE:
            return ContextHealth.CRITICAL
        if compiled is None:
            return ContextHealth.UNKNOWN
        return ContextHealth.HEALTHY

    @staticmethod
    def _optimization_status(
        run: HarnessRun, compiled: RunEvent | None
    ) -> OptimizationStatus:
        if compiled is None:
            return OptimizationStatus.UNKNOWN
        if run.stage in {RunStage.STALE, RunStage.INTERRUPTED}:
            return OptimizationStatus.NEEDS_RECOMPILE
        return OptimizationStatus.OPTIMIZED
