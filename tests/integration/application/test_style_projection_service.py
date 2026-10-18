from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.application.style_projection_service import (
    StyleProjectionRequest,
    StyleProjectionService,
)
from ai_novel_studio.core.context.style_retriever import StyleRetriever
from ai_novel_studio.domain.memory import (
    Authority,
    ReviewStatus,
    SourceType,
    StyleScope,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository


def _service(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Style projection")
    volume = project.list_volumes()[0]
    chapter = ChapterRevisionService(project).submit_creation(
        volume.id, "Style chapter", content="正文"
    ).chapter
    repository = StyleRepository(project)
    service = StyleProjectionService(StyleRetriever(repository))
    return service, repository, project, chapter


def test_book_rule_enters_projection(tmp_path: Path) -> None:
    service, repository, project, chapter = _service(tmp_path)
    repository.add_rule(
        StyleScope.BOOK,
        project.project.id,
        "禁用",
        "禁用感叹号",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )

    projection = service.build(
        StyleProjectionRequest(project.project.id, chapter.id)
    )

    assert projection.rules
    assert any(rule.rule_text == "禁用感叹号" for rule in projection.rules)
    assert projection.projection_id
    assert projection.samples == ()


def test_writer_sample_selection_bounds_samples(tmp_path: Path) -> None:
    service, repository, project, chapter = _service(tmp_path)
    for index in range(6):
        repository.add_sample(
            StyleScope.BOOK,
            project.project.id,
            f"样章{index}",
            f"样章正文{index}",
            SourceType.HUMAN,
            Authority.USER_CONFIRMED,
            ReviewStatus.APPROVED,
            immutable=True,
        )

    projection = service.build(
        StyleProjectionRequest(
            project.project.id,
            chapter.id,
            writer_sample_selection=True,
        )
    )

    assert projection.samples
    assert len(projection.samples) <= 4


def test_request_validation(tmp_path: Path) -> None:
    service, _repository, project, chapter = _service(tmp_path)

    with pytest.raises(ValueError):
        StyleProjectionRequest("bad-id", chapter.id)
    with pytest.raises(ValueError):
        StyleProjectionRequest(project.project.id, "bad-id")

    empty_scope = service.build(
        StyleProjectionRequest(project.project.id, chapter.id, scene_scope="  ")
    )
    assert empty_scope.rules == ()
