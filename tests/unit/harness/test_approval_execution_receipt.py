from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

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
    ProjectConstitutionResultEvidence,
    ProjectConstitutionTargetIdentity,
    SubjectMergeResultEvidence,
    SubjectMergeTargetIdentity,
    UnsupportedApprovalTargetIdentity,
    stable_evidence_json,
)
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalStatus


def _now() -> datetime:
    return datetime(2026, 8, 29, 1, 2, 3, tzinfo=UTC)


def _changeset_target(operation_count: int = 1) -> ChangeSetTargetIdentity:
    return ChangeSetTargetIdentity(
        change_set_id="change-set-1",
        operations=tuple(
            ChangeSetOperationIdentity(
                operation_id=f"operation-{index}",
                operation_kind="CHAPTER_CONTENT_REPLACE",
                target_id=f"chapter-{index}",
                expected_revision=index,
                source_hash="a" * 64,
            )
            for index in range(operation_count)
        ),
    )


def _receipt(
    *,
    kind: ApprovalKind = ApprovalKind.CHANGESET,
    decision: ApprovalStatus | None = None,
    execution_state: ApprovalExecutionState = ApprovalExecutionState.PENDING_DECISION,
    disposition: ApprovalDisposition | None = None,
    commit_target_kind: ApprovalCommitTargetKind = ApprovalCommitTargetKind.CHANGESET,
    target_identity: object | None = None,
    result_evidence: tuple[object, ...] = (),
    domain_receipt_id: str | None = None,
    failure_class: ApprovalFailureClass | None = None,
    failure_code: ApprovalFailureCode | None = None,
    failure_summary: str | None = None,
    started_at: datetime | None = None,
    finalized_at: datetime | None = None,
    revision: int = 0,
    migration_provenance: bool = False,
) -> ApprovalExecutionReceipt:
    target = target_identity if target_identity is not None else _changeset_target()
    commit_target_id = (
        target.change_set_id if isinstance(target, ChangeSetTargetIdentity) else "approval-1"
    )
    return ApprovalExecutionReceipt(
        approval_request_id="approval-1",
        run_id="run-1",
        idempotency_key="approval-key-1",
        kind=kind,
        decision=decision,
        execution_state=execution_state,
        disposition=disposition,
        commit_target_kind=commit_target_kind,
        commit_target_id=commit_target_id,
        target_identity=target,
        domain_receipt_id=domain_receipt_id,
        result_evidence=result_evidence,
        failure_class=failure_class,
        failure_code=failure_code,
        failure_summary=failure_summary,
        created_at=_now(),
        updated_at=_now(),
        started_at=started_at,
        finalized_at=finalized_at,
        revision=revision,
        migration_provenance=migration_provenance,
    )


def test_receipt_enum_vocabularies_match_adr_0025() -> None:
    assert {item.value for item in ApprovalDisposition} == {
        "APPLIED",
        "DISCARDED",
        "STALE",
        "FAILED",
    }
    assert {item.value for item in ApprovalExecutionState} == {
        "PENDING_DECISION",
        "READY",
        "EXECUTING",
        "RECOVERY_REQUIRED",
        "FINALIZED",
    }
    assert {item.value for item in ApprovalCommitTargetKind} == {
        "CHANGESET",
        "SUBJECT_MERGE",
        "PROJECT_CONSTITUTION",
        "UNSUPPORTED_APPROVAL",
        "LEGACY_UNRESOLVED",
    }


def test_target_identity_json_is_stable_allowlisted_and_bounded() -> None:
    target = _changeset_target(2)

    assert stable_evidence_json(target) == (
        '{"change_set_id":"change-set-1","operations":['
        '{"expected_revision":0,"operation_id":"operation-0",'
        '"operation_kind":"CHAPTER_CONTENT_REPLACE","source_hash":"'
        + "a"
        * 64
        + '","target_id":"chapter-0"},'
        '{"expected_revision":1,"operation_id":"operation-1",'
        '"operation_kind":"CHAPTER_CONTENT_REPLACE","source_hash":"'
        + "a" * 64
        + '","target_id":"chapter-1"}],"schema_version":"changeset-target-v1"}'
    )
    assert set(target.to_dict()) == {"schema_version", "change_set_id", "operations"}
    assert all(
        forbidden not in stable_evidence_json(target)
        for forbidden in ("payload", "proposal", "selection", "path", "prompt", "credential")
    )


def test_changeset_identity_rejects_more_than_fifty_operations() -> None:
    with pytest.raises(ValueError, match="at most 50"):
        _changeset_target(51)


