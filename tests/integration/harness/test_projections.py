from __future__ import annotations

from pathlib import Path

from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalStatus
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.model_roles import ModelRole, ModelRoleBinding
from ai_novel_studio.harness.projections import HarnessProjectionService
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.harness.state_capsule import ContextHealth, OptimizationStatus
from ai_novel_studio.harness.usage_meter import HarnessUsageMeter
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMUsage,
    ModelProfile,
    ModelRoute,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.llm.usage_tracker import UsageTracker
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _store(tmp_path: Path) -> HarnessEventStore:
    project = ProjectRepository.create(tmp_path / "novel", "Projection Test")
    return HarnessEventStore(HarnessEventRepository(project))


def _compiled_payload() -> dict[str, object]:
    return {
        "chapter_id": "ch-1",
        "manifest_id": "manifest-1",
        "estimated_input_tokens": 1500,
        "evidence_hit_count": 2,
        "included_categories": [["MEMORY", 4], ["EXACT_EVIDENCE", 2]],
    }


def test_status_projection_reflects_run_and_events(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, created = store.start_run(goal="draft chapter three")
    store.append(run.id, RunEventType.CONTEXT_COMPILATION_STARTED)
    store.append(run.id, RunEventType.CONTEXT_COMPILED)

    status = HarnessProjectionService(store).status(run.id)

    assert status.run_id == run.id
    assert status.stage is RunStage.CREATED
    assert status.event_count == 3
    assert status.last_sequence == 2
    assert created.occurred_at == status.created_at


def test_timeline_projection_preserves_order_without_payloads(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="timeline")
    store.append(run.id, RunEventType.AUDIT_STARTED, {"secret": "payload"})
    store.append(run.id, RunEventType.AUDIT_COMPLETED)

    timeline = HarnessProjectionService(store).timeline(run.id)

    assert [entry.sequence for entry in timeline.entries] == [0, 1, 2]
    assert [entry.event_type for entry in timeline.entries] == [
        RunEventType.RUN_CREATED,
        RunEventType.AUDIT_STARTED,
        RunEventType.AUDIT_COMPLETED,
    ]
    assert not hasattr(timeline.entries[1], "payload")


def test_recovery_projection_flags_resumable_stages(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = HarnessProjectionService(store)

    created_run, _ = store.start_run(goal="created")
    assert service.recovery(created_run.id).resumable is False

    interrupted_run, _ = store.start_run(goal="interrupted")
    store.transition(interrupted_run.id, RunStage.INTERRUPTED)
    interrupted = service.recovery(interrupted_run.id)
    assert interrupted.resumable is True
    assert interrupted.recommended_actions == ("RESUME_RUN",)

    approval_run, _ = store.start_run(goal="approval")
    store.transition(approval_run.id, RunStage.WAITING_APPROVAL)
    approval = service.recovery(approval_run.id)
    assert approval.recommended_actions == ("RESTORE_APPROVAL_VIEW",)


def test_usage_projection_splits_roles_and_defaults_to_empty(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="usage")

    tracker = UsageTracker()
    tracker.record_success(
        TaskPurpose.PLOT_DISCUSSION,
        ModelRoute("p", "agent"),
        ModelProfile(provider_id="p", model_id="agent"),
        LLMUsage(input_tokens=10, output_tokens=5),
        output_token_limit=500,
        duration_ms=1,
        retry_count=0,
    )
    meter = HarnessUsageMeter(
        tracker,
        (ModelRoleBinding(ModelRole.AGENT, TaskPurpose.PLOT_DISCUSSION, "p", "agent"),),
    )

    usage = HarnessProjectionService(store, meter).usage(run.id)
    assert [role.role for role in usage.roles] == [ModelRole.AGENT]
    assert usage.roles[0].input_tokens == 10

    empty = HarnessProjectionService(store).usage(run.id)
    assert empty.roles == ()


def test_recoverable_runs_lists_only_resumable_runs(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = HarnessProjectionService(store)

    done, _ = store.start_run(goal="done")
    store.transition(done.id, RunStage.COMPLETED)
    interrupted, _ = store.start_run(goal="interrupted")
    store.transition(interrupted.id, RunStage.INTERRUPTED)
    waiting, _ = store.start_run(goal="waiting")
    store.transition(waiting.id, RunStage.WAITING_APPROVAL)

    recoverable = service.recoverable_runs()

    assert [projection.run_id for projection in recoverable] == [
        interrupted.id,
        waiting.id,
    ]
    assert all(projection.resumable for projection in recoverable)


def test_list_runs_orders_by_creation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first, _ = store.start_run(goal="first")
    second, _ = store.start_run(goal="second")

    runs = store.list_runs()

    assert [run.id for run in runs] == [first.id, second.id]
    assert [run.goal for run in runs] == ["first", "second"]


def test_capsule_derives_run_facts_and_compile_payload(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="编译胶囊")
    store.append(
        run.id,
        RunEventType.CONTEXT_COMPILED,
        _compiled_payload(),
    )
    store.append(run.id, RunEventType.SKILL_LOADED, {"skill_id": "chapter_audit"})
    store.append(run.id, RunEventType.SKILL_LOADED, {"skill_id": "chapter_audit"})
    store.append(run.id, RunEventType.TOOL_SCHEMA_LOADED, {"tool_id": "subject.inspect"})

    capsule = HarnessProjectionService(store).capsule(run.id)

    assert capsule.run_id == run.id
    assert capsule.stage is RunStage.CREATED
    assert capsule.active_chapter_id is None
    assert capsule.context_manifest_id == "manifest-1"
    assert capsule.context_budget == 1500
    assert capsule.context_health is ContextHealth.HEALTHY
    assert capsule.optimization_status is OptimizationStatus.OPTIMIZED
    assert capsule.loaded_skills == ("chapter_audit",)
    assert capsule.loaded_tools == ("subject.inspect",)
    assert capsule.pending_approvals == ()
    assert capsule.editor_snapshot_revision is None


def test_capsule_without_compile_is_unknown(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="未编译")

    capsule = HarnessProjectionService(store).capsule(run.id)

    assert capsule.context_health is ContextHealth.UNKNOWN
    assert capsule.optimization_status is OptimizationStatus.UNKNOWN
    assert capsule.context_manifest_id is None
    assert capsule.context_budget is None


def test_capsule_stale_run_is_critical_and_needs_recompile(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="过期")
    store.append(run.id, RunEventType.CONTEXT_COMPILED, _compiled_payload())
    store.transition(run.id, RunStage.STALE)

    capsule = HarnessProjectionService(store).capsule(run.id)

    assert capsule.context_health is ContextHealth.CRITICAL
    assert capsule.optimization_status is OptimizationStatus.NEEDS_RECOMPILE


def test_capsule_lists_pending_approvals(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Capsule approvals")
    store = HarnessEventStore(HarnessEventRepository(project))
    run, _ = store.start_run(goal="审批中")
    approvals = ApprovalRepository(project)
    pending = approvals.create(
        run_id=run.id,
        kind=ApprovalKind.CHANGESET,
        summary="替换",
        payload={},
        expected_revisions=(),
        idempotency_key="cs-1",
    )
    resolved = approvals.create(
        run_id=run.id,
        kind=ApprovalKind.SUBJECT_MERGE,
        summary="合并",
        payload={},
        expected_revisions=(),
        idempotency_key="sm-1",
    )
    approvals.resolve(resolved.request_id, ApprovalStatus.REJECTED, None)

    capsule = HarnessProjectionService(
        store, approvals=approvals
    ).capsule(run.id)

    assert capsule.pending_approvals == (pending.request_id,)


def test_context_status_combines_compile_draft_and_usage(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="状态栏")
    store.append(run.id, RunEventType.CONTEXT_COMPILED, _compiled_payload())
    store.append(
        run.id,
        RunEventType.CHAPTER_STREAM_CHECKPOINT_SAVED,
        {"artifact_id": "sha256:aa", "character_count": 10},
    )
    store.append(
        run.id,
        RunEventType.CHAPTER_STREAM_COMPLETED,
        {"artifact_id": "sha256:bb", "character_count": 42},
    )

    tracker = UsageTracker()
    tracker.record_success(
        TaskPurpose.PLOT_DISCUSSION,
        ModelRoute("p", "agent"),
        ModelProfile(provider_id="p", model_id="agent"),
        LLMUsage(input_tokens=10, output_tokens=5),
        output_token_limit=500,
        duration_ms=1,
        retry_count=0,
    )
    meter = HarnessUsageMeter(
        tracker,
        (ModelRoleBinding(ModelRole.AGENT, TaskPurpose.PLOT_DISCUSSION, "p", "agent"),),
    )

    status = HarnessProjectionService(store, meter).context_status(run.id)

    assert status.context_manifest_id == "manifest-1"
    assert status.context_budget == 1500
    assert status.evidence_hit_count == 2
    assert status.included_categories == (("MEMORY", 4), ("EXACT_EVIDENCE", 2))
    assert status.draft_artifact_id == "sha256:bb"
    assert status.draft_character_count == 42
    assert status.draft_checkpoint_count == 1
    assert [role.role for role in status.usage_roles] == [ModelRole.AGENT]
    assert status.usage_roles[0].input_tokens == 10


def test_context_status_without_events_is_empty_shape(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run, _ = store.start_run(goal="空状态")

    status = HarnessProjectionService(store).context_status(run.id)

    assert status.context_manifest_id is None
    assert status.context_health is ContextHealth.UNKNOWN
    assert status.included_categories == ()
    assert status.draft_artifact_id is None
    assert status.draft_checkpoint_count == 0
    assert status.usage_roles == ()
    assert status.pending_approvals == ()
