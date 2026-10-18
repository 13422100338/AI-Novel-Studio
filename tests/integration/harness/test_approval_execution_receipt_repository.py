from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

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
    UnsupportedApprovalTargetIdentity,
    stable_evidence_json,
)
from ai_novel_studio.harness.approval_execution_receipt_repository import (
    ApprovalExecutionReceiptConflictError,
    ApprovalExecutionReceiptDataError,
    ApprovalExecutionReceiptRepository,
)
from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalRequest, ApprovalStatus
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _now() -> datetime:
    return datetime(2026, 8, 29, 2, 0, tzinfo=UTC)


def _target() -> ChangeSetTargetIdentity:
    return ChangeSetTargetIdentity(
        change_set_id="change-set-1",
        operations=(
            ChangeSetOperationIdentity(
                operation_id="operation-1",
                operation_kind="CHAPTER_CONTENT_REPLACE",
                target_id="chapter-1",
                expected_revision=4,
                source_hash="a" * 64,
            ),
        ),
    )


def _create_repository(
    tmp_path: Path,
    *,
    kind: ApprovalKind = ApprovalKind.CHANGESET,
    payload: dict[str, object] | None = None,
    idempotency_key: str = "key-1",
) -> tuple[
    ProjectRepository,
    ApprovalRequest,
    ApprovalExecutionReceiptRepository,
]:
    project = ProjectRepository.create(tmp_path / "novel", "Receipt Repository")
    store = HarnessEventStore(HarnessEventRepository(project))
    run, _ = store.start_run(goal="receipt repository")
    approval = ApprovalRepository(project).create(
        run_id=run.id,
        kind=kind,
        summary="review target",
        payload=payload if payload is not None else {},
        expected_revisions=(),
        idempotency_key=idempotency_key,
    )
    return project, approval, ApprovalExecutionReceiptRepository(project)


def _pending_receipt(approval: ApprovalRequest) -> ApprovalExecutionReceipt:
    target = _target()
    return ApprovalExecutionReceipt(
        approval_request_id=approval.request_id,
        run_id=approval.run_id,
        idempotency_key=approval.idempotency_key,
        kind=approval.kind,
        decision=None,
        execution_state=ApprovalExecutionState.PENDING_DECISION,
        disposition=None,
        commit_target_kind=ApprovalCommitTargetKind.CHANGESET,
        commit_target_id=target.change_set_id,
        target_identity=target,
        domain_receipt_id=None,
        result_evidence=(),
        failure_class=None,
        failure_code=None,
        failure_summary=None,
        created_at=_now(),
        updated_at=_now(),
        started_at=None,
        finalized_at=None,
        revision=0,
    )


def _applied_result() -> tuple[ChangeSetOperationResultEvidence, ...]:
    return (
        ChangeSetOperationResultEvidence(
            operation_id="operation-1",
            status=ApprovalOperationStatus.APPLIED,
            committed_revision=5,
            committed_hash="b" * 64,
        ),
    )


def test_repository_creates_gets_and_bounded_lists_receipts(tmp_path: Path) -> None:
    _project, approval, repository = _create_repository(tmp_path)
    receipt = repository.create(_pending_receipt(approval))

    assert repository.get(approval.request_id) == receipt
    assert repository.list_for_run(approval.run_id, limit=1) == (receipt,)
    with pytest.raises(ValueError, match="between 1 and 100"):
        repository.list_for_run(approval.run_id, limit=0)
    with pytest.raises(ValueError, match="between 1 and 100"):
        repository.list_for_run(approval.run_id, limit=101)


