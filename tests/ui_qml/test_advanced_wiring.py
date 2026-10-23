"""QP-3A: advanced-page wiring through the facade's read-only projections.

Covers: empty entry (no project), fresh project (no clues), chapter-boundary
filtering of the clue ledger, and the plan panel reflecting the requirement.
The facade only reaches storage through the two application services; the
services themselves are pure readers (covered by their unit tests).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("ai_novel_studio.application")

from ai_novel_studio.domain.memory import (
    Authority,
    ClueAction,
    ClueType,
    ReviewStatus,
    SourceType,
)
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import (
    MockNovelStudioFacade,
)

from .test_project_wiring import create_temp_project


def _seed_clue(root: Path, chapter_id: str, *, tag: str) -> None:
    from ai_novel_studio.infrastructure.storage.project_repository import (
        ProjectRepository,
    )

    project = ProjectRepository.open(root)
    memory = NarrativeMemoryRepository(project)
    clue = memory.add_clue(
        ClueType.FORESHADOW,
        f"铜钥匙{tag}",
        f"摘要 {tag}",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    memory.append_clue_action(
        clue.id,
        chapter_id,
        ClueAction.PLANT,
        f"埋下 {tag}",
        source_type=SourceType.SYSTEM,
        review_status=ReviewStatus.APPROVED,
    )


def _chapter_title_at(facade, index: int) -> str:  # type: ignore[no-untyped-def]
    """Resolve the chapter title behind a sidebar model row (headers included)."""
    chapters = facade.property("chapters")
    item = chapters.chapter_at_row(index)
    return item.title if item is not None else ""


def test_empty_entry_reports_no_project() -> None:
    facade = MockNovelStudioFacade()

    assert facade.property("advancedState") == "NO_PROJECT"
    assert facade.property("advancedClues") == []
    assert facade.property("advancedPlan") == {}


def test_facade_has_no_storage_or_retrieval_imports() -> None:
    """RC-4: the QML bridge must not import storage/retrieval modules."""
    import inspect

    source = inspect.getsource(MockNovelStudioFacade)
    assert "from ai_novel_studio.infrastructure.storage" not in source
    assert "SearchRepository" not in source
    assert "ChapterRepository" not in source
    assert "HistoryRetriever" not in source
    assert "NarrativeMemoryRepository" not in source
    assert "ViewAssertionRepository" not in source


def test_open_project_is_ready_and_empty_ledger(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()

    assert facade.openProject(str(root)) == ""

    # The fixture project has one chapter and no clues yet.
    assert facade.property("advancedState") == "READY"
    assert facade.property("advancedClues") == []
    plan = facade.property("advancedPlan")
    assert plan.get("domainKind") == "AUTHOR_PLAN"


def test_clue_ledger_respects_chapter_boundary(tmp_path: Path) -> None:
    from ai_novel_studio.application.project_workspace_service import (
        ProjectWorkspaceService,
    )

    root = create_temp_project(tmp_path / "novel")
    facade_probe = MockNovelStudioFacade()
    facade_probe.openProject(str(root))
    first_chapter_id = str(facade_probe.property("currentChapterId"))
    facade_probe.closeProject()
    _seed_clue(root, first_chapter_id, tag="A")

    # Viewing chapter 2 must surface chapter-1 plants; viewing chapter 1
    # itself must not (events are strictly-before).
    setup = ProjectWorkspaceService()
    setup.open_project(root)
    setup.create_chapter(setup.volume_tree()[0].id, "第二章", "2")
    setup.close_project()

    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    assert len(facade.property("advancedClues")) == 0

    # Row layout includes volume headers; find the row of "第二章".
    target_row = next(
        index
        for index in range(len(facade.volumes()[0].chapters) + 1)
        if str(facade.property("currentChapterTitle")) != "第二章"
        and index >= 1
        and _chapter_title_at(facade, index) == "第二章"
    )
    facade.selectChapter(target_row)
    assert str(facade.property("currentChapterTitle")) == "第二章"
    clues = facade.property("advancedClues")
    assert len(clues) == 1
    row = clues[0]
    assert row["title"] == "铜钥匙A"
    assert row["lastAction"] == "PLANT"

    # The projection never includes manuscript bodies.
    flat = repr(row)
    assert "这是测试正文" not in flat


def test_plan_panel_reflects_requirement_state(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))

    plan = facade.property("advancedPlan")

    assert plan["domainKind"] == "AUTHOR_PLAN"
    assert isinstance(plan["requirementText"], str)
    assert isinstance(plan["guidanceText"], str)


def test_readonly_projections_do_not_write(tmp_path: Path, monkeypatch) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))

    import sqlite3

    from ai_novel_studio.infrastructure.storage.database import Database

    denied: list[str] = []
    _ACTION_NAMES = {
        getattr(sqlite3, name): name
        for name in ("SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE")
        if hasattr(sqlite3, name)
    }

    def authorizer(action, arg1, arg2, db_name, trigger):  # type: ignore[no-untyped-def]
        name = _ACTION_NAMES.get(action)
        if name is not None:
            denied.append(name)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    original_connect = Database.connect

    def guarded_connect(database_obj):  # type: ignore[no-untyped-def]
        connection = original_connect(database_obj)
        connection.set_authorizer(authorizer)
        return connection

    monkeypatch.setattr(Database, "connect", guarded_connect)
    try:
        facade.property("advancedClues")
        facade.property("advancedPlan")
    finally:
        monkeypatch.undo()

    assert denied == []


def test_refresh_advanced_reads_is_safe_without_project() -> None:
    facade = MockNovelStudioFacade()

    facade.refreshAdvancedReads()

    assert facade.property("advancedState") == "NO_PROJECT"
    assert facade.property("auditCountText") == "—"


@pytest.fixture
def audit_ui(qtbot):
    from PySide6.QtCore import QCoreApplication, QEvent, QUrl
    from PySide6.QtQml import QQmlApplicationEngine

    from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
    from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(app_qml_path()).parent))
    facade = MockNovelStudioFacade()
    theme = ThemeProvider()
    register_frontend_types(engine, facade, theme)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    assert engine.rootObjects()
    window = engine.rootObjects()[0]

    # Context properties are non-owning. Destroy QML before releasing its
    # Python facade/theme, including when an assertion fails in the test.
    yield window, facade
    facade.closeProject()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qtbot.wait(20)


def test_audit_empty_state_copy_switches_with_project(
    audit_ui, qtbot, tmp_path: Path
) -> None:
    window, facade = audit_ui

    def find_item(item, name):  # type: ignore[no-untyped-def]
        if item.objectName() == name:
            return item
        try:
            children = item.childItems()
        except AttributeError:
            children = item.children()
        for child in children:
            found = find_item(child, name)
            if found is not None:
                return found
        return None

    advanced = window.findChild(object, "advancedCreationPage")
    assert advanced is not None
    empty = find_item(advanced, "auditEmptyState")
    assert empty is not None
    empty = find_item(advanced, "auditEmptyState")
    assert empty is not None

    facade.setActiveNav("advanced")
    qtbot.wait(50)
    assert "未打开项目" in str(empty.property("title"))

    root = create_temp_project(tmp_path / "novel")
    assert facade.openProject(str(root)) == ""
    qtbot.wait(50)
    assert "暂无审校问题" in str(empty.property("title"))

    refresh = find_item(advanced, "auditRefreshButton")
    assert refresh is not None
    refresh.property("clicked")  # attribute exists
    from PySide6.QtCore import QMetaObject

    QMetaObject.invokeMethod(refresh, "clicked")
    qtbot.wait(50)
    assert "暂无审校问题" in str(empty.property("title"))
