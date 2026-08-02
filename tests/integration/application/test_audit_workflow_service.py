import json
from pathlib import Path

import pytest

from ai_novel_studio.application.audit_workflow_service import AuditWorkflowService
from ai_novel_studio.domain.audit import (
    AuditFindingCategory,
    AuditFindingSource,
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


def _timeline_workspace(tmp_path: Path, target_content: str):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "novel", "Timeline Audit Workflow")
    chapters = ChapterRepository(project)
    volume_id = project.list_volumes()[0].id
    source = chapters.create_chapter(volume_id, "Source", "1", "source")
    target = chapters.create_chapter(volume_id, "Target", "2", target_content)
    future = chapters.create_chapter(volume_id, "Future", "3", "future")
    requirements = ChapterRequirementRepository(project)
    current = requirements.get_or_create(target.id)
    requirements.update(
        target.id,
        "must: find the letter",
        is_locked=False,
        expected_revision=current.revision,
    )
    audits = AuditRepository(project)
    memory = CharacterMemoryRepository(project)
    character = memory.create_character("Timeline subject")
    return (
        project,
        chapters,
        source,
        target,
        future,
        requirements,
        audits,
        memory,
        character,
    )


def _append_location_state(  # type: ignore[no-untyped-def]
    memory,
    *,
    character_id: str,
    chapter_id: str,
    location: str,
    review_status: ReviewStatus,
):
    return memory.append_state(
        character_id,
        chapter_id,
        motivation="protect the archive",
        psychology="alert",
        current_goal="find the letter",
        relationships="trusted",
        recent_activity="searching",
        confidence=1.0,
        source_type=SourceType.HUMAN,
        review_status=review_status,
        location=location,
    )


def _injury_workspace(tmp_path: Path, target_content: str):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "novel", "Injury Audit Workflow")
    chapters = ChapterRepository(project)
    volume_id = project.list_volumes()[0].id
    source = chapters.create_chapter(volume_id, "Source", "1", "source")
    latest = chapters.create_chapter(volume_id, "Latest", "2", "latest")
    target = chapters.create_chapter(volume_id, "Target", "3", target_content)
    future = chapters.create_chapter(volume_id, "Future", "4", "future")
    requirements = ChapterRequirementRepository(project)
    current = requirements.get_or_create(target.id)
    requirements.update(
        target.id,
        "must: find the letter",
        is_locked=False,
        expected_revision=current.revision,
    )
    audits = AuditRepository(project)
    memory = CharacterMemoryRepository(project)
    character = memory.create_character("Injury subject")
    return (
        project,
        chapters,
        source,
        latest,
        target,
        future,
        requirements,
        audits,
        memory,
        character,
    )


def _append_injury_state(  # type: ignore[no-untyped-def]
    memory,
    *,
    character_id: str,
    chapter_id: str,
    injury_status: str,
    review_status: ReviewStatus,
):
    return memory.append_state(
        character_id,
        chapter_id,
        motivation="protect the archive",
        psychology="alert",
        current_goal="find the letter",
        relationships="trusted",
        recent_activity="searching",
        confidence=1.0,
        source_type=SourceType.HUMAN,
        review_status=review_status,
        injury_status=injury_status,
    )


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


def test_contested_prior_character_location_persists_timeline_warning(
    tmp_path: Path,
) -> None:
    (
        _,
        chapters,
        source,
        target,
        _,
        requirements,
        audits,
        memory,
        character,
    ) = _timeline_workspace(
        tmp_path,
        "The protagonist finds the letter at Old harbor.",
    )
    first = _append_location_state(
        memory,
        character_id=character.id,
        chapter_id=source.id,
        location=" Clock tower ",
        review_status=ReviewStatus.APPROVED,
    )
    second = _append_location_state(
        memory,
        character_id=character.id,
        chapter_id=source.id,
        location="Old harbor",
        review_status=ReviewStatus.LOCKED,
    )
    service = AuditWorkflowService(
        chapters,
        requirements,
        audits,
        character_memory=memory,
    )

    result = service.run_deterministic_for_formal_chapter(
        target.id,
        mode=CreationMode.STANDARD,
        audit_policy=AuditPolicy.STANDARD,
    )

    timeline = [
        finding
        for finding in result.findings
        if finding.category == AuditFindingCategory.TIMELINE
    ]
    assert len(timeline) == 1
    finding = timeline[0]
    assert result.run.status == AuditRunStatus.COMPLETED
    assert result.run.mode == CreationMode.STANDARD
    assert result.run.audit_policy == AuditPolicy.STANDARD
    assert finding.severity == AuditSeverity.WARNING
    assert finding.source == AuditFindingSource.DETERMINISTIC
    assert finding.confidence == 1.0
    assert finding.evidence == "Old harbor"
    assert "unresolved" in finding.explanation.lower()
    assert "branch" in finding.explanation.lower()
    assert json.loads(finding.location_json) == {
        "character_id": character.id,
        "evidence_kind": "SOURCE_EXCERPT",
        "quote": "Old harbor",
        "source_boundary_chapter_id": source.id,
        "start": chapters.read_content(target.id).index("Old harbor"),
        "state_field": "location",
    }
    assert json.loads(finding.related_source_json) == [
        {"id": event_id, "type": "character_state_event"}
        for event_id in sorted((first.id, second.id))
    ]
    assert audits.list_findings(result.run.id) == result.findings


