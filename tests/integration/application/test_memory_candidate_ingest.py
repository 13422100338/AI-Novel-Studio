from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.application.memory_analysis_service import (
    CharacterStateCandidate,
    MemoryCandidateBundle,
    SummaryCandidate,
)
from ai_novel_studio.application.memory_candidate_ingest import (
    MemoryCandidateIngestReport,
    MemoryCandidateIngestService,
)
from ai_novel_studio.domain.memory import SummaryLevel
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


def _bundle(chapter_id: str, revision: int, content: str) -> MemoryCandidateBundle:
    return MemoryCandidateBundle(
        source_chapter_id=chapter_id,
        source_revision=revision,
        source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        summary=SummaryCandidate(content="剧情概况：旧港重逢。"),
        character_states=(
            CharacterStateCandidate(
                character_name="艾瑞克",
                motivation="寻找旧友",
                psychology="坚定",
                current_goal="抵达旧港",
                relationships="与莉娅重逢",
                recent_activity="登上渡船",
                location="旧港码头",
                injury_status="无",
            ),
        ),
        canon=(),
        clues=(),
        knowledge=(),
        style=(),
    )


def _project(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Ingest")
    volume = project.list_volumes()[0]
    chapter = ChapterRevisionService(project).submit_creation(
        volume.id, "Chapter", content="正文内容"
    ).chapter
    return project, chapter


def test_ingest_writes_deterministic_candidates(tmp_path: Path) -> None:
    project, chapter = _project(tmp_path)
    content = "正文内容"
    service = MemoryCandidateIngestService()

    report = service.ingest(
        project,
        chapter_id=chapter.id,
        bundle=_bundle(chapter.id, chapter.revision, content),
    )

    assert isinstance(report, MemoryCandidateIngestReport)
    assert report.summary_created is True
    assert report.created_character_states == 1
    summaries = SummaryRepository(project).list_scope(
        SummaryLevel.CHAPTER, chapter.id
    )
    assert summaries


def test_ingest_is_idempotent_for_same_bundle(tmp_path: Path) -> None:
    project, chapter = _project(tmp_path)
    content = "正文内容"
    service = MemoryCandidateIngestService()
    bundle = _bundle(chapter.id, chapter.revision, content)

    first = service.ingest(project, chapter_id=chapter.id, bundle=bundle)
    second = service.ingest(project, chapter_id=chapter.id, bundle=bundle)

    assert first.created_character_states == 1
    assert second.created_character_states == 0


def test_ingest_rejects_stale_bundle_source(tmp_path: Path) -> None:
    project, chapter = _project(tmp_path)
    stale = _bundle(chapter.id, chapter.revision + 1, "正文内容")

    with pytest.raises(ValueError):
        MemoryCandidateIngestService().ingest(
            project,
            chapter_id=chapter.id,
            bundle=stale,
        )
