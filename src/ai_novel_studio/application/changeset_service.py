from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import ClassVar

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
    FormalMaintenanceResult,
)
from ai_novel_studio.application.repair_application_service import (
    RepairApplicationError,
    RepairApplicationService,
)
from ai_novel_studio.application.selection_patch import (
    SelectionPatchStaleError,
    SelectionPatchValidationError,
    parse_selection_patch,
    replay_selection_patch,
)
from ai_novel_studio.domain.audit import RepairProposalStatus
from ai_novel_studio.domain.changeset import ChangeOperation, ChangeOperationKind, ChangeSet
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterFileTransaction,
    ChapterRepository,
    StaleChapterRevisionError,
)


class OperationStatus(StrEnum):
    READY = "READY"
    APPLIED = "APPLIED"
    FAILED = "FAILED"


class ChangeSetFailureClass(StrEnum):
    STALE_CONFLICT = "STALE_CONFLICT"
    VALIDATION = "VALIDATION"
    PERSISTENCE = "PERSISTENCE"
    INTEGRITY = "INTEGRITY"


class ChangeSetFailureCode(StrEnum):
    REVISION_CONFLICT = "REVISION_CONFLICT"
    CONTENT_HASH_CONFLICT = "CONTENT_HASH_CONFLICT"
    PATCH_REPLAY_CONFLICT = "PATCH_REPLAY_CONFLICT"
    INVALID_SELECTION_PATCH = "INVALID_SELECTION_PATCH"
    UNKNOWN_CHAPTER = "UNKNOWN_CHAPTER"
    CHAPTER_CONTENT_UNAVAILABLE = "CHAPTER_CONTENT_UNAVAILABLE"
    UNKNOWN_REPAIR_PROPOSAL = "UNKNOWN_REPAIR_PROPOSAL"
    REPAIR_NOT_VALIDATED = "REPAIR_NOT_VALIDATED"
    INVALID_REPAIR_PROPOSAL = "INVALID_REPAIR_PROPOSAL"
    DUPLICATE_REPAIR_PROPOSAL = "DUPLICATE_REPAIR_PROPOSAL"
    INVALID_OPERATION = "INVALID_OPERATION"
    CHANGESET_ABORTED = "CHANGESET_ABORTED"
    OPERATION_PERSISTENCE_FAILED = "OPERATION_PERSISTENCE_FAILED"
    RESULT_INTEGRITY_FAILED = "RESULT_INTEGRITY_FAILED"


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    operation_id: str
    kind: ChangeOperationKind
    chapter_id: str
    status: OperationStatus
    message: str | None = None
    failure_class: ChangeSetFailureClass | None = None
    failure_code: ChangeSetFailureCode | None = None
    committed_revision: int | None = None
    committed_hash: str | None = None

    def __post_init__(self) -> None:
        failed = self.status is OperationStatus.FAILED
        if failed != (self.failure_class is not None and self.failure_code is not None):
            raise ValueError("failed operation outcome requires typed failure")
        if self.status is not OperationStatus.APPLIED and (
            self.committed_revision is not None or self.committed_hash is not None
        ):
            raise ValueError("unapplied operation outcome cannot carry commit evidence")
        if self.committed_revision is not None and self.committed_revision < 0:
            raise ValueError("operation outcome committed revision is invalid")
        if self.committed_hash is not None and (
            len(self.committed_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.committed_hash)
        ):
            raise ValueError("operation outcome committed hash is invalid")
        if self.message is not None and len(self.message) > 200:
            raise ValueError("operation outcome message is too long")


@dataclass(frozen=True, slots=True)
class ChangeSetPreview:
    change_set_id: str
    outcomes: tuple[OperationOutcome, ...]

    @property
    def ready(self) -> bool:
        return all(outcome.status is OperationStatus.READY for outcome in self.outcomes)


