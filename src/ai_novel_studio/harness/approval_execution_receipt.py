from __future__ import annotations

import json
import re
from dataclasses import InitVar, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypeAlias

from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalStatus

MAX_EVIDENCE_BYTES = 16 * 1024
MAX_CHANGESET_OPERATIONS = 50
MAX_FAILURE_SUMMARY_CODEPOINTS = 512
MAX_MACHINE_TOKEN_LENGTH = 64

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ApprovalDisposition(StrEnum):
    APPLIED = "APPLIED"
    DISCARDED = "DISCARDED"
    STALE = "STALE"
    FAILED = "FAILED"


class ApprovalExecutionState(StrEnum):
    PENDING_DECISION = "PENDING_DECISION"
    READY = "READY"
    EXECUTING = "EXECUTING"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    FINALIZED = "FINALIZED"


class ApprovalCommitTargetKind(StrEnum):
    CHANGESET = "CHANGESET"
    SUBJECT_MERGE = "SUBJECT_MERGE"
    PROJECT_CONSTITUTION = "PROJECT_CONSTITUTION"
    UNSUPPORTED_APPROVAL = "UNSUPPORTED_APPROVAL"
    LEGACY_UNRESOLVED = "LEGACY_UNRESOLVED"


class ApprovalFailureClass(StrEnum):
    STALE_CONFLICT = "STALE_CONFLICT"
    VALIDATION = "VALIDATION"
    SERIALIZATION = "SERIALIZATION"
    UNSUPPORTED = "UNSUPPORTED"
    INTEGRITY = "INTEGRITY"
    PERSISTENCE = "PERSISTENCE"


class ApprovalFailureCode(StrEnum):
    REVISION_CONFLICT = "REVISION_CONFLICT"
    CONTENT_HASH_CONFLICT = "CONTENT_HASH_CONFLICT"
    PATCH_REPLAY_CONFLICT = "PATCH_REPLAY_CONFLICT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    SERIALIZATION_FAILED = "SERIALIZATION_FAILED"
    UNSUPPORTED_KIND = "UNSUPPORTED_KIND"
    IDEMPOTENCY_IDENTITY_MISMATCH = "IDEMPOTENCY_IDENTITY_MISMATCH"
    DATABASE_ERROR = "DATABASE_ERROR"
    MISSING_OUTCOME = "MISSING_OUTCOME"
    PARTIAL_OUTCOME = "PARTIAL_OUTCOME"
    MISSING_TARGET_IDENTITY = "MISSING_TARGET_IDENTITY"


class ApprovalOperationStatus(StrEnum):
    READY = "READY"
    APPLIED = "APPLIED"
    FAILED = "FAILED"


class _Evidence(Protocol):
    def to_dict(self) -> dict[str, object]: ...


