import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.domain.embedding import EmbeddingIndexIdentity
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterFileTransaction,
    ChapterRelocationExpectation,
    ChapterRepository,
)
from ai_novel_studio.infrastructure.storage.memory_dependency_repository import (
    MemoryDependencyRepository,
)
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


def test_caller_transaction_rollback_restores_content_title_and_history(
    tmp_path: Path,
) -> None:
    project, chapters = _repositories(tmp_path)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "old",
    )
    files = ChapterFileTransaction()

    with project.database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        chapters.save_content(
            chapter.id,
            "new",
            source="changeset",
            reason="tentative",
            expected_revision=chapter.revision,
            connection=connection,
            file_transaction=files,
        )
        chapters.rename_chapter(
            chapter.id,
            "Tentative",
            expected_revision=chapter.revision + 1,
            connection=connection,
            file_transaction=files,
        )
        connection.rollback()
        files.rollback()

    restored = chapters.get_chapter(chapter.id)
    assert restored.title == chapter.title
    assert restored.revision == chapter.revision
    assert chapters.read_content_exact(chapter.id) == "old"
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


def test_delete_stales_formal_projection_and_preserves_legacy_rows(
    tmp_path: Path,
) -> None:
    project, chapters = _repositories(tmp_path)
    content = "第一行😀\r\n第二行\r\n"
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        content,
    )
    search = SearchRepository(project)
    legacy = search.index_chapter(chapter.id, chapter.title, content)
    maintained = ChapterRevisionService(project).maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=source_hash,
    )
    formal = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=source_hash,
        chunk_policy_version=maintained.policy_version,
    )[0]
    identity = EmbeddingIndexIdentity("provider", "model", 1)
    embedding_source = search.embedding_source(formal.id)
    search.save_embedding(
        formal.id,
        identity,
        (1.0, 0.0),
        expected_content_hash=embedding_source.content_hash,
    )
    canonical = project.layout.root / chapter.content_path

    chapters.delete_chapter(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=source_hash,
    )

    deleted = chapters.get_chapter(chapter.id)
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
                (formal.id,),
            ).fetchone()
        )
    assert deleted.is_deleted is True
    assert deleted.revision == chapter.revision
    assert stored_hash == source_hash
    assert not canonical.exists()
    assert statuses == ("STALE", "STALE", "STALE")
    assert search.get(legacy.id).status.value == "CURRENT"


@pytest.mark.parametrize(
    ("expected_revision", "expected_source_hash"),
    [(1, hashlib.sha256(b"body").hexdigest()), (0, "a" * 64)],
)
def test_delete_rejects_stale_expected_identity_before_moving_source(
    tmp_path: Path,
    expected_revision: int,
    expected_source_hash: str,
) -> None:
    project, chapters = _repositories(tmp_path)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "body",
    )
    canonical = project.layout.root / chapter.content_path

    with pytest.raises(RuntimeError, match="changed"):
        chapters.delete_chapter(
            chapter.id,
            expected_revision=expected_revision,
            expected_source_hash=expected_source_hash,
        )

    assert chapters.get_chapter(chapter.id, include_deleted=False) == chapter
    assert canonical.read_text(encoding="utf-8") == "body"
    assert not project.layout.trash.exists() or not tuple(project.layout.trash.iterdir())


def test_delete_invalidation_failure_rolls_back_file_database_and_statuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters = _repositories(tmp_path)
    content = "rollback body"
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
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
        expected_source_hash=source_hash,
    )
    formal = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=source_hash,
        chunk_policy_version=maintained.policy_version,
    )[0]
    identity = EmbeddingIndexIdentity("provider", "model", 1)
    embedding_source = search.embedding_source(formal.id)
    search.save_embedding(
        formal.id,
        identity,
        (1.0, 0.0),
        expected_content_hash=embedding_source.content_hash,
    )
    canonical = project.layout.root / chapter.content_path

    def fail_invalidation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected deletion invalidation failure")

    monkeypatch.setattr(
        MemoryDependencyRepository,
        "invalidate_formal_manuscript_for_deleted_chapter_in_connection",
        fail_invalidation,
    )

    with pytest.raises(RuntimeError, match="injected deletion invalidation failure"):
        chapters.delete_chapter(
            chapter.id,
            expected_revision=chapter.revision,
            expected_source_hash=source_hash,
        )

    with project.database.connect() as connection:
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
                (formal.id,),
            ).fetchone()
        )
    assert chapters.get_chapter(chapter.id, include_deleted=False) == chapter
    assert canonical.read_text(encoding="utf-8") == content
    assert statuses == ("CURRENT", "CURRENT", "CURRENT")
    assert not project.layout.trash.exists() or not tuple(project.layout.trash.iterdir())


