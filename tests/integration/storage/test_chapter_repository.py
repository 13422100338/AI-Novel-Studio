import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.domain.embedding import EmbeddingIndexIdentity
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
)


def _repositories(tmp_path: Path) -> tuple[ProjectRepository, ChapterRepository]:
    project = ProjectRepository.create(tmp_path / "novel", "My Novel")
    return project, ChapterRepository(project)


def test_create_writes_canonical_utf8_markdown_and_preserves_order(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    volume = project.list_volumes()[0]

    first = chapters.create_chapter(volume.id, "开端", "第一章", "正文一")
    second = chapters.create_chapter(volume.id, "继续", "第二章", "正文二")

    assert chapters.read_content(first.id) == "正文一"
    assert not Path(first.content_path).is_absolute()
    assert (project.layout.root / first.content_path).read_bytes() == "正文一".encode()
    assert [chapter.id for chapter in chapters.list_chapters(volume.id)] == [first.id, second.id]


def test_save_snapshots_previous_revision_before_atomic_replace(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    chapter = chapters.create_chapter(project.list_volumes()[0].id, "Opening", "1", "old")

    updated = chapters.save_content(chapter.id, "new", source="manual", reason="rewrite")
    versions = chapters.list_versions(chapter.id)

    assert updated.revision == 1
    assert chapters.read_content(chapter.id) == "new"
    assert len(versions) == 1
    assert versions[0].revision == 0
    snapshot = project.layout.root / versions[0].content_snapshot_path
    assert snapshot.read_text(encoding="utf-8") == "old"
    assert versions[0].content_hash == hashlib.sha256(b"old").hexdigest()


def test_rename_advances_projection_revision_with_exact_content_snapshot(
    tmp_path: Path,
) -> None:
    project, chapters = _repositories(tmp_path)
    content = "first line\r\nemoji \U0001f600\r\n"
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        content,
    )
    search = SearchRepository(project)
    maintained = ChapterRevisionService(project).maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
    prior = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        chunk_policy_version=maintained.policy_version,
    )[0]
    identity = EmbeddingIndexIdentity("provider", "model", 1)
    embedding_source = search.embedding_source(prior.id)
    search.save_embedding(
        prior.id,
        identity,
        (1.0, 0.0),
        expected_content_hash=embedding_source.content_hash,
    )
    canonical = project.layout.root / chapter.content_path
    original_bytes = canonical.read_bytes()

    renamed = chapters.rename_chapter(chapter.id, "Storm Front")
    versions = chapters.list_versions(chapter.id)

    with project.database.connect() as connection:
        stored_hash = str(
            connection.execute(
                "SELECT content_hash FROM chapters WHERE id = ?",
                (chapter.id,),
            ).fetchone()["content_hash"]
        )
        statuses = tuple(
            connection.execute(
                """
                SELECT d.status, dep.status, e.status
                FROM memory_documents d
                JOIN memory_dependencies dep
                  ON dep.memory_type = 'SEARCH' AND dep.memory_id = d.id
                JOIN memory_embeddings e ON e.document_id = d.id
                WHERE d.id = ?
                """,
                (prior.id,),
            ).fetchone()
        )

    assert renamed.title == "Storm Front"
    assert renamed.revision == chapter.revision + 1
    assert renamed.memory_status == "stale"
    assert stored_hash == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert canonical.read_bytes() == original_bytes
    assert len(versions) == 1
    assert versions[0].revision == chapter.revision
    assert versions[0].source == "metadata_change"
    assert versions[0].reason == "chapter title changed"
    assert versions[0].content_hash == stored_hash
    snapshot = project.layout.root / versions[0].content_snapshot_path
    assert snapshot.read_bytes() == original_bytes
    assert statuses == ("STALE", "STALE", "STALE")


def test_same_title_rename_is_a_true_no_op(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "unchanged",
    )
    before = chapters.get_chapter(chapter.id)

    renamed = chapters.rename_chapter(chapter.id, "  Opening  ")

    assert renamed == before
    assert chapters.list_versions(chapter.id) == []
    history = project.layout.history / chapter.id
    assert not history.exists() or not tuple(history.iterdir())


def test_rename_invalidation_failure_rolls_back_metadata_and_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters = _repositories(tmp_path)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "unchanged body",
    )

    def fail_invalidation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected title invalidation failure")

    monkeypatch.setattr(
        ViewAssertionRepository,
        "invalidate_source_revision_in_connection",
        fail_invalidation,
    )

    with pytest.raises(RuntimeError, match="injected title invalidation failure"):
        chapters.rename_chapter(chapter.id, "Renamed")

    restored = chapters.get_chapter(chapter.id)
    assert restored.title == chapter.title
    assert restored.revision == chapter.revision
    assert restored.memory_status == chapter.memory_status
    assert chapters.read_content_exact(chapter.id) == "unchanged body"
    assert chapters.list_versions(chapter.id) == []
    history = project.layout.history / chapter.id
    assert not history.exists() or not tuple(history.iterdir())


