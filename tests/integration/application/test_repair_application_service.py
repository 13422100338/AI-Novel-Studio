import hashlib
from pathlib import Path

import pytest

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
) -> None:
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

    result = service.apply(proposal.id, chapter_id=chapter.id, expected_revision=0)

    assert chapters.read_content(chapter.id) == "The new sentence stayed."
    assert result.chapter.revision == 1
    assert result.proposal.status == RepairProposalStatus.APPLIED
    assert result.finding.status.value == "ACCEPTED_REPAIR"
    assert result.provenance.event_type == ProvenanceEventType.REPAIR_APPLIED
    assert len(chapters.list_versions(chapter.id)) == 1
    assert audits.list_provenance(chapter.id) == (result.provenance,)


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

