from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_context_pin_service import (
    ChapterContextPinService,
)
from ai_novel_studio.application.project_memory_workspace_gateway import (
    ProjectMemoryWorkspaceGateway,
)
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SummaryLevel
from ai_novel_studio.infrastructure.storage.chapter_context_pin_repository import (
    ChapterContextPinRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


def test_pin_service_persists_only_reviewed_pre_chapter_memory(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "Opening", "1", "body")
    target = chapters.create_chapter(volume.id, "Target", "2")
    future = chapters.create_chapter(volume.id, "Future", "3", "future")
    summaries = SummaryRepository(project)
    approved = summaries.add_human_summary(
        SummaryLevel.CHAPTER,
        first.id,
        "Reviewed history",
        (first.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    review = summaries.add_candidate(
        SummaryLevel.CHAPTER,
        first.id,
        "Unreviewed candidate",
        (first.id,),
        model_profile_id="model",
    )
    future_summary = summaries.add_human_summary(
        SummaryLevel.CHAPTER,
        future.id,
        "Future leak",
        (future.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    records = {
        record.id: record
        for record in ProjectMemoryWorkspaceGateway(project).load_before("__all__")
    }
    service = ChapterContextPinService(ChapterContextPinRepository(project))

    pin = service.pin(target.id, records[approved.id])

    assert pin.content == "Reviewed history"
    assert service.is_pinned(target.id, records[approved.id])
    assert service.list_for_chapter(target.id) == (pin,)
    with pytest.raises(PermissionError, match="先晋升"):
        service.pin(target.id, records[review.id])
    with pytest.raises(PermissionError, match="未来章节"):
        service.pin(target.id, records[future_summary.id])
    assert service.unpin(target.id, records[approved.id])
    assert service.list_for_chapter(target.id) == ()
    assert len(service.pin_compressed_history(target.id, tuple(records.values()))) == 1
    assert service.pin_compressed_history(target.id, tuple(records.values())) == ()