def test_create_rejects_approval_identity_drift_and_migration_only_target(
    tmp_path: Path,
) -> None:
    _project, approval, repository = _create_repository(tmp_path)
    receipt = _pending_receipt(approval)

    with pytest.raises(ValueError, match="approval identity"):
        repository.create(
            ApprovalExecutionReceipt(
                approval_request_id=receipt.approval_request_id,
                run_id=receipt.run_id,
                idempotency_key="other-key",
                kind=receipt.kind,
                decision=receipt.decision,
                execution_state=receipt.execution_state,
                disposition=receipt.disposition,
                commit_target_kind=receipt.commit_target_kind,
                commit_target_id=receipt.commit_target_id,
                target_identity=receipt.target_identity,
                domain_receipt_id=None,
                result_evidence=(),
                failure_class=None,
                failure_code=None,
                failure_summary=None,
                created_at=receipt.created_at,
                updated_at=receipt.updated_at,
                started_at=None,
                finalized_at=None,
                revision=0,
            )
        )

    legacy_identity = LegacyUnresolvedTargetIdentity(
        approval_request_id=approval.request_id,
        approval_kind=ApprovalKind.CHANGESET,
    )
    migration_receipt = ApprovalExecutionReceipt(
        approval_request_id=approval.request_id,
        run_id=approval.run_id,
        idempotency_key=approval.idempotency_key,
        kind=approval.kind,
        decision=None,
        execution_state=ApprovalExecutionState.PENDING_DECISION,
        disposition=None,
        commit_target_kind=ApprovalCommitTargetKind.LEGACY_UNRESOLVED,
        commit_target_id=approval.request_id,
        target_identity=legacy_identity,
        domain_receipt_id=None,
        result_evidence=(),
        failure_class=None,
        failure_code=None,
        failure_summary=None,
        created_at=_now(),
        updated_at=_now(),
        started_at=None,
        finalized_at=None,
        revision=0,
        migration_provenance=True,
    )
    with pytest.raises(ValueError, match="migration-only"):
        repository.create(migration_receipt)


def test_cas_transition_increments_revision_and_stale_claim_returns_conflict(
    tmp_path: Path,
) -> None:
    _project, approval, repository = _create_repository(tmp_path)
    repository.create(_pending_receipt(approval))

    ready = repository.transition(
        approval.request_id,
        expected_revision=0,
        expected_state=ApprovalExecutionState.PENDING_DECISION,
        target_state=ApprovalExecutionState.READY,
        decision=ApprovalStatus.APPROVED,
        updated_at=_now(),
    )
    assert ready.execution_state is ApprovalExecutionState.READY
    assert ready.decision is ApprovalStatus.APPROVED
    assert ready.revision == 1

    with pytest.raises(ApprovalExecutionReceiptConflictError) as captured:
        repository.transition(
            approval.request_id,
            expected_revision=0,
            expected_state=ApprovalExecutionState.PENDING_DECISION,
            target_state=ApprovalExecutionState.READY,
            decision=ApprovalStatus.APPROVED,
            updated_at=_now(),
        )
    assert captured.value.current == ready


def test_normal_transition_rejects_skipping_ready(tmp_path: Path) -> None:
    _project, approval, repository = _create_repository(tmp_path)
    repository.create(_pending_receipt(approval))

    for target_state in (
        ApprovalExecutionState.EXECUTING,
        ApprovalExecutionState.RECOVERY_REQUIRED,
    ):
        with pytest.raises(ValueError, match="legal receipt edge"):
            repository.transition(
                approval.request_id,
                expected_revision=0,
                expected_state=ApprovalExecutionState.PENDING_DECISION,
                target_state=target_state,
                decision=ApprovalStatus.APPROVED,
                updated_at=_now(),
            )
    assert repository.get(approval.request_id).execution_state is (
        ApprovalExecutionState.PENDING_DECISION
    )


def test_pending_to_ready_rejects_supplied_started_at_before_sql(tmp_path: Path) -> None:
    _project, approval, repository = _create_repository(tmp_path)
    pending = repository.create(_pending_receipt(approval))

    with pytest.raises(ValueError, match="READY.*started_at"):
        repository.transition(
            approval.request_id,
            expected_revision=pending.revision,
            expected_state=ApprovalExecutionState.PENDING_DECISION,
            target_state=ApprovalExecutionState.READY,
            decision=ApprovalStatus.APPROVED,
            updated_at=_now(),
            started_at=_now(),
        )

    unchanged = repository.get(approval.request_id)
    assert unchanged.execution_state is ApprovalExecutionState.PENDING_DECISION
    assert unchanged.revision == 0
    assert unchanged.started_at is None


