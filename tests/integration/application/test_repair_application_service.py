import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
    FormalMaintenanceResult,
)
from ai_novel_studio.application.repair_application_service import (
    RepairApplicationError,
    RepairApplicationService,
)
from ai_novel_studio.domain.audit import (
    AuditFindingCategory,
    AuditFindingSource,
    AuditRunStatus,
    AuditSeverity,
    AuditTargetKind,
    ProvenanceEventType,
    RepairProposalStatus,
    RepairStrategy,
)
from ai_novel_studio.domain.generation import CreationMode
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _workspace(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "novel", "Repair Workflow")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "The old sentence stayed.",
    )
    audits = AuditRepository(project)
    run = audits.create_run(
        chapter_id=chapter.id,
        target_kind=AuditTargetKind.FORMAL_CHAPTER,
        target_id=chapter.id,
        target_revision=chapter.revision,
        target_hash=_hash(chapters.read_content(chapter.id)),
        mode=CreationMode.BASIC,
        status=AuditRunStatus.COMPLETED,
        prompt_version="deterministic-v1",
    )
    finding = audits.add_finding(
        run_id=run.id,
        category=AuditFindingCategory.STYLE,
        severity=AuditSeverity.WARNING,
        source=AuditFindingSource.DETERMINISTIC,
        location_json="{}",
        evidence="old sentence",
        explanation="stale wording",
        related_source_json="[]",
        confidence=1.0,
    )
    return project, chapters, chapter, audits, finding


def test_apply_validated_replacement_creates_chapter_version_and_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters, chapter, audits, finding = _workspace(tmp_path)
    revisions = ChapterRevisionService(project)
    service = RepairApplicationService(
        chapters,
        audits,
        revision_service=revisions,
    )
    submit_calls = 0
    real_submit = revisions.submit_revision

    def track_submit(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal submit_calls
        submit_calls += 1
        return real_submit(*args, **kwargs)

    monkeypatch.setattr(revisions, "submit_revision", track_submit)
    proposal = service.create_validated_text_repair(
        finding_id=finding.id,
        chapter_id=chapter.id,
        strategy=RepairStrategy.REPLACE_TEXT,
        target_text="old sentence",
        replacement_text="new sentence",
        explanation="local repair",
        risk_note="low risk",
    )

    result = service.apply(proposal.id, chapter_id=chapter.id, expected_revision=0)

    assert chapters.read_content(chapter.id) == "The new sentence stayed."
    assert result.chapter.revision == 1
    assert result.proposal.status == RepairProposalStatus.APPLIED
    assert result.finding.status.value == "ACCEPTED_REPAIR"
    assert result.provenance.event_type == ProvenanceEventType.REPAIR_APPLIED
    assert len(chapters.list_versions(chapter.id)) == 1
    assert audits.list_provenance(chapter.id) == (result.provenance,)
    assert submit_calls == 1
    formal = SearchRepository(project).read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=1,
        expected_source_hash=_hash("The new sentence stayed."),
        chunk_policy_version="paragraph-codepoint-v1",
    )
    assert tuple(document.content for document in formal) == (
        "The new sentence stayed.",
    )


def test_apply_maintenance_failure_keeps_committed_repair_and_audit_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters, chapter, audits, finding = _workspace(tmp_path)
    revisions = ChapterRevisionService(project)
    revisions.maintain_current_revision(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_hash("The old sentence stayed."),
    )
    service = RepairApplicationService(
        chapters,
        audits,
        revision_service=revisions,
    )
    proposal = service.create_validated_text_repair(
        finding_id=finding.id,
        chapter_id=chapter.id,
        strategy=RepairStrategy.REPLACE_TEXT,
        target_text="old sentence",
        replacement_text="private replacement",
        explanation="local repair",
        risk_note="low risk",
    )
    maintenance_calls = 0

    def fail_maintenance(
        _chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
    ) -> FormalMaintenanceResult:
        nonlocal maintenance_calls
        maintenance_calls += 1
        raise RuntimeError(
            f"raw failure: {project.layout.root}: private replacement: "
            f"{expected_revision}: {expected_source_hash}"
        )

    monkeypatch.setattr(
        revisions,
        "maintain_current_revision",
        fail_maintenance,
    )

    result = service.apply(
        proposal.id,
        chapter_id=chapter.id,
        expected_revision=0,
    )

    with project.database.connect() as connection:
        formal_statuses = tuple(
            str(row["status"])
            for row in connection.execute(
                "SELECT status FROM memory_documents "
                "WHERE document_type = 'FORMAL_MANUSCRIPT' AND chapter_id = ?",
                (chapter.id,),
            ).fetchall()
        )
    assert chapters.read_content_exact(chapter.id) == "The private replacement stayed."
    assert result.chapter.revision == 1
    assert result.proposal.status == RepairProposalStatus.APPLIED
    assert result.finding.status.value == "ACCEPTED_REPAIR"
    assert result.provenance.event_type == ProvenanceEventType.REPAIR_APPLIED
    assert maintenance_calls == 1
    assert formal_statuses == ("STALE",)


