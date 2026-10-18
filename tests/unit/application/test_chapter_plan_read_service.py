"""QP-3A: bounded chapter-plan projection over PlanQueryService.

The service must reuse the canonical plan authority (never assemble a second
plan truth from memory tables), truncate long text honestly, and fail closed
on unknown chapters with fixed errors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("ai_novel_studio.application")

from ai_novel_studio.application.chapter_plan_read_service import (
    ChapterPlanReadService,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
    ProjectGuidanceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import (
    ProjectRepository,
)


def _project(tmp_path: Path) -> tuple[ProjectRepository, str]:
    project = ProjectRepository.create(tmp_path / "novel", "本章计划")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id, "第一章", "1", "正文"
    )
    return project, chapter.id


def test_returns_requirement_and_guidance_bounded(tmp_path: Path) -> None:
    project, chapter_id = _project(tmp_path)
    ChapterRequirementRepository(project).get_or_create(chapter_id)
    guidance = ProjectGuidanceRepository(project)
    current = guidance.load()
    guidance.save_manual(
        "保持悬念，不要提前揭示钥匙来源。",
        expected_revision=current.revision,
    )
    service = ChapterPlanReadService(project)

    result = service.plan_for(chapter_id)

    assert result.domain_kind == "AUTHOR_PLAN"
    assert result.requirement is not None
    assert "正文" not in result.requirement.content  # requirement starts empty
    assert result.guidance_truncated is False
    assert "悬念" in result.guidance_text


def test_long_texts_are_truncated_with_flag(tmp_path: Path) -> None:
    project, chapter_id = _project(tmp_path)
    requirements = ChapterRequirementRepository(project)
    requirements.get_or_create(chapter_id)
    requirements.update(
        chapter_id,
        "需" * 5000,
        is_locked=False,
        expected_revision=0,
    )
    guidance = ProjectGuidanceRepository(project)
    current = guidance.load()
    guidance.save_manual("指" * 5000, expected_revision=current.revision)
    service = ChapterPlanReadService(project)

    result = service.plan_for(chapter_id)

    if result.requirement is not None:
        assert len(result.requirement.content) <= 4000
    assert result.requirement_truncated is True
    assert len(result.guidance_text) <= 2000
    assert result.guidance_truncated is True


def test_unknown_chapter_fails_fixed(tmp_path: Path) -> None:
    from ai_novel_studio.domain.identifiers import new_id

    project, _chapter_id = _project(tmp_path)
    service = ChapterPlanReadService(project)

    with pytest.raises(ValueError, match="unknown chapter"):
        service.plan_for(new_id())
