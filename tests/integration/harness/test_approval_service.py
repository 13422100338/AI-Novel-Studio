from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approval_service import (
    ApprovalAlreadyResolvedError,
    ApprovalIdempotencyConflictError,
    ApprovalService,
)
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalStatus
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore, HarnessRunClosedError
from ai_novel_studio.harness.projections import HarnessProjectionService
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _service(tmp_path: Path) -> tuple[HarnessEventStore, ApprovalService]:
    project = ProjectRepository.create(tmp_path / "novel", "Approval Test")
    store = HarnessEventStore(HarnessEventRepository(project))
    return store, ApprovalService(store, ApprovalRepository(project))


def test_request_approval_creates_pending_and_waits(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    run, _ = store.start_run(goal="rewrite the scene")

    request = service.request_approval(
        run_id=run.id,
        kind=ApprovalKind.CHANGESET,
        summary="replace the opening scene",
        expected_revisions=(("chapter", 3),),
        idempotency_key="key-1",
    )

    assert request.status is ApprovalStatus.PENDING
    assert store.get_run(run.id).stage is RunStage.WAITING_APPROVAL
    events = store.replay(run.id)
    assert events[-1].event_type is RunEventType.APPROVAL_REQUESTED
    assert events[-1].correlation_id == request.request_id
    assert service.pending(run.id) == (request,)


def test_request_approval_is_idempotent_per_key(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    run, _ = store.start_run(goal="idempotent approvals")

    first = service.request_approval(
        run_id=run.id,
        kind=ApprovalKind.SKILL_CHANGE,
        summary="tweak the audit skill",
        idempotency_key="key-1",
    )
    again = service.request_approval(
        run_id=run.id,
        kind=ApprovalKind.SKILL_CHANGE,
        summary="tweak the audit skill",
        idempotency_key="key-1",
    )

    assert again == first
    requested_count = len(
        [e for e in store.replay(run.id) if e.event_type is RunEventType.APPROVAL_REQUESTED]
    )
    assert requested_count == 1

    with pytest.raises(ApprovalIdempotencyConflictError):
        service.request_approval(
            run_id=run.id,
            kind=ApprovalKind.PROMPT_CHANGE,
            summary="other",
            idempotency_key="key-1",
        )


def test_request_approval_rejected_on_closed_run(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    run, _ = store.start_run(goal="cancel me")
    store.transition(run.id, RunStage.CANCELLED)

    with pytest.raises(HarnessRunClosedError):
        service.request_approval(
            run_id=run.id,
            kind=ApprovalKind.CHANGESET,
            summary="too late",
            idempotency_key="key-1",
        )


def test_resolve_approval_records_outcome_once(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    run, _ = store.start_run(goal="approve the change")

    request = service.request_approval(
        run_id=run.id,
        kind=ApprovalKind.CHANGESET,
        summary="replace the opening scene",
        idempotency_key="key-1",
    )
    resolved = service.resolve_approval(
        request_id=request.request_id, approved=True, resolution_note="looks good"
    )

    assert resolved.status is ApprovalStatus.APPROVED
    assert resolved.resolved_at is not None
    assert resolved.resolution_note == "looks good"
    assert service.pending(run.id) == ()
    events = store.replay(run.id)
    assert events[-1].event_type is RunEventType.APPROVAL_RESOLVED
    assert events[-1].payload == {"request_id": request.request_id, "approved": True}

    with pytest.raises(ApprovalAlreadyResolvedError):
        service.resolve_approval(request_id=request.request_id, approved=False)


def test_projections_expose_approval_cards(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Approval Projection")
    store = HarnessEventStore(HarnessEventRepository(project))
    repository = ApprovalRepository(project)
    service = ApprovalService(store, repository)
    projections = HarnessProjectionService(store, approvals=repository)
    run, _ = store.start_run(goal="project approval cards")

    assert projections.approvals(run.id) == ()
    request = service.request_approval(
        run_id=run.id,
        kind=ApprovalKind.SUBJECT_MERGE,
        summary="merge duplicate characters",
        idempotency_key="key-1",
    )

    cards = projections.approvals(run.id)
    assert [card.request_id for card in cards] == [request.request_id]
    assert cards[0].status is ApprovalStatus.PENDING