@pytest.mark.parametrize(
    "excluded_reason",
    (
        "trusted_single",
        "same_location",
        "empty_location",
        "review",
        "rejected",
        "current",
        "future",
        "deleted_source",
        "inactive",
        "absent",
        "case_changed",
        "paraphrased",
    ),
)
def test_contested_character_location_ignores_ineligible_sources_and_text(
    tmp_path: Path,
    excluded_reason: str,
) -> None:
    target_content = {
        "absent": "The protagonist finds the letter elsewhere.",
        "case_changed": "The protagonist finds the letter at OLD HARBOR.",
        "paraphrased": "The protagonist finds the letter by the harbor district.",
    }.get(
        excluded_reason,
        "The protagonist finds the letter at Old harbor.",
    )
    (
        project,
        chapters,
        source,
        target,
        future,
        requirements,
        audits,
        memory,
        character,
    ) = _timeline_workspace(tmp_path, target_content)
    state_chapter_id = {
        "current": target.id,
        "future": future.id,
    }.get(excluded_reason, source.id)
    second_status = {
        "review": ReviewStatus.REVIEW,
        "rejected": ReviewStatus.REJECTED,
    }.get(excluded_reason, ReviewStatus.LOCKED)
    first_location = "" if excluded_reason == "empty_location" else "Clock tower"
    second_location = {
        "same_location": " Clock tower ",
        "empty_location": " ",
    }.get(excluded_reason, "Old harbor")
    _append_location_state(
        memory,
        character_id=character.id,
        chapter_id=state_chapter_id,
        location=first_location,
        review_status=ReviewStatus.APPROVED,
    )
    if excluded_reason != "trusted_single":
        _append_location_state(
            memory,
            character_id=character.id,
            chapter_id=state_chapter_id,
            location=second_location,
            review_status=second_status,
        )
    if excluded_reason == "deleted_source":
        chapters.delete_chapter(source.id)
    elif excluded_reason == "inactive":
        with project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE subjects SET active = 0 WHERE id = ?",
                (character.id,),
            )
    service = AuditWorkflowService(
        chapters,
        requirements,
        audits,
        character_memory=memory,
    )

    result = service.run_deterministic_for_formal_chapter(
        target.id,
        mode=CreationMode.STANDARD,
        audit_policy=AuditPolicy.STANDARD,
    )

    assert result.run.status == AuditRunStatus.COMPLETED
    assert not any(
        finding.category == AuditFindingCategory.TIMELINE
        for finding in result.findings
    )


