import json
from pathlib import Path

import pytest

from ai_novel_studio.application.audit_workflow_service import AuditWorkflowService
from ai_novel_studio.domain.audit import (
    AuditFindingCategory,
    AuditRunStatus,
    AuditSeverity,
    AuditTargetKind,
)
from ai_novel_studio.domain.generation import AuditPolicy, CreationMode
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType
from ai_novel_studio.domain.view import ViewAssertionDraft, ViewType
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
)


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


def _reader_view(  # type: ignore[no-untyped-def]
    project,
    *,
    source_id: str,
    source_revision: int,
    content: str,
    visible_from_sequence: int,
    review_status: ReviewStatus = ReviewStatus.APPROVED,
):
    character = CharacterMemoryRepository(project).create_character("Reader subject")
    assertion = ViewAssertionRepository(project).create(
        ViewAssertionDraft(
            subject_id=character.id,
            view_type=ViewType.READER_VIEW,
            content=content,
            narrative_visible_from_sequence=visible_from_sequence,
        ),
        authority=Authority.USER_CONFIRMED,
        review_status=review_status,
        source_type=SourceType.HUMAN,
        source_id=source_id,
        source_revision=source_revision,
    )
    return character, assertion


def test_run_deterministic_for_formal_chapter_persists_completed_run_and_findings(
    tmp_path: Path,
) -> None:
    project, chapters, chapter, requirements, audits = _workspace(
        tmp_path,
        'Of course, here is the chapter:\nThe crown is hollow.\nHe said, "unfinished',
        "must: find the letter",
    )
    _, assertion = _reader_view(
        project,
        source_id=chapter.id,
        source_revision=chapter.revision,
        content="The crown is hollow.",
        visible_from_sequence=2,
    )
    service = AuditWorkflowService(
        chapters,
        requirements,
        audits,
        view_assertions=ViewAssertionRepository(project),
    )

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
    knowledge = next(
        finding
        for finding in result.findings
        if finding.category == AuditFindingCategory.KNOWLEDGE
    )
    assert json.loads(knowledge.location_json) == {
        "current_sequence": 1,
        "evidence_kind": "SOURCE_EXCERPT",
        "quote": "The crown is hollow.",
        "start": chapters.read_content(chapter.id).index("The crown is hollow."),
        "visible_from_sequence": 2,
    }
    assert json.loads(knowledge.related_source_json) == [
        {"id": assertion.id, "type": "view_assertion"}
    ]
    persisted_kinds = {
        json.loads(finding.location_json)["evidence_kind"]
        for finding in audits.list_findings(result.run.id)
    }
    assert persisted_kinds == {
        "SOURCE_EXCERPT",
        "EXPECTED_MISSING",
        "DIAGNOSTIC",
    }


def test_run_deterministic_can_audit_generated_draft_without_changing_formal_chapter(
    tmp_path: Path,
) -> None:
    project, chapters, chapter, requirements, audits = _workspace(
        tmp_path,
        "formal chapter stays",
        "must: find the letter",
    )
    _, assertion = _reader_view(
        project,
        source_id="manual-reader-view",
        source_revision=0,
        content="The crown is hollow.",
        visible_from_sequence=2,
        review_status=ReviewStatus.LOCKED,
    )
    service = AuditWorkflowService(
        chapters,
        requirements,
        audits,
        view_assertions=ViewAssertionRepository(project),
    )

    result = service.run_deterministic_for_draft(
        chapter_id=chapter.id,
        generation_run_id="generation-run-1",
        draft_text="The crown is hollow. The protagonist finds the letter.",
        base_chapter_revision=chapter.revision,
        mode=CreationMode.STRICT,
        audit_policy=AuditPolicy.DEEP,
    )

    assert result.run.target_kind == AuditTargetKind.GENERATED_DRAFT
    assert result.run.target_id == "generation-run-1"
    assert result.run.mode == CreationMode.STRICT
    assert result.run.audit_policy == AuditPolicy.DEEP
    assert chapters.read_content(chapter.id) == "formal chapter stays"
    knowledge = next(
        finding
        for finding in result.findings
        if finding.category == AuditFindingCategory.KNOWLEDGE
    )
    assert json.loads(knowledge.related_source_json) == [
        {"id": assertion.id, "type": "view_assertion"}
    ]


@pytest.mark.parametrize(
    "excluded_reason",
    (
        "review",
        "rejected",
        "stale",
        "source_changed",
        "revision_mismatch",
        "inactive",
        "currently_visible",
    ),
)
def test_reader_view_exposure_ignores_ineligible_persisted_sources(
    tmp_path: Path,
    excluded_reason: str,
) -> None:
    project, chapters, chapter, requirements, audits = _workspace(
        tmp_path,
        "The crown is hollow. The protagonist finds the letter.",
        "must: find the letter",
    )
    review_status = {
        "review": ReviewStatus.REVIEW,
        "rejected": ReviewStatus.REJECTED,
    }.get(excluded_reason, ReviewStatus.APPROVED)
    source_revision = (
        chapter.revision + 1
        if excluded_reason == "revision_mismatch"
        else chapter.revision
    )
    visible_from_sequence = 1 if excluded_reason == "currently_visible" else 2
    character, assertion = _reader_view(
        project,
        source_id=chapter.id,
        source_revision=source_revision,
        content="The crown is hollow.",
        visible_from_sequence=visible_from_sequence,
        review_status=review_status,
    )
    with project.database.connect() as connection, connection:
        if excluded_reason == "stale":
            connection.execute(
                "UPDATE view_assertions SET stale = 1 WHERE id = ?",
                (assertion.id,),
            )
        elif excluded_reason == "source_changed":
            connection.execute(
                "UPDATE view_assertions SET source_changed = 1 WHERE id = ?",
                (assertion.id,),
            )
        elif excluded_reason == "inactive":
            connection.execute(
                "UPDATE subjects SET active = 0 WHERE id = ?",
                (character.id,),
            )
    service = AuditWorkflowService(
        chapters,
        requirements,
        audits,
        view_assertions=ViewAssertionRepository(project),
    )

    result = service.run_deterministic_for_formal_chapter(
        chapter.id,
        mode=CreationMode.STANDARD,
    )

    assert result.run.status == AuditRunStatus.COMPLETED
    assert result.findings == ()
