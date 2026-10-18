"""QP-3B: read-only character-cognition projection over View assertions.

Only currently-visible APPROVED/LOCKED assertions are exposed (the canonical
Context hard-filter path), with bounded content and deterministic ordering.
No extraction, no review writes, no repository mutations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("ai_novel_studio.application")

from ai_novel_studio.application.character_view_read_service import (
    CharacterViewReadService,
)
from ai_novel_studio.application.view_assertion_service import (
    ViewAssertionService,
)
from ai_novel_studio.domain.view import EpistemicStatus, ViewAssertionDraft, ViewType
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRepository,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import (
    ProjectRepository,
)


def _project(tmp_path: Path) -> tuple[ProjectRepository, str, str, str]:
    project = ProjectRepository.create(tmp_path / "novel", "人物认知")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id, "第一章", "1", "正文"
    )
    characters = CharacterMemoryRepository(project)
    alice = characters.create_character("艾琳")
    rolan = characters.create_character("罗兰")
    return project, chapter.id, alice.id, rolan.id


def _seed(
    service: ViewAssertionService,
    *,
    view_type: ViewType,
    subject_id: str,
    viewer_subject_id: str | None,
    content: str,
    visible_from: int,
) -> None:
    service.create_user_assertion(
        ViewAssertionDraft(
            subject_id=subject_id,
            view_type=view_type,
            viewer_subject_id=viewer_subject_id,
            content=content,
            epistemic_status=(
                EpistemicStatus.KNOWS if view_type is ViewType.CHARACTER_VIEW else None
            ),
            narrative_visible_from_sequence=visible_from,
        ),
        source_id="seed",
        source_revision=0,
        confirmed_by_user=True,
    )


def test_character_and_reader_views_visible_to_viewer(tmp_path: Path) -> None:
    project, chapter_id, alice, rolan = _project(tmp_path)
    views = ViewAssertionService(project)
    _seed(
        views,
        view_type=ViewType.CHARACTER_VIEW,
        subject_id=rolan,
        viewer_subject_id=alice,
        content="艾琳知道罗兰藏起了铜钥匙。",
        visible_from=1,
    )
    _seed(
        views,
        view_type=ViewType.READER_VIEW,
        subject_id=rolan,
        viewer_subject_id=None,
        content="读者已知钥匙的存在。",
        visible_from=2,
    )
    service = CharacterViewReadService(project)

    rows = service.views_for(viewer_subject_id=alice, narrative_sequence=2)

    assert [row.view_type for row in rows] == [
        ViewType.CHARACTER_VIEW.value,
        ViewType.READER_VIEW.value,
    ]
    by_type = {row.view_type: row for row in rows}
    assert by_type[ViewType.CHARACTER_VIEW.value].viewer_name == "艾琳"
    assert by_type[ViewType.CHARACTER_VIEW.value].target_name == "罗兰"
    assert by_type[ViewType.CHARACTER_VIEW.value].epistemic_status == "KNOWS"


def test_visibility_window_filters_future_rows(tmp_path: Path) -> None:
    project, _chapter_id, alice, rolan = _project(tmp_path)
    views = ViewAssertionService(project)
    _seed(
        views,
        view_type=ViewType.READER_VIEW,
        subject_id=rolan,
        viewer_subject_id=None,
        content="未来的揭示。",
        visible_from=5,
    )
    service = CharacterViewReadService(project)

    assert service.views_for(viewer_subject_id=alice, narrative_sequence=2) == ()
    assert len(service.views_for(viewer_subject_id=alice, narrative_sequence=9)) == 1


def test_unknown_viewer_fails_fixed_before_listing(tmp_path: Path) -> None:
    from ai_novel_studio.domain.identifiers import new_id

    project, _chapter_id, _alice, _rolan = _project(tmp_path)
    service = CharacterViewReadService(project)

    with pytest.raises(ValueError, match="unknown"):
        service.views_for(
            viewer_subject_id=new_id(), narrative_sequence=1
        )


def test_long_content_is_truncated_with_flag(tmp_path: Path) -> None:
    project, _chapter_id, alice, rolan = _project(tmp_path)
    views = ViewAssertionService(project)
    _seed(
        views,
        view_type=ViewType.CHARACTER_VIEW,
        subject_id=rolan,
        viewer_subject_id=alice,
        content="长" * 500,
        visible_from=1,
    )
    service = CharacterViewReadService(project)

    rows = service.views_for(viewer_subject_id=alice, narrative_sequence=1)

    assert len(rows) == 1
    assert len(rows[0].content) <= 300
    assert rows[0].content_truncated is True


def test_views_for_passes_sql_limit_and_stays_deterministic(
    tmp_path: Path,
) -> None:
    project, _chapter_id, alice, rolan = _project(tmp_path)
    views = ViewAssertionService(project)
    for index in range(6):
        _seed(
            views,
            view_type=ViewType.CHARACTER_VIEW,
            subject_id=rolan,
            viewer_subject_id=alice,
            content=f"认知 {index}",
            visible_from=1,
        )
    service = CharacterViewReadService(project)

    rows = service.views_for(
        viewer_subject_id=alice, narrative_sequence=1, limit=3
    )

    # SQL-level limit: at most `limit` character rows survive the merge.
    assert len(rows) <= 3
    ids = [row.assertion_id for row in rows]
    assert ids == sorted(ids)


def test_views_for_shared_budget_caps_merged_output(
    tmp_path: Path,
) -> None:
    """RC-4 follow-up: character + reader queries must not jointly exceed
    the caller-provided limit (shared remaining budget, not 2x)."""
    project, _chapter_id, alice, rolan = _project(tmp_path)
    views = ViewAssertionService(project)
    for index in range(5):
        _seed(
            views,
            view_type=ViewType.CHARACTER_VIEW,
            subject_id=rolan,
            viewer_subject_id=alice,
            content=f"角色认知 {index}",
            visible_from=1,
        )
    for index in range(5):
        _seed(
            views,
            view_type=ViewType.READER_VIEW,
            subject_id=rolan,
            viewer_subject_id=None,
            content=f"读者认知 {index}",
            visible_from=1,
        )
    service = CharacterViewReadService(project)

    rows = service.views_for(
        viewer_subject_id=alice, narrative_sequence=1, limit=6
    )

    assert len(rows) == 6
    assert all(len(row.content) <= 300 for row in rows)


def test_projection_is_read_only(tmp_path: Path, monkeypatch) -> None:
    project, _chapter_id, alice, rolan = _project(tmp_path)
    views = ViewAssertionService(project)
    _seed(
        views,
        view_type=ViewType.CHARACTER_VIEW,
        subject_id=rolan,
        viewer_subject_id=alice,
        content="只读检查。",
        visible_from=1,
    )
    service = CharacterViewReadService(project)

    import sqlite3

    from ai_novel_studio.infrastructure.storage.database import Database

    denied: list[str] = []
    actions = {
        getattr(sqlite3, name): name
        for name in ("SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE")
        if hasattr(sqlite3, name)
    }

    def authorizer(action, arg1, arg2, db_name, trigger):  # type: ignore[no-untyped-def]
        name = actions.get(action)
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
        service.views_for(viewer_subject_id=alice, narrative_sequence=1)
    finally:
        monkeypatch.undo()
    assert denied == []