def test_normal_pending_finalize_allows_only_rejected_discard(tmp_path: Path) -> None:
    _project, approval, repository = _create_repository(tmp_path)
    repository.create(_pending_receipt(approval))

    with pytest.raises(ValueError, match="legal receipt edge"):
        repository.finalize(
            approval.request_id,
            expected_revision=0,
            expected_state=ApprovalExecutionState.PENDING_DECISION,
            decision=ApprovalStatus.APPROVED,
            disposition=ApprovalDisposition.APPLIED,
            result_evidence=_applied_result(),
            domain_receipt_id="domain-receipt-1",
            failure_class=None,
            failure_code=None,
            failure_summary=None,
            finalized_at=_now(),
        )

    discarded = repository.finalize(
        approval.request_id,
        expected_revision=0,
        expected_state=ApprovalExecutionState.PENDING_DECISION,
        decision=ApprovalStatus.REJECTED,
        disposition=ApprovalDisposition.DISCARDED,
        result_evidence=(),
        domain_receipt_id=None,
        failure_class=None,
        failure_code=None,
        failure_summary=None,
        finalized_at=_now(),
    )
    assert discarded.disposition is ApprovalDisposition.DISCARDED


def test_ready_claim_and_prewrite_failure_are_the_only_legal_edges(
    tmp_path: Path,
) -> None:
    _project, approval, repository = _create_repository(tmp_path)
    repository.create(_pending_receipt(approval))
    ready = repository.transition(
        approval.request_id,
        expected_revision=0,
        expected_state=ApprovalExecutionState.PENDING_DECISION,
        target_state=ApprovalExecutionState.READY,
        decision=ApprovalStatus.APPROVED,
        updated_at=_now(),
    )

    with pytest.raises(ValueError, match="legal receipt edge"):
        repository.transition(
            approval.request_id,
            expected_revision=ready.revision,
            expected_state=ApprovalExecutionState.READY,
            target_state=ApprovalExecutionState.RECOVERY_REQUIRED,
            updated_at=_now(),
        )
    with pytest.raises(ValueError, match="legal receipt edge"):
        repository.finalize(
            approval.request_id,
            expected_revision=ready.revision,
            expected_state=ApprovalExecutionState.READY,
            disposition=ApprovalDisposition.APPLIED,
            result_evidence=_applied_result(),
            domain_receipt_id="domain-receipt-1",
            failure_class=None,
            failure_code=None,
            failure_summary=None,
            finalized_at=_now(),
        )

    executing = repository.transition(
        approval.request_id,
        expected_revision=ready.revision,
        expected_state=ApprovalExecutionState.READY,
        target_state=ApprovalExecutionState.EXECUTING,
        updated_at=_now(),
    )
    applied = repository.finalize(
        approval.request_id,
        expected_revision=executing.revision,
        expected_state=ApprovalExecutionState.EXECUTING,
        disposition=ApprovalDisposition.APPLIED,
        result_evidence=_applied_result(),
        domain_receipt_id="domain-receipt-1",
        failure_class=None,
        failure_code=None,
        failure_summary=None,
        finalized_at=_now(),
    )
    assert applied.started_at is not None
    assert applied.disposition is ApprovalDisposition.APPLIED


def test_recovery_applied_requires_explicit_nonempty_started_at(tmp_path: Path) -> None:
    project, approval, repository = _create_repository(tmp_path)
    target = _target()
    with project.database.connect() as connection, connection:
        connection.execute(
            """
            INSERT INTO harness_approval_execution_receipts(
                approval_request_id, run_id, idempotency_key, kind, decision,
                execution_state, disposition, commit_target_kind, commit_target_id,
                target_identity_json, result_evidence_json, created_at, updated_at,
                revision
            ) VALUES (?, ?, ?, ?, 'APPROVED', 'RECOVERY_REQUIRED', NULL,
                      'CHANGESET', ?, ?, '[]', ?, ?, 0)
            """,
            (
                approval.request_id,
                approval.run_id,
                approval.idempotency_key,
                approval.kind.value,
                target.change_set_id,
                stable_evidence_json(target),
                _now().isoformat(),
                _now().isoformat(),
            ),
        )

    with pytest.raises(ValueError, match="started_at"):
        repository.finalize(
            approval.request_id,
            expected_revision=0,
            expected_state=ApprovalExecutionState.RECOVERY_REQUIRED,
            disposition=ApprovalDisposition.APPLIED,
            result_evidence=_applied_result(),
            domain_receipt_id="domain-receipt-1",
            failure_class=None,
            failure_code=None,
            failure_summary=None,
            finalized_at=_now(),
        )

    applied = repository.finalize(
        approval.request_id,
        expected_revision=0,
        expected_state=ApprovalExecutionState.RECOVERY_REQUIRED,
        disposition=ApprovalDisposition.APPLIED,
        result_evidence=_applied_result(),
        domain_receipt_id="domain-receipt-1",
        failure_class=None,
        failure_code=None,
        failure_summary=None,
        started_at=_now(),
        finalized_at=_now(),
    )
    assert applied.started_at == _now()


