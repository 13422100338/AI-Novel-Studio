from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.application.plan_query_service import (
    PLAN_DOMAIN_KIND,
    PlanQueryRequest,
    PlanQueryService,
    PlanResult,
)
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
    ProjectGuidanceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _service(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Plan query")
    volume = project.list_volumes()[0]
    chapter = ChapterRevisionService(project).submit_creation(
        volume.id, "Chapter", content="正文"
    ).chapter
    return PlanQueryService(project), project, chapter


def test_query_returns_empty_plan_before_any_source(tmp_path: Path) -> None:
    service, _project, chapter = _service(tmp_path)

    result = service.query(PlanQueryRequest(chapter.id))

    assert isinstance(result, PlanResult)
    assert result.domain_kind == PLAN_DOMAIN_KIND
    assert result.requirement is None
    assert result.guidance_text == ""
    assert result.guidance_revision == 0


def test_query_aggregates_requirement_and_guidance(tmp_path: Path) -> None:
    service, project, chapter = _service(tmp_path)
    requirements = ChapterRequirementRepository(project)
    current = requirements.get_or_create(chapter.id)
    updated = requirements.update(
        chapter.id,
        "必须:夜访旧港",
        is_locked=True,
        expected_revision=current.revision,
    )
    guidance = ProjectGuidanceRepository(project)
    saved = guidance.save_manual(
        "本项目为第一人称视角", expected_revision=0
    )

    result = service.query(PlanQueryRequest(chapter.id))

    assert result.requirement is not None
    assert result.requirement.content == "必须:夜访旧港"
    assert result.requirement.is_locked is True
    assert result.requirement.revision == updated.revision
    assert result.requirement.content_hash == updated.content_hash
    assert result.guidance_text == "本项目为第一人称视角"
    assert result.guidance_revision == saved.revision


def test_query_rejects_invalid_chapter_id(tmp_path: Path) -> None:
    service, _project, _chapter = _service(tmp_path)

    with pytest.raises(ValueError):
        PlanQueryRequest("bad-id")
    with pytest.raises(TypeError):
        service.query("not a request")
