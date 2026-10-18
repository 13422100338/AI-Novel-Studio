from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from typing import cast

from ai_novel_studio.harness.approval_execution_receipt import (
    ApprovalCommitTargetKind,
    ApprovalDisposition,
    ApprovalExecutionReceipt,
    ApprovalExecutionState,
    ApprovalFailureClass,
    ApprovalFailureCode,
    ApprovalOperationStatus,
    ChangeSetOperationIdentity,
    ChangeSetOperationResultEvidence,
    ChangeSetTargetIdentity,
    LegacyUnresolvedTargetIdentity,
    ProjectConstitutionResultEvidence,
    ProjectConstitutionTargetIdentity,
    ResultEvidence,
    SubjectMergeResultEvidence,
    SubjectMergeTargetIdentity,
    TargetIdentity,
    UnsupportedApprovalTargetIdentity,
    stable_evidence_json,
    stable_evidence_list_json,
)
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalStatus
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_MAX_LIST_LIMIT = 100
_NORMAL_TARGET_KINDS = frozenset(
    {
        ApprovalCommitTargetKind.CHANGESET,
        ApprovalCommitTargetKind.SUBJECT_MERGE,
        ApprovalCommitTargetKind.PROJECT_CONSTITUTION,
    }
)


class ApprovalExecutionReceiptDataError(ValueError):
    """Persisted receipt data violates the closed v25 receipt contract."""


class ApprovalExecutionReceiptConflictError(RuntimeError):
    """A create or compare-and-swap lost to an already durable receipt."""

    def __init__(self, current: ApprovalExecutionReceipt) -> None:
        self.current = current
        super().__init__(
            "approval execution receipt changed before the requested operation completed"
        )


def _validate_transition_edge(
    current: ApprovalExecutionReceipt,
    *,
    target_state: ApprovalExecutionState,
    decision: ApprovalStatus | None,
) -> None:
    if current.commit_target_kind not in _NORMAL_TARGET_KINDS:
        raise ValueError("no legal receipt edge for a non-commit target")
    pending_to_ready = (
        current.execution_state is ApprovalExecutionState.PENDING_DECISION
        and target_state is ApprovalExecutionState.READY
        and decision is ApprovalStatus.APPROVED
    )
    ready_to_executing = (
        current.execution_state is ApprovalExecutionState.READY
        and current.decision is ApprovalStatus.APPROVED
        and target_state is ApprovalExecutionState.EXECUTING
        and decision in {None, ApprovalStatus.APPROVED}
    )
    if not (pending_to_ready or ready_to_executing):
        raise ValueError("no legal receipt edge for the requested transition")


def _validate_finalize_edge(
    current: ApprovalExecutionReceipt,
    *,
    decision: ApprovalStatus | None,
    disposition: ApprovalDisposition,
    started_at: datetime | None,
) -> None:
    effective_decision = decision if decision is not None else current.decision
    if current.commit_target_kind in _NORMAL_TARGET_KINDS:
        pending_discard = (
            current.execution_state is ApprovalExecutionState.PENDING_DECISION
            and effective_decision is ApprovalStatus.REJECTED
            and disposition is ApprovalDisposition.DISCARDED
        )
        ready_prewrite_failure = (
            current.execution_state is ApprovalExecutionState.READY
            and effective_decision is ApprovalStatus.APPROVED
            and disposition in {ApprovalDisposition.STALE, ApprovalDisposition.FAILED}
        )
        evidence_finalization = (
            current.execution_state
            in {
                ApprovalExecutionState.EXECUTING,
                ApprovalExecutionState.RECOVERY_REQUIRED,
            }
            and effective_decision is ApprovalStatus.APPROVED
            and disposition
            in {
                ApprovalDisposition.APPLIED,
                ApprovalDisposition.STALE,
                ApprovalDisposition.FAILED,
            }
        )
        if not (pending_discard or ready_prewrite_failure or evidence_finalization):
            raise ValueError("no legal receipt edge for the requested finalization")
        if (
            disposition is ApprovalDisposition.APPLIED
            and current.started_at is None
            and started_at is None
        ):
            raise ValueError("APPLIED finalization requires non-null started_at")
        return
    if current.commit_target_kind is ApprovalCommitTargetKind.LEGACY_UNRESOLVED:
        allowed = current.execution_state in {
            ApprovalExecutionState.PENDING_DECISION,
            ApprovalExecutionState.RECOVERY_REQUIRED,
        } and (
            (
                effective_decision is ApprovalStatus.REJECTED
                and disposition is ApprovalDisposition.DISCARDED
            )
            or (
                effective_decision is ApprovalStatus.APPROVED
                and disposition is ApprovalDisposition.FAILED
            )
        )
        if not allowed:
            raise ValueError("no legal receipt edge for LEGACY_UNRESOLVED finalization")
        return
    allowed = (
        current.commit_target_kind is ApprovalCommitTargetKind.UNSUPPORTED_APPROVAL
        and current.execution_state is ApprovalExecutionState.PENDING_DECISION
        and (
            (
                effective_decision is ApprovalStatus.REJECTED
                and disposition is ApprovalDisposition.DISCARDED
            )
            or (
                effective_decision is ApprovalStatus.APPROVED
                and disposition is ApprovalDisposition.FAILED
            )
        )
    )
    if not allowed:
        raise ValueError("no legal receipt edge for UNSUPPORTED_APPROVAL finalization")


