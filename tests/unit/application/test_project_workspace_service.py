import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
    FormalMaintenanceResult,
)
from ai_novel_studio.application.project_workspace_service import (
    ProjectWorkspaceService,
    WorkspaceNotOpenError,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_workspace_creates_project_and_returns_tree(tmp_path: Path) -> None:
    service = ProjectWorkspaceService()

    summary = service.create_project(tmp_path / "novel", "My Novel")
    tree = service.volume_tree()

    assert summary.title == "My Novel"
    assert summary.root == (tmp_path / "novel").resolve()
    assert len(tree) == 1
    assert tree[0].chapters == ()
    service.close_project()


def test_workspace_loads_and_saves_chapter_without_bypassing_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "My Novel")
    chapter_repo = ChapterRepository(project)
    chapter = chapter_repo.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "old text",
    )
    service = ProjectWorkspaceService()
    service.open_project(project.layout.root)
    calls: list[str] = []
    original = ChapterRevisionService.submit_revision

    def track_submit(
        revisions: ChapterRevisionService,
        chapter_id: str,
        content: str,
        **kwargs: object,
    ):  # type: ignore[no-untyped-def]
        calls.append(chapter_id)
        return original(revisions, chapter_id, content, **kwargs)

    monkeypatch.setattr(ChapterRevisionService, "submit_revision", track_submit)

    workspace = service.load_chapter(chapter.id)
    saved = service.save_chapter(
        chapter.id,
        "new text",
        expected_revision=workspace.revision,
        requirement_content="must happen",
        expected_requirement_revision=workspace.requirement_revision,
    )

    assert workspace.content == "old text"
    assert workspace.requirement_content == ""
    assert saved.revision == 1
    assert saved.requirement_revision == 1
    assert chapter_repo.read_content(chapter.id) == "new text"
    assert len(chapter_repo.list_versions(chapter.id)) == 1
    reloaded = service.load_chapter(chapter.id)
    assert reloaded.requirement_content == "must happen"
    formal = SearchRepository(project).read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=1,
        expected_source_hash=_source_hash("new text"),
        chunk_policy_version="paragraph-codepoint-v1",
    )
    assert calls == [chapter.id]
    assert tuple(document.content for document in formal) == ("new text",)
    service.close_project()


def test_workspace_maintenance_failure_commits_once_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "My Novel")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "old text",
    )
    ChapterRevisionService(project).maintain_current_revision(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash("old text"),
    )
    service = ProjectWorkspaceService()
    service.open_project(project.layout.root)
    revisions = service.revision_service
    assert isinstance(revisions, ChapterRevisionService)
    maintenance_calls = 0

    def fail_maintenance(
        _chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
    ) -> FormalMaintenanceResult:
        nonlocal maintenance_calls
        maintenance_calls += 1
        raise RuntimeError(
            f"raw maintenance failure: {project.layout.root}: new private text: "
            f"{expected_revision}: {expected_source_hash}"
        )

    monkeypatch.setattr(
        revisions,
        "maintain_current_revision",
        fail_maintenance,
    )

    saved = service.save_chapter(
        chapter.id,
        "new private text",
        expected_revision=0,
    )

    with project.database.connect() as connection:
        formal_statuses = tuple(
            str(row["status"])
            for row in connection.execute(
                "SELECT status FROM memory_documents "
                "WHERE document_type = 'FORMAL_MANUSCRIPT' AND chapter_id = ?",
                (chapter.id,),
            ).fetchall()
        )
    assert saved.revision == 1
    assert chapters.read_content_exact(chapter.id) == "new private text"
    assert len(chapters.list_versions(chapter.id)) == 1
    assert maintenance_calls == 1
    assert formal_statuses == ("STALE",)

    monkeypatch.undo()
    report = revisions.recover_current_revisions(limit=10)
    repaired = SearchRepository(project).read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=1,
        expected_source_hash=_source_hash("new private text"),
        chunk_policy_version="paragraph-codepoint-v1",
    )
    assert report.repaired_chapters == 1
    assert tuple(document.content for document in repaired) == ("new private text",)
    service.close_project()


def test_workspace_reports_stale_revision_without_overwriting_content(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "My Novel")
    chapter_repo = ChapterRepository(project)
    chapter = chapter_repo.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "old text",
    )
    service = ProjectWorkspaceService()
    service.open_project(project.layout.root)
    chapter_repo.save_content(chapter.id, "external", source="test", reason="stale")

    with pytest.raises(RuntimeError, match="revision"):
        service.save_chapter(chapter.id, "new text", expected_revision=0)

    assert chapter_repo.read_content(chapter.id) == "external"
    service.close_project()


def test_workspace_requires_open_project_before_operations() -> None:
    service = ProjectWorkspaceService()

    with pytest.raises(WorkspaceNotOpenError):
        service.volume_tree()


def test_workspace_creates_and_renames_chapters_and_volumes(tmp_path: Path) -> None:
    service = ProjectWorkspaceService()
    service.create_project(tmp_path / "novel", "My Novel")
    first_volume = service.volume_tree()[0]

    second_volume = service.create_volume("第二卷")
    chapter = service.create_chapter(second_volume.id, "新章节", "第 1 章")
    service.rename_volume(second_volume.id, "第二卷·风暴")
    service.rename_chapter(chapter.id, "风暴将至")

    tree = service.volume_tree()
    assert [volume.title for volume in tree] == [first_volume.title, "第二卷·风暴"]
    assert tree[1].chapters[0].title == "风暴将至"
    service.close_project()


def test_workspace_rename_chapter_uses_shared_revision_coordinator_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "My Novel")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "title-aware body",
    )
    service = ProjectWorkspaceService()
    service.open_project(project.layout.root)
    revisions = service.revision_service
    assert isinstance(revisions, ChapterRevisionService)
    calls: list[tuple[str, str]] = []
    original = revisions.submit_title_revision

    def track_submit(chapter_id: str, title: str):  # type: ignore[no-untyped-def]
        calls.append((chapter_id, title))
        return original(chapter_id, title)

    monkeypatch.setattr(revisions, "submit_title_revision", track_submit)

    renamed = service.rename_chapter(chapter.id, "Storm Front")

    assert calls == [(chapter.id, "Storm Front")]
    assert renamed.id == chapter.id
    assert renamed.title == "Storm Front"
    assert renamed.revision == 1
    assert renamed.word_count == len("title-awarebody")
    formal = SearchRepository(project).read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=1,
        expected_source_hash=_source_hash("title-aware body"),
        chunk_policy_version="paragraph-codepoint-v1",
    )
    assert formal
    assert all(document.title == "Storm Front" for document in formal)
    service.close_project()


def test_deleting_volume_moves_its_chapters_to_previous_volume(tmp_path: Path) -> None:
    service = ProjectWorkspaceService()
    service.create_project(tmp_path / "novel", "My Novel")
    first_volume = service.volume_tree()[0]
    second_volume = service.create_volume("第二卷")
    chapter = service.create_chapter(second_volume.id, "不会丢失", "第 1 章")

    target_volume_id = service.delete_volume(second_volume.id)

    tree = service.volume_tree()
    assert target_volume_id == first_volume.id
    assert len(tree) == 1
    assert tree[0].chapters[0].id == chapter.id
    assert service.load_chapter(chapter.id).title == "不会丢失"
    service.close_project()
