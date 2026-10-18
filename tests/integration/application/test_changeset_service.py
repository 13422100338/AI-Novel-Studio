from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from ai_novel_studio.application.changeset_service import (
    ChangeSetFailureClass,
    ChangeSetFailureCode,
    ChangeSetPreview,
    ChangeSetResult,
    ChangeSetService,
    ChangeSetUnitOfWork,
    OperationOutcome,
    OperationStatus,
)
from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
    FormalMaintenanceFailureCode,
    FormalMaintenanceStatus,
)
from ai_novel_studio.application.repair_application_service import (
    RepairApplicationService,
)
from ai_novel_studio.domain.audit import (
    AuditFindingCategory,
    AuditFindingSource,
    AuditRunStatus,
    AuditSeverity,
    AuditTargetKind,
    RepairProposalStatus,
    RepairStrategy,
)
from ai_novel_studio.domain.changeset import (
    ChangeOperation,
    ChangeOperationKind,
    ChangeSet,
)
from ai_novel_studio.domain.generation import CreationMode
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
)


def _service(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "ChangeSet")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    chapter = revisions.submit_creation(volume.id, "Chapter", content="v0").chapter
    chapters = ChapterRepository(project)
    repairs = RepairApplicationService(chapters, AuditRepository(project))
    service = ChangeSetService(chapters, revisions, repairs)
    return service, project, chapter, repairs


def _op(
    kind: ChangeOperationKind,
    chapter_id: str,
    revision: int,
    **payload: object,
) -> ChangeOperation:
    return ChangeOperation(str(new_id()), kind, chapter_id, revision, dict(payload))


def _content_op(chapter_id: str, revision: int, **payload: object) -> ChangeOperation:
    fields: dict[str, object] = dict(content="v1", source="author", reason="polish")
    fields.update(payload)
    return _op(
        ChangeOperationKind.CHAPTER_CONTENT_REPLACE,
        chapter_id,
        revision,
        **fields,
    )


def _validated_repair(
    project: ProjectRepository,
    chapter_id: str,
    repairs: RepairApplicationService,
):
    source = ChapterRepository(project).read_content_exact(chapter_id)
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    run = repairs.audits.create_run(
        chapter_id=chapter_id,
        target_kind=AuditTargetKind.FORMAL_CHAPTER,
        target_id=chapter_id,
        target_revision=0,
        target_hash=source_hash,
        mode=CreationMode.BASIC,
        status=AuditRunStatus.COMPLETED,
        prompt_version="deterministic-v1",
    )
    finding = repairs.audits.add_finding(
        run_id=run.id,
        category=AuditFindingCategory.STYLE,
        severity=AuditSeverity.WARNING,
        source=AuditFindingSource.DETERMINISTIC,
        location_json="{}",
        evidence="v0",
        explanation="replace stale wording",
        related_source_json="[]",
        confidence=1.0,
    )
    proposal = repairs.create_validated_text_repair(
        finding_id=finding.id,
        chapter_id=chapter_id,
        strategy=RepairStrategy.REPLACE_TEXT,
        target_text="v0",
        replacement_text="repaired",
        explanation="approved repair",
        risk_note="low risk",
    )
    return finding, proposal


def test_domain_validation() -> None:
    with pytest.raises(ValueError):
        _content_op("bad-id", 0)
    with pytest.raises(ValueError):
        _content_op(str(new_id()), 0, content=" ")
    with pytest.raises(ValueError):
        _op(ChangeOperationKind.CHAPTER_TITLE_CHANGE, str(new_id()), 0, title=" ")
    with pytest.raises(ValueError):
        _op(ChangeOperationKind.REPAIR_APPLY, str(new_id()), 0, proposal_id="bad")
    with pytest.raises(ValueError):
        ChangeSet(str(new_id()), ())