def test_view_invalidation_failure_restores_chapter_file_and_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters = _repositories(tmp_path)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "old",
    )

    def fail_invalidation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected view invalidation failure")

    monkeypatch.setattr(
        ViewAssertionRepository,
        "invalidate_source_revision_in_connection",
        fail_invalidation,
    )

    with pytest.raises(RuntimeError, match="injected view invalidation failure"):
        chapters.save_content(
            chapter.id,
            "new",
            source="manual",
            reason="rewrite",
        )

    restored = chapters.get_chapter(chapter.id)
    assert restored.revision == 0
    assert chapters.read_content(chapter.id) == "old"
    assert chapters.list_versions(chapter.id) == []
    history = project.layout.history / chapter.id
    assert not history.exists() or not tuple(history.iterdir())


def test_noninvalidating_save_stales_only_prior_formal_projection(
    tmp_path: Path,
) -> None:
    project, chapters = _repositories(tmp_path)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "old body",
    )
    search = SearchRepository(project)
    legacy = search.index_chapter(chapter.id, chapter.title, "old body")
    old_hash = hashlib.sha256(b"old body").hexdigest()
    maintained = ChapterRevisionService(project).maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=old_hash,
    )
    formal = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=old_hash,
        chunk_policy_version=maintained.policy_version,
    )[0]
    identity = EmbeddingIndexIdentity("provider", "model", 1)
    source = search.embedding_source(formal.id)
    search.save_embedding(
        formal.id,
        identity,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )

    updated = chapters.save_content(
        chapter.id,
        "new body",
        source="manual",
        reason="punctuation",
        invalidate_memory=False,
    )

    with project.database.connect() as connection:
        document_rows = connection.execute(
            """
            SELECT id, status FROM memory_documents
            WHERE id IN (?, ?)
            ORDER BY id
            """,
            (formal.id, legacy.id),
        ).fetchall()
        dependency_rows = connection.execute(
            """
            SELECT memory_id, status FROM memory_dependencies
            WHERE memory_type = 'SEARCH' AND memory_id IN (?, ?)
            ORDER BY memory_id
            """,
            (formal.id, legacy.id),
        ).fetchall()
        embedding_status = connection.execute(
            """
            SELECT status FROM memory_embeddings
            WHERE document_id = ? AND provider_id = ? AND model_id = ?
              AND embedding_schema_version = ?
            """,
            (
                formal.id,
                identity.provider_id,
                identity.model_id,
                identity.embedding_schema_version,
            ),
        ).fetchone()["status"]

    assert updated.revision == chapter.revision + 1
    assert updated.memory_status == chapter.memory_status
    assert {row["id"]: row["status"] for row in document_rows} == {
        formal.id: "STALE",
        legacy.id: "CURRENT",
    }
    assert {row["memory_id"]: row["status"] for row in dependency_rows} == {
        formal.id: "STALE",
        legacy.id: "CURRENT",
    }
    assert embedding_status == "STALE"


def test_delete_moves_chapter_to_trash_and_restore_recovers_it(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    chapter = chapters.create_chapter(project.list_volumes()[0].id, "Opening", "1", "body")
    canonical = project.layout.root / chapter.content_path

    chapters.delete_chapter(chapter.id)

    assert not canonical.exists()
    assert chapters.list_chapters() == []
    assert any(project.layout.trash.iterdir())

    restored = chapters.restore_chapter(chapter.id)
    assert restored.is_deleted is False
    assert chapters.read_content(chapter.id) == "body"


def test_delete_volume_reassigns_chapters_and_removes_empty_volume(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    target = project.list_volumes()[0]
    source = project.create_volume("Part Two")
    chapter = chapters.create_chapter(source.id, "Opening", "1", "body")

    chapters.delete_volume(source.id, target.id)

    assert [volume.id for volume in project.list_volumes()] == [target.id]
    moved = chapters.list_chapters(target.id)[0]
    assert moved.id == chapter.id
    assert moved.volume_id == target.id
    assert chapters.read_content(moved.id) == "body"
    assert f"volume_{target.id}" in moved.content_path


def test_volume_cannot_be_deleted_into_itself(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    volume = project.list_volumes()[0]

    with pytest.raises(ValueError, match="different"):
        chapters.delete_volume(volume.id, volume.id)