def _required(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


def _optional_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return _required(value, field)


def _non_negative(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _positive(value: int, field: str) -> int:
    normalized = _non_negative(value, field)
    if normalized == 0:
        raise ValueError(f"{field} must be positive")
    return normalized


def _datetime(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a datetime")
    if value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _optional_datetime(value: datetime | None, field: str) -> datetime | None:
    return None if value is None else _datetime(value, field)


def _digest(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    normalized = _required(value, field)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a lowercase 64-character hex digest")
    return normalized


def _enum(value: object, expected_type: type[StrEnum], field: str) -> None:
    if not isinstance(value, expected_type):
        raise ValueError(f"{field} must be a {expected_type.__name__}")


def _stable_json(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(serialized.encode("utf-8")) > MAX_EVIDENCE_BYTES:
        raise ValueError("evidence JSON must be at most 16 KiB of UTF-8")
    return serialized


def stable_evidence_json(value: _Evidence) -> str:
    return _stable_json(value.to_dict())


def stable_evidence_list_json(values: tuple[_Evidence, ...]) -> str:
    return _stable_json([value.to_dict() for value in values])


@dataclass(frozen=True, slots=True)
class ChangeSetOperationIdentity:
    operation_id: str
    operation_kind: str
    target_id: str
    expected_revision: int | None
    source_hash: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _required(self.operation_id, "operation_id"))
        object.__setattr__(self, "operation_kind", _required(self.operation_kind, "operation_kind"))
        object.__setattr__(self, "target_id", _required(self.target_id, "target_id"))
        if self.expected_revision is not None:
            object.__setattr__(
                self,
                "expected_revision",
                _non_negative(self.expected_revision, "expected_revision"),
            )
        object.__setattr__(self, "source_hash", _digest(self.source_hash, "source_hash"))

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "operation_kind": self.operation_kind,
            "target_id": self.target_id,
            "expected_revision": self.expected_revision,
            "source_hash": self.source_hash,
        }


@dataclass(frozen=True, slots=True)
class ChangeSetTargetIdentity:
    change_set_id: str
    operations: tuple[ChangeSetOperationIdentity, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_set_id", _required(self.change_set_id, "change_set_id"))
        if not isinstance(self.operations, tuple):
            raise ValueError("operations must be a tuple")
        if not self.operations:
            raise ValueError("operations cannot be empty")
        if len(self.operations) > MAX_CHANGESET_OPERATIONS:
            raise ValueError("operations must contain at most 50 items")
        if any(not isinstance(item, ChangeSetOperationIdentity) for item in self.operations):
            raise ValueError("operations must contain ChangeSetOperationIdentity values")
        operation_ids = [item.operation_id for item in self.operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("operation_id values must be unique")
        stable_evidence_json(self)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "changeset-target-v1",
            "change_set_id": self.change_set_id,
            "operations": [item.to_dict() for item in self.operations],
        }


@dataclass(frozen=True, slots=True)
class SubjectMergeTargetIdentity:
    approval_request_id: str
    source_subject_id: str
    target_subject_id: str
    expected_revisions: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "approval_request_id",
            _required(self.approval_request_id, "approval_request_id"),
        )
        object.__setattr__(
            self, "source_subject_id", _required(self.source_subject_id, "source_subject_id")
        )
        object.__setattr__(
            self, "target_subject_id", _required(self.target_subject_id, "target_subject_id")
        )
        if self.source_subject_id == self.target_subject_id:
            raise ValueError("source_subject_id and target_subject_id must differ")
        if not isinstance(self.expected_revisions, tuple):
            raise ValueError("expected_revisions must be a tuple")
        normalized: list[tuple[str, int]] = []
        for key, revision in self.expected_revisions:
            normalized.append(
                (_required(key, "expected revision key"), _non_negative(revision, "revision"))
            )
        if len({key for key, _ in normalized}) != len(normalized):
            raise ValueError("expected revision keys must be unique")
        object.__setattr__(self, "expected_revisions", tuple(normalized))
        stable_evidence_json(self)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "subject-merge-target-v1",
            "approval_request_id": self.approval_request_id,
            "source_subject_id": self.source_subject_id,
            "target_subject_id": self.target_subject_id,
            "expected_revisions": [
                {"key": key, "revision": revision} for key, revision in self.expected_revisions
            ],
        }


@dataclass(frozen=True, slots=True)
class ProjectConstitutionTargetIdentity:
    approval_request_id: str
    project_id: str
    base_revision: int
    proposal_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "approval_request_id",
            _required(self.approval_request_id, "approval_request_id"),
        )
        object.__setattr__(self, "project_id", _required(self.project_id, "project_id"))
        object.__setattr__(
            self, "base_revision", _non_negative(self.base_revision, "base_revision")
        )
        object.__setattr__(
            self,
            "proposal_digest",
            _digest(self.proposal_digest, "proposal_digest"),
        )
        stable_evidence_json(self)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "project-constitution-target-v1",
            "approval_request_id": self.approval_request_id,
            "project_id": self.project_id,
            "base_revision": self.base_revision,
            "proposal_digest": self.proposal_digest,
        }


@dataclass(frozen=True, slots=True)
class UnsupportedApprovalTargetIdentity:
    approval_request_id: str
    approval_kind: ApprovalKind

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "approval_request_id",
            _required(self.approval_request_id, "approval_request_id"),
        )
        _enum(self.approval_kind, ApprovalKind, "approval_kind")
        if self.approval_kind not in {ApprovalKind.PROMPT_CHANGE, ApprovalKind.SKILL_CHANGE}:
            raise ValueError("unsupported identity requires PROMPT_CHANGE or SKILL_CHANGE")
        stable_evidence_json(self)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "unsupported-approval-v1",
            "approval_request_id": self.approval_request_id,
            "approval_kind": self.approval_kind.value,
            "reason_code": "UNSUPPORTED_KIND",
        }


