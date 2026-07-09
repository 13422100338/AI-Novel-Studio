from pathlib import Path

from ai_novel_studio.application.audit_workflow_service import AuditWorkflowService
from ai_novel_studio.domain.audit import (
    AuditFindingCategory,
    AuditRunStatus,
    AuditSeverity,
    AuditTargetKind,
)
from ai_novel_studio.domain.generation import CreationMode
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _workspace(tmp_path: Path, content: str, requirement: str):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "novel", "Audit Workflow")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(project.list_volumes()[0].id, "Opening", "1", content)
    requirements = ChapterRequirementRepository(project)
    current = requirements.get_or_create(chapter.id)
    requirements.update(
        chapter.id,
        requirement,
        is_locked=False,
        expected_revision=current.revision,
    )
    audits = AuditRepository(project)
    return project, chapters, chapter, requirements, audits


def test_run_deterministic_for_formal_chapter_persists_completed_run_and_findings(
    tmp_path: Path,
) -> None:
    _, chapters, chapter, requirements, audits = _workspace(
        tmp_path,
        'Of course, here is the chapter:\nHe said, "unfinished',
        "must: find the letter",
    )
    service = AuditWorkflowService(chapters, requirements, audits)

    result = service.run_deterministic_for_formal_chapter(
        chapter.id,
        mode=CreationMode.BASIC,
    )

    assert result.run.status == AuditRunStatus.COMPLETED
    assert result.run.target_kind == AuditTargetKind.FORMAL_CHAPTER
    assert result.run.target_revision == 0
    assert len(result.findings) >= 3
    assert audits.list_findings(result.run.id) == result.findings
    assert any(finding.category == AuditFindingCategory.FORMAT for finding in result.findings)
    assert any(
        finding.category == AuditFindingCategory.REQUIREMENT
        and finding.severity == AuditSeverity.WARNING
        for finding in result.findings
    )


def test_run_deterministic_can_audit_generated_draft_without_changing_formal_chapter(
    tmp_path: Path,
) -> None:
    _, chapters, chapter, requirements, audits = _workspace(
        tmp_path,
        "formal chapter stays",
        "must: find the letter",
    )
    service = AuditWorkflowService(chapters, requirements, audits)

    result = service.run_deterministic_for_draft(
        chapter_id=chapter.id,
        generation_run_id="generation-run-1",
        draft_text="draft without required event",
        base_chapter_revision=chapter.revision,
        mode=CreationMode.STRICT,
    )

    assert result.run.target_kind == AuditTargetKind.GENERATED_DRAFT
    assert result.run.target_id == "generation-run-1"
    assert chapters.read_content(chapter.id) == "formal chapter stays"
    assert any(finding.category == AuditFindingCategory.REQUIREMENT for finding in result.findings)

