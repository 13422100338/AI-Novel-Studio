from __future__ import annotations

from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalRequest, ApprovalStatus
from ai_novel_studio.harness.event_store import HarnessEventStore, HarnessRunClosedError
from ai_novel_studio.harness.run_state import CLOSED_STAGES, RunEventType, RunStage


class ApprovalIdempotencyConflictError(ValueError):
    """The same idempotency_key is bound to a different approval kind."""


class ApprovalAlreadyResolvedError(ValueError):
    """A resolved approval request cannot be resolved again."""


class ApprovalService:
    """Harness-owned approval lifecycle (backend audit 2026-08-14).

    request_approval is idempotent per (run_id, idempotency_key), appends the
    APPROVAL_REQUESTED event and moves the run to WAITING_APPROVAL.
    resolve_approval records APPROVED / REJECTED once and appends the
    APPROVAL_RESOLVED event; the backend later validates the approval and
    executes the deterministic commit (out of scope here).
    """

    def __init__(self, store: HarnessEventStore, repository: ApprovalRepository) -> None:
        self._store = store
        self._repository = repository

    def request_approval(
        self,
        *,
        run_id: str,
        kind: ApprovalKind,
        summary: str,
        payload: dict[str, object] | None = None,
        expected_revisions: tuple[tuple[str, int], ...] = (),
        idempotency_key: str,
    ) -> ApprovalRequest:
        run = self._store.get_run(run_id)
        if run.stage in CLOSED_STAGES:
            raise HarnessRunClosedError(
                f"run {run_id} is closed at stage {run.stage.value}; "
                "approval requests are rejected"
            )
        existing = self._repository.get_by_key(run_id, idempotency_key)
        if existing is not None:
            if existing.kind is not kind:
                raise ApprovalIdempotencyConflictError(
                    f"idempotency_key {idempotency_key} is bound to "
                    f"{existing.kind.value}, not {kind.value}"
                )
            return existing
        request = self._repository.create(
            run_id=run_id,
            kind=kind,
            summary=summary,
            payload=payload if payload is not None else {},
            expected_revisions=expected_revisions,
            idempotency_key=idempotency_key,
        )
        self._store.append(
            run_id,
            RunEventType.APPROVAL_REQUESTED,
            {"request_id": request.request_id, "kind": request.kind.value},
            correlation_id=request.request_id,
        )
        self._store.transition(run_id, RunStage.WAITING_APPROVAL)
        return request

    def resolve_approval(
        self, *, request_id: str, approved: bool, resolution_note: str | None = None
    ) -> ApprovalRequest:
        request = self._repository.get(request_id)
        if request.status is not ApprovalStatus.PENDING:
            raise ApprovalAlreadyResolvedError(
                f"approval {request_id} is already {request.status.value}"
            )
        resolved = self._repository.resolve(
            request_id,
            ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
            resolution_note,
        )
        self._store.append(
            request.run_id,
            RunEventType.APPROVAL_RESOLVED,
            {"request_id": request_id, "approved": approved},
            correlation_id=request_id,
        )
        return resolved

    def pending(self, run_id: str) -> tuple[ApprovalRequest, ...]:
        return tuple(
            request
            for request in self._repository.list_for_run(run_id)
            if request.status is ApprovalStatus.PENDING
        )