@dataclass(frozen=True, slots=True)
class LegacyUnresolvedTargetIdentity:
    approval_request_id: str
    approval_kind: ApprovalKind

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "approval_request_id",
            _required(self.approval_request_id, "approval_request_id"),
        )
        _enum(self.approval_kind, ApprovalKind, "approval_kind")
        if self.approval_kind not in {
            ApprovalKind.CHANGESET,
            ApprovalKind.SUBJECT_MERGE,
            ApprovalKind.PROJECT_CONSTITUTION,
        }:
            raise ValueError("legacy unresolved identity requires a commit-capable kind")
        stable_evidence_json(self)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "legacy-unresolved-v1",
            "approval_request_id": self.approval_request_id,
            "approval_kind": self.approval_kind.value,
            "reason_code": "MISSING_OR_INVALID_TARGET_IDENTITY",
        }


TargetIdentity: TypeAlias = (
    ChangeSetTargetIdentity
    | SubjectMergeTargetIdentity
    | ProjectConstitutionTargetIdentity
    | UnsupportedApprovalTargetIdentity
    | LegacyUnresolvedTargetIdentity
)


@dataclass(frozen=True, slots=True)
class ChangeSetOperationResultEvidence:
    operation_id: str
    status: ApprovalOperationStatus
    committed_revision: int | None = None
    committed_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _required(self.operation_id, "operation_id"))
        _enum(self.status, ApprovalOperationStatus, "status")
        if self.committed_revision is not None:
            object.__setattr__(
                self,
                "committed_revision",
                _non_negative(self.committed_revision, "committed_revision"),
            )
        object.__setattr__(
            self,
            "committed_hash",
            _digest(self.committed_hash, "committed_hash"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_kind": "CHANGESET_OPERATION",
            "operation_id": self.operation_id,
            "status": self.status.value,
            "committed_revision": self.committed_revision,
            "committed_hash": self.committed_hash,
        }


@dataclass(frozen=True, slots=True)
class SubjectMergeResultEvidence:
    merge_record_id: str
    status: ApprovalOperationStatus

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "merge_record_id", _required(self.merge_record_id, "merge_record_id")
        )
        _enum(self.status, ApprovalOperationStatus, "status")

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_kind": "SUBJECT_MERGE",
            "merge_record_id": self.merge_record_id,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class ProjectConstitutionResultEvidence:
    constitution_revision: int
    status: ApprovalOperationStatus

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "constitution_revision",
            _positive(self.constitution_revision, "constitution_revision"),
        )
        _enum(self.status, ApprovalOperationStatus, "status")

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_kind": "PROJECT_CONSTITUTION",
            "constitution_revision": self.constitution_revision,
            "status": self.status.value,
        }


ResultEvidence: TypeAlias = (
    ChangeSetOperationResultEvidence
    | SubjectMergeResultEvidence
    | ProjectConstitutionResultEvidence
)

_NORMAL_TARGETS = {
    ApprovalCommitTargetKind.CHANGESET,
    ApprovalCommitTargetKind.SUBJECT_MERGE,
    ApprovalCommitTargetKind.PROJECT_CONSTITUTION,
}
_STALE_CODES = {
    ApprovalFailureCode.REVISION_CONFLICT,
    ApprovalFailureCode.CONTENT_HASH_CONFLICT,
    ApprovalFailureCode.PATCH_REPLAY_CONFLICT,
}
_FAILURE_CODES_BY_CLASS = {
    ApprovalFailureClass.STALE_CONFLICT: frozenset(_STALE_CODES),
    ApprovalFailureClass.VALIDATION: frozenset({ApprovalFailureCode.VALIDATION_FAILED}),
    ApprovalFailureClass.SERIALIZATION: frozenset({ApprovalFailureCode.SERIALIZATION_FAILED}),
    ApprovalFailureClass.UNSUPPORTED: frozenset({ApprovalFailureCode.UNSUPPORTED_KIND}),
    ApprovalFailureClass.INTEGRITY: frozenset(
        {
            ApprovalFailureCode.IDEMPOTENCY_IDENTITY_MISMATCH,
            ApprovalFailureCode.MISSING_OUTCOME,
            ApprovalFailureCode.PARTIAL_OUTCOME,
            ApprovalFailureCode.MISSING_TARGET_IDENTITY,
        }
    ),
    ApprovalFailureClass.PERSISTENCE: frozenset({ApprovalFailureCode.DATABASE_ERROR}),
}


