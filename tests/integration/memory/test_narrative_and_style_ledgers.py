from pathlib import Path

import pytest

from ai_novel_studio.core.context.style_retriever import StyleRetriever
from ai_novel_studio.core.memory.canon_ledger import CanonLedger
from ai_novel_studio.core.memory.narrative_clue_ledger import NarrativeClueLedger
from ai_novel_studio.domain.memory import (
    Authority,
    ClueAction,
    ClueType,
    ReviewStatus,
    SourceType,
    StyleScope,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
    ProtectedMemoryError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository


def _project_with_chapters(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "账本测试")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    return project, tuple(
        chapters.create_chapter(volume.id, f"第 {index} 章", str(index))
        for index in range(1, 5)
    )


def test_canon_ledger_prefers_authority_and_reports_equal_authority_conflict(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_chapters(tmp_path)
    repository = NarrativeMemoryRepository(project)
    repository.add_canon(
        "钟楼状态",
        "钟楼已经废弃",
        chapters[0].id,
        confidence=0.6,
        authority=Authority.INFERRED,
        review_status=ReviewStatus.APPROVED,
    )
    confirmed = repository.add_canon(
        "钟楼状态",
        "钟楼十二年前停止公开使用",
        chapters[0].id,
        confidence=1,
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.LOCKED,
    )
    resolution = CanonLedger(repository).resolve("钟楼状态", chapters[1].id)

    assert resolution.entry == confirmed
    assert resolution.conflicts == ()

    repository.add_canon(
        "钟楼状态",
        "钟楼十年前停止使用",
        chapters[0].id,
        confidence=1,
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    conflict = CanonLedger(repository).resolve("钟楼状态", chapters[1].id)
    assert conflict.entry is None
    assert len(conflict.conflicts) == 2


def test_typed_clue_history_is_time_bounded_and_locked_misdirection_is_protected(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_chapters(tmp_path)
    repository = NarrativeMemoryRepository(project)
    clue = repository.add_clue(
        ClueType.MISDIRECTION,
        "错误的寄信人",
        "让读者暂时怀疑旧港管理员。",
        Authority.USER_CONFIRMED,
        ReviewStatus.LOCKED,
    )
    repository.append_clue_action(
        clue.id,
        chapters[0].id,
        ClueAction.PLANT,
        "管理员出现在门外",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    repository.append_clue_action(
        clue.id,
        chapters[1].id,
        ClueAction.REINFORCE,
        "管理员隐瞒行踪",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    repository.append_clue_action(
        clue.id,
        chapters[2].id,
        ClueAction.RESOLVE,
        "证实管理员并非寄信人",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )

    active = NarrativeClueLedger(repository).active_before(chapters[2].id)
    after_resolution = NarrativeClueLedger(repository).active_before(chapters[3].id)

    assert active[0].clue.clue_type == ClueType.MISDIRECTION
    assert [event.action for event in active[0].events] == [
        ClueAction.PLANT,
        ClueAction.REINFORCE,
    ]
    assert after_resolution == ()
    with pytest.raises(ProtectedMemoryError, match="锁定"):
        repository.update_clue_detail(clue.id, "直接改成真凶", SourceType.MODEL)


def test_style_retriever_compiles_layers_and_keeps_human_samples_immutable(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_chapters(tmp_path)
    repository = StyleRepository(project)
    book_rule = repository.add_rule(
        StyleScope.BOOK,
        project.project.id,
        "声音",
        "克制的近距离第三人称",
        Authority.USER_CONFIRMED,
        ReviewStatus.LOCKED,
        limit_per_book=1,
    )
    scene_rule = repository.add_rule(
        StyleScope.GENRE_OR_SCENE,
        "mystery",
        "悬疑场景",
        "证据先于解释出现",
        Authority.OUTLINE,
        ReviewStatus.APPROVED,
    )
    character_rule = repository.add_rule(
        StyleScope.CHARACTER,
        "character-lan",
        "人物声音",
        "林岚避免直接承认恐惧",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    chapter_rule = repository.add_rule(
        StyleScope.CHAPTER,
        chapters[1].id,
        "本章覆盖",
        "结尾停在未拆开的第二封信",
        Authority.OUTLINE,
        ReviewStatus.APPROVED,
    )
    repository.add_rule(
        StyleScope.BOOK,
        project.project.id,
        "候选",
        "尚未确认的模型建议",
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REVIEW,
    )
    sample = repository.add_sample(
        StyleScope.BOOK,
        project.project.id,
        "人工样章",
        "潮声在窗外停了一瞬。",
        SourceType.HUMAN,
        Authority.USER_CONFIRMED,
        ReviewStatus.LOCKED,
        immutable=True,
    )

    compiled = StyleRetriever(repository).for_task(
        project.project.id,
        "mystery",
        ("character-lan",),
        chapters[1].id,
    )

    assert compiled.rules == (book_rule, scene_rule, character_rule, chapter_rule)
    assert compiled.samples == (sample,)
    assert compiled.rules[0].limit_per_book == 1
    with pytest.raises(ProtectedMemoryError, match="不可修改"):
        repository.update_sample(sample.id, "被模型改写", SourceType.MODEL)
    with pytest.raises(ValueError, match="次数"):
        repository.add_rule(
            StyleScope.BOOK,
            project.project.id,
            "错误限制",
            "无效",
            Authority.USER_CONFIRMED,
            ReviewStatus.APPROVED,
            limit_per_chapter=-1,
        )