def test_commit_revalidates_mutated_operation_payload_before_mutation(
    tmp_path: Path,
) -> None:
    service, project, chapter, _repairs = _service(tmp_path)
    operation = _content_op(chapter.id, chapter.revision, content="must not persist")
    operation.payload["invalidate_memory"] = "not-a-boolean"
    change_set = ChangeSet(str(new_id()), (operation,))

    result = service.commit(change_set, idempotency_key="key-revalidate")

    assert result.outcomes[0].failure_class is ChangeSetFailureClass.VALIDATION
    assert result.outcomes[0].failure_code is ChangeSetFailureCode.INVALID_OPERATION
    chapters = ChapterRepository(project)
    assert chapters.read_content_exact(chapter.id) == "v0"
    assert chapters.get_chapter(chapter.id).revision == chapter.revision
    assert chapters.list_versions(chapter.id) == []


def test_build_dry_run_reports_stale(tmp_path: Path) -> None:
    service, _project, chapter, _repairs = _service(tmp_path)
    change_set = ChangeSet(
        str(new_id()),
        (_content_op(chapter.id, chapter.revision + 1),),
    )

    preview = service.build(change_set)

    assert isinstance(preview, ChangeSetPreview)
    assert preview.ready is False
    assert preview.outcomes[0].status is OperationStatus.FAILED
    assert "stale revision" in (preview.outcomes[0].message or "")


def test_commit_applies_content_and_title(tmp_path: Path) -> None:
    service, _project, chapter, _repairs = _service(tmp_path)
    content_op = _content_op(chapter.id, chapter.revision, content="v1 正文")
    title_op = _op(
        ChangeOperationKind.CHAPTER_TITLE_CHANGE,
        chapter.id,
        chapter.revision + 1,
        title="新标题",
    )
    change_set = ChangeSet(str(new_id()), (content_op, title_op))

    result = service.commit(change_set, idempotency_key="key-1")

    assert isinstance(result, ChangeSetResult)
    assert [outcome.status for outcome in result.outcomes] == [
        OperationStatus.APPLIED,
        OperationStatus.APPLIED,
    ]
    chapters = ChapterRepository(ProjectRepository.open(tmp_path / "novel"))
    assert chapters.read_content(chapter.id) == "v1 正文"
    assert chapters.get_chapter(chapter.id, include_deleted=False).title == "新标题"


def test_commit_stops_on_stale_and_rejects_empty_key(tmp_path: Path) -> None:
    service, _project, chapter, _repairs = _service(tmp_path)
    change_set = ChangeSet(
        str(new_id()),
        (_content_op(chapter.id, chapter.revision + 9),),
    )

    result = service.commit(change_set, idempotency_key="key-1")
    assert result.outcomes[0].status is OperationStatus.FAILED

    with pytest.raises(ValueError):
        service.commit(change_set, idempotency_key="  ")


def test_commit_preflights_every_operation_before_first_mutation(
    tmp_path: Path,
) -> None:
    service, project, chapter, _repairs = _service(tmp_path)
    change_set = ChangeSet(
        str(new_id()),
        (
            _content_op(chapter.id, chapter.revision, content="must roll back"),
            _op(
                ChangeOperationKind.CHAPTER_TITLE_CHANGE,
                chapter.id,
                chapter.revision + 9,
                title="stale title",
            ),
            _content_op(chapter.id, chapter.revision, content="must not run"),
        ),
    )

    result = service.commit(change_set, idempotency_key="key-preflight")

    assert len(result.outcomes) == len(change_set.operations)
    assert all(outcome.status is OperationStatus.FAILED for outcome in result.outcomes)
    assert result.outcomes[1].failure_class is ChangeSetFailureClass.STALE_CONFLICT
    assert result.outcomes[1].failure_code is ChangeSetFailureCode.REVISION_CONFLICT
    assert result.outcomes[0].failure_code is ChangeSetFailureCode.CHANGESET_ABORTED
    assert result.outcomes[2].failure_code is ChangeSetFailureCode.REVISION_CONFLICT
    with pytest.raises(ValueError, match="exactly match"):
        ChangeSetResult(
            result.change_set_id,
            result.outcomes[:-1],
            tuple(op.operation_id for op in change_set.operations),
        )
    chapters = ChapterRepository(project)
    assert chapters.read_content_exact(chapter.id) == "v0"
    assert chapters.get_chapter(chapter.id).revision == chapter.revision
    assert chapters.list_versions(chapter.id) == []