def test_contested_prior_character_injury_status_persists_character_warning(
    tmp_path: Path,
) -> None:
    (
        _,
        chapters,
        source,
        _,
        target,
        _,
        requirements,
        audits,
        memory,
        character,
    ) = _injury_workspace(
        tmp_path,
        "The protagonist finds the letter with a Sprained left ankle.",
    )
    first = _append_injury_state(
        memory,
        character_id=character.id,
        chapter_id=source.id,
        injury_status=" Sprained left ankle ",
        review_status=ReviewStatus.APPROVED,
    )
    second = _append_injury_state(
        memory,
        character_id=character.id,
        chapter_id=source.id,
        injury_status="Broken wrist",
        review_status=ReviewStatus.LOCKED,
    )
    service = AuditWorkflowService(
        chapters,
        requirements,
        audits,
        character_memory=memory,
    )

    result = service.run_deterministic_for_formal_chapter(
        target.id,
        mode=CreationMode.STANDARD,
        audit_policy=AuditPolicy.STANDARD,
    )

    character_findings = [
        finding
        for finding in result.findings
        if finding.category == AuditFindingCategory.CHARACTER
    ]
    assert len(character_findings) == 1
    finding = character_findings[0]
    assert result.run.status == AuditRunStatus.COMPLETED
    assert result.run.mode == CreationMode.STANDARD
    assert result.run.audit_policy == AuditPolicy.STANDARD
    assert finding.severity == AuditSeverity.WARNING
    assert finding.source == AuditFindingSource.DETERMINISTIC
    assert finding.confidence == 1.0
    assert finding.evidence == "Sprained left ankle"
    assert "unresolved" in finding.explanation.lower()
    assert "injury-status" in finding.explanation.lower()
    assert "branch" in finding.explanation.lower()
    assert json.loads(finding.location_json) == {
        "character_id": character.id,
        "evidence_kind": "SOURCE_EXCERPT",
        "quote": "Sprained left ankle",
        "source_boundary_chapter_id": source.id,
        "start": chapters.read_content(target.id).index("Sprained left ankle"),
        "state_field": "injury_status",
    }
    assert json.loads(finding.related_source_json) == [
        {"id": event_id, "type": "character_state_event"}
        for event_id in sorted((first.id, second.id))
    ]
    assert audits.list_findings(result.run.id) == result.findings


@pytest.mark.parametrize(
    "excluded_reason",
    (
        "trusted_single",
        "same_injury_status",
        "empty_injury_status",
        "review",
        "rejected",
        "current",
        "future",
        "deleted_source",
        "inactive",
        "older_boundary",
        "absent",
        "case_changed",
        "paraphrased",
    ),
)
def test_contested_character_injury_status_ignores_ineligible_sources_and_text(
    tmp_path: Path,
    excluded_reason: str,
) -> None:
    target_content = {
        "absent": "The protagonist finds the letter without an injury mention.",
        "case_changed": "The protagonist finds the letter with a SPRAINED LEFT ANKLE.",
        "paraphrased": "The protagonist finds the letter after the injury improved.",
    }.get(
        excluded_reason,
        "The protagonist finds the letter with a Sprained left ankle.",
    )
    (
        project,
        chapters,
        source,
        latest,
        target,
        future,
        requirements,
        audits,
        memory,
        character,
    ) = _injury_workspace(tmp_path, target_content)
    state_chapter_id = {
        "current": target.id,
        "future": future.id,
    }.get(excluded_reason, source.id)
    second_status = {
        "review": ReviewStatus.REVIEW,
        "rejected": ReviewStatus.REJECTED,
    }.get(excluded_reason, ReviewStatus.LOCKED)
    first_status = "" if excluded_reason == "empty_injury_status" else "Sprained left ankle"
    second_status_value = {
        "same_injury_status": " Sprained left ankle ",
        "empty_injury_status": " ",
    }.get(excluded_reason, "Broken wrist")
    _append_injury_state(
        memory,
        character_id=character.id,
        chapter_id=state_chapter_id,
        injury_status=first_status,
        review_status=ReviewStatus.APPROVED,
    )
    if excluded_reason != "trusted_single":
        _append_injury_state(
            memory,
            character_id=character.id,
            chapter_id=state_chapter_id,
            injury_status=second_status_value,
            review_status=second_status,
        )
    if excluded_reason == "older_boundary":
        _append_injury_state(
            memory,
            character_id=character.id,
            chapter_id=latest.id,
            injury_status="Healed ankle",
            review_status=ReviewStatus.APPROVED,
        )
    if excluded_reason == "deleted_source":
        chapters.delete_chapter(source.id)
    elif excluded_reason == "inactive":
        with project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE subjects SET active = 0 WHERE id = ?",
                (character.id,),
            )
    service = AuditWorkflowService(
        chapters,
        requirements,
        audits,
        character_memory=memory,
    )

    result = service.run_deterministic_for_formal_chapter(
        target.id,
        mode=CreationMode.STANDARD,
        audit_policy=AuditPolicy.STANDARD,
    )

    assert result.run.status == AuditRunStatus.COMPLETED
    assert not any(
        finding.category == AuditFindingCategory.CHARACTER
        for finding in result.findings
    )