@pytest.mark.parametrize(
    ("identity", "expected_json"),
    [
        (
            UnsupportedApprovalTargetIdentity(
                approval_request_id="approval-1",
                approval_kind=ApprovalKind.PROMPT_CHANGE,
            ),
            '{"approval_kind":"PROMPT_CHANGE","approval_request_id":"approval-1",'
            '"reason_code":"UNSUPPORTED_KIND",'
            '"schema_version":"unsupported-approval-v1"}',
        ),
        (
            LegacyUnresolvedTargetIdentity(
                approval_request_id="approval-1",
                approval_kind=ApprovalKind.CHANGESET,
            ),
            '{"approval_kind":"CHANGESET","approval_request_id":"approval-1",'
            '"reason_code":"MISSING_OR_INVALID_TARGET_IDENTITY",'
            '"schema_version":"legacy-unresolved-v1"}',
        ),
    ],
)
def test_non_commit_target_identities_have_exact_fixed_shapes(
    identity: object, expected_json: str
) -> None:
    assert stable_evidence_json(identity) == expected_json
    assert {field.name for field in dataclasses.fields(identity)} == {
        "approval_request_id",
        "approval_kind",
    }


def test_pending_ready_and_executing_state_combinations_are_closed() -> None:
    assert _receipt().decision is None
    assert (
        _receipt(
            decision=ApprovalStatus.APPROVED,
            execution_state=ApprovalExecutionState.READY,
        ).execution_state
        is ApprovalExecutionState.READY
    )
    assert (
        _receipt(
            decision=ApprovalStatus.APPROVED,
            execution_state=ApprovalExecutionState.EXECUTING,
            started_at=_now(),
            revision=2,
        ).revision
        == 2
    )

    with pytest.raises(ValueError, match="PENDING_DECISION"):
        _receipt(decision=ApprovalStatus.APPROVED)
    with pytest.raises(ValueError, match="READY"):
        _receipt(execution_state=ApprovalExecutionState.READY)
    with pytest.raises(ValueError, match="started_at"):
        _receipt(
            decision=ApprovalStatus.APPROVED,
            execution_state=ApprovalExecutionState.EXECUTING,
        )
    with pytest.raises(ValueError, match="non-negative"):
        _receipt(revision=-1)


def test_pending_and_ready_receipts_reject_started_at() -> None:
    with pytest.raises(ValueError, match="PENDING_DECISION.*started_at"):
        _receipt(started_at=_now())
    with pytest.raises(ValueError, match="READY.*started_at"):
        _receipt(
            decision=ApprovalStatus.APPROVED,
            execution_state=ApprovalExecutionState.READY,
            started_at=_now(),
        )


def test_non_commit_pending_receipts_reject_started_at() -> None:
    unsupported = UnsupportedApprovalTargetIdentity(
        approval_request_id="approval-1",
        approval_kind=ApprovalKind.PROMPT_CHANGE,
    )
    with pytest.raises(ValueError, match="PENDING_DECISION.*started_at"):
        _receipt(
            kind=ApprovalKind.PROMPT_CHANGE,
            commit_target_kind=ApprovalCommitTargetKind.UNSUPPORTED_APPROVAL,
            target_identity=unsupported,
            started_at=_now(),
        )

    legacy = LegacyUnresolvedTargetIdentity(
        approval_request_id="approval-1",
        approval_kind=ApprovalKind.CHANGESET,
    )
    with pytest.raises(ValueError, match="PENDING_DECISION.*started_at"):
        _receipt(
            commit_target_kind=ApprovalCommitTargetKind.LEGACY_UNRESOLVED,
            target_identity=legacy,
            started_at=_now(),
            migration_provenance=True,
        )


def test_finalized_applied_requires_complete_unique_changeset_results() -> None:
    target = _changeset_target(2)
    results = tuple(
        ChangeSetOperationResultEvidence(
            operation_id=f"operation-{index}",
            status=ApprovalOperationStatus.APPLIED,
            committed_revision=index + 1,
            committed_hash="b" * 64,
        )
        for index in range(2)
    )
    receipt = _receipt(
        decision=ApprovalStatus.APPROVED,
        execution_state=ApprovalExecutionState.FINALIZED,
        disposition=ApprovalDisposition.APPLIED,
        target_identity=target,
        result_evidence=results,
        domain_receipt_id="domain-receipt-1",
        started_at=_now(),
        finalized_at=_now(),
    )
    assert receipt.disposition is ApprovalDisposition.APPLIED

    with pytest.raises(ValueError, match="exactly one APPLIED"):
        _receipt(
            decision=ApprovalStatus.APPROVED,
            execution_state=ApprovalExecutionState.FINALIZED,
            disposition=ApprovalDisposition.APPLIED,
            target_identity=target,
            result_evidence=results[:1],
            domain_receipt_id="domain-receipt-1",
            started_at=_now(),
            finalized_at=_now(),
        )


