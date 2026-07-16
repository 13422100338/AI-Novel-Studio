from pathlib import Path

from ai_novel_studio.application.character_status_service import CharacterStatusService
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

    CharacterStatusService(repository).save(
        chapters[0].id,
        character_id=character.id,
        name=character.canonical_name,
        motivation="Protect the town",
        psychology="Guarded",
        goal="Find the letter",
        relationships="Trusts Alice cautiously",
        recent="Returned to the old harbor",
    )

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

    assert snapshot.state is None
    assert {event.psychology for event in snapshot.conflicting_states} == {"冷静", "恐慌"}
