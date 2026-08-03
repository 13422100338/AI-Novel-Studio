"""Frontend Wave F12: read-only list views for page skeletons."""

from __future__ import annotations

from pathlib import Path

from ai_novel_studio.application.project_workspace_service import ProjectWorkspaceService
from ai_novel_studio.domain.memory import ReviewStatus, SourceType
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.models.readonly_list_models import (
    AuditListModel,
    CharacterJourneyListModel,
    CharacterListModel,
    MemoryListModel,
)
from ai_novel_studio.ui_qml.bridge.readonly_views import (
    AuditViewDto,
    CharacterJourneyViewDto,
    CharacterViewDto,
    MemoryViewDto,
    ReadonlyViews,
    readonly_views,
)

from .test_project_wiring import create_temp_project


def create_project_with_character(tmp_path: Path) -> tuple[Path, str]:
    """Create a project with one character and two state events (two chapters)."""
    root = create_temp_project(tmp_path / "novel")
    service = ProjectWorkspaceService()
    service.open_project(root)
    project = service.project
    chapters = ChapterRepository(project)
    volume = project.list_volumes()[0]
    chapters.create_chapter(volume.id, "第二章 钟声", "第 2 章")
    first_chapter = service.volume_tree()[0].chapters[0].id
    second_chapter = service.volume_tree()[0].chapters[1].id
    repository = CharacterMemoryRepository(project)
    character = repository.create_character("林默", ("林先生",), "调查员")
    repository.append_state(
        character.id,
        first_chapter,
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
        second_chapter,
        motivation="追踪寄信人",
        psychology="动摇",
        current_goal="进入钟楼",
        relationships="开始依赖同伴",
        recent_activity="识别暗号",
        confidence=0.8,
        source_type=SourceType.MODEL,
        review_status=ReviewStatus.APPROVED,
    )
    service.close_project()
    return root, character.id


def test_empty_project_views_are_empty(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    service = ProjectWorkspaceService()
    service.open_project(root)
    chapter_id = service.volume_tree()[0].chapters[0].id

    views = readonly_views(service.project, chapter_id)

    assert views.characters == ()
    assert views.memories == ()
    assert views.audits == ()
    service.close_project()


def test_views_are_frozen_dtos() -> None:
    views = ReadonlyViews(
        characters=(CharacterViewDto(id="c1", name="林默"),),
        memories=(
            MemoryViewDto(id="m1", category="设定", title="灯塔", revision=1),
        ),
        audits=(AuditViewDto(id="a1", category="一致性"),),
    )
    assert views.characters[0].name == "林默"
    assert views.memories[0].title == "灯塔"
    assert views.audits[0].category == "一致性"


def test_character_model_exposes_roles() -> None:
    model = CharacterListModel()
    model.set_items((CharacterViewDto(id="c1", name="林默", goal="查明真相"),))

    assert model.rowCount() == 1
    index = model.index(0)
    assert model.data(index, model.ROLE_ID) == "c1"
    assert model.data(index, model.ROLE_NAME) == "林默"
    assert model.data(index, model.ROLE_GOAL) == "查明真相"
    assert model.roleNames()[model.ROLE_NAME] == b"name"


def test_memory_model_exposes_roles() -> None:
    model = MemoryListModel()
    model.set_items(
        (MemoryViewDto(id="m1", category="设定", title="灯塔", revision=3),)
    )

    index = model.index(0)
    assert model.data(index, model.ROLE_TITLE) == "灯塔"
    assert model.data(index, model.ROLE_CATEGORY) == "设定"
    assert model.data(index, model.ROLE_REVISION) == 3
    assert model.roleNames()[model.ROLE_TITLE] == b"title"


def test_audit_model_exposes_roles() -> None:
    model = AuditListModel()
    model.set_items(
        (AuditViewDto(id="a1", category="一致性", severity="WARNING"),)
    )

    index = model.index(0)
    assert model.data(index, model.ROLE_CATEGORY) == "一致性"
    assert model.data(index, model.ROLE_SEVERITY) == "WARNING"
    assert model.roleNames()[model.ROLE_SEVERITY] == b"severity"


def test_facade_exposes_empty_lists_for_project(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))

    assert facade.property("characterViews").rowCount() == 0
    assert facade.property("memoryViews").rowCount() == 0
    assert facade.property("auditViews").rowCount() == 0


def test_facade_exposes_empty_lists_without_project() -> None:
    facade = MockNovelStudioFacade()
    assert facade.property("characterViews").rowCount() == 0
    assert facade.property("memoryViews").rowCount() == 0
    assert facade.property("auditViews").rowCount() == 0


def test_character_journey_model_roles() -> None:
    model = CharacterJourneyListModel()
    model.set_items(
        (
            CharacterJourneyViewDto(
                state_id="s1",
                chapter_id="c1",
                motivation="寻找失踪者",
                psychology="警惕",
                goal="检查来信",
                relationships="尚未信任同伴",
                recent_activity="返回旧港",
            ),
        )
    )

    assert model.rowCount() == 1
    index = model.index(0)
    assert model.data(index, model.ROLE_STATE_ID) == "s1"
    assert model.data(index, model.ROLE_CHAPTER_ID) == "c1"
    assert model.data(index, model.ROLE_MOTIVATION) == "寻找失踪者"
    assert model.data(index, model.ROLE_PSYCHOLOGY) == "警惕"
    assert model.data(index, model.ROLE_RECENT) == "返回旧港"
    assert model.roleNames()[model.ROLE_GOAL] == b"goal"


def test_readonly_views_carry_journey_history(tmp_path: Path) -> None:
    root, character_id = create_project_with_character(tmp_path)
    service = ProjectWorkspaceService()
    service.open_project(root)
    chapters = service.volume_tree()[0].chapters
    first_chapter = chapters[0].id
    second_chapter = chapters[1].id

    first_views = readonly_views(service.project, first_chapter)
    second_views = readonly_views(service.project, second_chapter)

    assert len(first_views.characters) == 1
    assert len(first_views.characters[0].journey) == 1
    assert len(second_views.characters[0].journey) == 2
    assert second_views.characters[0].id == character_id
    assert second_views.characters[0].name == "林默"
    assert second_views.characters[0].journey[-1].goal == "进入钟楼"
    service.close_project()


def test_facade_select_character_shows_detail_and_journey(tmp_path: Path) -> None:
    root, _ = create_project_with_character(tmp_path)
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    # Row 1 is the first chapter row (row 0 is the volume header).
    facade.selectChapter(1)

    facade.selectCharacter(0)

    assert facade.property("characterDetailVisible") is True
    assert facade.property("characterDetailName") == "林默"
    assert facade.property("characterDetailGoal") == "检查来信"
    assert facade.property("characterDetailMotivation") == "寻找失踪者"
    assert facade.property("characterJourney").rowCount() == 1

    facade.closeCharacterDetail()
    assert facade.property("characterDetailVisible") is False
    assert facade.property("characterJourney").rowCount() == 0


def test_facade_select_character_after_chapter_switch_updates_journey(
    tmp_path: Path,
) -> None:
    root, _ = create_project_with_character(tmp_path)
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    facade.selectChapter(1)
    facade.selectCharacter(0)
    assert facade.property("characterJourney").rowCount() == 1

    facade.selectChapter(2)
    facade.selectCharacter(0)

    assert facade.property("characterJourney").rowCount() == 2
    journey = facade.property("characterJourney")
    assert journey.data(journey.index(1), journey.ROLE_GOAL) == "进入钟楼"