def test_typed_stale_and_failed_combinations_do_not_use_message_inference() -> None:
    stale = _receipt(
        decision=ApprovalStatus.APPROVED,
        execution_state=ApprovalExecutionState.FINALIZED,
        disposition=ApprovalDisposition.STALE,
        failure_class=ApprovalFailureClass.STALE_CONFLICT,
        failure_code=ApprovalFailureCode.REVISION_CONFLICT,
        failure_summary="目标版本已变化",
        finalized_at=_now(),
    )
    assert stale.disposition is ApprovalDisposition.STALE

    with pytest.raises(ValueError, match="STALE_CONFLICT"):
        _receipt(
            decision=ApprovalStatus.APPROVED,
            execution_state=ApprovalExecutionState.FINALIZED,
            disposition=ApprovalDisposition.STALE,
            failure_class=ApprovalFailureClass.INTEGRITY,
            failure_code=ApprovalFailureCode.MISSING_OUTCOME,
            finalized_at=_now(),
        )
    with pytest.raises(ValueError, match="failure_class"):
        _receipt(
            decision=ApprovalStatus.APPROVED,
            execution_state=ApprovalExecutionState.FINALIZED,
            disposition=ApprovalDisposition.FAILED,
            finalized_at=_now(),
        )


@pytest.mark.parametrize(
    ("failure_class", "failure_code"),
    [
        (ApprovalFailureClass.VALIDATION, ApprovalFailureCode.DATABASE_ERROR),
        (
            ApprovalFailureClass.SERIALIZATION,
            ApprovalFailureCode.VALIDATION_FAILED,
        ),
        (ApprovalFailureClass.UNSUPPORTED, ApprovalFailureCode.MISSING_OUTCOME),
        (ApprovalFailureClass.INTEGRITY, ApprovalFailureCode.UNSUPPORTED_KIND),
        (ApprovalFailureClass.PERSISTENCE, ApprovalFailureCode.PARTIAL_OUTCOME),
    ],
)
def test_failure_class_code_cross_pairs_are_rejected(
    failure_class: ApprovalFailureClass,
    failure_code: ApprovalFailureCode,
) -> None:
    with pytest.raises(ValueError, match="failure_class.*failure_code"):
        _receipt(
            decision=ApprovalStatus.APPROVED,
            execution_state=ApprovalExecutionState.FINALIZED,
            disposition=ApprovalDisposition.FAILED,
            failure_class=failure_class,
            failure_code=failure_code,
            finalized_at=_now(),
        )


@pytest.mark.parametrize(
    ("disposition", "failure_class", "failure_code"),
    [
        (
            ApprovalDisposition.STALE,
            ApprovalFailureClass.STALE_CONFLICT,
            ApprovalFailureCode.REVISION_CONFLICT,
        ),
        (
            ApprovalDisposition.STALE,
            ApprovalFailureClass.STALE_CONFLICT,
            ApprovalFailureCode.CONTENT_HASH_CONFLICT,
        ),
        (
            ApprovalDisposition.STALE,
            ApprovalFailureClass.STALE_CONFLICT,
            ApprovalFailureCode.PATCH_REPLAY_CONFLICT,
        ),
        (
            ApprovalDisposition.FAILED,
            ApprovalFailureClass.VALIDATION,
            ApprovalFailureCode.VALIDATION_FAILED,
        ),
        (
            ApprovalDisposition.FAILED,
            ApprovalFailureClass.SERIALIZATION,
            ApprovalFailureCode.SERIALIZATION_FAILED,
        ),
        (
            ApprovalDisposition.FAILED,
            ApprovalFailureClass.UNSUPPORTED,
            ApprovalFailureCode.UNSUPPORTED_KIND,
        ),
        (
            ApprovalDisposition.FAILED,
            ApprovalFailureClass.INTEGRITY,
            ApprovalFailureCode.IDEMPOTENCY_IDENTITY_MISMATCH,
        ),
        (
            ApprovalDisposition.FAILED,
            ApprovalFailureClass.INTEGRITY,
            ApprovalFailureCode.MISSING_OUTCOME,
        ),
        (
            ApprovalDisposition.FAILED,
            ApprovalFailureClass.INTEGRITY,
            ApprovalFailureCode.PARTIAL_OUTCOME,
        ),
        (
            ApprovalDisposition.FAILED,
            ApprovalFailureClass.INTEGRITY,
            ApprovalFailureCode.MISSING_TARGET_IDENTITY,
        ),
        (
            ApprovalDisposition.FAILED,
            ApprovalFailureClass.PERSISTENCE,
            ApprovalFailureCode.DATABASE_ERROR,
        ),
    ],
)
def test_failure_class_code_mapping_accepts_only_frozen_pairs(
    disposition: ApprovalDisposition,
    failure_class: ApprovalFailureClass,
    failure_code: ApprovalFailureCode,
) -> None:
    receipt = _receipt(
        decision=ApprovalStatus.APPROVED,
        execution_state=ApprovalExecutionState.FINALIZED,
        disposition=disposition,
        failure_class=failure_class,
        failure_code=failure_code,
        finalized_at=_now(),
    )
    assert (receipt.failure_class, receipt.failure_code) == (
        failure_class,
        failure_code,
    )


