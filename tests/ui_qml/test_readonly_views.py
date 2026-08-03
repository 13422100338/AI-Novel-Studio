"""Frontend Wave F12: read-only list views for page skeletons."""

from __future__ import annotations

from pathlib import Path

from ai_novel_studio.application.project_workspace_service import ProjectWorkspaceService
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.models.readonly_list_models import (
    AuditListModel,
    CharacterListModel,
    MemoryListModel,
)
from ai_novel_studio.ui_qml.bridge.readonly_views import (
    AuditViewDto,
    CharacterViewDto,
    MemoryViewDto,
    ReadonlyViews,
    readonly_views,
)

from .test_project_wiring import create_temp_project


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

