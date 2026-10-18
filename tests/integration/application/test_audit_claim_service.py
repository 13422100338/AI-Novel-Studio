from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.application.audit_claim_service import (
    AuditClaimService,
    AuditClaimsRequest,
)
from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.domain.audit import AuditFindingCategory, AuditRunStatus, AuditTargetKind
from ai_novel_studio.domain.generation import AuditPolicy, CreationMode
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _service(tmp_path: Path) -> tuple[AuditClaimService, ProjectRepository]:
    project = ProjectRepository.create(tmp_path / "novel", "Audit claims")
    return AuditClaimService.for_project(project), project


def _chapter(project: ProjectRepository, text: str):
    volume = project.list_volumes()[0]
    return ChapterRevisionService(project).submit_creation(
        volume.id, "Audited chapter", content=text
    ).chapter


def test_formal_chapter_audit_finds_missing_requirement_phrase(
    tmp_path: Path,
) -> None:
    service, project = _service(tmp_path)
    chapter = _chapter(project, "雨夜，艾瑞克走过旧港的栈桥。")

    result = service.run(
        AuditClaimsRequest(
            chapter_id=chapter.id,
            target_kind=AuditTargetKind.FORMAL_CHAPTER,
            target_id=chapter.id,
            target_revision=chapter.revision,
            mode=CreationMode.STANDARD,
            requirement_content="必须:夜访旧港钟楼",
        )
    )

    assert result.run.chapter_id == chapter.id
    assert any(
        finding.category is AuditFindingCategory.REQUIREMENT
        for finding in result.findings
    )
    # 持久化证据
    from ai_novel_studio.infrastructure.storage.audit_repository import (
        AuditRepository,
    )

    persisted = AuditRepository(project).list_findings(result.run.id)
    assert len(persisted) == len(result.findings)


def test_draft_audit_uses_supplied_text(tmp_path: Path) -> None:
    service, project = _service(tmp_path)
    chapter = _chapter(project, "既有正文")
    draft_text = "here is your chapter: 雨夜。"

    result = service.run(
        AuditClaimsRequest(
            chapter_id=chapter.id,
            target_kind=AuditTargetKind.GENERATED_DRAFT,
            target_id=str(new_id()),
            target_revision=chapter.revision,
            target_text=draft_text,
            mode=CreationMode.STANDARD,
            audit_policy=AuditPolicy.STANDARD,
        )
    )

    assert result.run.target_kind is AuditTargetKind.GENERATED_DRAFT
    assert any(
        finding.category is AuditFindingCategory.FORMAT
        and "model residue" in finding.explanation
        for finding in result.findings
    )


def test_request_validation(tmp_path: Path) -> None:
    service, project = _service(tmp_path)
    chapter = _chapter(project, "正文")

    with pytest.raises(ValueError):
        AuditClaimsRequest(
            "bad-id", AuditTargetKind.FORMAL_CHAPTER, "bad-id", 0, CreationMode.STANDARD
        )
    with pytest.raises(ValueError):
        AuditClaimsRequest(
            chapter.id,
            AuditTargetKind.FORMAL_CHAPTER,
            str(new_id()),
            chapter.revision,
            CreationMode.STANDARD,
        )
    with pytest.raises(ValueError):
        AuditClaimsRequest(
            chapter.id,
            AuditTargetKind.GENERATED_DRAFT,
            str(new_id()),
            chapter.revision,
            CreationMode.STANDARD,
            target_text=" ",
        )

    result = service.run(
        AuditClaimsRequest(
            chapter_id=chapter.id,
            target_kind=AuditTargetKind.FORMAL_CHAPTER,
            target_id=chapter.id,
            target_revision=chapter.revision,
            mode=CreationMode.STANDARD,
            requirement_content="",
        )
    )
    assert result.run.status is not AuditRunStatus.FAILED
