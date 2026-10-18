from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
    StaleChapterRevisionError,
)
from ai_novel_studio.application.revision_submission_service import (
    RevisionSubmissionRequest,
    RevisionSubmissionService,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _service(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Revision facade")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    chapter = revisions.submit_creation(volume.id, "Chapter", content="v0").chapter
    return RevisionSubmissionService(revisions), project, chapter


def test_submission_commits_and_reports_impact(tmp_path: Path) -> None:
    service, project, chapter = _service(tmp_path)

    submitted = service.run(
        RevisionSubmissionRequest(
            chapter.id,
            "v1 正文",
            source="author",
            reason="polish",
            expected_revision=chapter.revision,
        )
    )

    assert submitted.chapter.revision == chapter.revision + 1
    assert submitted.impact.manuscript_committed is True
    assert submitted.maintenance is not None
    from ai_novel_studio.infrastructure.storage.chapter_repository import (
        ChapterRepository,
    )

    assert ChapterRepository(project).read_content(chapter.id) == "v1 正文"


def test_stale_revision_fails_closed(tmp_path: Path) -> None:
    service, _project, chapter = _service(tmp_path)

    with pytest.raises(StaleChapterRevisionError):
        service.run(
            RevisionSubmissionRequest(
                chapter.id,
                "v1 正文",
                source="author",
                reason="polish",
                expected_revision=chapter.revision + 5,
            )
        )


def test_request_validation(tmp_path: Path) -> None:
    _service_obj, _project, chapter = _service(tmp_path)

    with pytest.raises(ValueError):
        RevisionSubmissionRequest("bad-id", "text", "author", "why", 0)
    with pytest.raises(ValueError):
        RevisionSubmissionRequest(chapter.id, "  ", "author", "why", 0)
    with pytest.raises(ValueError):
        RevisionSubmissionRequest(chapter.id, "text", " ", "why", 0)
    with pytest.raises(ValueError):
        RevisionSubmissionRequest(chapter.id, "text", "author", " ", 0)
    with pytest.raises(ValueError):
        RevisionSubmissionRequest(chapter.id, "text", "author", "why", -1)
