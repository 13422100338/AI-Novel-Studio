import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.core.context.style_retriever import StyleRetriever
from ai_novel_studio.core.memory.canon_ledger import CanonLedger
from ai_novel_studio.core.memory.narrative_clue_ledger import NarrativeClueLedger
from ai_novel_studio.domain.memory import (
    Authority,
    ClueAction,
    ClueType,
    MemoryStatus,
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


def test_canon_review_candidates_are_current_time_bounded_and_body_free(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_chapters(tmp_path)
    repository = NarrativeMemoryRepository(project)
    global_review = repository.add_canon(
        "全局待审",
        "GLOBAL_REVIEW_CANON_SECRET",
        None,
        confidence=0.8,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
    )
    prior_review = repository.add_canon(
        "前章待审",
        "PRIOR_REVIEW_CANON_SECRET",
        chapters[0].id,
        confidence=0.8,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
    )
    repository.add_canon(
        "前章已批准",
        "APPROVED_CANON_DETAIL",
        chapters[0].id,
        confidence=1,
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    repository.add_canon(
        "前章已拒绝",
        "REJECTED_CANON_DETAIL",
        chapters[0].id,
        confidence=0.2,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REJECTED,
    )
    stale_review = repository.add_canon(
        "失效待审",
        "STALE_REVIEW_CANON_DETAIL",
        chapters[0].id,
        confidence=0.5,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
    )
    repository.add_canon(
        "当前章待审",
        "CURRENT_CHAPTER_REVIEW_CANON_DETAIL",
        chapters[1].id,
        confidence=0.5,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
    )
    repository.add_canon(
        "未来章待审",
        "FUTURE_REVIEW_CANON_DETAIL",
        chapters[2].id,
        confidence=0.5,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE canon_entries SET status = 'STALE' WHERE id = ?",
            (stale_review.id,),
        )

    candidates = repository.list_ineligible_canon_before(chapters[1].id, limit=100)

    assert tuple(item.id for item in candidates) == (
        global_review.id,
        prior_review.id,
    )
    assert tuple(item.status for item in candidates) == (
        MemoryStatus.CURRENT,
        MemoryStatus.CURRENT,
    )
    assert tuple(item.review_status for item in candidates) == (
        ReviewStatus.REVIEW,
        ReviewStatus.REVIEW,
    )
    assert tuple(item.source_hash for item in candidates) == (
        hashlib.sha256(
            "全局待审\0GLOBAL_REVIEW_CANON_SECRET".encode()
        ).hexdigest(),
        hashlib.sha256(
            "前章待审\0PRIOR_REVIEW_CANON_SECRET".encode()
        ).hexdigest(),
    )
    assert all(not hasattr(item, "title") for item in candidates)
    assert all(not hasattr(item, "detail") for item in candidates)
    with pytest.raises(ValueError, match="候选数量"):
        repository.list_ineligible_canon_before(chapters[1].id, limit=True)
    with pytest.raises(ValueError, match="候选数量"):
        repository.list_ineligible_canon_before(chapters[1].id, limit=101)


def test_canon_review_candidates_have_a_deterministic_global_cap(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_chapters(tmp_path)
    repository = NarrativeMemoryRepository(project)
    created = [
        repository.add_canon(
            f"候选-{index:03d}",
            f"REVIEW_CANON_DETAIL_{index:03d}",
            chapters[0].id,
            confidence=0.8,
            authority=Authority.MODEL_EXTRACTED,
            review_status=ReviewStatus.REVIEW,
        )
        for index in range(101)
    ]

    candidates = repository.list_ineligible_canon_before(chapters[1].id, limit=100)

    expected = sorted(created, key=lambda item: (item.created_at, item.id))[:100]
    assert tuple(item.id for item in candidates) == tuple(item.id for item in expected)
    assert len(candidates) == 100


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


def test_review_clue_events_are_time_bounded_body_free_and_audit_only(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_chapters(tmp_path)
    repository = NarrativeMemoryRepository(project)
    approved_clue = repository.add_clue(
        ClueType.FORESHADOW,
        "批准伏笔",
        "批准伏笔正文",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    locked_clue = repository.add_clue(
        ClueType.MISDIRECTION,
        "锁定伏笔",
        "锁定伏笔正文",
        Authority.USER_CONFIRMED,
        ReviewStatus.LOCKED,
    )
    review_clue = repository.add_clue(
        ClueType.FORESHADOW,
        "待审伏笔",
        "待审伏笔正文",
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REVIEW,
    )
    stale_clue = repository.add_clue(
        ClueType.FORESHADOW,
        "失效伏笔",
        "失效伏笔正文",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    allowed = repository.append_clue_action(
        approved_clue.id,
        chapters[0].id,
        ClueAction.PLANT,
        "已批准事件",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    first_review = repository.append_clue_action(
        approved_clue.id,
        chapters[0].id,
        ClueAction.RESOLVE,
        "FIRST_REVIEW_CLUE_EVENT_SECRET",
        SourceType.MODEL,
        ReviewStatus.REVIEW,
    )
    second_review = repository.append_clue_action(
        locked_clue.id,
        chapters[0].id,
        ClueAction.ABANDON,
        "SECOND_REVIEW_CLUE_EVENT_SECRET",
        SourceType.MODEL,
        ReviewStatus.REVIEW,
    )
    repository.append_clue_action(
        approved_clue.id,
        chapters[0].id,
        ClueAction.REINFORCE,
        "已拒绝事件",
        SourceType.MODEL,
        ReviewStatus.REJECTED,
    )
    repository.append_clue_action(
        review_clue.id,
        chapters[0].id,
        ClueAction.PLANT,
        "未批准父伏笔的事件",
        SourceType.MODEL,
        ReviewStatus.REVIEW,
    )
    repository.append_clue_action(
        stale_clue.id,
        chapters[0].id,
        ClueAction.PLANT,
        "非当前父伏笔的事件",
        SourceType.MODEL,
        ReviewStatus.REVIEW,
    )
    repository.append_clue_action(
        approved_clue.id,
        chapters[1].id,
        ClueAction.REINFORCE,
        "当前章事件",
        SourceType.MODEL,
        ReviewStatus.REVIEW,
    )
    repository.append_clue_action(
        approved_clue.id,
        chapters[2].id,
        ClueAction.REINFORCE,
        "未来章事件",
        SourceType.MODEL,
        ReviewStatus.REVIEW,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE narrative_clues SET status = 'STALE' WHERE id = ?",
            (stale_clue.id,),
        )

    candidates = repository.list_ineligible_clue_events_before(
        chapters[1].id,
        limit=100,
    )
    active = NarrativeClueLedger(repository).active_before(chapters[1].id)

    expected = sorted(
        (first_review, second_review),
        key=lambda event: (event.created_at, event.id),
    )
    assert tuple(item.id for item in candidates) == tuple(
        event.id for event in expected
    )
    assert tuple(item.clue_id for item in candidates) == tuple(
        event.clue_id for event in expected
    )
    assert tuple(item.source_chapter_id for item in candidates) == tuple(
        event.chapter_id for event in expected
    )
    assert tuple(item.review_status for item in candidates) == (
        ReviewStatus.REVIEW,
        ReviewStatus.REVIEW,
    )
    assert tuple(item.source_hash for item in candidates) == tuple(
        hashlib.sha256(
            f"{event.id}\x1f{event.action.value}\x1f{event.detail}".encode()
        ).hexdigest()
        for event in expected
    )
    assert all(not hasattr(item, "action") for item in candidates)
    assert all(not hasattr(item, "detail") for item in candidates)
    assert all(not hasattr(item, "source_type") for item in candidates)
    assert active[0].events == (allowed,)
    with pytest.raises(ValueError, match="伏笔事件候选数量"):
        repository.list_ineligible_clue_events_before(chapters[1].id, limit=True)
    with pytest.raises(ValueError, match="伏笔事件候选数量"):
        repository.list_ineligible_clue_events_before(chapters[1].id, limit=101)


def test_review_clue_event_candidates_have_a_deterministic_global_cap(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_chapters(tmp_path)
    repository = NarrativeMemoryRepository(project)
    clue = repository.add_clue(
        ClueType.FORESHADOW,
        "容量伏笔",
        "容量伏笔正文",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    created = [
        repository.append_clue_action(
            clue.id,
            chapters[0].id,
            ClueAction.REINFORCE,
            f"REVIEW_CLUE_EVENT_{index:03d}",
            SourceType.MODEL,
            ReviewStatus.REVIEW,
        )
        for index in range(101)
    ]

    candidates = repository.list_ineligible_clue_events_before(
        chapters[1].id,
        limit=100,
    )

    expected = sorted(created, key=lambda event: (event.created_at, event.id))[:100]
    assert tuple(item.id for item in candidates) == tuple(
        event.id for event in expected
    )
    assert len(candidates) == 100


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
    candidate_rule = repository.add_rule(
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
    assert compiled.ineligible_rules == ()
    assert compiled.rules[0].limit_per_book == 1

    audited = StyleRetriever(repository).for_task(
        project.project.id,
        "mystery",
        ("character-lan",),
        chapters[1].id,
        include_ineligible_rules=True,
    )

    assert audited.rules == compiled.rules
    assert audited.samples == compiled.samples
    assert audited.ineligible_rules == (candidate_rule,)
    assert audited.ineligible_samples == ()
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


def test_style_retriever_bounds_writer_samples_by_scope_precedence(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_chapters(tmp_path)
    repository = StyleRepository(project)
    character_a = "character-a"
    character_b = "character-b"

    repository.add_sample(
        StyleScope.BOOK,
        project.project.id,
        "book",
        "BOOK_SAMPLE",
        SourceType.HUMAN,
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
        immutable=False,
    )
    repository.add_sample(
        StyleScope.GENRE_OR_SCENE,
        "mystery",
        "scene",
        "SCENE_SAMPLE",
        SourceType.HUMAN,
        Authority.OUTLINE,
        ReviewStatus.LOCKED,
        immutable=True,
    )
    repository.add_sample(
        StyleScope.CHARACTER,
        character_a,
        "character-a",
        "CHARACTER_A_SAMPLE",
        SourceType.HUMAN,
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
        immutable=False,
    )
    repository.add_sample(
        StyleScope.CHARACTER,
        character_b,
        "character-b",
        "CHARACTER_B_SAMPLE",
        SourceType.HUMAN,
        Authority.OUTLINE,
        ReviewStatus.APPROVED,
        immutable=False,
    )
    repository.add_sample(
        StyleScope.CHAPTER,
        chapters[1].id,
        "chapter-outline",
        "CHAPTER_OUTLINE_SAMPLE",
        SourceType.HUMAN,
        Authority.OUTLINE,
        ReviewStatus.APPROVED,
        immutable=False,
    )
    repository.add_sample(
        StyleScope.CHAPTER,
        chapters[1].id,
        "chapter-locked",
        "CHAPTER_LOCKED_SAMPLE",
        SourceType.HUMAN,
        Authority.USER_CONFIRMED,
        ReviewStatus.LOCKED,
        immutable=True,
    )
    review = repository.add_sample(
        StyleScope.CHAPTER,
        chapters[1].id,
        "chapter-review",
        "CHAPTER_REVIEW_SAMPLE",
        SourceType.MODEL,
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REVIEW,
        immutable=False,
    )
    retriever = StyleRetriever(repository)
    character_ids = (character_b, character_a)

    default = retriever.for_task(
        project.project.id,
        "mystery",
        character_ids,
        chapters[1].id,
    )
    writer = retriever.for_task(
        project.project.id,
        "mystery",
        character_ids,
        chapters[1].id,
        writer_sample_selection=True,
    )
    scene_then_book = retriever.for_task(
        project.project.id,
        "mystery",
        (),
        chapters[2].id,
        writer_sample_selection=True,
    )

    expected_default = (
        *repository.samples(StyleScope.BOOK, project.project.id),
        *repository.samples(StyleScope.GENRE_OR_SCENE, "mystery"),
        *repository.samples(StyleScope.CHARACTER, character_b),
        *repository.samples(StyleScope.CHARACTER, character_a),
        *repository.samples(StyleScope.CHAPTER, chapters[1].id),
    )
    expected_writer = (
        *repository.samples(StyleScope.CHAPTER, chapters[1].id),
        *repository.samples(StyleScope.CHARACTER, character_b),
        *repository.samples(StyleScope.CHARACTER, character_a),
        *repository.samples(StyleScope.GENRE_OR_SCENE, "mystery"),
        *repository.samples(StyleScope.BOOK, project.project.id),
    )[:4]

    assert default.samples == expected_default
    assert writer.samples == expected_writer
    assert len(writer.samples) == 4
    assert review not in default.samples
    assert review not in writer.samples
    assert scene_then_book.samples == (
        *repository.samples(StyleScope.GENRE_OR_SCENE, "mystery"),
        *repository.samples(StyleScope.BOOK, project.project.id),
    )
    assert writer.rules == default.rules


def test_style_retriever_audits_metadata_only_ineligible_samples_on_opt_in(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_chapters(tmp_path)
    repository = StyleRepository(project)
    approved = repository.add_sample(
        StyleScope.BOOK,
        project.project.id,
        "已批准样章",
        "APPROVED_SAMPLE_BODY",
        SourceType.HUMAN,
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
        immutable=False,
    )
    review = repository.add_sample(
        StyleScope.BOOK,
        project.project.id,
        "待审样章",
        "REVIEW_SAMPLE_SECRET_BODY",
        SourceType.MODEL,
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REVIEW,
        immutable=False,
    )
    rejected = repository.add_sample(
        StyleScope.CHAPTER,
        chapters[1].id,
        "已拒绝样章",
        "REJECTED_SAMPLE_SECRET_BODY",
        SourceType.MODEL,
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REJECTED,
        immutable=False,
    )
    retriever = StyleRetriever(repository)

    default = retriever.for_task(project.project.id, None, (), chapters[1].id)
    audited = retriever.for_task(
        project.project.id,
        None,
        (),
        chapters[1].id,
        include_ineligible_samples=True,
    )

    assert default.samples == (approved,)
    assert default.ineligible_samples == ()
    assert audited.samples == default.samples
    assert tuple(item.id for item in audited.ineligible_samples) == (
        review.id,
        rejected.id,
    )
    assert tuple(item.review_status for item in audited.ineligible_samples) == (
        ReviewStatus.REVIEW,
        ReviewStatus.REJECTED,
    )
    assert tuple(item.content_hash for item in audited.ineligible_samples) == (
        review.content_hash,
        rejected.content_hash,
    )
    assert all(not hasattr(item, "content") for item in audited.ineligible_samples)


def test_style_retriever_bounds_ineligible_samples_across_scopes(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_chapters(tmp_path)
    repository = StyleRepository(project)
    book_samples = [
        repository.add_sample(
            StyleScope.BOOK,
            project.project.id,
            f"候选-{index:03d}",
            f"BOOK_REVIEW_SAMPLE_BODY_{index:03d}",
            SourceType.MODEL,
            Authority.MODEL_EXTRACTED,
            ReviewStatus.REVIEW,
            immutable=False,
        )
        for index in range(12)
    ]
    chapter_samples = [
        repository.add_sample(
            StyleScope.CHAPTER,
            chapters[1].id,
            f"候选-{index:03d}",
            f"CHAPTER_REJECTED_SAMPLE_BODY_{index:03d}",
            SourceType.MODEL,
            Authority.MODEL_EXTRACTED,
            ReviewStatus.REJECTED,
            immutable=False,
        )
        for index in range(12)
    ]

    compiled = StyleRetriever(repository).for_task(
        project.project.id,
        None,
        (),
        chapters[1].id,
        include_ineligible_samples=True,
    )

    expected_ids = tuple(
        sample.id
        for sample in (
            *sorted(book_samples, key=lambda item: item.id),
            *sorted(chapter_samples, key=lambda item: item.id)[:8],
        )
    )
    assert tuple(item.id for item in compiled.ineligible_samples) == expected_ids
    assert len(compiled.ineligible_samples) == 20


def test_style_retriever_bounds_ineligible_rules_across_scopes(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_chapters(tmp_path)
    repository = StyleRepository(project)
    for index in range(120):
        scope_type, scope_id = (
            (StyleScope.BOOK, project.project.id)
            if index < 60
            else (StyleScope.CHAPTER, chapters[1].id)
        )
        repository.add_rule(
            scope_type,
            scope_id,
            f"候选-{index:03d}",
            f"未批准文风规则-{index:03d}",
            Authority.MODEL_EXTRACTED,
            ReviewStatus.REVIEW,
        )

    compiled = StyleRetriever(repository).for_task(
        project.project.id,
        None,
        (),
        chapters[1].id,
        include_ineligible_rules=True,
    )

    assert compiled.rules == ()
    assert compiled.samples == ()
    assert len(compiled.ineligible_rules) == 100