def test_rejected_receipt_can_only_finalize_discarded_without_failure() -> None:
    receipt = _receipt(
        decision=ApprovalStatus.REJECTED,
        execution_state=ApprovalExecutionState.FINALIZED,
        disposition=ApprovalDisposition.DISCARDED,
        finalized_at=_now(),
    )
    assert receipt.disposition is ApprovalDisposition.DISCARDED

    with pytest.raises(ValueError, match="REJECTED"):
        _receipt(
            decision=ApprovalStatus.REJECTED,
            execution_state=ApprovalExecutionState.FINALIZED,
            disposition=ApprovalDisposition.FAILED,
            failure_class=ApprovalFailureClass.INTEGRITY,
            failure_code=ApprovalFailureCode.MISSING_OUTCOME,
            finalized_at=_now(),
        )


def test_unsupported_target_matrix_never_enters_execution_states() -> None:
    identity = UnsupportedApprovalTargetIdentity(
        approval_request_id="approval-1",
        approval_kind=ApprovalKind.SKILL_CHANGE,
    )
    pending = _receipt(
        kind=ApprovalKind.SKILL_CHANGE,
        commit_target_kind=ApprovalCommitTargetKind.UNSUPPORTED_APPROVAL,
        target_identity=identity,
    )
    assert pending.execution_state is ApprovalExecutionState.PENDING_DECISION

    with pytest.raises(ValueError, match="UNSUPPORTED_APPROVAL"):
        _receipt(
            kind=ApprovalKind.SKILL_CHANGE,
            decision=ApprovalStatus.APPROVED,
            execution_state=ApprovalExecutionState.READY,
            commit_target_kind=ApprovalCommitTargetKind.UNSUPPORTED_APPROVAL,
            target_identity=identity,
        )

    failed = _receipt(
        kind=ApprovalKind.SKILL_CHANGE,
        decision=ApprovalStatus.APPROVED,
        execution_state=ApprovalExecutionState.FINALIZED,
        disposition=ApprovalDisposition.FAILED,
        commit_target_kind=ApprovalCommitTargetKind.UNSUPPORTED_APPROVAL,
        target_identity=identity,
        failure_class=ApprovalFailureClass.UNSUPPORTED,
        failure_code=ApprovalFailureCode.UNSUPPORTED_KIND,
        finalized_at=_now(),
    )
    assert failed.failure_code is ApprovalFailureCode.UNSUPPORTED_KIND


def test_legacy_unresolved_is_migration_only_and_never_ready_applied_or_stale() -> None:
    identity = LegacyUnresolvedTargetIdentity(
        approval_request_id="approval-1",
        approval_kind=ApprovalKind.CHANGESET,
    )
    with pytest.raises(ValueError, match="migration provenance"):
        _receipt(
            commit_target_kind=ApprovalCommitTargetKind.LEGACY_UNRESOLVED,
            target_identity=identity,
        )

    pending = _receipt(
        commit_target_kind=ApprovalCommitTargetKind.LEGACY_UNRESOLVED,
        target_identity=identity,
        migration_provenance=True,
    )
    assert pending.execution_state is ApprovalExecutionState.PENDING_DECISION

    for state, disposition in (
        (ApprovalExecutionState.READY, None),
        (ApprovalExecutionState.EXECUTING, None),
        (ApprovalExecutionState.FINALIZED, ApprovalDisposition.APPLIED),
        (ApprovalExecutionState.FINALIZED, ApprovalDisposition.STALE),
    ):
        with pytest.raises(ValueError, match="LEGACY_UNRESOLVED"):
            _receipt(
                decision=ApprovalStatus.APPROVED,
                execution_state=state,
                disposition=disposition,
                commit_target_kind=ApprovalCommitTargetKind.LEGACY_UNRESOLVED,
                target_identity=identity,
                started_at=_now() if state is ApprovalExecutionState.EXECUTING else None,
                finalized_at=_now() if state is ApprovalExecutionState.FINALIZED else None,
                migration_provenance=True,
            )


