from pathlib import Path

from ai_novel_studio.application.plot_memory_context_service import (
    PlotMemoryContextService,
)
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SummaryLevel
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


def test_plot_memory_prefers_reviewed_summary_and_labels_unreviewed_fallback(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "第一章", "1", "第一章正文")
    second = chapters.create_chapter(volume.id, "第二章", "2", "第二章正文")
    target = chapters.create_chapter(volume.id, "第三章", "3", "第三章正文")
    summaries = SummaryRepository(project)
    summaries.add_candidate(
        SummaryLevel.CHAPTER,
        first.id,
        "不应覆盖已审查版本",
        (first.id,),
        model_profile_id="model",
    )
    summaries.add_human_summary(
        SummaryLevel.CHAPTER,
        first.id,
        "第一章已确认剧情",
        (first.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    summaries.add_candidate(
        SummaryLevel.CHAPTER,
        second.id,
        "第二章尚未审查剧情",
        (second.id,),
        model_profile_id="model",
    )

    selection = PlotMemoryContextService(project).select(target.id)

    assert selection.message is not None
    assert "【已审查" in selection.message.content
    assert "第一章已确认剧情" in selection.message.content
    assert "不应覆盖已审查版本" not in selection.message.content
    assert "【待审查" in selection.message.content
    assert "第二章尚未审查剧情" in selection.message.content
    assert "不得当作正典" in selection.message.content
    assert selection.approved_count == 1
    assert selection.review_count == 1


def test_plot_memory_excludes_current_and_later_chapters(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "第一章", "1", "第一章正文")
    target = chapters.create_chapter(volume.id, "第二章", "2", "第二章正文")
    summaries = SummaryRepository(project)
    summaries.add_human_summary(
        SummaryLevel.CHAPTER,
        first.id,
        "第一章剧情",
        (first.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    summaries.add_candidate(
        SummaryLevel.CHAPTER,
        target.id,
        "当前章不应作为前文",
        (target.id,),
        model_profile_id="model",
    )

    selection = PlotMemoryContextService(project).select(target.id)

    assert selection.message is not None
    assert "第一章剧情" in selection.message.content
    assert "当前章不应作为前文" not in selection.message.content
