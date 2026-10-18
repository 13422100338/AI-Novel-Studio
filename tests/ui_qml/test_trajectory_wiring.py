"""QP-3B: trajectory (H1 INDEX/DETAIL/Evidence) and cognition wiring.

Seeds a real approved Occurrence+Link at the current chapter revision, then
drives the facade slots end-to-end. Evidence goes through the R3b-Q1
boundary explicitly; cognition reads are authorizer-guarded read-only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("ai_novel_studio.application")

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType
from ai_novel_studio.domain.occurrence import (
    OCCURRENCE_TYPE_VOCABULARY_V1,
    Occurrence,
    OccurrenceSourceRange,
    OccurrenceType,
    SubjectOccurrenceLink,
    SubjectOccurrenceLinkSourceRange,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import (
    ProjectRepository,
)
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import (
    MockNovelStudioFacade,
)

from .test_project_wiring import create_temp_project

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def _seed_occurrence(
    root: Path,
    chapter_id: str,
    subject_id: str,
    other_id: str,
) -> str:
    from ai_novel_studio.application.view_assertion_service import (
        ViewAssertionService,
    )
    from ai_novel_studio.domain.view import (
        EpistemicStatus as _EpistemicStatus,
    )
    from ai_novel_studio.domain.view import ViewAssertionDraft, ViewType
    from ai_novel_studio.infrastructure.storage.occurrence_repository import (
        OccurrenceRepository,
    )

    project = ProjectRepository.open(root)
    with project.database.connect() as connection:
        row = connection.execute(
            "SELECT revision FROM chapters WHERE id = ?", (chapter_id,)
        ).fetchone()
    revision = int(row["revision"])
    content = "这是测试正文。\n\n第二段。"
    start = content.index("测试")
    occurrence = Occurrence(
        id=new_id(),
        candidate_source_id=f"semantic-window:{chapter_id}:seed",
        type_code=OccurrenceType.DISCOVERY,
        vocabulary_version=OCCURRENCE_TYPE_VOCABULARY_V1,
        title="发现铜钥匙",
        summary="艾琳发现了一把铜钥匙。",
        narrative_sequence=1,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
        source_type=SourceType.MODEL,
        stale=False,
        source_changed=False,
        source_ranges=(
            OccurrenceSourceRange(
                ordinal=0,
                source_chapter_id=chapter_id,
                source_revision=revision,
                source_hash=_hash_of(root, chapter_id),
                semantic_window_source_id=f"semantic-window:{chapter_id}",
                policy_version="semantic-window-v1",
                source_start=start,
                source_end=start + len("测试正文"),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    link = SubjectOccurrenceLink(
        id=new_id(),
        candidate_source_id=f"semantic-window:{chapter_id}:link",
        occurrence_id=occurrence.id,
        subject_id=subject_id,
        role="发现者",
        subject_summary="艾琳首先发现了钥匙。",
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
        source_type=SourceType.MODEL,
        stale=False,
        source_changed=False,
        source_ranges=(
            SubjectOccurrenceLinkSourceRange(
                ordinal=0,
                source_chapter_id=chapter_id,
                source_revision=revision,
                source_hash=_hash_of(root, chapter_id),
                semantic_window_source_id=f"semantic-window:{chapter_id}",
                policy_version="semantic-window-v1",
                source_start=start,
                source_end=start + len("测试"),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    repository = OccurrenceRepository(project)
    repository.create_model_candidates_for_chapter(
        chapter_id,
        expected_revision=revision,
        expected_source_hash=_hash_of(root, chapter_id),
        occurrences=(occurrence,),
        links=(link,),
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE occurrences SET review_status = 'APPROVED' WHERE id = ?",
            (occurrence.id,),
        )
        connection.execute(
            "UPDATE subject_occurrence_links SET review_status = 'APPROVED' "
            "WHERE id = ?",
            (link.id,),
        )
    views = ViewAssertionService(project)
    views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=other_id,
            view_type=ViewType.CHARACTER_VIEW,
            viewer_subject_id=subject_id,
            epistemic_status=_EpistemicStatus.KNOWS,
            content="艾琳知道守卫藏起了钥匙。",
            narrative_visible_from_sequence=2,
        ),
        source_id="seed-view",
        source_revision=0,
        confirmed_by_user=True,
    )
    return occurrence.id


def _hash_of(root: Path, chapter_id: str) -> str:

    project = ProjectRepository.open(root)
    with project.database.connect() as connection:
        row = connection.execute(
            "SELECT content_hash FROM chapters WHERE id = ?", (chapter_id,)
        ).fetchone()
    return str(row["content_hash"])


def test_trajectory_and_cognition_end_to_end(tmp_path: Path) -> None:
    from ai_novel_studio.application.project_workspace_service import (
        ProjectWorkspaceService,
    )

    root = create_temp_project(tmp_path / "novel")
    setup = ProjectWorkspaceService()
    setup.open_project(root)
    characters = CharacterMemoryRepository(setup.project)
    subject_id = characters.create_character("艾琳").id
    other_id = characters.create_character("守卫").id
    setup.create_chapter(setup.volume_tree()[0].id, "第二章", "2")
    setup.close_project()

    probe = MockNovelStudioFacade()
    probe.openProject(str(root))
    chapter_id = str(probe.property("currentChapterId"))
    probe.closeProject()
    occurrence_id = _seed_occurrence(root, chapter_id, subject_id, other_id)

    facade = MockNovelStudioFacade()
    assert facade.openProject(str(root)) == ""

    assert facade.property("trajectoryState") == "NO_SUBJECT"
    facade.loadTrajectory(subject_id)
    assert facade.property("trajectoryState") == "READY"
    index_rows = facade.property("trajectoryIndex")
    assert len(index_rows) == 1
    assert index_rows[0]["title"] == "发现铜钥匙"

    assert facade.property("trajectoryDetail") == {}
    facade.openTrajectoryDetail(str(index_rows[0]["occurrenceId"]))
    detail = facade.property("trajectoryDetail")
    assert detail["title"] == "发现铜钥匙"
    assert detail["participants"][0]["subjectId"] == subject_id

    facade.loadTrajectoryEvidence(occurrence_id)
    outcome = str(facade._trajectory_evidence_outcome)
    assert outcome in {"FOUND", "NOT_FOUND", "INSUFFICIENT"}

    # Cognition visibility is narrative-sequence bound: the seeded view
    # becomes visible from chapter 2.
    facade.selectChapter(2)
    assert str(facade.property("currentChapterTitle")) == "第二章"
    facade.loadCognition(subject_id)
    assert facade.property("cognitionState") == "READY"
    rows = facade.property("cognitionRows")
    assert len(rows) == 1
    assert rows[0]["content"] == "艾琳知道守卫藏起了钥匙。"


def test_cognition_read_only(tmp_path: Path, monkeypatch) -> None:
    from ai_novel_studio.application.project_workspace_service import (
        ProjectWorkspaceService,
    )

    root = create_temp_project(tmp_path / "novel")
    setup = ProjectWorkspaceService()
    setup.open_project(root)
    subject_id = CharacterMemoryRepository(setup.project).create_character("守卫").id
    setup.close_project()
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))

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
        facade.loadCognition(subject_id)
    finally:
        monkeypatch.undo()
    assert denied == []


def test_close_project_resets_trajectory(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    facade.loadCognition("")
    assert facade.property("cognitionState") == "NO_SUBJECT"

    facade.closeProject()

    assert facade.property("trajectoryState") == "NO_PROJECT"
    assert facade.property("cognitionState") == "NO_PROJECT"