@dataclass(frozen=True, slots=True)
class ApprovalExecutionReceipt:
    approval_request_id: str
    run_id: str
    idempotency_key: str
    kind: ApprovalKind
    decision: ApprovalStatus | None
    execution_state: ApprovalExecutionState
    disposition: ApprovalDisposition | None
    commit_target_kind: ApprovalCommitTargetKind
    commit_target_id: str
    target_identity: TargetIdentity
    domain_receipt_id: str | None
    result_evidence: tuple[ResultEvidence, ...]
    failure_class: ApprovalFailureClass | None
    failure_code: ApprovalFailureCode | None
    failure_summary: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finalized_at: datetime | None
    revision: int
    migration_provenance: InitVar[bool] = False

    def __post_init__(self, migration_provenance: bool) -> None:
        self._normalize_fields()
        self._validate_timestamps()
        self._validate_target(migration_provenance=migration_provenance)
        self._validate_state()
        self._validate_result_evidence()
        self._validate_failure()

    def _normalize_fields(self) -> None:
        object.__setattr__(
            self,
            "approval_request_id",
            _required(self.approval_request_id, "approval_request_id"),
        )
        object.__setattr__(self, "run_id", _required(self.run_id, "run_id"))
        object.__setattr__(
            self,
            "idempotency_key",
            _required(self.idempotency_key, "idempotency_key"),
        )
        _enum(self.kind, ApprovalKind, "kind")
        if self.decision is not None:
            _enum(self.decision, ApprovalStatus, "decision")
            if self.decision is ApprovalStatus.PENDING:
                raise ValueError("decision cannot be PENDING")
        _enum(self.execution_state, ApprovalExecutionState, "execution_state")
        if self.disposition is not None:
            _enum(self.disposition, ApprovalDisposition, "disposition")
        _enum(self.commit_target_kind, ApprovalCommitTargetKind, "commit_target_kind")
        object.__setattr__(
            self,
            "commit_target_id",
            _required(self.commit_target_id, "commit_target_id"),
        )
        object.__setattr__(
            self,
            "domain_receipt_id",
            _optional_text(self.domain_receipt_id, "domain_receipt_id"),
        )
        if not isinstance(self.result_evidence, tuple):
            raise ValueError("result_evidence must be a tuple")
        if len(self.result_evidence) > MAX_CHANGESET_OPERATIONS:
            raise ValueError("result_evidence must contain at most 50 items")
        if any(
            not isinstance(
                item,
                (
                    ChangeSetOperationResultEvidence,
                    SubjectMergeResultEvidence,
                    ProjectConstitutionResultEvidence,
                ),
            )
            for item in self.result_evidence
        ):
            raise ValueError("result_evidence contains an unsupported evidence type")
        stable_evidence_list_json(self.result_evidence)
        if self.failure_class is not None:
            _enum(self.failure_class, ApprovalFailureClass, "failure_class")
            if len(self.failure_class.value) > MAX_MACHINE_TOKEN_LENGTH:
                raise ValueError("failure_class exceeds 64 characters")
        if self.failure_code is not None:
            _enum(self.failure_code, ApprovalFailureCode, "failure_code")
            if len(self.failure_code.value) > MAX_MACHINE_TOKEN_LENGTH:
                raise ValueError("failure_code exceeds 64 characters")
        object.__setattr__(
            self,
            "failure_summary",
            _optional_text(self.failure_summary, "failure_summary"),
        )
        if (
            self.failure_summary is not None
            and len(self.failure_summary) > MAX_FAILURE_SUMMARY_CODEPOINTS
        ):
            raise ValueError("failure_summary must be at most 512 Unicode code points")
        object.__setattr__(self, "revision", _non_negative(self.revision, "revision"))

    def _validate_timestamps(self) -> None:
        object.__setattr__(self, "created_at", _datetime(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", _datetime(self.updated_at, "updated_at"))
        object.__setattr__(self, "started_at", _optional_datetime(self.started_at, "started_at"))
        object.__setattr__(
            self, "finalized_at", _optional_datetime(self.finalized_at, "finalized_at")
        )
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        for field, value in (
            ("started_at", self.started_at),
            ("finalized_at", self.finalized_at),
        ):
            if value is not None and value < self.created_at:
                raise ValueError(f"{field} cannot precede created_at")
            if value is not None and value > self.updated_at:
                raise ValueError(f"{field} cannot follow updated_at")
        if (
            self.started_at is not None
            and self.finalized_at is not None
            and self.finalized_at < self.started_at
        ):
            raise ValueError("finalized_at cannot precede started_at")

    def _validate_target(self, *, migration_provenance: bool) -> None:
        if self.commit_target_kind is ApprovalCommitTargetKind.CHANGESET:
            if self.kind is not ApprovalKind.CHANGESET or not isinstance(
                self.target_identity, ChangeSetTargetIdentity
            ):
                raise ValueError("CHANGESET target must match ApprovalKind.CHANGESET")
            expected_target_id = self.target_identity.change_set_id
        elif self.commit_target_kind is ApprovalCommitTargetKind.SUBJECT_MERGE:
            if self.kind is not ApprovalKind.SUBJECT_MERGE or not isinstance(
                self.target_identity, SubjectMergeTargetIdentity
            ):
                raise ValueError("SUBJECT_MERGE target must match ApprovalKind.SUBJECT_MERGE")
            expected_target_id = self.approval_request_id
        elif self.commit_target_kind is ApprovalCommitTargetKind.PROJECT_CONSTITUTION:
            if self.kind is not ApprovalKind.PROJECT_CONSTITUTION or not isinstance(
                self.target_identity, ProjectConstitutionTargetIdentity
            ):
                raise ValueError(
                    "PROJECT_CONSTITUTION target must match ApprovalKind.PROJECT_CONSTITUTION"
                )
            expected_target_id = self.approval_request_id
        elif self.commit_target_kind is ApprovalCommitTargetKind.UNSUPPORTED_APPROVAL:
            if not isinstance(self.target_identity, UnsupportedApprovalTargetIdentity):
                raise ValueError("UNSUPPORTED_APPROVAL requires its fixed identity DTO")
            if self.kind is not self.target_identity.approval_kind:
                raise ValueError("UNSUPPORTED_APPROVAL identity kind mismatch")
            expected_target_id = self.approval_request_id
        else:
            if not migration_provenance:
                raise ValueError("LEGACY_UNRESOLVED is accepted only as migration provenance")
            if not isinstance(self.target_identity, LegacyUnresolvedTargetIdentity):
                raise ValueError("LEGACY_UNRESOLVED requires its fixed identity DTO")
            if self.kind is not self.target_identity.approval_kind:
                raise ValueError("LEGACY_UNRESOLVED identity kind mismatch")
            expected_target_id = self.approval_request_id
        if (
            not isinstance(self.target_identity, ChangeSetTargetIdentity)
            and self.target_identity.approval_request_id != self.approval_request_id
        ):
            raise ValueError("target identity approval_request_id mismatch")
        if self.commit_target_id != expected_target_id:
            raise ValueError("commit_target_id does not match target identity")
        stable_evidence_json(self.target_identity)

    def _validate_state(self) -> None:
        if self.commit_target_kind is ApprovalCommitTargetKind.LEGACY_UNRESOLVED:
            self._validate_legacy_state()
            return
        if self.commit_target_kind is ApprovalCommitTargetKind.UNSUPPORTED_APPROVAL:
            self._validate_unsupported_state()
            return
        if self.execution_state is ApprovalExecutionState.PENDING_DECISION:
            self._require_pending()
        elif self.execution_state is ApprovalExecutionState.READY:
            if self.decision is not ApprovalStatus.APPROVED or self.disposition is not None:
                raise ValueError("READY requires APPROVED with no disposition")
            if self.started_at is not None:
                raise ValueError("READY requires null started_at")
        elif self.execution_state is ApprovalExecutionState.RECOVERY_REQUIRED:
            if self.decision is not ApprovalStatus.APPROVED or self.disposition is not None:
                raise ValueError("RECOVERY_REQUIRED requires APPROVED with no disposition")
        elif self.execution_state is ApprovalExecutionState.EXECUTING:
            if self.decision is not ApprovalStatus.APPROVED or self.disposition is not None:
                raise ValueError("EXECUTING requires APPROVED with no disposition")
            if self.started_at is None:
                raise ValueError("EXECUTING requires started_at")
        else:
            self._require_normal_finalized()

    def _require_pending(self) -> None:
        if self.decision is not None or self.disposition is not None:
            raise ValueError("PENDING_DECISION requires null decision and disposition")
        if self.started_at is not None:
            raise ValueError("PENDING_DECISION requires null started_at")

    def _require_normal_finalized(self) -> None:
        if self.finalized_at is None or self.disposition is None:
            raise ValueError("FINALIZED requires finalized_at and disposition")
        if self.decision is ApprovalStatus.REJECTED:
            if self.disposition is not ApprovalDisposition.DISCARDED:
                raise ValueError("REJECTED may only finalize DISCARDED")
        elif self.decision is ApprovalStatus.APPROVED:
            if self.disposition not in {
                ApprovalDisposition.APPLIED,
                ApprovalDisposition.STALE,
                ApprovalDisposition.FAILED,
            }:
                raise ValueError("APPROVED has an invalid finalized disposition")
        else:
            raise ValueError("FINALIZED requires APPROVED or REJECTED")

    def _validate_legacy_state(self) -> None:
        if self.execution_state in {
            ApprovalExecutionState.READY,
            ApprovalExecutionState.EXECUTING,
        }:
            raise ValueError("LEGACY_UNRESOLVED may never enter READY or EXECUTING")
        if self.execution_state is ApprovalExecutionState.PENDING_DECISION:
            self._require_pending()
        elif self.execution_state is ApprovalExecutionState.RECOVERY_REQUIRED:
            if self.decision is not ApprovalStatus.APPROVED or self.disposition is not None:
                raise ValueError("LEGACY_UNRESOLVED RECOVERY_REQUIRED requires APPROVED")
        elif self.execution_state is ApprovalExecutionState.FINALIZED:
            if self.finalized_at is None:
                raise ValueError("LEGACY_UNRESOLVED FINALIZED requires finalized_at")
            valid_rejected = (
                self.decision is ApprovalStatus.REJECTED
                and self.disposition is ApprovalDisposition.DISCARDED
            )
            valid_approved = (
                self.decision is ApprovalStatus.APPROVED
                and self.disposition is ApprovalDisposition.FAILED
                and self.failure_class is ApprovalFailureClass.INTEGRITY
                and self.failure_code is ApprovalFailureCode.MISSING_TARGET_IDENTITY
            )
            if not (valid_rejected or valid_approved):
                raise ValueError("LEGACY_UNRESOLVED has an invalid terminal combination")
        else:
            raise ValueError("LEGACY_UNRESOLVED has an invalid execution state")

    def _validate_unsupported_state(self) -> None:
        if self.execution_state is ApprovalExecutionState.PENDING_DECISION:
            self._require_pending()
            return
        if self.execution_state is not ApprovalExecutionState.FINALIZED:
            raise ValueError("UNSUPPORTED_APPROVAL may only be pending or finalized")
        if self.finalized_at is None:
            raise ValueError("UNSUPPORTED_APPROVAL FINALIZED requires finalized_at")
        valid_rejected = (
            self.decision is ApprovalStatus.REJECTED
            and self.disposition is ApprovalDisposition.DISCARDED
        )
        valid_approved = (
            self.decision is ApprovalStatus.APPROVED
            and self.disposition is ApprovalDisposition.FAILED
            and self.failure_class is ApprovalFailureClass.UNSUPPORTED
            and self.failure_code is ApprovalFailureCode.UNSUPPORTED_KIND
        )
        if not (valid_rejected or valid_approved):
            raise ValueError("UNSUPPORTED_APPROVAL has an invalid terminal combination")

    def _validate_result_evidence(self) -> None:
        if self.execution_state is not ApprovalExecutionState.FINALIZED:
            if self.result_evidence or self.domain_receipt_id is not None:
                raise ValueError("non-finalized receipts cannot carry result evidence")
            return
        if self.disposition is ApprovalDisposition.DISCARDED:
            if self.result_evidence or self.domain_receipt_id is not None:
                raise ValueError("DISCARDED cannot carry result evidence")
            return
        if self.commit_target_kind not in _NORMAL_TARGETS:
            if self.result_evidence or self.domain_receipt_id is not None:
                raise ValueError("non-commit targets cannot carry result evidence")
            return
        expected_evidence_type: type[
            ChangeSetOperationResultEvidence
            | SubjectMergeResultEvidence
            | ProjectConstitutionResultEvidence
        ]
        if self.commit_target_kind is ApprovalCommitTargetKind.CHANGESET:
            expected_evidence_type = ChangeSetOperationResultEvidence
        elif self.commit_target_kind is ApprovalCommitTargetKind.SUBJECT_MERGE:
            expected_evidence_type = SubjectMergeResultEvidence
        else:
            expected_evidence_type = ProjectConstitutionResultEvidence
        if any(not isinstance(item, expected_evidence_type) for item in self.result_evidence):
            raise ValueError("result evidence does not match commit_target_kind")
        if self.disposition is ApprovalDisposition.APPLIED:
            self._validate_applied_result()

    def _validate_applied_result(self) -> None:
        if self.started_at is None:
            raise ValueError("APPLIED requires non-null started_at")
        if self.domain_receipt_id is None:
            raise ValueError("APPLIED requires domain_receipt_id")
        if self.commit_target_kind is ApprovalCommitTargetKind.CHANGESET:
            target = self.target_identity
            if not isinstance(target, ChangeSetTargetIdentity):
                raise ValueError("CHANGESET target identity is invalid")
            results = self.result_evidence
            intended_ids = {operation.operation_id for operation in target.operations}
            applied_ids = {
                item.operation_id
                for item in results
                if isinstance(item, ChangeSetOperationResultEvidence)
                and item.status is ApprovalOperationStatus.APPLIED
            }
            if len(results) != len(intended_ids) or applied_ids != intended_ids:
                raise ValueError("APPLIED requires exactly one APPLIED result per operation")
        elif self.commit_target_kind is ApprovalCommitTargetKind.SUBJECT_MERGE:
            if len(self.result_evidence) != 1:
                raise ValueError("APPLIED SubjectMerge requires exactly one result")
            result = self.result_evidence[0]
            if (
                not isinstance(result, SubjectMergeResultEvidence)
                or result.status is not ApprovalOperationStatus.APPLIED
                or result.merge_record_id != self.domain_receipt_id
            ):
                raise ValueError("APPLIED SubjectMerge requires its exact merge receipt")
        elif self.commit_target_kind is ApprovalCommitTargetKind.PROJECT_CONSTITUTION:
            if len(self.result_evidence) != 1:
                raise ValueError("APPLIED ProjectConstitution requires exactly one result")
            result = self.result_evidence[0]
            if (
                not isinstance(result, ProjectConstitutionResultEvidence)
                or result.status is not ApprovalOperationStatus.APPLIED
            ):
                raise ValueError("APPLIED ProjectConstitution requires an applied revision")

    def _validate_failure(self) -> None:
        if self.execution_state is not ApprovalExecutionState.FINALIZED:
            if (
                self.failure_class is not None
                or self.failure_code is not None
                or self.failure_summary is not None
            ):
                raise ValueError("non-finalized receipts cannot carry failure data")
            return
        if self.disposition in {
            ApprovalDisposition.APPLIED,
            ApprovalDisposition.DISCARDED,
        }:
            if (
                self.failure_class is not None
                or self.failure_code is not None
                or self.failure_summary is not None
            ):
                raise ValueError(f"{self.disposition.value} cannot carry failure data")
            return
        if self.failure_class is None or self.failure_code is None:
            raise ValueError("FAILED and STALE require failure_class and failure_code")
        if self.failure_code not in _FAILURE_CODES_BY_CLASS[self.failure_class]:
            raise ValueError("failure_class and failure_code do not form a valid pair")
        if self.disposition is ApprovalDisposition.STALE:
            if (
                self.failure_class is not ApprovalFailureClass.STALE_CONFLICT
                or self.failure_code not in _STALE_CODES
            ):
                raise ValueError("STALE requires STALE_CONFLICT and a typed conflict failure code")
        elif self.failure_class is ApprovalFailureClass.STALE_CONFLICT:
            raise ValueError("STALE_CONFLICT failures must use STALE disposition")


__all__ = [
    "ApprovalCommitTargetKind",
    "ApprovalDisposition",
    "ApprovalExecutionReceipt",
    "ApprovalExecutionState",
    "ApprovalFailureClass",
    "ApprovalFailureCode",
    "ApprovalOperationStatus",
    "ChangeSetOperationIdentity",
    "ChangeSetOperationResultEvidence",
    "ChangeSetTargetIdentity",
    "LegacyUnresolvedTargetIdentity",
    "ProjectConstitutionResultEvidence",
    "ProjectConstitutionTargetIdentity",
    "ResultEvidence",
    "SubjectMergeResultEvidence",
    "SubjectMergeTargetIdentity",
    "TargetIdentity",
    "UnsupportedApprovalTargetIdentity",
    "stable_evidence_json",
    "stable_evidence_list_json",
]
