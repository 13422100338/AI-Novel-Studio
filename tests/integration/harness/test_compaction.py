from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approval_service import ApprovalService
from ai_novel_studio.harness.approvals import ApprovalKind
from ai_novel_studio.harness.artifacts import ArtifactKind, ArtifactStore, FileArtifactBackend
from ai_novel_studio.harness.compaction import (
    CompactionGate,
    build_program_skeleton,
    persist_summary_revision,
)
from ai_novel_studio.harness.conversation_summary import (
    ConversationSummary,
    SummaryRevision,
)
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _setup(tmp_path: Path) -> tuple[HarnessEventStore, ApprovalService, CompactionGate]:
    project = ProjectRepository.create(tmp_path / "novel", "Compaction Test")
    store = HarnessEventStore(HarnessEventRepository(project))
    approvals = ApprovalService(store, ApprovalRepository(project))
    gate = CompactionGate(store, ApprovalRepository(project))
    return store, approvals, gate


def test_gate_allows_idle_run(tmp_path: Path) -> None:
    store, _approvals, gate = _setup(tmp_path)
    run, _ = store.start_run(goal="idle run")

    decision = gate.evaluate(run.id)
    assert decision.allowed is True


def test_gate_forbids_streaming_pending_and_closed(tmp_path: Path) -> None:
    store, approvals, gate = _setup(tmp_path)
    run, _ = store.start_run(goal="busy run")

    store.transition(run.id, RunStage.MODEL_RUNNING)
    assert gate.evaluate(run.id).allowed is False
    store.transition(run.id, RunStage.INTERRUPTED)
    store.transition(run.id, RunStage.CONTEXT_COMPILED)
    assert gate.evaluate(run.id).allowed is True

    approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.CHANGESET,
        summary="replace scene",
        idempotency_key="key-1",
    )
    assert gate.evaluate(run.id).allowed is False

    store.transition(run.id, RunStage.COMPLETED)
    assert gate.evaluate(run.id).allowed is False


def test_program_skeleton_extracts_resolved_approvals(tmp_path: Path) -> None:
    store, approvals, _gate = _setup(tmp_path)
    run, _ = store.start_run(goal="skeleton source")
    first = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.CHANGESET,
        summary="replace the opening scene",
        idempotency_key="key-1",
    )
    second = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.SKILL_CHANGE,
        summary="tighten the audit skill",
        idempotency_key="key-2",
    )
    approvals.resolve_approval(
        request_id=first.request_id, approved=True, resolution_note="作者认可"
    )
    approvals.resolve_approval(request_id=second.request_id, approved=False)

    repository = ApprovalRepository(ProjectRepository.open(tmp_path / "novel"))
    skeleton = build_program_skeleton(repository, run.id)

    assert skeleton.confirmed_decisions == ("replace the opening scene",)
    assert skeleton.rejected_options == ("tighten the audit skill",)
    assert skeleton.important_rationale == ("作者认可",)
    assert skeleton.unresolved_questions == ()


def test_summary_revision_persists_as_content_addressed_artifact(tmp_path: Path) -> None:
    store, _approvals, _gate = _setup(tmp_path)
    run, _ = store.start_run(goal="persist summary")
    artifacts = ArtifactStore(FileArtifactBackend(tmp_path / "artifacts-root"))
    revision = SummaryRevision(
        1, ConversationSummary(confirmed_decisions=("decide",)), datetime.now(UTC)
    )

    artifact = persist_summary_revision(artifacts, run.id, revision)
    assert artifact.kind is ArtifactKind.SUMMARY_REVISION
    loaded = artifacts.get(artifact.artifact_id)
    assert loaded.content == revision.summary.to_json().encode()


def test_gate_forbids_open_tool_call(tmp_path: Path) -> None:
    store, _approvals, gate = _setup(tmp_path)
    run, _ = store.start_run(goal="open tool call")
    store.append(run.id, RunEventType.TOOL_CALL_STARTED, {"tool_id": "manuscript.read"})

    decision = gate.evaluate(run.id)
    assert decision.allowed is False
    assert decision.reason == "a tool call is still open"

    store.append(run.id, RunEventType.TOOL_CALL_COMPLETED, {"tool_id": "manuscript.read"})
    assert gate.evaluate(run.id).allowed is True


def test_gate_forbids_commit_in_flight_until_run_closes(tmp_path: Path) -> None:
    store, approvals, gate = _setup(tmp_path)
    run, _ = store.start_run(goal="committing")
    request = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.CHANGESET,
        summary="replace scene",
        idempotency_key="key-1",
    )
    approvals.resolve_approval(request_id=request.request_id, approved=True)

    assert gate.evaluate(run.id).allowed is False

    store.transition(run.id, RunStage.COMPLETED)
    assert gate.evaluate(run.id).allowed is False


def test_gate_allows_after_rejected_approval_resolution(tmp_path: Path) -> None:
    store, approvals, gate = _setup(tmp_path)
    run, _ = store.start_run(goal="rejected")
    request = approvals.request_approval(
        run_id=run.id,
        kind=ApprovalKind.CHANGESET,
        summary="replace scene",
        idempotency_key="key-1",
    )
    approvals.resolve_approval(request_id=request.request_id, approved=False)

    assert gate.evaluate(run.id).allowed is True
