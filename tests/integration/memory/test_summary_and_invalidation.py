import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.core.memory.summary_tree import SummaryTree
from ai_novel_studio.domain.memory import (
    Authority,
    MemoryStatus,
    ReviewStatus,
    SourceType,
    SummaryLevel,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    ProtectedMemoryError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import (
    StaleSummaryWriteError,
    SummaryRepository,
)


def _project_with_chapters(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "摘要测试")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    return project, chapters, tuple(
        chapters.create_chapter(volume.id, f"第 {index} 章", str(index), f"正文 {index}")
        for index in range(1, 4)
    )


def test_summary_levels_keep_source_revision_hash_and_require_explicit_promotion(
    tmp_path: Path,
) -> None:
    project, _, chapters = _project_with_chapters(tmp_path)
    repository = SummaryRepository(project)
    created = tuple(
        repository.add_candidate(
            level,
            scope_id,
            f"{level.value} 摘要",
            source_chapter_ids,
            model_profile_id="relay/model",
        )
        for level, scope_id, source_chapter_ids in (
            (SummaryLevel.CHAPTER, chapters[0].id, (chapters[0].id,)),
            (SummaryLevel.ARC, "arc-1", (chapters[0].id, chapters[1].id)),
            (SummaryLevel.VOLUME, chapters[0].volume_id, (chapters[0].id, chapters[1].id)),
            (
                SummaryLevel.BOOK,
                project.project.id,
                (chapters[0].id, chapters[1].id),
            ),
        )
    )

    assert {summary.level for summary in created} == {
        SummaryLevel.CHAPTER,
        SummaryLevel.ARC,
        SummaryLevel.VOLUME,
        SummaryLevel.BOOK,
    }
    assert all(summary.review_status == ReviewStatus.REVIEW for summary in created)
    expected_hash = hashlib.sha256("正文 1".encode()).hexdigest()
    assert created[0].source_revisions[0][1:] == (0, expected_hash)
    promoted = repository.promote(created[0].id, expected_revision=0)
    assert promoted.review_status == ReviewStatus.APPROVED
    assert promoted.status == MemoryStatus.CURRENT
    assert promoted.revision == 1
    with pytest.raises(StaleSummaryWriteError, match="修订"):
        repository.promote(created[0].id, expected_revision=0)


def test_story_change_marks_all_dependent_summaries_stale_and_preserves_text(
    tmp_path: Path,
) -> None:
    project, chapters_repository, chapters = _project_with_chapters(tmp_path)
    summaries = SummaryRepository(project)
    chapter_summary = summaries.promote(
        summaries.add_candidate(
            SummaryLevel.CHAPTER,
            chapters[0].id,
            "第一章旧摘要",
            (chapters[0].id,),
            model_profile_id="relay/model",
        ).id,
        expected_revision=0,
    )
    volume_summary = summaries.promote(
        summaries.add_candidate(
            SummaryLevel.VOLUME,
            chapters[0].volume_id,
            "第一卷旧摘要",
            (chapters[0].id, chapters[1].id),
            model_profile_id="relay/model",
        ).id,
        expected_revision=0,
    )

    chapters_repository.save_content(
        chapters[0].id,
        "剧情发生实质变化",
        source="manual",
        reason="story rewrite",
    )

    stale_chapter = summaries.get(chapter_summary.id)
    stale_volume = summaries.get(volume_summary.id)
    assert stale_chapter.status == MemoryStatus.STALE
    assert stale_volume.status == MemoryStatus.STALE
    assert stale_chapter.content == "第一章旧摘要"
    selection = SummaryTree(summaries).best_available(
        SummaryLevel.CHAPTER, chapters[0].id, chapters[1].id
    )
    assert selection.current is None
    assert selection.stale == (stale_chapter,)


def test_typo_save_can_explicitly_skip_memory_rebuild(tmp_path: Path) -> None:
    project, chapters_repository, chapters = _project_with_chapters(tmp_path)
    summaries = SummaryRepository(project)
    summary = summaries.promote(
        summaries.add_candidate(
            SummaryLevel.CHAPTER,
            chapters[0].id,
            "仍然有效的摘要",
            (chapters[0].id,),
            model_profile_id="relay/model",
        ).id,
        expected_revision=0,
    )

    chapters_repository.save_content(
        chapters[0].id,
        "正文 1。",
        source="manual",
        reason="punctuation",
        invalidate_memory=False,
    )

    assert summaries.get(summary.id).status == MemoryStatus.CURRENT


def test_locked_human_summary_cannot_be_overwritten_by_model(tmp_path: Path) -> None:
    project, _, chapters = _project_with_chapters(tmp_path)
    summaries = SummaryRepository(project)
    summary = summaries.add_human_summary(
        SummaryLevel.CHAPTER,
        chapters[0].id,
        "作者确认摘要",
        (chapters[0].id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.LOCKED,
    )

    with pytest.raises(ProtectedMemoryError, match="锁定"):
        summaries.update_content(
            summary.id,
            "模型试图覆盖",
            SourceType.MODEL,
            expected_revision=summary.revision,
        )