def test_subject_merge_and_constitution_applied_evidence_is_typed() -> None:
    merge_target = SubjectMergeTargetIdentity(
        approval_request_id="approval-1",
        source_subject_id="subject-source",
        target_subject_id="subject-target",
        expected_revisions=(("subject.state_events:subject-source", 3),),
    )
    merge_receipt = _receipt(
        kind=ApprovalKind.SUBJECT_MERGE,
        decision=ApprovalStatus.APPROVED,
        execution_state=ApprovalExecutionState.FINALIZED,
        disposition=ApprovalDisposition.APPLIED,
        commit_target_kind=ApprovalCommitTargetKind.SUBJECT_MERGE,
        target_identity=merge_target,
        result_evidence=(
            SubjectMergeResultEvidence(
                merge_record_id="merge-1", status=ApprovalOperationStatus.APPLIED
            ),
        ),
        domain_receipt_id="merge-1",
        started_at=_now(),
        finalized_at=_now(),
    )
    assert merge_receipt.domain_receipt_id == "merge-1"

    constitution_target = ProjectConstitutionTargetIdentity(
        approval_request_id="approval-1",
        project_id="project-1",
        base_revision=2,
        proposal_digest="c" * 64,
    )
    constitution_receipt = _receipt(
        kind=ApprovalKind.PROJECT_CONSTITUTION,
        decision=ApprovalStatus.APPROVED,
        execution_state=ApprovalExecutionState.FINALIZED,
        disposition=ApprovalDisposition.APPLIED,
        commit_target_kind=ApprovalCommitTargetKind.PROJECT_CONSTITUTION,
        target_identity=constitution_target,
        result_evidence=(
            ProjectConstitutionResultEvidence(
                constitution_revision=3,
                status=ApprovalOperationStatus.APPLIED,
            ),
        ),
        domain_receipt_id="constitution-3",
        started_at=_now(),
        finalized_at=_now(),
    )
    assert constitution_receipt.result_evidence[0].to_dict()["constitution_revision"] == 3


def test_json_field_and_failure_summary_caps_are_enforced() -> None:
    with pytest.raises(ValueError, match="16 KiB"):
        ChangeSetTargetIdentity(
            change_set_id="change-set-1",
            operations=(
                ChangeSetOperationIdentity(
                    operation_id="operation-1",
                    operation_kind="X" * 17000,
                    target_id="chapter-1",
                    expected_revision=1,
                    source_hash=None,
                ),
            ),
        )
    with pytest.raises(ValueError, match="512"):
        _receipt(
            decision=ApprovalStatus.APPROVED,
            execution_state=ApprovalExecutionState.FINALIZED,
            disposition=ApprovalDisposition.FAILED,
            failure_class=ApprovalFailureClass.INTEGRITY,
            failure_code=ApprovalFailureCode.MISSING_OUTCOME,
            failure_summary="x" * 513,
            finalized_at=_now(),
        )


def test_receipt_rejects_bad_timestamp_order_and_non_datetime_values() -> None:
    with pytest.raises(ValueError, match="updated_at"):
        ApprovalExecutionReceipt(
            approval_request_id="approval-1",
            run_id="run-1",
            idempotency_key="key-1",
            kind=ApprovalKind.CHANGESET,
            decision=None,
            execution_state=ApprovalExecutionState.PENDING_DECISION,
            disposition=None,
            commit_target_kind=ApprovalCommitTargetKind.CHANGESET,
            commit_target_id="change-set-1",
            target_identity=_changeset_target(),
            domain_receipt_id=None,
            result_evidence=(),
            failure_class=None,
            failure_code=None,
            failure_summary=None,
            created_at=_now(),
            updated_at=_now() - timedelta(seconds=1),
            started_at=None,
            finalized_at=None,
            revision=0,
        )
    with pytest.raises(ValueError, match="datetime"):
        _receipt(started_at="not-a-datetime")  # type: ignore[arg-type]
