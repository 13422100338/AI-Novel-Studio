from pathlib import Path

from ai_novel_studio.application.plot_memory_context_service import (
    PlotMemoryContextService,
)
from ai_novel_studio.application.project_guidance_service import ProjectGuidanceService
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SummaryLevel
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
    ProjectGuidanceRepository,
)
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
    chapters.create_chapter(volume.id, "第三章", "3", "第三章正文")
    chapters.create_chapter(volume.id, "第四章", "4", "第四章正文")
    chapters.create_chapter(volume.id, "第五章", "5", "第五章正文")
    target = chapters.create_chapter(volume.id, "第六章", "6", "第六章正文")
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
    assert tuple(item.content for item in selection.summaries) == (
        "第一章已确认剧情",
        "第二章尚未审查剧情",
    )


def test_plot_memory_excludes_current_and_later_chapters(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "第一章", "1", "第一章正文")
    chapters.create_chapter(volume.id, "第二章", "2", "第二章正文")
    chapters.create_chapter(volume.id, "第三章", "3", "第三章正文")
    chapters.create_chapter(volume.id, "第四章", "4", "第四章正文")
    target = chapters.create_chapter(volume.id, "第五章", "5", "第五章正文")
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


def test_plot_context_always_includes_full_project_guidance_before_memory(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    target = ChapterRepository(project).create_chapter(
        volume.id, "第一章", "1", "第一章正文"
    )
    guidance = ProjectGuidanceService(ProjectGuidanceRepository(project)).save_manual(
        "整部小说讨论责任与自由意志。叙事固定使用近距离第三人称。",
        expected_revision=0,
    )

    selection = PlotMemoryContextService(project).select(target.id, token_budget=1)

    assert selection.message is not None
    assert selection.message.role == "system"
    assert selection.message.content.startswith(
        f"【小说最高系统提示｜人工修订 {guidance.revision}】"
    )
    assert guidance.highest_system_prompt in selection.message.content
    assert selection.summaries == ()


def test_plot_context_includes_latest_three_full_chapters_in_book_order(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    previous = tuple(
        chapters.create_chapter(
            volume.id,
            f"第{index}章",
            str(index),
            f"正文标记-{index}",
        )
        for index in range(1, 5)
    )
    target = chapters.create_chapter(volume.id, "第5章", "5", "当前章标记")

    selection = PlotMemoryContextService(project).select(target.id, token_budget=1)

    assert selection.message is not None
    content = selection.message.content
    assert "正文标记-1" not in content
    assert "当前章标记" not in content
    assert all(f"正文标记-{index}" in content for index in (2, 3, 4))
    assert content.index("正文标记-2") < content.index("正文标记-3")
    assert content.index("正文标记-3") < content.index("正文标记-4")
    assert previous[0].title not in content


def test_summary_node_selection_has_an_independent_budget_from_shared_plot_context(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "第一章", "1", "第一章完整正文" * 100)
    chapters.create_chapter(volume.id, "第二章", "2", "第二章完整正文")
    chapters.create_chapter(volume.id, "第三章", "3", "第三章完整正文")
    chapters.create_chapter(volume.id, "第四章", "4", "第四章完整正文")
    target = chapters.create_chapter(volume.id, "第五章", "5")
    summary = SummaryRepository(project).add_human_summary(
        SummaryLevel.CHAPTER,
        first.id,
        "独立摘要预算标记",
        (first.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    ProjectGuidanceService(ProjectGuidanceRepository(project)).save_manual(
        "最高提示" * 100,
        expected_revision=0,
    )

    selected = PlotMemoryContextService(project).select_summary_nodes(
        target.id,
        token_budget=100,
    )

    assert selected == (summary,)


def test_automatic_summaries_do_not_repeat_the_latest_three_full_chapters(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "第一章", "1", "第一章完整正文")
    second = chapters.create_chapter(volume.id, "第二章", "2", "第二章完整正文")
    chapters.create_chapter(volume.id, "第三章", "3", "第三章完整正文")
    chapters.create_chapter(volume.id, "第四章", "4", "第四章完整正文")
    target = chapters.create_chapter(volume.id, "第五章", "5")
    summaries = SummaryRepository(project)
    older = summaries.add_human_summary(
        SummaryLevel.CHAPTER,
        first.id,
        "第一章较早摘要标记",
        (first.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    summaries.add_human_summary(
        SummaryLevel.CHAPTER,
        second.id,
        "第二章重复摘要标记",
        (second.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    service = PlotMemoryContextService(project)

    selection = service.select(target.id, token_budget=6_000)
    summary_nodes = service.select_summary_nodes(target.id, token_budget=6_000)

    assert selection.message is not None
    assert "第二章完整正文" in selection.message.content
    assert "第一章较早摘要标记" in selection.message.content
    assert "第二章重复摘要标记" not in selection.message.content
    assert selection.summaries == (older,)
    assert summary_nodes == (older,)