def test_finalize_uses_cas_and_enforces_typed_failure_matrix(tmp_path: Path) -> None:
    _project, approval, repository = _create_repository(tmp_path)
    repository.create(_pending_receipt(approval))
    ready = repository.transition(
        approval.request_id,
        expected_revision=0,
        expected_state=ApprovalExecutionState.PENDING_DECISION,
        target_state=ApprovalExecutionState.READY,
        decision=ApprovalStatus.APPROVED,
        updated_at=_now(),
    )

    finalized = repository.finalize(
        approval.request_id,
        expected_revision=ready.revision,
        expected_state=ApprovalExecutionState.READY,
        disposition=ApprovalDisposition.FAILED,
        result_evidence=(),
        domain_receipt_id=None,
        failure_class=ApprovalFailureClass.INTEGRITY,
        failure_code=ApprovalFailureCode.MISSING_OUTCOME,
        failure_summary="未找到完整结果",
        finalized_at=_now(),
    )

    assert finalized.execution_state is ApprovalExecutionState.FINALIZED
    assert finalized.revision == 2
    assert finalized.failure_code is ApprovalFailureCode.MISSING_OUTCOME
    with pytest.raises(ApprovalExecutionReceiptConflictError):
        repository.finalize(
            approval.request_id,
            expected_revision=ready.revision,
            expected_state=ApprovalExecutionState.READY,
            disposition=ApprovalDisposition.FAILED,
            result_evidence=(),
            domain_receipt_id=None,
            failure_class=ApprovalFailureClass.INTEGRITY,
            failure_code=ApprovalFailureCode.MISSING_OUTCOME,
            failure_summary=None,
            finalized_at=_now(),
        )


def test_repository_candidate_rejects_failure_class_code_cross_pair(
    tmp_path: Path,
) -> None:
    _project, approval, repository = _create_repository(tmp_path)
    repository.create(_pending_receipt(approval))
    ready = repository.transition(
        approval.request_id,
        expected_revision=0,
        expected_state=ApprovalExecutionState.PENDING_DECISION,
        target_state=ApprovalExecutionState.READY,
        decision=ApprovalStatus.APPROVED,
        updated_at=_now(),
    )

    with pytest.raises(ValueError, match="failure_class.*failure_code"):
        repository.finalize(
            approval.request_id,
            expected_revision=ready.revision,
            expected_state=ApprovalExecutionState.READY,
            disposition=ApprovalDisposition.FAILED,
            result_evidence=(),
            domain_receipt_id=None,
            failure_class=ApprovalFailureClass.VALIDATION,
            failure_code=ApprovalFailureCode.DATABASE_ERROR,
            failure_summary=None,
            finalized_at=_now(),
        )


def test_repository_load_rejects_failure_class_code_cross_pair(
    tmp_path: Path,
) -> None:
    project, approval, repository = _create_repository(tmp_path)
    target = _target()
    with project.database.connect() as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            """
            INSERT INTO harness_approval_execution_receipts(
                approval_request_id, run_id, idempotency_key, kind, decision,
                execution_state, disposition, commit_target_kind, commit_target_id,
                target_identity_json, result_evidence_json, failure_class,
                failure_code, created_at, updated_at, finalized_at, revision
            ) VALUES (?, ?, ?, ?, 'APPROVED', 'FINALIZED', 'FAILED',
                      'CHANGESET', ?, ?, '[]', 'VALIDATION', 'DATABASE_ERROR',
                      ?, ?, ?, 0)
            """,
            (
                approval.request_id,
                approval.run_id,
                approval.idempotency_key,
                approval.kind.value,
                target.change_set_id,
                stable_evidence_json(target),
                _now().isoformat(),
                _now().isoformat(),
                _now().isoformat(),
            ),
        )
        connection.execute("PRAGMA ignore_check_constraints = OFF")

    with pytest.raises(ApprovalExecutionReceiptDataError, match="invalid persisted receipt"):
        repository.get(approval.request_id)


