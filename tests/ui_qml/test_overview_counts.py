"""Frontend Wave F9: read-only overview counts for page skeletons."""

from __future__ import annotations

from pathlib import Path

from ai_novel_studio.application.project_workspace_service import ProjectWorkspaceService
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.overview_counts import (
    OverviewCounts,
    readonly_overview_counts,
)

from .test_project_wiring import create_temp_project


def test_empty_project_counts_are_zero(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    service = ProjectWorkspaceService()
    service.open_project(root)
    chapter_id = service.volume_tree()[0].chapters[0].id

    counts = readonly_overview_counts(service.project, chapter_id)

    assert counts.character_count == 0
    assert counts.memory_count == 0
    assert counts.audit_count == 0
    service.close_project()


def test_counts_are_independent_on_failure(tmp_path: Path) -> None:
    """A failing query must not prevent the other counts from being read."""
    root = create_temp_project(tmp_path / "novel")
    service = ProjectWorkspaceService()
    service.open_project(root)
    chapter_id = service.volume_tree()[0].chapters[0].id

    counts = readonly_overview_counts(service.project, chapter_id)
    assert isinstance(counts, OverviewCounts)

    service.close_project()


def test_facade_shows_zero_counts_for_project(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))

    assert facade.property("characterCountText") == "0 人"
    assert facade.property("memoryCountText") == "0 条"
    assert facade.property("auditCountText") == "0 项"


def test_facade_shows_placeholder_without_project() -> None:
    facade = MockNovelStudioFacade()
    assert facade.property("characterCountText") == "—"
    assert facade.property("memoryCountText") == "—"
    assert facade.property("auditCountText") == "—"


def test_close_project_restores_placeholder(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    assert facade.property("characterCountText") == "0 人"

    facade.closeProject()

    assert facade.property("characterCountText") == "—"
    assert facade.property("memoryCountText") == "—"
    assert facade.property("auditCountText") == "—"

