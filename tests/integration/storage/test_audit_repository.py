from pathlib import Path

from ai_novel_studio.domain.audit import (
    AuditFindingCategory,
    AuditFindingSource,
    AuditFindingStatus,
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


def _workspace(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "novel", "Audit Repository")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "old text",
    )
    return project, chapter, AuditRepository(project)


def test_audit_repository_persists_run_findings_proposals_and_provenance(
    tmp_path: Path,
) -> None:
    _, chapter, audits = _workspace(tmp_path)

    run = audits.create_run(
        chapter_id=chapter.id,
        target_kind=AuditTargetKind.FORMAL_CHAPTER,
        target_id=chapter.id,
        target_revision=chapter.revision,
        target_hash="hash",
        mode=CreationMode.BASIC,
        status=AuditRunStatus.PREPARING,
        prompt_version="deterministic-v1",
    )
    completed = audits.update_run_status(run.id, AuditRunStatus.COMPLETED)
    finding = audits.add_finding(
        run_id=run.id,
        category=AuditFindingCategory.FORMAT,
        severity=AuditSeverity.WARNING,
        source=AuditFindingSource.DETERMINISTIC,
        location_json="{}",
        evidence="old text",
        explanation="example finding",
        related_source_json="[]",
        confidence=1.0,
    )
    proposal = audits.add_repair_proposal(
        finding_id=finding.id,
        target_revision=chapter.revision,
        target_hash="hash",
        strategy=RepairStrategy.REPLACE_TEXT,
        target_text="old",
        replacement_text="new",
        patch_json='{"strategy":"replace"}',
        explanation="replace stale wording",
        risk_note="low risk",
        status=RepairProposalStatus.VALIDATED,
    )
    event = audits.add_provenance_event(
        chapter_id=chapter.id,
        chapter_revision_before=0,
        chapter_revision_after=1,
        event_type=ProvenanceEventType.REPAIR_APPLIED,
        source_audit_run_id=run.id,
        source_finding_id=finding.id,
        source_repair_id=proposal.id,
        summary="applied repair",
    )

    assert completed.status == AuditRunStatus.COMPLETED
    assert audits.get_run(run.id) == completed
    assert audits.list_findings(run.id) == (finding,)
    assert audits.get_repair_proposal(proposal.id) == proposal
    assert audits.list_provenance(chapter.id) == (event,)


def test_audit_repository_updates_finding_and_proposal_status(tmp_path: Path) -> None:
    _, chapter, audits = _workspace(tmp_path)
    run = audits.create_run(
        chapter_id=chapter.id,
        target_kind=AuditTargetKind.FORMAL_CHAPTER,
        target_id=chapter.id,
        target_revision=0,
        target_hash="hash",
        mode=CreationMode.BASIC,
        status=AuditRunStatus.COMPLETED,
        prompt_version="deterministic-v1",
    )
    finding = audits.add_finding(
        run_id=run.id,
        category=AuditFindingCategory.FORMAT,
        severity=AuditSeverity.WARNING,
        source=AuditFindingSource.DETERMINISTIC,
        location_json="{}",
        evidence="old",
        explanation="example",
        related_source_json="[]",
        confidence=1.0,
    )
    proposal = audits.add_repair_proposal(
        finding_id=finding.id,
        target_revision=0,
        target_hash="hash",
        strategy=RepairStrategy.REPLACE_TEXT,
        target_text="old",
        replacement_text="new",
        patch_json="{}",
        explanation="example",
        risk_note="low",
        status=RepairProposalStatus.VALIDATED,
    )

    updated_finding = audits.update_finding_status(
        finding.id, AuditFindingStatus.FALSE_POSITIVE
    )
    updated_proposal = audits.update_repair_status(
        proposal.id, RepairProposalStatus.APPLIED
    )

    assert updated_finding.status == AuditFindingStatus.FALSE_POSITIVE
    assert updated_proposal.status == RepairProposalStatus.APPLIED