def test_unsupported_receipt_finalizes_directly_without_execution_state(
    tmp_path: Path,
) -> None:
    _project, approval, repository = _create_repository(
        tmp_path,
        kind=ApprovalKind.PROMPT_CHANGE,
    )
    identity = UnsupportedApprovalTargetIdentity(
        approval_request_id=approval.request_id,
        approval_kind=approval.kind,
    )
    pending = ApprovalExecutionReceipt(
        approval_request_id=approval.request_id,
        run_id=approval.run_id,
        idempotency_key=approval.idempotency_key,
        kind=approval.kind,
        decision=None,
        execution_state=ApprovalExecutionState.PENDING_DECISION,
        disposition=None,
        commit_target_kind=ApprovalCommitTargetKind.UNSUPPORTED_APPROVAL,
        commit_target_id=approval.request_id,
        target_identity=identity,
        domain_receipt_id=None,
        result_evidence=(),
        failure_class=None,
        failure_code=None,
        failure_summary=None,
        created_at=_now(),
        updated_at=_now(),
        started_at=None,
        finalized_at=None,
        revision=0,
    )
    repository.create(pending)

    finalized = repository.finalize(
        approval.request_id,
        expected_revision=0,
        expected_state=ApprovalExecutionState.PENDING_DECISION,
        decision=ApprovalStatus.APPROVED,
        disposition=ApprovalDisposition.FAILED,
        result_evidence=(),
        domain_receipt_id=None,
        failure_class=ApprovalFailureClass.UNSUPPORTED,
        failure_code=ApprovalFailureCode.UNSUPPORTED_KIND,
        failure_summary=None,
        finalized_at=_now(),
    )
    assert finalized.execution_state is ApprovalExecutionState.FINALIZED
    assert finalized.failure_code is ApprovalFailureCode.UNSUPPORTED_KIND


def test_load_rejects_unknown_or_invalid_persisted_receipt_state(tmp_path: Path) -> None:
    project, approval, repository = _create_repository(tmp_path)
    target = _target()
    with project.database.connect() as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            """
            INSERT INTO harness_approval_execution_receipts(
                approval_request_id, run_id, idempotency_key, kind, decision,
                execution_state, disposition, commit_target_kind, commit_target_id,
                target_identity_json, result_evidence_json, created_at, updated_at, revision
            ) VALUES (?, ?, ?, ?, NULL, 'UNKNOWN', NULL, 'CHANGESET', ?, ?, '[]', ?, ?, 0)
            """,
            (
                approval.request_id,
                approval.run_id,
                approval.idempotency_key,
                approval.kind.value,
                target.change_set_id,
                stable_evidence_json(target),
                _now().isoformat(),
                _now().isoformat(),
            ),
        )
        connection.execute("PRAGMA ignore_check_constraints = OFF")

    with pytest.raises(ApprovalExecutionReceiptDataError, match="invalid persisted receipt"):
        repository.get(approval.request_id)


def test_load_rejects_raw_or_unknown_identity_json_shape(tmp_path: Path) -> None:
    project, approval, repository = _create_repository(tmp_path)
    with project.database.connect() as connection, connection:
        connection.execute(
            """
            INSERT INTO harness_approval_execution_receipts(
                approval_request_id, run_id, idempotency_key, kind, decision,
                execution_state, disposition, commit_target_kind, commit_target_id,
                target_identity_json, result_evidence_json, created_at, updated_at, revision
            ) VALUES (?, ?, ?, ?, NULL, 'PENDING_DECISION', NULL, 'CHANGESET', ?,
                      '{"schema_version":"changeset-target-v1","payload":"raw"}',
                      '[]', ?, ?, 0)
            """,
            (
                approval.request_id,
                approval.run_id,
                approval.idempotency_key,
                approval.kind.value,
                "change-set-1",
                _now().isoformat(),
                _now().isoformat(),
            ),
        )

    with pytest.raises(ApprovalExecutionReceiptDataError, match="invalid persisted receipt"):
        repository.get(approval.request_id)


def test_repository_uses_parameterized_sql_for_receipt_identity(tmp_path: Path) -> None:
    _project, _approval, repository = _create_repository(tmp_path)
    with pytest.raises(KeyError):
        repository.get("x' OR 1=1 --")