def test_unit_of_work_caller_abort_restores_canonical_file_and_history(
    tmp_path: Path,
) -> None:
    service, project, chapter, _repairs = _service(tmp_path)
    change_set = ChangeSet(
        str(new_id()),
        (_content_op(chapter.id, chapter.revision, content="tentative content"),),
    )

    with pytest.raises(RuntimeError, match="simulated receipt failure"):
        with service.unit_of_work() as unit_of_work:
            result = unit_of_work.execute(
                change_set,
                idempotency_key="key-caller-abort",
            )
            assert result.applied is True
            assert ChapterRepository(project).read_content_exact(chapter.id) == (
                "tentative content"
            )
            raise RuntimeError("simulated receipt failure")

    chapters = ChapterRepository(project)
    assert chapters.read_content_exact(chapter.id) == "v0"
    assert chapters.get_chapter(chapter.id).revision == chapter.revision
    assert chapters.list_versions(chapter.id) == []
    history = project.layout.history / chapter.id
    assert not history.exists() or not tuple(history.iterdir())


def test_unit_of_work_caller_abort_restores_content_and_title_chain(
    tmp_path: Path,
) -> None:
    service, project, chapter, _repairs = _service(tmp_path)
    change_set = ChangeSet(
        str(new_id()),
        (
            _content_op(chapter.id, chapter.revision, content="tentative content"),
            _op(
                ChangeOperationKind.CHAPTER_TITLE_CHANGE,
                chapter.id,
                chapter.revision + 1,
                title="Tentative Title",
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="simulated receipt failure"):
        with service.unit_of_work() as unit_of_work:
            result = unit_of_work.execute(
                change_set,
                idempotency_key="key-title-abort",
            )
            assert result.applied is True
            raise RuntimeError("simulated receipt failure")

    chapters = ChapterRepository(project)
    restored = chapters.get_chapter(chapter.id)
    assert restored.title == chapter.title
    assert restored.revision == chapter.revision
    assert chapters.read_content_exact(chapter.id) == "v0"
    assert chapters.list_versions(chapter.id) == []
    history = project.layout.history / chapter.id
    assert not history.exists() or not tuple(history.iterdir())


def test_unit_of_work_uses_clean_caller_connection_and_rejects_active_one(
    tmp_path: Path,
) -> None:
    service, project, chapter, _repairs = _service(tmp_path)
    change_set = ChangeSet(
        str(new_id()),
        (_content_op(chapter.id, chapter.revision, content="committed content"),),
    )

    assert ChangeSetUnitOfWork.crash_recovery_supported is False
    with project.database.connect() as connection:
        with service.unit_of_work(connection=connection) as unit_of_work:
            assert unit_of_work.connection is connection
            result = unit_of_work.execute(
                change_set,
                idempotency_key="key-caller-connection",
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                ("2040-01-01T00:00:00+00:00", project.project.id),
            )
        assert connection.in_transaction is False
        updated_at = connection.execute(
            "SELECT updated_at FROM projects WHERE id = ?",
            (project.project.id,),
        ).fetchone()["updated_at"]

        connection.execute("BEGIN")
        with pytest.raises(ValueError, match="active transaction"):
            with service.unit_of_work(connection=connection):
                pass
        connection.rollback()

    assert result.applied is True
    assert ChapterRepository(project).read_content_exact(chapter.id) == ("committed content")
    assert updated_at == "2040-01-01T00:00:00+00:00"


def test_failed_domain_savepoint_keeps_outer_transaction_for_failure_facts(
    tmp_path: Path,
) -> None:
    service, project, chapter, _repairs = _service(tmp_path)
    change_set = ChangeSet(
        str(new_id()),
        (_content_op(chapter.id, chapter.revision + 1, content="must not persist"),),
    )

    with project.database.connect() as connection:
        with service.unit_of_work(connection=connection) as unit_of_work:
            result = unit_of_work.execute(
                change_set,
                idempotency_key="key-failed-fact",
            )
            assert result.applied is False
            assert connection.in_transaction is True
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                ("2041-01-01T00:00:00+00:00", project.project.id),
            )
        updated_at = connection.execute(
            "SELECT updated_at FROM projects WHERE id = ?",
            (project.project.id,),
        ).fetchone()["updated_at"]

    assert updated_at == "2041-01-01T00:00:00+00:00"
    chapters = ChapterRepository(project)
    assert chapters.read_content_exact(chapter.id) == "v0"
    assert chapters.get_chapter(chapter.id).revision == chapter.revision
    assert chapters.list_versions(chapter.id) == []


def test_unit_of_work_caller_abort_restores_repair_and_audit_side_effects(
    tmp_path: Path,
) -> None:
    service, project, chapter, repairs = _service(tmp_path)
    finding, proposal = _validated_repair(project, chapter.id, repairs)
    change_set = ChangeSet(
        str(new_id()),
        (
            _op(
                ChangeOperationKind.REPAIR_APPLY,
                chapter.id,
                chapter.revision,
                proposal_id=proposal.id,
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="simulated receipt failure"):
        with service.unit_of_work() as unit_of_work:
            result = unit_of_work.execute(
                change_set,
                idempotency_key="key-repair-abort",
            )
            assert result.applied is True
            raise RuntimeError("simulated receipt failure")

    chapters = ChapterRepository(project)
    assert chapters.read_content_exact(chapter.id) == "v0"
    assert chapters.get_chapter(chapter.id).revision == chapter.revision
    assert chapters.list_versions(chapter.id) == []
    assert repairs.audits.get_repair_proposal(proposal.id).status is (
        RepairProposalStatus.VALIDATED
    )
    assert repairs.audits.get_finding(finding.id).status.value == "OPEN"
    assert repairs.audits.list_provenance(chapter.id) == ()


def test_repair_audit_exception_rolls_back_revision_and_audit_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, project, chapter, repairs = _service(tmp_path)
    finding, proposal = _validated_repair(project, chapter.id, repairs)
    change_set = ChangeSet(
        str(new_id()),
        (
            _op(
                ChangeOperationKind.REPAIR_APPLY,
                chapter.id,
                chapter.revision,
                proposal_id=proposal.id,
            ),
        ),
    )

    def fail_status(*_args: object, **_kwargs: object):
        raise sqlite3.IntegrityError(f"raw private audit failure: {project.layout.root}: repaired")

    monkeypatch.setattr(repairs.audits, "update_repair_status", fail_status)

    result = service.commit(change_set, idempotency_key="key-repair-failure")

    assert result.outcomes[0].failure_class is ChangeSetFailureClass.PERSISTENCE
    assert result.outcomes[0].failure_code is (ChangeSetFailureCode.OPERATION_PERSISTENCE_FAILED)
    assert "private" not in (result.outcomes[0].message or "")
    chapters = ChapterRepository(project)
    assert chapters.read_content_exact(chapter.id) == "v0"
    assert chapters.get_chapter(chapter.id).revision == chapter.revision
    assert chapters.list_versions(chapter.id) == []
    assert repairs.audits.get_repair_proposal(proposal.id).status is (
        RepairProposalStatus.VALIDATED
    )
    assert repairs.audits.get_finding(finding.id).status.value == "OPEN"
    assert repairs.audits.list_provenance(chapter.id) == ()


def test_second_operation_sql_failure_returns_complete_safe_rollback_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, project, chapter, _repairs = _service(tmp_path)
    change_set = ChangeSet(
        str(new_id()),
        (
            _content_op(chapter.id, chapter.revision, content="tentative content"),
            _op(
                ChangeOperationKind.CHAPTER_TITLE_CHANGE,
                chapter.id,
                chapter.revision + 1,
                title="Tentative Title",
            ),
        ),
    )
    real_invalidate = ViewAssertionRepository.invalidate_source_revision_in_connection
    calls = 0

    def fail_second_invalidation(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.IntegrityError(
                f"raw private failure: {project.layout.root}: tentative content"
            )
        real_invalidate(*args, **kwargs)

    monkeypatch.setattr(
        ViewAssertionRepository,
        "invalidate_source_revision_in_connection",
        fail_second_invalidation,
    )

    result = service.commit(change_set, idempotency_key="key-execute-failure")

    assert len(result.outcomes) == len(change_set.operations)
    assert all(outcome.status is OperationStatus.FAILED for outcome in result.outcomes)
    assert result.outcomes[0].failure_code is ChangeSetFailureCode.CHANGESET_ABORTED
    assert result.outcomes[1].failure_class is ChangeSetFailureClass.PERSISTENCE
    assert result.outcomes[1].failure_code is (ChangeSetFailureCode.OPERATION_PERSISTENCE_FAILED)
    assert all(
        "private" not in (outcome.message or "")
        and str(project.layout.root) not in (outcome.message or "")
        for outcome in result.outcomes
    )
    chapters = ChapterRepository(project)
    restored = chapters.get_chapter(chapter.id)
    assert restored.title == chapter.title
    assert restored.revision == chapter.revision
    assert chapters.read_content_exact(chapter.id) == "v0"
    assert chapters.list_versions(chapter.id) == []
    with project.database.connect() as connection:
        statuses = tuple(
            str(row["status"])
            for row in connection.execute(
                "SELECT status FROM memory_documents "
                "WHERE document_type = 'FORMAL_MANUSCRIPT' AND chapter_id = ?",
                (chapter.id,),
            ).fetchall()
        )
    assert statuses == ("CURRENT",)


def test_invalid_execution_outcome_is_typed_integrity_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, project, chapter, _repairs = _service(tmp_path)
    operation = _content_op(
        chapter.id,
        chapter.revision,
        content="must not persist",
    )
    change_set = ChangeSet(str(new_id()), (operation,))

    def invalid_outcome(*_args: object, **_kwargs: object) -> OperationOutcome:
        return OperationOutcome(
            str(new_id()),
            operation.kind,
            operation.chapter_id,
            OperationStatus.APPLIED,
            committed_revision=1,
            committed_hash="a" * 64,
        )

    monkeypatch.setattr(service, "_execute", invalid_outcome)

    result = service.commit(change_set, idempotency_key="key-integrity")

    assert tuple(outcome.operation_id for outcome in result.outcomes) == (operation.operation_id,)
    assert result.outcomes[0].failure_class is ChangeSetFailureClass.INTEGRITY
    assert result.outcomes[0].failure_code is (ChangeSetFailureCode.RESULT_INTEGRITY_FAILED)
    chapters = ChapterRepository(project)
    assert chapters.read_content_exact(chapter.id) == "v0"
    assert chapters.get_chapter(chapter.id).revision == chapter.revision
    assert chapters.list_versions(chapter.id) == []


def test_applied_outcome_without_commit_evidence_is_integrity_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, project, chapter, _repairs = _service(tmp_path)
    operation = _content_op(
        chapter.id,
        chapter.revision,
        content="must not persist",
    )
    change_set = ChangeSet(str(new_id()), (operation,))

    def incomplete_outcome(*_args: object, **_kwargs: object) -> OperationOutcome:
        return OperationOutcome(
            operation.operation_id,
            operation.kind,
            operation.chapter_id,
            OperationStatus.APPLIED,
        )

    monkeypatch.setattr(service, "_execute", incomplete_outcome)

    result = service.commit(change_set, idempotency_key="key-missing-evidence")

    assert result.outcomes[0].failure_class is ChangeSetFailureClass.INTEGRITY
    assert result.outcomes[0].failure_code is (ChangeSetFailureCode.RESULT_INTEGRITY_FAILED)
    chapters = ChapterRepository(project)
    assert chapters.read_content_exact(chapter.id) == "v0"
    assert chapters.get_chapter(chapter.id).revision == chapter.revision
    assert chapters.list_versions(chapter.id) == []


def test_post_commit_maintenance_failure_stays_applied_and_reports_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, project, chapter, _repairs = _service(tmp_path)
    change_set = ChangeSet(
        str(new_id()),
        (_content_op(chapter.id, chapter.revision, content="committed private text"),),
    )

    def fail_maintenance(
        _chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
    ):
        raise RuntimeError(
            f"raw failure: {project.layout.root}: committed private text: "
            f"{expected_revision}: {expected_source_hash}"
        )

    monkeypatch.setattr(
        service.revisions,
        "maintain_current_revision",
        fail_maintenance,
    )

    with service.unit_of_work() as unit_of_work:
        result = unit_of_work.execute(
            change_set,
            idempotency_key="key-maintenance-pending",
        )

    assert result.applied is True
    assert ChapterRepository(project).read_content_exact(chapter.id) == ("committed private text")
    assert len(unit_of_work.maintenance_results) == 1
    maintenance = unit_of_work.maintenance_results[0]
    assert maintenance.status is FormalMaintenanceStatus.PENDING
    assert maintenance.failure is not None
    assert maintenance.failure.code is FormalMaintenanceFailureCode.REPAIR_FAILED
    assert "private" not in maintenance.failure.message
    assert str(project.layout.root) not in maintenance.failure.message


def test_commit_combines_all_kinds_across_chapters_with_projected_revisions(
    tmp_path: Path,
) -> None:
    service, project, chapter, repairs = _service(tmp_path)
    second = service.revisions.submit_creation(
        project.list_volumes()[0].id,
        "Second",
        content="v0",
    ).chapter
    finding, proposal = _validated_repair(project, second.id, repairs)
    change_set = ChangeSet(
        str(new_id()),
        (
            _op(
                ChangeOperationKind.CHAPTER_TITLE_CHANGE,
                chapter.id,
                chapter.revision,
                title=chapter.title,
            ),
            _content_op(chapter.id, chapter.revision, content="chapter one body"),
            _op(
                ChangeOperationKind.CHAPTER_TITLE_CHANGE,
                chapter.id,
                chapter.revision + 1,
                title="Chapter One",
            ),
            _op(
                ChangeOperationKind.REPAIR_APPLY,
                second.id,
                second.revision,
                proposal_id=proposal.id,
            ),
        ),
    )

    result = service.commit(change_set, idempotency_key="key-all-kinds")

    assert result.applied is True
    assert tuple(outcome.operation_id for outcome in result.outcomes) == tuple(
        op.operation_id for op in change_set.operations
    )
    assert [outcome.committed_revision for outcome in result.outcomes] == [
        0,
        1,
        2,
        1,
    ]
    chapters = ChapterRepository(project)
    first_current = chapters.get_chapter(chapter.id)
    second_current = chapters.get_chapter(second.id)
    assert (first_current.title, first_current.revision) == ("Chapter One", 2)
    assert chapters.read_content_exact(chapter.id) == "chapter one body"
    assert second_current.revision == 1
    assert chapters.read_content_exact(second.id) == "repaired"
    assert repairs.audits.get_repair_proposal(proposal.id).status is (RepairProposalStatus.APPLIED)
    assert repairs.audits.get_finding(finding.id).status.value == "ACCEPTED_REPAIR"
    assert len(repairs.audits.list_provenance(second.id)) == 1
    with project.database.connect() as connection:
        current_sources = tuple(
            (str(row["chapter_id"]), int(row["source_revision"]))
            for row in connection.execute(
                "SELECT DISTINCT chapter_id, source_revision "
                "FROM memory_documents "
                "WHERE document_type = 'FORMAL_MANUSCRIPT' AND status = 'CURRENT' "
                "ORDER BY chapter_id"
            ).fetchall()
        )
    assert current_sources == tuple(sorted(((chapter.id, 2), (second.id, 1))))


def test_repair_target_is_fully_preflighted_without_stale_status_mutation(
    tmp_path: Path,
) -> None:
    service, project, chapter, repairs = _service(tmp_path)
    _finding, proposal = _validated_repair(project, chapter.id, repairs)
    change_set = ChangeSet(
        str(new_id()),
        (
            _op(
                ChangeOperationKind.CHAPTER_TITLE_CHANGE,
                chapter.id,
                chapter.revision,
                title="Projected Title",
            ),
            _op(
                ChangeOperationKind.REPAIR_APPLY,
                chapter.id,
                chapter.revision + 1,
                proposal_id=proposal.id,
            ),
        ),
    )

    result = service.commit(change_set, idempotency_key="key-repair-preflight")

    assert result.outcomes[0].failure_code is ChangeSetFailureCode.CHANGESET_ABORTED
    assert result.outcomes[1].failure_class is ChangeSetFailureClass.STALE_CONFLICT
    assert result.outcomes[1].failure_code is ChangeSetFailureCode.REVISION_CONFLICT
    assert ChapterRepository(project).get_chapter(chapter.id) == chapter
    assert repairs.audits.get_repair_proposal(proposal.id).status is (
        RepairProposalStatus.VALIDATED
    )


def test_repair_proposal_cannot_cross_its_audit_run_chapter_identity(
    tmp_path: Path,
) -> None:
    service, project, chapter_a, repairs = _service(tmp_path)
    chapter_b = service.revisions.submit_creation(
        project.list_volumes()[0].id,
        "Second",
        content="v0",
    ).chapter
    finding, proposal = _validated_repair(project, chapter_a.id, repairs)
    change_set = ChangeSet(
        str(new_id()),
        (
            _op(
                ChangeOperationKind.REPAIR_APPLY,
                chapter_b.id,
                chapter_b.revision,
                proposal_id=proposal.id,
            ),
        ),
    )

    result = service.commit(change_set, idempotency_key="key-cross-chapter-repair")

    assert result.applied is False
    assert result.outcomes[0].failure_class is ChangeSetFailureClass.VALIDATION
    assert result.outcomes[0].failure_code is (ChangeSetFailureCode.INVALID_REPAIR_PROPOSAL)
    chapters = ChapterRepository(project)
    assert chapters.read_content_exact(chapter_a.id) == "v0"
    assert chapters.read_content_exact(chapter_b.id) == "v0"
    assert chapters.get_chapter(chapter_a.id).revision == chapter_a.revision
    assert chapters.get_chapter(chapter_b.id).revision == chapter_b.revision
    assert chapters.list_versions(chapter_a.id) == []
    assert chapters.list_versions(chapter_b.id) == []
    assert repairs.audits.get_repair_proposal(proposal.id).status is (
        RepairProposalStatus.VALIDATED
    )
    assert repairs.audits.get_finding(finding.id).status.value == "OPEN"
    assert repairs.audits.list_provenance(chapter_a.id) == ()
    assert repairs.audits.list_provenance(chapter_b.id) == ()


def test_repair_apply_requires_validated_proposal(tmp_path: Path) -> None:
    service, _project, chapter, _repairs = _service(tmp_path)
    change_set = ChangeSet(
        str(new_id()),
        (
            _op(
                ChangeOperationKind.REPAIR_APPLY,
                chapter.id,
                chapter.revision,
                proposal_id=str(new_id()),
            ),
        ),
    )

    preview = service.build(change_set)

    assert preview.ready is False
    assert "unknown repair proposal" in (preview.outcomes[0].message or "")