@dataclass(frozen=True, slots=True)
class ChangeSetResult:
    change_set_id: str
    outcomes: tuple[OperationOutcome, ...]
    intended_operation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.outcomes, tuple)
            or not isinstance(self.intended_operation_ids, tuple)
            or not self.intended_operation_ids
            or len(set(self.intended_operation_ids)) != len(self.intended_operation_ids)
            or tuple(outcome.operation_id for outcome in self.outcomes)
            != self.intended_operation_ids
        ):
            raise ValueError("change set outcomes must exactly match intended operations")

    @property
    def applied(self) -> bool:
        return all(outcome.status is OperationStatus.APPLIED for outcome in self.outcomes)


@dataclass(slots=True)
class _ProjectedChapter:
    revision: int
    title: str
    content: str


class ChangeSetUnitOfWork:
    """Same-process ChangeSet transaction; durable crash recovery is S2b."""

    crash_recovery_supported: ClassVar[bool] = False

    def __init__(
        self,
        service: ChangeSetService,
        connection: sqlite3.Connection | None,
    ) -> None:
        self._service = service
        self._provided_connection = connection
        self._connection: sqlite3.Connection | None = None
        self._owns_connection = connection is None
        self._files = ChapterFileTransaction()
        self._executed = False
        self._maintenance_sources: dict[str, tuple[int, str]] = {}
        self.maintenance_results: tuple[FormalMaintenanceResult, ...] = ()

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("change set unit of work is not active")
        return self._connection

    def __enter__(self) -> ChangeSetUnitOfWork:
        if self._connection is not None:
            raise RuntimeError("change set unit of work is already active")
        connection = (
            self._service.chapters.project.database.connect()
            if self._provided_connection is None
            else self._provided_connection
        )
        try:
            self._service._validate_connection(connection)
            connection.execute("BEGIN IMMEDIATE")
        except BaseException:
            if self._owns_connection:
                connection.close()
            raise
        self._connection = connection
        return self

    def execute(
        self,
        change_set: ChangeSet,
        *,
        idempotency_key: str,
    ) -> ChangeSetResult:
        if self._executed:
            raise RuntimeError("change set unit of work already executed")
        connection = self.connection
        self._executed = True
        checkpoint = self._files.checkpoint()
        connection.execute("SAVEPOINT changeset_domain")
        savepoint_active = True
        try:
            result = self._service._commit_in_transaction(
                change_set,
                idempotency_key=idempotency_key,
                connection=connection,
                file_transaction=self._files,
            )
            if result.applied:
                connection.execute("RELEASE SAVEPOINT changeset_domain")
                savepoint_active = False
                self._maintenance_sources = {
                    outcome.chapter_id: (
                        outcome.committed_revision,
                        outcome.committed_hash,
                    )
                    for outcome in result.outcomes
                    if outcome.committed_revision is not None and outcome.committed_hash is not None
                }
            else:
                connection.execute("ROLLBACK TO SAVEPOINT changeset_domain")
                connection.execute("RELEASE SAVEPOINT changeset_domain")
                savepoint_active = False
                self._files.rollback_to(checkpoint)
            return result
        except BaseException:
            if savepoint_active:
                connection.execute("ROLLBACK TO SAVEPOINT changeset_domain")
                connection.execute("RELEASE SAVEPOINT changeset_domain")
            self._files.rollback_to(checkpoint)
            raise

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        connection = self.connection
        try:
            if not connection.in_transaction:
                raise RuntimeError(
                    "change set transaction was closed outside unit-of-work protocol"
                )
            if exception_type is not None:
                connection.rollback()
                self._files.rollback()
                return
            try:
                connection.commit()
            except BaseException:
                connection.rollback()
                self._files.rollback()
                raise
            self._files.finalize()
            results: list[FormalMaintenanceResult] = []
            for chapter_id, (revision, source_hash) in self._maintenance_sources.items():
                try:
                    results.append(
                        self._service.revisions.maintain_current_revision(
                            chapter_id,
                            expected_revision=revision,
                            expected_source_hash=source_hash,
                        )
                    )
                except Exception:
                    results.append(
                        self._service.revisions.pending_maintenance_result(
                            chapter_id,
                            expected_revision=revision,
                            expected_source_hash=source_hash,
                        )
                    )
            self.maintenance_results = tuple(results)
        finally:
            self._connection = None
            if self._owns_connection:
                connection.close()