def test_delete_volume_reassigns_chapters_and_removes_empty_volume(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    target = project.list_volumes()[0]
    source = project.create_volume("Part Two")
    first_content = "first line\r\nemoji \U0001f600\r\n"
    second_content = "second chapter"
    first = chapters.create_chapter(source.id, "Opening", "1", first_content)
    second = chapters.create_chapter(source.id, "Follow-up", "2", second_content)
    search = SearchRepository(project)
    legacy = search.index_chapter(first.id, first.title, first_content)
    maintained = ChapterRevisionService(project).maintain_current_revision(
        first.id,
        expected_revision=first.revision,
        expected_source_hash=hashlib.sha256(first_content.encode("utf-8")).hexdigest(),
    )
    formal = search.read_formal_manuscript_chunks(
        first.id,
        expected_revision=first.revision,
        expected_source_hash=hashlib.sha256(first_content.encode("utf-8")).hexdigest(),
        chunk_policy_version=maintained.policy_version,
    )[0]
    identity = EmbeddingIndexIdentity("provider", "model", 1)
    embedding_source = search.embedding_source(formal.id)
    search.save_embedding(
        formal.id,
        identity,
        (1.0, 0.0),
        expected_content_hash=embedding_source.content_hash,
    )
    original_bytes = {
        chapter.id: (project.layout.root / chapter.content_path).read_bytes()
        for chapter in (first, second)
    }

    relocated = chapters.delete_volume(source.id, target.id)

    assert [volume.id for volume in project.list_volumes()] == [target.id]
    assert [chapter.id for chapter in relocated] == [first.id, second.id]
    for original, moved in zip((first, second), relocated, strict=True):
        assert moved.volume_id == target.id
        assert moved.revision == original.revision + 1
        assert moved.memory_status == "stale"
        assert f"volume_{target.id}" in moved.content_path
        assert (project.layout.root / moved.content_path).read_bytes() == original_bytes[moved.id]
        version = chapters.list_versions(moved.id)
        assert len(version) == 1
        assert version[0].revision == original.revision
        assert version[0].source == "metadata_change"
        assert version[0].reason == "chapter relocated by volume deletion"
        assert (
            project.layout.root / version[0].content_snapshot_path
        ).read_bytes() == original_bytes[moved.id]
    with project.database.connect() as connection:
        formal_statuses = tuple(
            connection.execute(
                """
                SELECT d.status, dep.status, e.status
                FROM memory_documents d
                JOIN memory_dependencies dep
                  ON dep.memory_type = 'SEARCH' AND dep.memory_id = d.id
                JOIN memory_embeddings e ON e.document_id = d.id
                WHERE d.id = ?
                """,
                (formal.id,),
            ).fetchone()
        )
    assert formal_statuses == ("STALE", "STALE", "STALE")
    assert search.get(legacy.id).status.value == "STALE"


def test_delete_volume_rolls_back_all_chapters_when_later_invalidation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters = _repositories(tmp_path)
    target = project.list_volumes()[0]
    source = project.create_volume("Part Two")
    first = chapters.create_chapter(source.id, "Opening", "1", "first")
    second = chapters.create_chapter(source.id, "Follow-up", "2", "second")
    search = SearchRepository(project)
    identity = EmbeddingIndexIdentity("provider", "model", 1)
    formal_ids: list[str] = []
    for chapter, content in ((first, "first"), (second, "second")):
        maintained = ChapterRevisionService(project).maintain_current_revision(
            chapter.id,
            expected_revision=chapter.revision,
            expected_source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        formal = search.read_formal_manuscript_chunks(
            chapter.id,
            expected_revision=chapter.revision,
            expected_source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            chunk_policy_version=maintained.policy_version,
        )[0]
        formal_ids.append(formal.id)
        embedding_source = search.embedding_source(formal.id)
        search.save_embedding(
            formal.id,
            identity,
            (1.0, 0.0),
            expected_content_hash=embedding_source.content_hash,
        )
    original_paths = {
        chapter.id: project.layout.root / chapter.content_path for chapter in (first, second)
    }
    real_invalidate = ViewAssertionRepository.invalidate_source_revision_in_connection
    calls = 0

    def fail_second(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected relocation invalidation failure")
        return real_invalidate(*args, **kwargs)

    monkeypatch.setattr(
        ViewAssertionRepository,
        "invalidate_source_revision_in_connection",
        fail_second,
    )

    with pytest.raises(RuntimeError, match="injected relocation invalidation failure"):
        chapters.delete_volume(source.id, target.id)

    assert [volume.id for volume in project.list_volumes()] == [target.id, source.id]
    for original in (first, second):
        assert chapters.get_chapter(original.id) == original
        assert original_paths[original.id].read_text(encoding="utf-8") in {"first", "second"}
        assert chapters.list_versions(original.id) == []
    with project.database.connect() as connection:
        statuses = connection.execute(
            """
            SELECT d.status, dep.status, e.status
            FROM memory_documents d
            JOIN memory_dependencies dep
              ON dep.memory_type = 'SEARCH' AND dep.memory_id = d.id
            JOIN memory_embeddings e ON e.document_id = d.id
            WHERE d.id IN (?, ?)
            ORDER BY d.id
            """,
            tuple(formal_ids),
        ).fetchall()
    assert [tuple(row) for row in statuses] == [
        ("CURRENT", "CURRENT", "CURRENT"),
        ("CURRENT", "CURRENT", "CURRENT"),
    ]
    target_directory = project.layout.manuscript / f"volume_{target.id}"
    assert not any(target_directory.glob(f"chapter_{first.id}.md"))
    assert not any(target_directory.glob(f"chapter_{second.id}.md"))


def test_delete_volume_rejects_deleted_source_chapters_before_moving(
    tmp_path: Path,
) -> None:
    project, chapters = _repositories(tmp_path)
    target = project.list_volumes()[0]
    source = project.create_volume("Part Two")
    active = chapters.create_chapter(source.id, "Opening", "1", "active")
    deleted = chapters.create_chapter(source.id, "Deleted", "2", "deleted")
    chapters.delete_chapter(deleted.id)
    active_path = project.layout.root / active.content_path

    with pytest.raises(RuntimeError, match="deleted chapters"):
        chapters.delete_volume(source.id, target.id)

    assert chapters.get_chapter(active.id) == active
    assert active_path.read_text(encoding="utf-8") == "active"
    assert [volume.id for volume in project.list_volumes()] == [target.id, source.id]


def test_delete_volume_rejects_a_stale_expected_source_identity(
    tmp_path: Path,
) -> None:
    project, chapters = _repositories(tmp_path)
    target = project.list_volumes()[0]
    source = project.create_volume("Part Two")
    chapter = chapters.create_chapter(source.id, "Opening", "1", "body")
    canonical = project.layout.root / chapter.content_path

    with pytest.raises(RuntimeError, match="chapters changed"):
        chapters.delete_volume(
            source.id,
            target.id,
            expected_sources=(
                ChapterRelocationExpectation(
                    chapter.id,
                    chapter.revision + 1,
                    hashlib.sha256(b"body").hexdigest(),
                ),
            ),
        )

    assert chapters.get_chapter(chapter.id) == chapter
    assert canonical.read_text(encoding="utf-8") == "body"
    assert [volume.id for volume in project.list_volumes()] == [target.id, source.id]


def test_volume_cannot_be_deleted_into_itself(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    volume = project.list_volumes()[0]

    with pytest.raises(ValueError, match="different"):
        chapters.delete_volume(volume.id, volume.id)


def test_failed_save_restores_crlf_content_byte_identically(tmp_path: Path) -> None:
    import sqlite3

    project, chapters = _repositories(tmp_path)
    content = "first line\r\nemoji \U0001f600\r\n"
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        content,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "CREATE TRIGGER fail_chapter_update BEFORE UPDATE ON chapters "
            "BEGIN SELECT RAISE(ABORT, 'RAW_TRIGGER'); END"
        )

    with pytest.raises(sqlite3.IntegrityError):
        chapters.save_content(
            chapter.id,
            "new text",
            source="manual",
            reason="failed save",
        )

    assert chapters.read_content_exact(chapter.id) == content
    stored = chapters.get_chapter(chapter.id)
    assert stored.revision == 0
    with project.database.connect() as connection:
        row = connection.execute(
            "SELECT content_hash FROM chapters WHERE id = ?", (chapter.id,)
        ).fetchone()
        canonical = (project.layout.root / stored.content_path).read_bytes()
    assert row is not None
    assert str(row["content_hash"]) == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert canonical == content.encode("utf-8")


_RESTORE_BODY = "第一章\r\n\r\n艾琳在旧塔发现了铜钥匙🔑。\r\n守卫没有察觉。\r\n"


def _restore_fixture(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "project", "restore 验证")
    revisions = ChapterRevisionService(project)
    submitted = revisions.submit_creation(
        project.list_volumes()[0].id, "第一章", "1", _RESTORE_BODY
    )
    chapters = ChapterRepository(project)
    chapters.delete_chapter(submitted.chapter.id)
    trash = (
        project.layout.root
        / ".ai_pipeline"
        / "trash"
        / f"chapter_{submitted.chapter.id}_r{submitted.chapter.revision}.md"
    )
    return project, chapters, submitted.chapter.id, trash


def test_restore_rejects_tampered_trash_and_keeps_deleted(tmp_path: Path) -> None:
    project, chapters, chapter_id, trash = _restore_fixture(tmp_path)
    trash.write_text("被篡改的正文。", encoding="utf-8")

    with pytest.raises(RuntimeError, match="chapter restore source changed"):
        chapters.restore_chapter(chapter_id)

    assert chapters.get_chapter(chapter_id).is_deleted is True
    assert trash.read_text(encoding="utf-8") == "被篡改的正文。"
    assert not (project.layout.root / ".ai_pipeline" / "chapters").exists() or all(
        item.suffix == ".md" and "tampered" not in item.name
        for item in (project.layout.root / ".ai_pipeline" / "chapters").rglob("*")
    )


def test_restore_rejects_missing_and_invalid_utf8_trash(tmp_path: Path) -> None:
    _project, chapters, chapter_id, trash = _restore_fixture(tmp_path)

    missing = trash.with_name(trash.name + ".gone")
    trash.rename(missing)
    with pytest.raises(RuntimeError, match="chapter restore source is missing"):
        chapters.restore_chapter(chapter_id)
    missing.rename(trash)

    trash.write_bytes(b"\xff\xfe\x00broken")
    with pytest.raises(RuntimeError, match="chapter restore source is invalid"):
        chapters.restore_chapter(chapter_id)
    assert chapters.get_chapter(chapter_id).is_deleted is True


def test_restore_rejects_trash_outside_project_trash_boundary(
    tmp_path: Path,
) -> None:
    project, chapters, chapter_id, trash = _restore_fixture(tmp_path)
    escaped = project.layout.root / "escaped-body.md"
    trash.replace(escaped)
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE chapters SET deleted_content_path = 'escaped-body.md' WHERE id = ?",
            (chapter_id,),
        )

    with pytest.raises(RuntimeError, match="chapter restore source is invalid"):
        chapters.restore_chapter(chapter_id)

    assert escaped.exists()
    assert not trash.exists()
    assert chapters.get_chapter(chapter_id).is_deleted is True


def test_restore_database_failure_rolls_file_back_to_trash(
    tmp_path: Path,
) -> None:
    import sqlite3

    project, chapters, chapter_id, trash = _restore_fixture(tmp_path)
    with project.database.connect() as connection, connection:
        connection.execute(
            "CREATE TRIGGER fail_chapter_update BEFORE UPDATE ON chapters "
            "BEGIN SELECT RAISE(ABORT, 'RAW_TRIGGER'); END"
        )

    canonical = Path(project.layout.root) / chapters.get_chapter(chapter_id).content_path

    with pytest.raises(sqlite3.IntegrityError):
        chapters.restore_chapter(chapter_id)

    assert trash.exists()
    assert not canonical.exists()
    assert chapters.get_chapter(chapter_id).is_deleted is True


def test_restored_content_matches_exact_verified_bytes(tmp_path: Path) -> None:
    project, chapters, chapter_id, trash = _restore_fixture(tmp_path)

    restored = chapters.restore_chapter(chapter_id)

    assert restored.is_deleted is False
    actual = chapters.read_content_exact(chapter_id)
    assert actual == _RESTORE_BODY
    with project.database.connect() as connection:
        stored_hash = connection.execute(
            "SELECT content_hash FROM chapters WHERE id = ?", (chapter_id,)
        ).fetchone()["content_hash"]
    assert hashlib.sha256(actual.encode("utf-8")).hexdigest() == stored_hash
    assert not trash.exists()


def test_restore_rejects_race_tamper_between_validation_and_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_novel_studio.infrastructure.storage.chapter_repository as restore_module

    project, chapters, chapter_id, trash = _restore_fixture(tmp_path)
    canonical = chapters._resolve_manuscript_path(chapters.get_chapter(chapter_id).content_path)
    real_replace = restore_module.os.replace
    calls = {"n": 0}

    def racing_replace(src, dst, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            Path(src).write_text("竞争后篡改字节。", encoding="utf-8")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(restore_module.os, "replace", racing_replace)

    with pytest.raises(RuntimeError, match="chapter restore source changed"):
        chapters.restore_chapter(chapter_id)

    assert calls["n"] == 2
    assert chapters.get_chapter(chapter_id).is_deleted is True
    assert not canonical.exists()
    assert trash.read_text(encoding="utf-8") == "竞争后篡改字节。"
    with project.database.connect() as connection:
        row = connection.execute(
            "SELECT revision, content_hash, deleted_content_path FROM chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
    assert int(row["revision"]) == submitted_revision(chapters, chapter_id)
    assert row["content_hash"] == hashlib.sha256(_RESTORE_BODY.encode("utf-8")).hexdigest()
    assert row["deleted_content_path"]


def test_restore_sanitizes_invalid_utf8_race_after_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_novel_studio.infrastructure.storage.chapter_repository as restore_module

    _project, chapters, chapter_id, trash = _restore_fixture(tmp_path)
    canonical = chapters._resolve_manuscript_path(chapters.get_chapter(chapter_id).content_path)
    real_replace = restore_module.os.replace
    calls = {"n": 0}

    def racing_replace(src, dst, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            Path(src).write_bytes(b"\xff\xfe\x00broken")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(restore_module.os, "replace", racing_replace)

    with pytest.raises(RuntimeError) as caught:
        chapters.restore_chapter(chapter_id)

    assert str(caught.value) == "chapter restore source is invalid"
    assert calls["n"] == 2
    assert chapters.get_chapter(chapter_id).is_deleted is True
    assert not canonical.exists()
    assert trash.read_bytes() == b"\xff\xfe\x00broken"


def submitted_revision(chapters: ChapterRepository, chapter_id: str) -> int:
    with chapters.project.database.connect() as connection:
        row = connection.execute(
            "SELECT revision FROM chapters WHERE id = ?", (chapter_id,)
        ).fetchone()
    assert row is not None
    return int(row["revision"])


def test_restore_rejects_canonical_escape_outside_manuscript(
    tmp_path: Path,
) -> None:
    project, chapters, chapter_id, trash = _restore_fixture(tmp_path)
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE chapters SET content_path = '../escaped.md' WHERE id = ?",
            (chapter_id,),
        )

    with pytest.raises(RuntimeError, match="outside manuscript directory"):
        chapters.restore_chapter(chapter_id)

    escaped_sibling = project.layout.root.parent / "escaped.md"
    assert not escaped_sibling.exists()
    assert not (project.layout.root / "escaped.md").exists()
    assert trash.exists()
    assert chapters.get_chapter(chapter_id).is_deleted is True


def test_restore_cas_rejects_identity_drift_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters, chapter_id, trash = _restore_fixture(tmp_path)
    canonical = chapters._resolve_manuscript_path(chapters.get_chapter(chapter_id).content_path)
    real_connect = project.database.connect
    state = {"drifted": False}

    class _DriftConnection:
        def __init__(self, real) -> None:  # type: ignore[no-untyped-def]
            self._real = real

        def execute(self, statement, *args):  # type: ignore[no-untyped-def]
            cursor = self._real.execute(statement, *args)
            if not state["drifted"] and statement.lstrip().upper().startswith("SELECT REVISION"):
                state["drifted"] = True
                self._real.execute(
                    "UPDATE chapters SET deleted_content_path = "
                    "'.ai_pipeline/trash/diverted.md' WHERE id = ?",
                    (chapter_id,),
                )
                self._real.commit()
            return cursor

        def commit(self) -> None:
            self._real.commit()

        def rollback(self) -> None:
            self._real.rollback()

        def close(self) -> None:
            self._real.close()

    monkeypatch.setattr(
        type(project.database),
        "connect",
        staticmethod(lambda: _DriftConnection(real_connect())),
    )

    with pytest.raises(RuntimeError, match="chapter changed before restore"):
        chapters.restore_chapter(chapter_id)

    monkeypatch.undo()

    assert chapters.get_chapter(chapter_id).is_deleted is True
    assert not canonical.exists()
    assert trash.read_bytes() == _RESTORE_BODY.encode("utf-8")
    with project.database.connect() as connection:
        row = connection.execute(
            "SELECT content_hash, deleted_content_path FROM chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
    assert row["content_hash"] == hashlib.sha256(_RESTORE_BODY.encode("utf-8")).hexdigest()
    assert row["deleted_content_path"] == ".ai_pipeline/trash/diverted.md"
    assert row["content_hash"] == hashlib.sha256(_RESTORE_BODY.encode("utf-8")).hexdigest()
    assert row["deleted_content_path"]