def test_note_only_repair_preserves_same_content_revision_behavior(
    tmp_path: Path,
) -> None:
    project, chapters, chapter, audits, finding = _workspace(tmp_path)
    revisions = ChapterRevisionService(project)
    service = RepairApplicationService(
        chapters,
        audits,
        revision_service=revisions,
    )
    proposal = service.create_validated_text_repair(
        finding_id=finding.id,
        chapter_id=chapter.id,
        strategy=RepairStrategy.NOTE_ONLY,
        target_text="",
        replacement_text="",
        explanation="record only",
        risk_note="no text mutation",
    )

    result = service.apply(
        proposal.id,
        chapter_id=chapter.id,
        expected_revision=0,
    )

    assert chapters.read_content_exact(chapter.id) == "The old sentence stayed."
    assert result.chapter.revision == 1
    assert len(chapters.list_versions(chapter.id)) == 1
    assert result.proposal.status == RepairProposalStatus.APPLIED
    formal = SearchRepository(project).read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=1,
        expected_source_hash=_hash("The old sentence stayed."),
        chunk_policy_version="paragraph-codepoint-v1",
    )
    assert tuple(document.content for document in formal) == (
        "The old sentence stayed.",
    )


def test_post_write_audit_failure_does_not_rollback_repaired_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters, chapter, audits, finding = _workspace(tmp_path)
    service = RepairApplicationService(chapters, audits)
    proposal = service.create_validated_text_repair(
        finding_id=finding.id,
        chapter_id=chapter.id,
        strategy=RepairStrategy.REPLACE_TEXT,
        target_text="old sentence",
        replacement_text="committed replacement",
        explanation="local repair",
        risk_note="low risk",
    )
    real_update = audits.update_repair_status

    def fail_applied_status(
        proposal_id: str,
        status: RepairProposalStatus,
    ):  # type: ignore[no-untyped-def]
        if status == RepairProposalStatus.APPLIED:
            raise RuntimeError("injected audit transition failure")
        return real_update(proposal_id, status)

    monkeypatch.setattr(audits, "update_repair_status", fail_applied_status)

    with pytest.raises(RuntimeError, match="audit transition"):
        service.apply(
            proposal.id,
            chapter_id=chapter.id,
            expected_revision=0,
        )

    assert chapters.read_content_exact(chapter.id) == "The committed replacement stayed."
    assert chapters.get_chapter(chapter.id).revision == 1
    assert audits.get_repair_proposal(proposal.id).status == RepairProposalStatus.VALIDATED
    formal = SearchRepository(project).read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=1,
        expected_source_hash=_hash("The committed replacement stayed."),
        chunk_policy_version="paragraph-codepoint-v1",
    )
    assert tuple(document.content for document in formal) == (
        "The committed replacement stayed.",
    )


def test_apply_rejects_stale_revision_without_changing_chapter(tmp_path: Path) -> None:
    _, chapters, chapter, audits, finding = _workspace(tmp_path)
    service = RepairApplicationService(chapters, audits)
    proposal = service.create_validated_text_repair(
        finding_id=finding.id,
        chapter_id=chapter.id,
        strategy=RepairStrategy.REPLACE_TEXT,
        target_text="old sentence",
        replacement_text="new sentence",
        explanation="local repair",
        risk_note="low risk",
    )
    chapters.save_content(chapter.id, "human edit", source="manual", reason="edit")

    with pytest.raises(RepairApplicationError, match="stale"):
        service.apply(proposal.id, chapter_id=chapter.id, expected_revision=0)

    assert chapters.read_content(chapter.id) == "human edit"
    assert audits.get_repair_proposal(proposal.id).status == RepairProposalStatus.STALE


def test_create_repair_rejects_missing_target_text(tmp_path: Path) -> None:
    _, _, chapter, audits, finding = _workspace(tmp_path)
    service = RepairApplicationService(ChapterRepository(audits.project), audits)

    with pytest.raises(RepairApplicationError, match="target text"):
        service.create_validated_text_repair(
            finding_id=finding.id,
            chapter_id=chapter.id,
            strategy=RepairStrategy.REPLACE_TEXT,
            target_text="missing sentence",
            replacement_text="new sentence",
            explanation="local repair",
            risk_note="low risk",
        )