class ChangeSetService:
    """Minimal ChangeSet facade: dry-run build + approval-gated commit.

    Operations map to the existing write boundaries (submit_revision /
    submit_title_revision / repair apply); the Harness approval layer owns
    idempotency, this facade only requires and records the key.
    """

    def __init__(
        self,
        chapters: ChapterRepository,
        revisions: ChapterRevisionService,
        repairs: RepairApplicationService,
    ) -> None:
        self.chapters = chapters
        self.revisions = revisions
        self.repairs = repairs

    def unit_of_work(
        self,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> ChangeSetUnitOfWork:
        return ChangeSetUnitOfWork(self, connection)

    def build(self, change_set: ChangeSet) -> ChangeSetPreview:
        if not isinstance(change_set, ChangeSet):
            raise TypeError("change set is invalid")
        outcomes = self._preflight(change_set)
        return ChangeSetPreview(change_set.change_set_id, outcomes)

    def commit(self, change_set: ChangeSet, *, idempotency_key: str) -> ChangeSetResult:
        with self.unit_of_work() as unit_of_work:
            return unit_of_work.execute(
                change_set,
                idempotency_key=idempotency_key,
            )

    def _commit_in_transaction(
        self,
        change_set: ChangeSet,
        *,
        idempotency_key: str,
        connection: sqlite3.Connection,
        file_transaction: ChapterFileTransaction,
    ) -> ChangeSetResult:
        if not isinstance(change_set, ChangeSet):
            raise TypeError("change set is invalid")
        if not idempotency_key.strip():
            raise ValueError("change set idempotency key cannot be empty")
        operation_ids = tuple(op.operation_id for op in change_set.operations)
        readiness = self._preflight(change_set, connection=connection)
        if any(outcome.status is not OperationStatus.READY for outcome in readiness):
            failed = tuple(
                outcome
                if outcome.status is OperationStatus.FAILED
                else self._failed_outcome(
                    op,
                    ChangeSetFailureClass.VALIDATION,
                    ChangeSetFailureCode.CHANGESET_ABORTED,
                    "change set preflight failed",
                )
                for op, outcome in zip(change_set.operations, readiness, strict=True)
            )
            return ChangeSetResult(change_set.change_set_id, failed, operation_ids)
        applied: list[OperationOutcome] = []
        for op in change_set.operations:
            outcome = self._execute(
                op,
                connection=connection,
                file_transaction=file_transaction,
            )
            if (
                not isinstance(outcome, OperationOutcome)
                or outcome.operation_id != op.operation_id
                or outcome.kind is not op.kind
                or outcome.chapter_id != op.chapter_id
                or outcome.status is OperationStatus.READY
                or (
                    outcome.status is OperationStatus.APPLIED
                    and (outcome.committed_revision is None or outcome.committed_hash is None)
                )
            ):
                outcome = self._failed_outcome(
                    op,
                    ChangeSetFailureClass.INTEGRITY,
                    ChangeSetFailureCode.RESULT_INTEGRITY_FAILED,
                    "change operation returned invalid result evidence",
                )
            applied.append(outcome)
            if outcome.status is OperationStatus.FAILED:
                break
        if len(applied) != len(change_set.operations) or any(
            outcome.status is OperationStatus.FAILED for outcome in applied
        ):
            root_failure = next(
                (outcome for outcome in applied if outcome.status is OperationStatus.FAILED),
                None,
            )
            failed = tuple(
                root_failure
                if root_failure is not None and root_failure.operation_id == op.operation_id
                else self._failed_outcome(
                    op,
                    ChangeSetFailureClass.PERSISTENCE,
                    ChangeSetFailureCode.CHANGESET_ABORTED,
                    "change set transaction was rolled back",
                )
                for op in change_set.operations
            )
            return ChangeSetResult(
                change_set.change_set_id,
                failed,
                operation_ids,
            )
        return ChangeSetResult(
            change_set.change_set_id,
            tuple(applied),
            operation_ids,
        )

    def _preflight(
        self,
        change_set: ChangeSet,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[OperationOutcome, ...]:
        chapters: dict[str, _ProjectedChapter] = {}
        used_repairs: set[str] = set()
        return tuple(
            self._preflight_operation(
                op,
                chapters,
                used_repairs,
                connection=connection,
            )
            for op in change_set.operations
        )

    def _preflight_operation(
        self,
        op: ChangeOperation,
        chapters: dict[str, _ProjectedChapter],
        used_repairs: set[str],
        *,
        connection: sqlite3.Connection | None,
    ) -> OperationOutcome:
        try:
            payload = json.loads(
                json.dumps(
                    op.payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            validated = ChangeOperation(
                op.operation_id,
                op.kind,
                op.chapter_id,
                op.expected_revision,
                payload,
            )
        except (TypeError, ValueError):
            return self._failed_outcome(
                op,
                ChangeSetFailureClass.VALIDATION,
                ChangeSetFailureCode.INVALID_OPERATION,
                "change operation is invalid",
            )
        if validated != op:
            return self._failed_outcome(
                op,
                ChangeSetFailureClass.VALIDATION,
                ChangeSetFailureCode.INVALID_OPERATION,
                "change operation changed after validation",
            )
        projected = chapters.get(op.chapter_id)
        if projected is None:
            try:
                chapter = self.chapters.get_chapter(
                    op.chapter_id,
                    include_deleted=False,
                    connection=connection,
                )
                content = self.chapters.read_content_exact(
                    op.chapter_id,
                    connection=connection,
                )
            except KeyError:
                return self._failed_outcome(
                    op,
                    ChangeSetFailureClass.VALIDATION,
                    ChangeSetFailureCode.UNKNOWN_CHAPTER,
                    "unknown chapter",
                )
            except (OSError, RuntimeError, UnicodeError):
                return self._failed_outcome(
                    op,
                    ChangeSetFailureClass.PERSISTENCE,
                    ChangeSetFailureCode.CHAPTER_CONTENT_UNAVAILABLE,
                    "chapter content is unavailable",
                )
            projected = _ProjectedChapter(chapter.revision, chapter.title, content)
            chapters[op.chapter_id] = projected
        if projected.revision != op.expected_revision:
            return self._failed_outcome(
                op,
                ChangeSetFailureClass.STALE_CONFLICT,
                ChangeSetFailureCode.REVISION_CONFLICT,
                f"stale revision: expected {op.expected_revision}, current {projected.revision}",
            )
        if op.kind is ChangeOperationKind.CHAPTER_CONTENT_REPLACE:
            try:
                content = self._content_for_source(
                    op,
                    source=projected.content,
                    revision=projected.revision,
                )
            except SelectionPatchStaleError:
                return self._failed_outcome(
                    op,
                    ChangeSetFailureClass.STALE_CONFLICT,
                    ChangeSetFailureCode.PATCH_REPLAY_CONFLICT,
                    "selection patch is stale",
                )
            except SelectionPatchValidationError:
                return self._failed_outcome(
                    op,
                    ChangeSetFailureClass.VALIDATION,
                    ChangeSetFailureCode.INVALID_SELECTION_PATCH,
                    "selection patch is invalid",
                )
            projected.content = content
            projected.revision += 1
        elif op.kind is ChangeOperationKind.CHAPTER_TITLE_CHANGE:
            title = str(op.payload["title"])
            if title != projected.title:
                projected.title = title
                projected.revision += 1
        else:
            proposal_id = str(op.payload["proposal_id"])
            if proposal_id in used_repairs:
                return self._failed_outcome(
                    op,
                    ChangeSetFailureClass.VALIDATION,
                    ChangeSetFailureCode.DUPLICATE_REPAIR_PROPOSAL,
                    "repair proposal is duplicated",
                )
            try:
                proposal = self.repairs.audits.get_repair_proposal(
                    proposal_id,
                    connection=connection,
                )
            except KeyError:
                return self._failed_outcome(
                    op,
                    ChangeSetFailureClass.VALIDATION,
                    ChangeSetFailureCode.UNKNOWN_REPAIR_PROPOSAL,
                    "unknown repair proposal",
                )
            if proposal.status is not RepairProposalStatus.VALIDATED:
                return self._failed_outcome(
                    op,
                    ChangeSetFailureClass.VALIDATION,
                    ChangeSetFailureCode.REPAIR_NOT_VALIDATED,
                    f"repair proposal is not validated: {proposal.status.value}",
                )
            if proposal.target_revision != projected.revision:
                return self._failed_outcome(
                    op,
                    ChangeSetFailureClass.STALE_CONFLICT,
                    ChangeSetFailureCode.REVISION_CONFLICT,
                    "stale repair proposal revision",
                )
            source_hash = hashlib.sha256(projected.content.encode("utf-8")).hexdigest()
            if proposal.target_hash != source_hash:
                return self._failed_outcome(
                    op,
                    ChangeSetFailureClass.STALE_CONFLICT,
                    ChangeSetFailureCode.CONTENT_HASH_CONFLICT,
                    "stale repair proposal hash",
                )
            try:
                prepared = self.repairs.prepare_apply(
                    proposal_id,
                    chapter_id=op.chapter_id,
                    expected_revision=projected.revision,
                    source_content=projected.content,
                    connection=connection,
                )
            except (KeyError, RepairApplicationError):
                return self._failed_outcome(
                    op,
                    ChangeSetFailureClass.VALIDATION,
                    ChangeSetFailureCode.INVALID_REPAIR_PROPOSAL,
                    "repair proposal is invalid",
                )
            projected.content = prepared.repaired_content
            used_repairs.add(proposal_id)
            projected.revision += 1
        return self._ready_outcome(op)

    def _execute(
        self,
        op: ChangeOperation,
        *,
        connection: sqlite3.Connection,
        file_transaction: ChapterFileTransaction,
    ) -> OperationOutcome:
        try:
            if op.kind is ChangeOperationKind.CHAPTER_CONTENT_REPLACE:
                content = self._content_for_source(
                    op,
                    source=self.chapters.read_content_exact(
                        op.chapter_id,
                        connection=connection,
                    ),
                    revision=op.expected_revision,
                )
                committed = self.revisions.commit_revision(
                    op.chapter_id,
                    content,
                    source=str(op.payload["source"]),
                    reason=str(op.payload["reason"]),
                    expected_revision=op.expected_revision,
                    invalidate_memory=bool(op.payload.get("invalidate_memory", True)),
                    connection=connection,
                    file_transaction=file_transaction,
                )
                chapter = committed.chapter
            elif op.kind is ChangeOperationKind.CHAPTER_TITLE_CHANGE:
                committed_title = self.revisions.commit_title_revision(
                    op.chapter_id,
                    str(op.payload["title"]),
                    expected_revision=op.expected_revision,
                    connection=connection,
                    file_transaction=file_transaction,
                )
                chapter = committed_title.chapter
            else:
                prepared_repair = self.repairs.prepare_apply(
                    str(op.payload["proposal_id"]),
                    chapter_id=op.chapter_id,
                    expected_revision=op.expected_revision,
                    source_content=self.chapters.read_content_exact(
                        op.chapter_id,
                        connection=connection,
                    ),
                    connection=connection,
                )
                applied_repair = self.repairs.commit_prepared(
                    prepared_repair,
                    connection=connection,
                    file_transaction=file_transaction,
                )
                chapter = applied_repair.chapter
        except SelectionPatchStaleError:
            return self._failed_outcome(
                op,
                ChangeSetFailureClass.STALE_CONFLICT,
                ChangeSetFailureCode.PATCH_REPLAY_CONFLICT,
                "selection patch is stale",
            )
        except SelectionPatchValidationError:
            return self._failed_outcome(
                op,
                ChangeSetFailureClass.VALIDATION,
                ChangeSetFailureCode.INVALID_SELECTION_PATCH,
                "selection patch is invalid",
            )
        except StaleChapterRevisionError:
            return self._failed_outcome(
                op,
                ChangeSetFailureClass.STALE_CONFLICT,
                ChangeSetFailureCode.REVISION_CONFLICT,
                "chapter revision changed before commit",
            )
        except (
            OSError,
            RuntimeError,
            UnicodeError,
            ValueError,
            KeyError,
            sqlite3.Error,
        ):
            return self._failed_outcome(
                op,
                ChangeSetFailureClass.PERSISTENCE,
                ChangeSetFailureCode.OPERATION_PERSISTENCE_FAILED,
                "change operation could not be persisted",
            )
        try:
            content = self.chapters.read_content_exact(
                op.chapter_id,
                connection=connection,
            )
        except (KeyError, OSError, RuntimeError, UnicodeError):
            return self._failed_outcome(
                op,
                ChangeSetFailureClass.INTEGRITY,
                ChangeSetFailureCode.RESULT_INTEGRITY_FAILED,
                "committed operation evidence is unavailable",
            )
        return OperationOutcome(
            op.operation_id,
            op.kind,
            op.chapter_id,
            OperationStatus.APPLIED,
            committed_revision=chapter.revision,
            committed_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )

    def _validate_connection(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("change set connection is invalid")
        try:
            if connection.in_transaction:
                raise ValueError("change set connection already has an active transaction")
            if connection.row_factory is not sqlite3.Row:
                raise ValueError("change set connection row factory is invalid")
            rows = connection.execute("PRAGMA database_list").fetchall()
            main = next((row for row in rows if str(row["name"]) == "main"), None)
            if main is None or Path(str(main["file"])).resolve() != (
                self.chapters.project.database.path.resolve()
            ):
                raise ValueError("change set connection belongs to another project")
            foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
            if foreign_keys is None or int(foreign_keys[0]) != 1:
                raise ValueError("change set connection foreign keys are disabled")
        except sqlite3.ProgrammingError:
            raise ValueError("change set connection is closed") from None

    @staticmethod
    def _content_for_source(
        op: ChangeOperation,
        *,
        source: str,
        revision: int,
    ) -> str:
        raw_patch = op.payload.get("selection_patch")
        if raw_patch is None:
            return str(op.payload["content"])
        if not isinstance(raw_patch, dict):
            raise SelectionPatchValidationError()
        patch = parse_selection_patch(raw_patch)
        content = replay_selection_patch(
            patch,
            source=source,
            chapter_id=op.chapter_id,
            revision=revision,
        )
        if patch.result_hash != op.payload.get("content"):
            raise SelectionPatchValidationError()
        return content

    @staticmethod
    def _ready_outcome(op: ChangeOperation) -> OperationOutcome:
        return OperationOutcome(
            op.operation_id,
            op.kind,
            op.chapter_id,
            OperationStatus.READY,
        )

    @staticmethod
    def _failed_outcome(
        op: ChangeOperation,
        failure_class: ChangeSetFailureClass,
        failure_code: ChangeSetFailureCode,
        message: str,
    ) -> OperationOutcome:
        return OperationOutcome(
            op.operation_id,
            op.kind,
            op.chapter_id,
            OperationStatus.FAILED,
            message,
            failure_class,
            failure_code,
        )
