import hashlib
from inspect import signature
from pathlib import Path

import pytest

from ai_novel_studio.application.character_card_context_service import (
    CharacterCardContextService,
)
from ai_novel_studio.application.character_status_service import (
    CharacterStatusCard,
    CharacterStatusRecord,
    CharacterStatusService,
)
from ai_novel_studio.application.generation_memory_context_provider import (
    GenerationMemoryContextProvider,
)
from ai_novel_studio.core.memory.character_timeline import CharacterTimeline
from ai_novel_studio.domain.memory import (
    Authority,
    KnowledgeState,
    KnowledgeSubject,
    ReviewStatus,
    SourceType,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
    MemoryConflictError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _project_with_three_chapters(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "时间线测试")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    return project, tuple(
        chapters.create_chapter(volume.id, f"第 {index} 章", str(index))
        for index in range(1, 4)
    )


def test_character_state_is_append_only_and_excludes_current_future_events(tmp_path: Path) -> None:
    project, chapters = _project_with_three_chapters(tmp_path)
    repository = CharacterMemoryRepository(project)
    character = repository.create_character("林岚", ("阿岚",), "调查员")
    repository.append_state(
        character.id,
        chapters[0].id,
        motivation="寻找失踪者",
        psychology="警惕",
        current_goal="检查来信",
        relationships="尚未信任同伴",
        recent_activity="返回旧港",
        confidence=1,
        source_type=SourceType.HUMAN,
        review_status=ReviewStatus.APPROVED,
    )
    repository.append_state(
        character.id,
        chapters[1].id,
        motivation="追踪寄信人",
        psychology="动摇",
        current_goal="进入钟楼",
        relationships="开始依赖同伴",
        recent_activity="识别暗号",
        confidence=0.8,
        source_type=SourceType.MODEL,
        review_status=ReviewStatus.REVIEW,
    )
    repository.append_state(
        character.id,
        chapters[2].id,
        motivation="揭开骗局",
        psychology="愤怒",
        current_goal="质问寄信人",
        relationships="与同伴决裂",
        recent_activity="发现伪证",
        confidence=1,
        source_type=SourceType.HUMAN,
        review_status=ReviewStatus.APPROVED,
    )

    before_second = repository.state_before(character.id, chapters[1].id)
    before_third = repository.state_before(character.id, chapters[2].id)

    assert before_second is not None
    assert before_second.current_goal == "检查来信"
    assert before_third is not None
    assert before_third.current_goal == "检查来信"
    assert len(repository.state_history(character.id)) == 3
    assert repository.get_character(character.id).aliases == ("阿岚",)


def test_physical_state_round_trips_through_existing_derived_snapshot(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_three_chapters(tmp_path)
    repository = CharacterMemoryRepository(project)
    character = repository.create_character("Lin Yu")
    stored = repository.append_state(
        character.id,
        chapters[0].id,
        motivation="Find the truth",
        psychology="Guarded",
        current_goal="Reach the archive",
        relationships="Distrusts the guide",
        recent_activity="Crossed the old harbor",
        location="Clock tower",
        injury_status="Sprained left ankle",
        confidence=1,
        source_type=SourceType.HUMAN,
        review_status=ReviewStatus.APPROVED,
    )

    history = repository.state_history(character.id)
    snapshot = CharacterTimeline(repository).snapshot(
        (character.id,),
        chapters[1].id,
    )[0]

    assert stored.location == "Clock tower"
    assert stored.injury_status == "Sprained left ankle"
    assert history[0].location == "Clock tower"
    assert history[0].injury_status == "Sprained left ankle"
    assert snapshot.state is not None
    assert snapshot.state.location == "Clock tower"
    assert snapshot.state.injury_status == "Sprained left ankle"


def test_character_status_projects_trusted_physical_state_and_empty_defaults(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_three_chapters(tmp_path)
    repository = CharacterMemoryRepository(project)
    selected = repository.create_character("Eric")
    without_state = repository.create_character("Mara")
    repository.append_state(
        selected.id,
        chapters[0].id,
        motivation="Protect the town",
        psychology="Guarded",
        current_goal="Reach the archive",
        relationships="Distrusts Mara",
        recent_activity="Crossed the old harbor",
        location="Clock tower",
        injury_status="Sprained left ankle",
        confidence=1,
        source_type=SourceType.HUMAN,
        review_status=ReviewStatus.APPROVED,
    )
    repository.append_state(
        selected.id,
        chapters[0].id,
        motivation="REVIEW SECRET",
        psychology="REVIEW SECRET",
        current_goal="REVIEW SECRET",
        relationships="REVIEW SECRET",
        recent_activity="REVIEW SECRET",
        location="REVIEW LOCATION SECRET",
        injury_status="REVIEW INJURY SECRET",
        confidence=0.8,
        source_type=SourceType.MODEL,
        review_status=ReviewStatus.REVIEW,
    )
    repository.append_state(
        selected.id,
        chapters[2].id,
        motivation="FUTURE SECRET",
        psychology="FUTURE SECRET",
        current_goal="FUTURE SECRET",
        relationships="FUTURE SECRET",
        recent_activity="FUTURE SECRET",
        location="FUTURE LOCATION SECRET",
        injury_status="FUTURE INJURY SECRET",
        confidence=1,
        source_type=SourceType.HUMAN,
        review_status=ReviewStatus.APPROVED,
    )

    service = CharacterStatusService(repository)
    records = {item.id: item for item in service.list_for_chapter(chapters[1].id)}
    cards = {
        item.id: item for item in service.list_cards_for_chapter(chapters[1].id)
    }

    assert records[selected.id].location == "Clock tower"
    assert records[selected.id].injury_status == "Sprained left ankle"
    assert cards[selected.id].location == "Clock tower"
    assert cards[selected.id].injury_status == "Sprained left ankle"
    assert records[without_state.id].location == ""
    assert records[without_state.id].injury_status == ""
    assert cards[without_state.id].location == ""
    assert cards[without_state.id].injury_status == ""


def test_physical_state_does_not_change_character_card_or_writer_content(
    tmp_path: Path,
) -> None:
    def build_projection(
        root: Path,
        *,
        location: str,
        injury_status: str,
    ) -> tuple[CharacterStatusCard, str, str, str, str]:
        project = ProjectRepository.create(root, "Novel")
        volume = project.list_volumes()[0]
        chapters = ChapterRepository(project)
        previous = chapters.create_chapter(volume.id, "Opening", "1")
        target = chapters.create_chapter(volume.id, "Visit", "2")
        repository = CharacterMemoryRepository(project)
        character = repository.create_character("Eric")
        repository.append_state(
            character.id,
            previous.id,
            motivation="Protect the town",
            psychology="Guarded",
            current_goal="Reach the archive",
            relationships="Distrusts Mara",
            recent_activity="Crossed the old harbor",
            location=location,
            injury_status=injury_status,
            confidence=1,
            source_type=SourceType.HUMAN,
            review_status=ReviewStatus.APPROVED,
        )
        card = CharacterStatusService(repository).list_cards_for_chapter(target.id)[0]
        item = CharacterCardContextService(project).items_before(target.id)[0]
        writer_block = next(
            block
            for block in GenerationMemoryContextProvider(project).blocks(
                target.id,
                "Eric visits Mara.",
                (),
            )
            if block.id == f"character-card-{character.id}"
        )
        return (
            card,
            item.content,
            item.content_hash,
            writer_block.content,
            writer_block.source_hash,
        )

    first = build_projection(
        tmp_path / "first",
        location="Clock tower",
        injury_status="Sprained left ankle",
    )
    second = build_projection(
        tmp_path / "second",
        location="Old harbor",
        injury_status="Bandaged right hand",
    )

    assert first[0].location == "Clock tower"
    assert first[0].injury_status == "Sprained left ankle"
    assert second[0].location == "Old harbor"
    assert second[0].injury_status == "Bandaged right hand"
    assert first[1:] == second[1:]
    for marker in (
        "Clock tower",
        "Sprained left ankle",
        "Old harbor",
        "Bandaged right hand",
    ):
        assert marker not in first[1]
        assert marker not in first[3]
        assert marker not in second[1]
        assert marker not in second[3]


def test_physical_state_projection_preserves_old_dto_and_save_contracts() -> None:
    record = CharacterStatusRecord(
        "character-1",
        "Eric",
        "Investigator",
        "Protect the town",
        "Guarded",
        "Reach the archive",
        "Distrusts Mara",
        "Crossed the old harbor",
    )
    card = CharacterStatusCard(
        "character-1",
        "Eric",
        ("the investigator",),
        "Investigator",
        "Protect the town",
        "Guarded",
        "Reach the archive",
        "Distrusts Mara",
        "Crossed the old harbor",
        (),
    )

    assert record.location == ""
    assert record.injury_status == ""
    assert card.location == ""
    assert card.injury_status == ""
    assert "location" not in signature(CharacterStatusService.save).parameters
    assert "injury_status" not in signature(CharacterStatusService.save).parameters


def test_character_states_can_be_loaded_in_one_batch(tmp_path: Path) -> None:
    project, chapters = _project_with_three_chapters(tmp_path)
    repository = CharacterMemoryRepository(project)
    first = repository.create_character("林岚")
    second = repository.create_character("苏澄")
    for character, goal in ((first, "检查来信"), (second, "守住码头")):
        repository.append_state(
            character.id,
            chapters[0].id,
            motivation="推进调查",
            psychology="警惕",
            current_goal=goal,
            relationships="仍在观察",
            recent_activity="返回旧港",
            confidence=1,
            source_type=SourceType.HUMAN,
            review_status=ReviewStatus.APPROVED,
        )

    states = repository.state_candidates_before_many(
        (first.id, second.id), chapters[1].id
    )

    assert states[first.id][0].current_goal == "检查来信"
    assert states[second.id][0].current_goal == "守住码头"
    histories = repository.state_histories((first.id, second.id))
    assert histories[first.id][0].current_goal == "检查来信"
    assert histories[second.id][0].current_goal == "守住码头"


def test_review_state_candidates_are_all_time_bounded_body_free_and_hashed(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_three_chapters(tmp_path)
    repository = CharacterMemoryRepository(project)
    first = repository.create_character("林岚")
    second = repository.create_character("苏澄")

    def append(  # type: ignore[no-untyped-def]
        character_id: str,
        chapter_id: str,
        marker: str,
        review_status: ReviewStatus,
    ):
        return repository.append_state(
            character_id,
            chapter_id,
            motivation=f"{marker}-MOTIVATION",
            psychology=f"{marker}-PSYCHOLOGY",
            current_goal=f"{marker}-GOAL",
            relationships=f"{marker}-RELATIONSHIPS",
            recent_activity=f"{marker}-RECENT",
            confidence=0.8,
            source_type=SourceType.MODEL,
            review_status=review_status,
        )

    included = (
        append(first.id, chapters[0].id, "FIRST-REVIEW-ONE", ReviewStatus.REVIEW),
        append(first.id, chapters[0].id, "FIRST-REVIEW-TWO", ReviewStatus.REVIEW),
        append(second.id, chapters[0].id, "SECOND-REVIEW", ReviewStatus.REVIEW),
    )
    append(first.id, chapters[0].id, "APPROVED", ReviewStatus.APPROVED)
    append(first.id, chapters[0].id, "LOCKED", ReviewStatus.LOCKED)
    append(first.id, chapters[0].id, "REJECTED", ReviewStatus.REJECTED)
    append(first.id, chapters[1].id, "CURRENT-REVIEW", ReviewStatus.REVIEW)
    append(first.id, chapters[2].id, "FUTURE-REVIEW", ReviewStatus.REVIEW)

    candidates = repository.list_ineligible_state_events_before(
        chapters[1].id,
        limit=100,
    )

    expected = sorted(
        included,
        key=lambda item: (item.character_id, item.created_at, item.id),
    )
    assert tuple(item.id for item in candidates) == tuple(item.id for item in expected)
    assert all(item.review_status == ReviewStatus.REVIEW for item in candidates)
    assert tuple(item.source_hash for item in candidates) == tuple(
        hashlib.sha256(
            "\x1f".join(
                (
                    item.motivation,
                    item.psychology,
                    item.current_goal,
                    item.relationships,
                    item.recent_activity,
                )
            ).encode()
        ).hexdigest()
        for item in expected
    )
    assert all(not hasattr(item, "motivation") for item in candidates)
    assert all(not hasattr(item, "psychology") for item in candidates)
    assert all(not hasattr(item, "current_goal") for item in candidates)
    with pytest.raises(ValueError, match="候选数量"):
        repository.list_ineligible_state_events_before(chapters[1].id, limit=True)
    with pytest.raises(ValueError, match="候选数量"):
        repository.list_ineligible_state_events_before(chapters[1].id, limit=101)


def test_review_state_candidates_have_a_deterministic_global_cap(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_three_chapters(tmp_path)
    repository = CharacterMemoryRepository(project)
    character = repository.create_character("林岚")
    created = [
        repository.append_state(
            character.id,
            chapters[0].id,
            motivation=f"MOTIVATION-{index:03d}",
            psychology=f"PSYCHOLOGY-{index:03d}",
            current_goal=f"GOAL-{index:03d}",
            relationships=f"RELATIONSHIPS-{index:03d}",
            recent_activity=f"RECENT-{index:03d}",
            confidence=0.8,
            source_type=SourceType.MODEL,
            review_status=ReviewStatus.REVIEW,
        )
        for index in range(101)
    ]

    candidates = repository.list_ineligible_state_events_before(
        chapters[1].id,
        limit=100,
    )

    expected = sorted(created, key=lambda item: (item.created_at, item.id))[:100]
    assert tuple(item.id for item in candidates) == tuple(item.id for item in expected)
    assert len(candidates) == 100


def test_character_status_cards_aggregate_reviewed_history_without_future_leak(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_three_chapters(tmp_path)
    repository = CharacterMemoryRepository(project)
    character = repository.create_character(
        "Eric Windermere",
        ("Eric", "the protagonist"),
        "A restrained investigator.",
    )
    for chapter, goal, psychology, review_status in (
        (chapters[0], "Find the letter", "Guarded", ReviewStatus.APPROVED),
        (chapters[1], "Enter the tower", "Shaken", ReviewStatus.LOCKED),
        (chapters[1], "Ignore the warning", "Uncertain", ReviewStatus.REVIEW),
        (chapters[2], "Confront the sender", "Angry", ReviewStatus.APPROVED),
    ):
        repository.append_state(
            character.id,
            chapter.id,
            motivation="Protect the town",
            psychology=psychology,
            current_goal=goal,
            relationships="Trusts Alice cautiously",
            recent_activity=f"Activity for {goal}",
            confidence=1,
            source_type=SourceType.HUMAN,
            review_status=review_status,
        )

    cards = CharacterStatusService(repository).list_cards_for_chapter(chapters[2].id)

    assert len(cards) == 1
    card = cards[0]
    assert card.id == character.id
    assert card.aliases == ("Eric", "the protagonist")
    assert card.profile == "A restrained investigator."
    assert card.goal == "Enter the tower"
    assert card.psychology == "Shaken"
    assert [entry.goal for entry in card.journey] == [
        "Find the letter",
        "Enter the tower",
    ]
    assert [entry.chapter_id for entry in card.journey] == [
        chapters[0].id,
        chapters[1].id,
    ]


def test_character_status_save_without_profile_preserves_existing_profile(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_three_chapters(tmp_path)
    repository = CharacterMemoryRepository(project)
    character = repository.create_character(
        "Eric Windermere",
        profile="Restrained voice and deliberate movements.",
    )

    saved = CharacterStatusService(repository).save(
        chapters[0].id,
        character_id=character.id,
        name=character.canonical_name,
        motivation="Protect the town",
        psychology="Guarded",
        goal="Find the letter",
        relationships="Trusts Alice cautiously",
        recent="Returned to the old harbor",
    )

    assert saved.location == ""
    assert saved.injury_status == ""
    assert repository.get_character(character.id).profile == (
        "Restrained voice and deliberate movements."
    )


def test_deleted_chapter_states_are_preserved_but_excluded_from_runtime_views(
    tmp_path: Path,
) -> None:
    project, chapters = _project_with_three_chapters(tmp_path)
    chapter_repository = ChapterRepository(project)
    repository = CharacterMemoryRepository(project)
    character = repository.create_character("林岚")
    for chapter, goal in (
        (chapters[0], "检查来信"),
        (chapters[1], "进入钟楼"),
    ):
        repository.append_state(
            character.id,
            chapter.id,
            motivation="推进调查",
            psychology="警惕",
            current_goal=goal,
            relationships="仍在观察",
            recent_activity="返回旧港",
            confidence=1,
            source_type=SourceType.HUMAN,
            review_status=ReviewStatus.APPROVED,
        )

    chapter_repository.delete_chapter(chapters[1].id)

    current = repository.state_before(character.id, chapters[2].id)
    batched = repository.state_candidates_before_many(
        (character.id,), chapters[2].id
    )
    history = repository.state_history(character.id)
    histories = repository.state_histories((character.id,))
    with project.database.connect() as connection:
        stored_count = connection.execute(
            "SELECT COUNT(*) FROM character_state_events WHERE character_id = ?",
            (character.id,),
        ).fetchone()[0]

    assert current is not None
    assert current.current_goal == "检查来信"
    assert batched[character.id][0].current_goal == "检查来信"
    assert [item.current_goal for item in history] == ["检查来信"]
    assert [item.current_goal for item in histories[character.id]] == ["检查来信"]
    assert stored_count == 2


def test_character_and_reader_knowledge_are_separate_and_time_bounded(tmp_path: Path) -> None:
    project, chapters = _project_with_three_chapters(tmp_path)
    repository = CharacterMemoryRepository(project)
    character = repository.create_character("林岚")
    item = repository.create_knowledge_item(
        "暗号属于兄长",
        "林岚童年见过该暗号。",
        Authority.USER_CONFIRMED,
        ReviewStatus.LOCKED,
    )
    repository.append_knowledge_event(
        item.id,
        KnowledgeSubject.CHARACTER,
        character.id,
        chapters[0].id,
        KnowledgeState.KNOWN,
        "第一章识别暗号",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    repository.append_knowledge_event(
        item.id,
        KnowledgeSubject.READER,
        project.project.id,
        chapters[0].id,
        KnowledgeState.SUSPECTED,
        "读者看到投信背影",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    repository.append_knowledge_event(
        item.id,
        KnowledgeSubject.CHARACTER,
        character.id,
        chapters[2].id,
        KnowledgeState.FORGOTTEN,
        "第三章受伤后失忆",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )

    character_view = repository.knowledge_before(
        KnowledgeSubject.CHARACTER, character.id, chapters[2].id
    )
    reader_view = repository.knowledge_before(
        KnowledgeSubject.READER, project.project.id, chapters[2].id
    )

    assert [(entry.item.title, entry.event.state) for entry in character_view] == [
        ("暗号属于兄长", KnowledgeState.KNOWN)
    ]
    assert reader_view[0].event.state == KnowledgeState.SUSPECTED


def test_timeline_reports_same_boundary_conflicts_instead_of_guessing(tmp_path: Path) -> None:
    project, chapters = _project_with_three_chapters(tmp_path)
    repository = CharacterMemoryRepository(project)
    character = repository.create_character("林岚")
    for psychology in ("冷静", "恐慌"):
        repository.append_state(
            character.id,
            chapters[0].id,
            motivation="调查",
            psychology=psychology,
            current_goal="进入钟楼",
            relationships="未知",
            recent_activity="收到信",
            confidence=1,
            source_type=SourceType.HUMAN,
            review_status=ReviewStatus.APPROVED,
        )

    snapshot = CharacterTimeline(repository).snapshot((character.id,), chapters[1].id)[0]

    with pytest.raises(MemoryConflictError):
        CharacterStatusService(repository).list_cards_for_chapter(chapters[1].id)
    assert snapshot.state is None
    assert {event.psychology for event in snapshot.conflicting_states} == {"冷静", "恐慌"}