def _exact_dict(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("evidence object has an invalid shape")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    return None if value is None else _integer(value, field)


def _optional_string(value: object, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _json_value(serialized: str) -> object:
    return json.loads(serialized)


def _target_from_json(serialized: str) -> TargetIdentity:
    value = _json_value(serialized)
    if not isinstance(value, dict):
        raise ValueError("target identity must be an object")
    schema_version = value.get("schema_version")
    if schema_version == "changeset-target-v1":
        parsed = _exact_dict(value, {"schema_version", "change_set_id", "operations"})
        operations_value = parsed["operations"]
        if not isinstance(operations_value, list):
            raise ValueError("operations must be a list")
        operations: list[ChangeSetOperationIdentity] = []
        for item in operations_value:
            operation = _exact_dict(
                item,
                {
                    "operation_id",
                    "operation_kind",
                    "target_id",
                    "expected_revision",
                    "source_hash",
                },
            )
            operations.append(
                ChangeSetOperationIdentity(
                    operation_id=_string(operation["operation_id"], "operation_id"),
                    operation_kind=_string(operation["operation_kind"], "operation_kind"),
                    target_id=_string(operation["target_id"], "target_id"),
                    expected_revision=_optional_integer(
                        operation["expected_revision"], "expected_revision"
                    ),
                    source_hash=_optional_string(operation["source_hash"], "source_hash"),
                )
            )
        return ChangeSetTargetIdentity(
            change_set_id=_string(parsed["change_set_id"], "change_set_id"),
            operations=tuple(operations),
        )
    if schema_version == "subject-merge-target-v1":
        parsed = _exact_dict(
            value,
            {
                "schema_version",
                "approval_request_id",
                "source_subject_id",
                "target_subject_id",
                "expected_revisions",
            },
        )
        revisions_value = parsed["expected_revisions"]
        if not isinstance(revisions_value, list):
            raise ValueError("expected_revisions must be a list")
        revisions: list[tuple[str, int]] = []
        for item in revisions_value:
            revision = _exact_dict(item, {"key", "revision"})
            revisions.append(
                (
                    _string(revision["key"], "expected revision key"),
                    _integer(revision["revision"], "revision"),
                )
            )
        return SubjectMergeTargetIdentity(
            approval_request_id=_string(parsed["approval_request_id"], "approval_request_id"),
            source_subject_id=_string(parsed["source_subject_id"], "source_subject_id"),
            target_subject_id=_string(parsed["target_subject_id"], "target_subject_id"),
            expected_revisions=tuple(revisions),
        )
    if schema_version == "project-constitution-target-v1":
        parsed = _exact_dict(
            value,
            {
                "schema_version",
                "approval_request_id",
                "project_id",
                "base_revision",
                "proposal_digest",
            },
        )
        return ProjectConstitutionTargetIdentity(
            approval_request_id=_string(parsed["approval_request_id"], "approval_request_id"),
            project_id=_string(parsed["project_id"], "project_id"),
            base_revision=_integer(parsed["base_revision"], "base_revision"),
            proposal_digest=_string(parsed["proposal_digest"], "proposal_digest"),
        )
    if schema_version == "unsupported-approval-v1":
        parsed = _exact_dict(
            value,
            {
                "schema_version",
                "approval_request_id",
                "approval_kind",
                "reason_code",
            },
        )
        if parsed["reason_code"] != "UNSUPPORTED_KIND":
            raise ValueError("unsupported reason_code is invalid")
        return UnsupportedApprovalTargetIdentity(
            approval_request_id=_string(parsed["approval_request_id"], "approval_request_id"),
            approval_kind=ApprovalKind(_string(parsed["approval_kind"], "approval_kind")),
        )
    if schema_version == "legacy-unresolved-v1":
        parsed = _exact_dict(
            value,
            {
                "schema_version",
                "approval_request_id",
                "approval_kind",
                "reason_code",
            },
        )
        if parsed["reason_code"] != "MISSING_OR_INVALID_TARGET_IDENTITY":
            raise ValueError("legacy reason_code is invalid")
        return LegacyUnresolvedTargetIdentity(
            approval_request_id=_string(parsed["approval_request_id"], "approval_request_id"),
            approval_kind=ApprovalKind(_string(parsed["approval_kind"], "approval_kind")),
        )
    raise ValueError("unknown target identity schema")


def _result_from_json(serialized: str) -> tuple[ResultEvidence, ...]:
    value = _json_value(serialized)
    if not isinstance(value, list):
        raise ValueError("result evidence must be a list")
    results: list[ResultEvidence] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("result evidence item must be an object")
        evidence_kind = item.get("evidence_kind")
        if evidence_kind == "CHANGESET_OPERATION":
            parsed = _exact_dict(
                item,
                {
                    "evidence_kind",
                    "operation_id",
                    "status",
                    "committed_revision",
                    "committed_hash",
                },
            )
            results.append(
                ChangeSetOperationResultEvidence(
                    operation_id=_string(parsed["operation_id"], "operation_id"),
                    status=ApprovalOperationStatus(_string(parsed["status"], "status")),
                    committed_revision=_optional_integer(
                        parsed["committed_revision"], "committed_revision"
                    ),
                    committed_hash=_optional_string(parsed["committed_hash"], "committed_hash"),
                )
            )
        elif evidence_kind == "SUBJECT_MERGE":
            parsed = _exact_dict(item, {"evidence_kind", "merge_record_id", "status"})
            results.append(
                SubjectMergeResultEvidence(
                    merge_record_id=_string(parsed["merge_record_id"], "merge_record_id"),
                    status=ApprovalOperationStatus(_string(parsed["status"], "status")),
                )
            )
        elif evidence_kind == "PROJECT_CONSTITUTION":
            parsed = _exact_dict(item, {"evidence_kind", "constitution_revision", "status"})
            results.append(
                ProjectConstitutionResultEvidence(
                    constitution_revision=_integer(
                        parsed["constitution_revision"], "constitution_revision"
                    ),
                    status=ApprovalOperationStatus(_string(parsed["status"], "status")),
                )
            )
        else:
            raise ValueError("unknown result evidence kind")
    return tuple(results)


class ApprovalExecutionReceiptRepository:
    """Bounded SQLite receipt access with strict DTO validation and CAS writes."""

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def create(
        self,
        receipt: ApprovalExecutionReceipt,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> ApprovalExecutionReceipt:
        if receipt.commit_target_kind is ApprovalCommitTargetKind.LEGACY_UNRESOLVED:
            raise ValueError("LEGACY_UNRESOLVED is a migration-only target")
        if connection is None:
            with self.project.database.connect() as owned, owned:
                return self._create(owned, receipt)
        return self._create(connection, receipt)

    def _create(
        self,
        connection: sqlite3.Connection,
        receipt: ApprovalExecutionReceipt,
    ) -> ApprovalExecutionReceipt:
        self._validate_approval_identity(connection, receipt)
        try:
            connection.execute(
                """
                INSERT INTO harness_approval_execution_receipts(
                    approval_request_id, run_id, idempotency_key, kind, decision,
                    execution_state, disposition, commit_target_kind, commit_target_id,
                    target_identity_json, domain_receipt_id, result_evidence_json,
                    failure_class, failure_code, failure_summary, created_at, updated_at,
                    started_at, finalized_at, revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(receipt),
            )
        except sqlite3.IntegrityError:
            try:
                current = self.get(receipt.approval_request_id, connection=connection)
            except KeyError:
                raise ApprovalExecutionReceiptDataError(
                    "receipt insert violated a database constraint"
                ) from None
            raise ApprovalExecutionReceiptConflictError(current) from None
        return self.get(receipt.approval_request_id, connection=connection)

    def get(
        self,
        approval_request_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> ApprovalExecutionReceipt:
        if connection is None:
            with self.project.database.connect() as owned:
                return self._get(owned, approval_request_id)
        return self._get(connection, approval_request_id)

    def _get(
        self,
        connection: sqlite3.Connection,
        approval_request_id: str,
    ) -> ApprovalExecutionReceipt:
        row = connection.execute(
            """
            SELECT receipt.*,
                   approval.run_id AS approval_run_id,
                   approval.idempotency_key AS approval_idempotency_key,
                   approval.kind AS approval_kind
            FROM harness_approval_execution_receipts AS receipt
            JOIN harness_approvals AS approval
              ON approval.id = receipt.approval_request_id
            WHERE receipt.approval_request_id = ?
            """,
            (approval_request_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown approval execution receipt: {approval_request_id}")
        return self._from_row(row)

    def list_for_run(
        self,
        run_id: str,
        *,
        limit: int = _MAX_LIST_LIMIT,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[ApprovalExecutionReceipt, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if connection is None:
            with self.project.database.connect() as owned:
                return self._list_for_run(owned, run_id, limit)
        return self._list_for_run(connection, run_id, limit)

    def _list_for_run(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        limit: int,
    ) -> tuple[ApprovalExecutionReceipt, ...]:
        rows = connection.execute(
            """
            SELECT receipt.*,
                   approval.run_id AS approval_run_id,
                   approval.idempotency_key AS approval_idempotency_key,
                   approval.kind AS approval_kind
            FROM harness_approval_execution_receipts AS receipt
            JOIN harness_approvals AS approval
              ON approval.id = receipt.approval_request_id
            WHERE receipt.run_id = ?
            ORDER BY receipt.created_at, receipt.approval_request_id
            LIMIT ?
            """,
            (run_id, limit),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def transition(
        self,
        approval_request_id: str,
        *,
        expected_revision: int,
        expected_state: ApprovalExecutionState,
        target_state: ApprovalExecutionState,
        decision: ApprovalStatus | None = None,
        updated_at: datetime,
        started_at: datetime | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> ApprovalExecutionReceipt:
        if connection is None:
            with self.project.database.connect() as owned, owned:
                return self._transition(
                    owned,
                    approval_request_id,
                    expected_revision=expected_revision,
                    expected_state=expected_state,
                    target_state=target_state,
                    decision=decision,
                    updated_at=updated_at,
                    started_at=started_at,
                )
        return self._transition(
            connection,
            approval_request_id,
            expected_revision=expected_revision,
            expected_state=expected_state,
            target_state=target_state,
            decision=decision,
            updated_at=updated_at,
            started_at=started_at,
        )

    def _transition(
        self,
        connection: sqlite3.Connection,
        approval_request_id: str,
        *,
        expected_revision: int,
        expected_state: ApprovalExecutionState,
        target_state: ApprovalExecutionState,
        decision: ApprovalStatus | None,
        updated_at: datetime,
        started_at: datetime | None,
    ) -> ApprovalExecutionReceipt:
        current = self.get(approval_request_id, connection=connection)
        if current.revision != expected_revision or current.execution_state is not expected_state:
            raise ApprovalExecutionReceiptConflictError(
                self.get(approval_request_id, connection=connection)
            )
        _validate_transition_edge(
            current,
            target_state=target_state,
            decision=decision,
        )
        if target_state is ApprovalExecutionState.READY and started_at is not None:
            raise ValueError("READY transition requires null started_at")
        candidate = replace(
            current,
            decision=decision if decision is not None else current.decision,
            execution_state=target_state,
            updated_at=updated_at,
            started_at=(
                started_at
                if started_at is not None
                else updated_at
                if target_state is ApprovalExecutionState.EXECUTING
                else current.started_at
            ),
            revision=current.revision + 1,
            migration_provenance=(
                current.commit_target_kind is ApprovalCommitTargetKind.LEGACY_UNRESOLVED
            ),
        )
        cursor = connection.execute(
            """
            UPDATE harness_approval_execution_receipts
            SET decision = ?, execution_state = ?, updated_at = ?,
                started_at = ?, revision = ?
            WHERE approval_request_id = ? AND revision = ? AND execution_state = ?
            """,
            (
                candidate.decision.value if candidate.decision is not None else None,
                candidate.execution_state.value,
                candidate.updated_at.isoformat(),
                (candidate.started_at.isoformat() if candidate.started_at is not None else None),
                candidate.revision,
                approval_request_id,
                expected_revision,
                expected_state.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ApprovalExecutionReceiptConflictError(
                self.get(approval_request_id, connection=connection)
            )
        return self.get(approval_request_id, connection=connection)

    def finalize(
        self,
        approval_request_id: str,
        *,
        expected_revision: int,
        expected_state: ApprovalExecutionState,
        disposition: ApprovalDisposition,
        result_evidence: tuple[ResultEvidence, ...],
        domain_receipt_id: str | None,
        failure_class: ApprovalFailureClass | None,
        failure_code: ApprovalFailureCode | None,
        failure_summary: str | None,
        finalized_at: datetime,
        started_at: datetime | None = None,
        decision: ApprovalStatus | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> ApprovalExecutionReceipt:
        if connection is None:
            with self.project.database.connect() as owned, owned:
                return self._finalize(
                    owned,
                    approval_request_id,
                    expected_revision=expected_revision,
                    expected_state=expected_state,
                    decision=decision,
                    disposition=disposition,
                    result_evidence=result_evidence,
                    domain_receipt_id=domain_receipt_id,
                    failure_class=failure_class,
                    failure_code=failure_code,
                    failure_summary=failure_summary,
                    finalized_at=finalized_at,
                    started_at=started_at,
                )
        return self._finalize(
            connection,
            approval_request_id,
            expected_revision=expected_revision,
            expected_state=expected_state,
            decision=decision,
            disposition=disposition,
            result_evidence=result_evidence,
            domain_receipt_id=domain_receipt_id,
            failure_class=failure_class,
            failure_code=failure_code,
            failure_summary=failure_summary,
            finalized_at=finalized_at,
            started_at=started_at,
        )

    def reclassify_legacy(
        self,
        approval_request_id: str,
        *,
        expected_revision: int,
        expected_state: ApprovalExecutionState,
        commit_target_kind: ApprovalCommitTargetKind,
        commit_target_id: str,
        target_identity: TargetIdentity,
        updated_at: datetime,
        connection: sqlite3.Connection | None = None,
    ) -> ApprovalExecutionReceipt:
        if commit_target_kind not in {
            ApprovalCommitTargetKind.CHANGESET,
            ApprovalCommitTargetKind.SUBJECT_MERGE,
            ApprovalCommitTargetKind.PROJECT_CONSTITUTION,
        }:
            raise ValueError("legacy receipts may reclassify only to a normal target")
        if connection is None:
            with self.project.database.connect() as owned, owned:
                return self._reclassify_legacy(
                    owned,
                    approval_request_id,
                    expected_revision=expected_revision,
                    expected_state=expected_state,
                    commit_target_kind=commit_target_kind,
                    commit_target_id=commit_target_id,
                    target_identity=target_identity,
                    updated_at=updated_at,
                )
        return self._reclassify_legacy(
            connection,
            approval_request_id,
            expected_revision=expected_revision,
            expected_state=expected_state,
            commit_target_kind=commit_target_kind,
            commit_target_id=commit_target_id,
            target_identity=target_identity,
            updated_at=updated_at,
        )

    def _reclassify_legacy(
        self,
        connection: sqlite3.Connection,
        approval_request_id: str,
        *,
        expected_revision: int,
        expected_state: ApprovalExecutionState,
        commit_target_kind: ApprovalCommitTargetKind,
        commit_target_id: str,
        target_identity: TargetIdentity,
        updated_at: datetime,
    ) -> ApprovalExecutionReceipt:
        current = self.get(approval_request_id, connection=connection)
        if (
            current.revision != expected_revision
            or current.execution_state is not expected_state
            or current.commit_target_kind is not ApprovalCommitTargetKind.LEGACY_UNRESOLVED
        ):
            raise ApprovalExecutionReceiptConflictError(
                self.get(approval_request_id, connection=connection)
            )
        if (
            current.execution_state is not ApprovalExecutionState.RECOVERY_REQUIRED
            or current.decision is not ApprovalStatus.APPROVED
        ):
            raise ValueError(
                "LEGACY_UNRESOLVED reclassification requires APPROVED RECOVERY_REQUIRED"
            )
        candidate = replace(
            current,
            commit_target_kind=commit_target_kind,
            commit_target_id=commit_target_id,
            target_identity=target_identity,
            updated_at=updated_at,
            revision=current.revision + 1,
        )
        cursor = connection.execute(
            """
            UPDATE harness_approval_execution_receipts
            SET commit_target_kind = ?, commit_target_id = ?,
                target_identity_json = ?, updated_at = ?, revision = ?
            WHERE approval_request_id = ? AND revision = ?
              AND execution_state = ? AND commit_target_kind = 'LEGACY_UNRESOLVED'
            """,
            (
                candidate.commit_target_kind.value,
                candidate.commit_target_id,
                stable_evidence_json(candidate.target_identity),
                candidate.updated_at.isoformat(),
                candidate.revision,
                approval_request_id,
                expected_revision,
                expected_state.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ApprovalExecutionReceiptConflictError(
                self.get(approval_request_id, connection=connection)
            )
        return self.get(approval_request_id, connection=connection)

    def _finalize(
        self,
        connection: sqlite3.Connection,
        approval_request_id: str,
        *,
        expected_revision: int,
        expected_state: ApprovalExecutionState,
        decision: ApprovalStatus | None,
        disposition: ApprovalDisposition,
        result_evidence: tuple[ResultEvidence, ...],
        domain_receipt_id: str | None,
        failure_class: ApprovalFailureClass | None,
        failure_code: ApprovalFailureCode | None,
        failure_summary: str | None,
        finalized_at: datetime,
        started_at: datetime | None,
    ) -> ApprovalExecutionReceipt:
        current = self.get(approval_request_id, connection=connection)
        if current.revision != expected_revision or current.execution_state is not expected_state:
            raise ApprovalExecutionReceiptConflictError(
                self.get(approval_request_id, connection=connection)
            )
        _validate_finalize_edge(
            current,
            decision=decision,
            disposition=disposition,
            started_at=started_at,
        )
        candidate = replace(
            current,
            decision=decision if decision is not None else current.decision,
            execution_state=ApprovalExecutionState.FINALIZED,
            disposition=disposition,
            domain_receipt_id=domain_receipt_id,
            result_evidence=result_evidence,
            failure_class=failure_class,
            failure_code=failure_code,
            failure_summary=failure_summary,
            updated_at=finalized_at,
            started_at=started_at if started_at is not None else current.started_at,
            finalized_at=finalized_at,
            revision=current.revision + 1,
            migration_provenance=(
                current.commit_target_kind is ApprovalCommitTargetKind.LEGACY_UNRESOLVED
            ),
        )
        candidate_finalized_at = candidate.finalized_at
        if candidate_finalized_at is None:
            raise ApprovalExecutionReceiptDataError("finalized receipt is missing finalized_at")
        cursor = connection.execute(
            """
            UPDATE harness_approval_execution_receipts
            SET decision = ?, execution_state = 'FINALIZED', disposition = ?,
                domain_receipt_id = ?, result_evidence_json = ?,
                failure_class = ?, failure_code = ?, failure_summary = ?,
                updated_at = ?, started_at = ?, finalized_at = ?, revision = ?
            WHERE approval_request_id = ? AND revision = ? AND execution_state = ?
            """,
            (
                candidate.decision.value if candidate.decision is not None else None,
                candidate.disposition.value if candidate.disposition is not None else None,
                candidate.domain_receipt_id,
                stable_evidence_list_json(candidate.result_evidence),
                (candidate.failure_class.value if candidate.failure_class is not None else None),
                (candidate.failure_code.value if candidate.failure_code is not None else None),
                candidate.failure_summary,
                candidate.updated_at.isoformat(),
                candidate.started_at.isoformat() if candidate.started_at is not None else None,
                candidate_finalized_at.isoformat(),
                candidate.revision,
                approval_request_id,
                expected_revision,
                expected_state.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ApprovalExecutionReceiptConflictError(
                self.get(approval_request_id, connection=connection)
            )
        return self.get(approval_request_id, connection=connection)

    @staticmethod
    def _validate_approval_identity(
        connection: sqlite3.Connection,
        receipt: ApprovalExecutionReceipt,
    ) -> None:
        row = connection.execute(
            """
            SELECT run_id, idempotency_key, kind
            FROM harness_approvals
            WHERE id = ?
            """,
            (receipt.approval_request_id,),
        ).fetchone()
        if row is None:
            raise ValueError("approval identity does not exist")
        if (
            row["run_id"] != receipt.run_id
            or row["idempotency_key"] != receipt.idempotency_key
            or row["kind"] != receipt.kind.value
        ):
            raise ValueError("receipt does not match approval identity")

    @staticmethod
    def _values(receipt: ApprovalExecutionReceipt) -> tuple[object, ...]:
        return (
            receipt.approval_request_id,
            receipt.run_id,
            receipt.idempotency_key,
            receipt.kind.value,
            receipt.decision.value if receipt.decision is not None else None,
            receipt.execution_state.value,
            receipt.disposition.value if receipt.disposition is not None else None,
            receipt.commit_target_kind.value,
            receipt.commit_target_id,
            stable_evidence_json(receipt.target_identity),
            receipt.domain_receipt_id,
            stable_evidence_list_json(receipt.result_evidence),
            receipt.failure_class.value if receipt.failure_class is not None else None,
            receipt.failure_code.value if receipt.failure_code is not None else None,
            receipt.failure_summary,
            receipt.created_at.isoformat(),
            receipt.updated_at.isoformat(),
            receipt.started_at.isoformat() if receipt.started_at is not None else None,
            receipt.finalized_at.isoformat() if receipt.finalized_at is not None else None,
            receipt.revision,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ApprovalExecutionReceipt:
        try:
            if (
                row["run_id"] != row["approval_run_id"]
                or row["idempotency_key"] != row["approval_idempotency_key"]
                or row["kind"] != row["approval_kind"]
            ):
                raise ValueError("approval identity mismatch")
            target_kind = ApprovalCommitTargetKind(row["commit_target_kind"])
            return ApprovalExecutionReceipt(
                approval_request_id=row["approval_request_id"],
                run_id=row["run_id"],
                idempotency_key=row["idempotency_key"],
                kind=ApprovalKind(row["kind"]),
                decision=(ApprovalStatus(row["decision"]) if row["decision"] is not None else None),
                execution_state=ApprovalExecutionState(row["execution_state"]),
                disposition=(
                    ApprovalDisposition(row["disposition"])
                    if row["disposition"] is not None
                    else None
                ),
                commit_target_kind=target_kind,
                commit_target_id=row["commit_target_id"],
                target_identity=_target_from_json(row["target_identity_json"]),
                domain_receipt_id=row["domain_receipt_id"],
                result_evidence=_result_from_json(row["result_evidence_json"]),
                failure_class=(
                    ApprovalFailureClass(row["failure_class"])
                    if row["failure_class"] is not None
                    else None
                ),
                failure_code=(
                    ApprovalFailureCode(row["failure_code"])
                    if row["failure_code"] is not None
                    else None
                ),
                failure_summary=row["failure_summary"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                started_at=(
                    datetime.fromisoformat(row["started_at"])
                    if row["started_at"] is not None
                    else None
                ),
                finalized_at=(
                    datetime.fromisoformat(row["finalized_at"])
                    if row["finalized_at"] is not None
                    else None
                ),
                revision=row["revision"],
                migration_provenance=(target_kind is ApprovalCommitTargetKind.LEGACY_UNRESOLVED),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ApprovalExecutionReceiptDataError("invalid persisted receipt") from None


__all__ = [
    "ApprovalExecutionReceiptConflictError",
    "ApprovalExecutionReceiptDataError",
    "ApprovalExecutionReceiptRepository",
]
