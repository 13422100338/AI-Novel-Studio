from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.changeset_service import (
    ChangeSetResult,
    ChangeSetService,
)
from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.application.repair_application_service import (
    RepairApplicationService,
)
from ai_novel_studio.application.subject_merge_service import SubjectMergeService
from ai_novel_studio.domain.changeset import (
    ChangeOperation,
    ChangeOperationKind,
    ChangeSet,
)
from ai_novel_studio.domain.character_identity import CharacterIdentityMerge
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approval_service import ApprovalService
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalRequest
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_state import RunStage
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class UnsupportedCommitError(RuntimeError):
    """No backend commit facade is wired for this approval kind."""


class StaleSubjectMergeError(RuntimeError):
    """The subject cards changed since the merge was proposed; commit refused."""


@dataclass(frozen=True, slots=True)
class ApprovalResolution:
    """One resolved approval with its backend commit result, if any."""

    approval: ApprovalRequest
    result: ChangeSetResult | CharacterIdentityMerge | None


def changeset_to_payload(change_set: ChangeSet) -> dict[str, object]:
    if not isinstance(change_set, ChangeSet):
        raise TypeError("change set is invalid")
    return {
        "change_set_id": change_set.change_set_id,
        "operations": [
            {
                "operation_id": op.operation_id,
                "kind": op.kind.value,
                "chapter_id": op.chapter_id,
                "expected_revision": op.expected_revision,
                "payload": op.payload,
            }
            for op in change_set.operations
        ],
    }


def changeset_from_payload(payload: dict[str, object]) -> ChangeSet:
    raw_operations = payload.get("operations")
    if not isinstance(raw_operations, list) or not raw_operations:
        raise ValueError("change set payload operations are invalid")
    operations: list[ChangeOperation] = []
    for raw in raw_operations:
        if not isinstance(raw, dict):
            raise ValueError("change set payload operation is invalid")
        operation_payload = raw.get("payload")
        if not isinstance(operation_payload, dict):
            raise ValueError("change set payload operation payload is invalid")
        revision = raw.get("expected_revision")
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise ValueError("change set payload expected_revision is invalid")
        operations.append(
            ChangeOperation(
                str(raw.get("operation_id", "")),
                ChangeOperationKind(str(raw.get("kind", ""))),
                str(raw.get("chapter_id", "")),
                revision,
                operation_payload,
            )
        )
    return ChangeSet(str(payload.get("change_set_id", "")), tuple(operations))


def subject_merge_to_payload(
    source_character_id: str,
    target_character_id: str,
    *,
    reason: str,
) -> dict[str, object]:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("subject merge reason cannot be empty")
    return {
        "source_character_id": validate_id(source_character_id),
        "target_character_id": validate_id(target_character_id),
        "reason": normalized_reason,
    }


def subject_merge_from_payload(payload: dict[str, object]) -> tuple[str, str, str]:
    source = payload.get("source_character_id")
    target = payload.get("target_character_id")
    reason = payload.get("reason")
    if not isinstance(source, str) or not isinstance(target, str):
        raise ValueError("subject merge payload character ids are invalid")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("subject merge payload reason is invalid")
    validate_id(source)
    validate_id(target)
    if source == target:
        raise ValueError("cannot merge a character into itself")
    return source, target, reason.strip()


class ApprovalResolver:
    """A8 resolver: approved resolutions hand over to backend commit facades.

    resolve_and_commit resolves through the harness ApprovalService; approved
    CHANGESET / SUBJECT_MERGE requests dispatch to the wired backend facades
    using the approval idempotency_key, rejected requests never touch the
    backend. PROJECT_CONSTITUTION has its own ConstitutionFlowService (B4);
    PROMPT_CHANGE / SKILL_CHANGE have no V1 commit facade and raise
    UnsupportedCommitError.
    """

    def __init__(
        self,
        approvals: ApprovalService,
        *,
        changesets: ChangeSetService | None = None,
        merges: SubjectMergeService | None = None,
        store: HarnessEventStore | None = None,
        approvals_repository: ApprovalRepository | None = None,
    ) -> None:
        self._approvals = approvals
        self._changesets = changesets
        self._merges = merges
        self._store = store
        self._approvals_repository = approvals_repository

    @classmethod
    def for_project(cls, project: ProjectRepository) -> ApprovalResolver:
        store = HarnessEventStore(HarnessEventRepository(project))
        approvals_repository = ApprovalRepository(project)
        approvals = ApprovalService(store, approvals_repository)
        chapters = ChapterRepository(project)
        changesets = ChangeSetService(
            chapters,
            ChapterRevisionService(project),
            RepairApplicationService(chapters, AuditRepository(project)),
        )
        merges = SubjectMergeService(project)
        return cls(
            approvals,
            changesets=changesets,
            merges=merges,
            store=store,
            approvals_repository=approvals_repository,
        )

    def resolve_and_commit(
        self,
        request_id: str,
        *,
        approved: bool,
        resolution_note: str | None = None,
    ) -> ApprovalResolution:
        if approved and self._approvals_repository is not None:
            pending = self._approvals_repository.get(request_id)
            if pending.kind is ApprovalKind.SUBJECT_MERGE:
                self._check_merge_revisions(pending)
        approval = self._approvals.resolve_approval(
            request_id=request_id,
            approved=approved,
            resolution_note=resolution_note,
        )
        if not approved:
            return ApprovalResolution(approval=approval, result=None)
        if approval.kind is ApprovalKind.CHANGESET:
            if self._changesets is None:
                raise UnsupportedCommitError("no ChangeSet facade is wired")
            change_set = changeset_from_payload(approval.payload)
            result = self._changesets.commit(
                change_set, idempotency_key=approval.idempotency_key
            )
            return ApprovalResolution(approval=approval, result=result)
        if approval.kind is ApprovalKind.SUBJECT_MERGE:
            if self._merges is None:
                raise UnsupportedCommitError("no SubjectMerge facade is wired")
            source, target, reason = subject_merge_from_payload(approval.payload)
            merge = self._merges.merge(
                source,
                target,
                reason=reason,
                confirmed_by_user=True,
                expected_revisions=approval.expected_revisions,
            )
            return ApprovalResolution(approval=approval, result=merge)
        raise UnsupportedCommitError(
            f"no commit facade for approval kind {approval.kind.value}"
        )

    def _check_merge_revisions(self, request: ApprovalRequest) -> None:
        """Fail-closed revision check before an approved merge commits.

        The proposal records expected subject revisions; if the cards moved
        since, the commit is refused, the approval stays PENDING and the run
        is marked STALE with a readable conflict note (contract §8.2).
        """
        if self._merges is None:
            raise UnsupportedCommitError("no SubjectMerge facade is wired")
        expected = dict(request.expected_revisions)
        if not expected:
            return
        source, target, _reason = subject_merge_from_payload(request.payload)
        preview = self._merges.preview(source, target)
        current = {
            f"subject.state_events:{preview.source_character_id}": preview.state_event_count
        }
        mismatches = [
            f"{key}: expected {revision}, current {current.get(key)}"
            for key, revision in expected.items()
            if current.get(key) != revision
        ]
        if not mismatches:
            return
        message = "subject cards changed since proposal: " + "; ".join(mismatches)
        if self._store is not None:
            self._store.transition(
                request.run_id,
                RunStage.STALE,
                failure_code="SUBJECT_REVISION_CONFLICT",
                failure_message=message,
            )
        raise StaleSubjectMergeError(message)