def test_database_unique_identity_conflict_is_typed(tmp_path: Path) -> None:
    _project, approval, repository = _create_repository(tmp_path)
    receipt = repository.create(_pending_receipt(approval))

    with pytest.raises(ApprovalExecutionReceiptConflictError) as captured:
        repository.create(receipt)
    assert captured.value.current == receipt


def test_legacy_reclassification_is_cas_and_stays_recovery_only(
    tmp_path: Path,
) -> None:
    project, approval, repository = _create_repository(tmp_path)
    identity = LegacyUnresolvedTargetIdentity(
        approval_request_id=approval.request_id,
        approval_kind=approval.kind,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            """
            INSERT INTO harness_approval_execution_receipts(
                approval_request_id, run_id, idempotency_key, kind, decision,
                execution_state, disposition, commit_target_kind, commit_target_id,
                target_identity_json, result_evidence_json, created_at, updated_at,
                revision
            ) VALUES (?, ?, ?, ?, 'APPROVED', 'RECOVERY_REQUIRED', NULL,
                      'LEGACY_UNRESOLVED', ?, ?, '[]', ?, ?, 0)
            """,
            (
                approval.request_id,
                approval.run_id,
                approval.idempotency_key,
                approval.kind.value,
                approval.request_id,
                stable_evidence_json(identity),
                _now().isoformat(),
                _now().isoformat(),
            ),
        )

    target = _target()
    reclassified = repository.reclassify_legacy(
        approval.request_id,
        expected_revision=0,
        expected_state=ApprovalExecutionState.RECOVERY_REQUIRED,
        commit_target_kind=ApprovalCommitTargetKind.CHANGESET,
        commit_target_id=target.change_set_id,
        target_identity=target,
        updated_at=_now(),
    )

    assert reclassified.commit_target_kind is ApprovalCommitTargetKind.CHANGESET
    assert reclassified.execution_state is ApprovalExecutionState.RECOVERY_REQUIRED
    assert reclassified.revision == 1
    with pytest.raises(ApprovalExecutionReceiptConflictError):
        repository.reclassify_legacy(
            approval.request_id,
            expected_revision=0,
            expected_state=ApprovalExecutionState.RECOVERY_REQUIRED,
            commit_target_kind=ApprovalCommitTargetKind.CHANGESET,
            commit_target_id=target.change_set_id,
            target_identity=target,
            updated_at=_now(),
        )


def test_pending_legacy_receipt_cannot_reclassify(tmp_path: Path) -> None:
    project, approval, repository = _create_repository(tmp_path)
    identity = LegacyUnresolvedTargetIdentity(
        approval_request_id=approval.request_id,
        approval_kind=approval.kind,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            """
            INSERT INTO harness_approval_execution_receipts(
                approval_request_id, run_id, idempotency_key, kind, decision,
                execution_state, disposition, commit_target_kind, commit_target_id,
                target_identity_json, result_evidence_json, created_at, updated_at,
                revision
            ) VALUES (?, ?, ?, ?, NULL, 'PENDING_DECISION', NULL,
                      'LEGACY_UNRESOLVED', ?, ?, '[]', ?, ?, 0)
            """,
            (
                approval.request_id,
                approval.run_id,
                approval.idempotency_key,
                approval.kind.value,
                approval.request_id,
                stable_evidence_json(identity),
                _now().isoformat(),
                _now().isoformat(),
            ),
        )

    target = _target()
    with pytest.raises(ValueError, match="RECOVERY_REQUIRED"):
        repository.reclassify_legacy(
            approval.request_id,
            expected_revision=0,
            expected_state=ApprovalExecutionState.PENDING_DECISION,
            commit_target_kind=ApprovalCommitTargetKind.CHANGESET,
            commit_target_id=target.change_set_id,
            target_identity=target,
            updated_at=_now(),
        )
    assert repository.get(approval.request_id).commit_target_kind is (
        ApprovalCommitTargetKind.LEGACY_UNRESOLVED
    )


def test_test_fixture_does_not_disable_foreign_key_checks(tmp_path: Path) -> None:
    project, _approval, _repository = _create_repository(tmp_path)
    with project.database.connect() as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM harness_approval_execution_receipts"
            ).fetchone()[0]
            == 0
        )
        assert isinstance(connection, sqlite3.Connection)
