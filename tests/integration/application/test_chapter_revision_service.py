from __future__ import annotations

import hashlib
from dataclasses import fields
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterMutationKind,
    ChapterRevisionService,
    FormalMaintenanceFailure,
    FormalMaintenanceFailureCode,
    FormalMaintenanceResult,
    FormalMaintenanceStatus,
    FormalRecoveryCursor,
    FormalRecoveryReport,
    RevisionImpact,
    RevisionSourceIdentity,
    SubmittedRevision,
    SubmittedTitleRevision,
)
from ai_novel_studio.core.context.manuscript_chunking import (
    DEFAULT_MANUSCRIPT_CHUNK_POLICY,
    project_formal_manuscript_chunks,
)
from ai_novel_studio.domain.embedding import EmbeddingIndexIdentity
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRepository,
    StaleChapterRevisionError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository

_EMBEDDING_IDENTITY = EmbeddingIndexIdentity("provider-a", "embedding-model", 1)


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _project_with_chapter(
    tmp_path: Path,
    *,
    content: str,
) -> tuple[ProjectRepository, ChapterRepository, str]:
    project = ProjectRepository.create(tmp_path / "novel", "Revision maintenance")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        content,
    )
    return project, chapters, chapter.id


def test_revision_contract_dtos_reject_invalid_or_leaky_states() -> None:
    source = RevisionSourceIdentity(2, "a" * 64, is_deleted=False)
    impact = RevisionImpact(
        ChapterMutationKind.CONTENT,
        "00000000-0000-0000-0000-000000000001",
        RevisionSourceIdentity(1, "b" * 64, is_deleted=False),
        source,
        manuscript_committed=True,
        semantic_memory_invalidated=False,
    )
    failure = FormalMaintenanceFailure(
        FormalMaintenanceFailureCode.REPAIR_FAILED
    )

    assert impact.after == source
    assert failure.message == "formal manuscript projection requires recovery"
    assert [field.name for field in fields(FormalMaintenanceFailure)] == ["code"]
    assert all(
        forbidden not in {field.name for field in fields(RevisionImpact)}
        for forbidden in ("content", "body", "path", "exception", "api_key")
    )

    with pytest.raises(ValueError):
        RevisionSourceIdentity(True, "a" * 64, is_deleted=False)
    with pytest.raises(ValueError):
        RevisionSourceIdentity(0, "not-a-hash", is_deleted=False)
    with pytest.raises(ValueError):
        RevisionImpact(
            ChapterMutationKind.CREATE,
            impact.chapter_id,
            source,
            source,
            manuscript_committed=True,
            semantic_memory_invalidated=False,
        )
    with pytest.raises(ValueError):
        FormalMaintenanceResult(
            impact.chapter_id,
            source,
            FormalMaintenanceStatus.CURRENT,
            DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
            chunk_count=1,
            recovery_required=True,
            failure=failure,
        )
    with pytest.raises(ValueError):
        FormalRecoveryCursor("not-an-id")
    with pytest.raises(ValueError):
        FormalRecoveryReport(
            scanned_chapters=1,
            current_chapters=0,
            repaired_chapters=0,
            removed_chapters=0,
            pending_chapters=0,
            failed_chapters=0,
            failures=(),
            cancelled=False,
            next_cursor=None,
        )


def test_submit_revision_rejects_stale_cas_before_write_or_index(
    tmp_path: Path,
) -> None:
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content="old authoritative text",
    )
    service = ChapterRevisionService(project)

    with pytest.raises(StaleChapterRevisionError):
        service.submit_revision(
            chapter_id,
            "new text must not be written",
            source="manual",
            reason="stale test",
            expected_revision=1,
        )

    chapter = chapters.get_chapter(chapter_id)
    with project.database.connect() as connection:
        formal_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_documents "
                "WHERE document_type = 'FORMAL_MANUSCRIPT' AND chapter_id = ?",
                (chapter_id,),
            ).fetchone()[0]
        )
    assert chapter.revision == 0
    assert chapters.read_content_exact(chapter_id) == "old authoritative text"
    assert chapters.list_versions(chapter_id) == []
    assert formal_count == 0


def test_submit_creation_builds_revision_zero_formal_projection_without_vectors(
    tmp_path: Path,
) -> None:
    content = "第一段😀\r\n\r\n第二段"
    project = ProjectRepository.create(tmp_path / "novel", "Imported revision")
    volume = project.list_volumes()[0]
    service = ChapterRevisionService(project)

    result = service.submit_creation(
        volume.id,
        "Imported chapter",
        "第1章",
        content,
    )

    chapters = ChapterRepository(project)
    search = SearchRepository(project)
    expected_chunks = project_formal_manuscript_chunks(
        result.chapter.id,
        0,
        content,
    )
    stored = search.read_formal_manuscript_chunks(
        result.chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    pending = search.pending_embedding_sources(_EMBEDDING_IDENTITY)
    with project.database.connect() as connection:
        embedding_count = int(
            connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
        )

    assert result.impact == RevisionImpact(
        ChapterMutationKind.CREATE,
        result.chapter.id,
        None,
        RevisionSourceIdentity(0, _source_hash(content), is_deleted=False),
        manuscript_committed=True,
        semantic_memory_invalidated=False,
    )
    assert result.chapter.revision == 0
    assert chapters.read_content_exact(result.chapter.id) == content
    assert chapters.list_versions(result.chapter.id) == []
    assert result.maintenance.status == FormalMaintenanceStatus.REPAIRED
    assert tuple(document.source_id for document in stored) == tuple(
        chunk.source_id for chunk in expected_chunks
    )
    assert all(document.title == "Imported chapter" for document in stored)
    assert all(document.volume_id == volume.id for document in stored)
    assert all(
        document.content == content[document.source_start : document.source_end]
        for document in stored
        if document.source_start is not None and document.source_end is not None
    )
    assert {source.document_id for source in pending} == {
        document.id for document in stored
    }
    assert embedding_count == 0


def test_submit_creation_preserves_whitespace_as_a_successful_empty_projection(
    tmp_path: Path,
) -> None:
    content = " \t\r\n"
    project = ProjectRepository.create(tmp_path / "novel", "Empty import")
    volume = project.list_volumes()[0]

    result = ChapterRevisionService(project).submit_creation(
        volume.id,
        "Empty chapter",
        content=content,
    )

    chapters = ChapterRepository(project)
    stored = SearchRepository(project).read_formal_manuscript_chunks(
        result.chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    assert chapters.read_content_exact(result.chapter.id) == content
    assert result.impact.after == RevisionSourceIdentity(
        0,
        _source_hash(content),
        is_deleted=False,
    )
    assert result.maintenance.status == FormalMaintenanceStatus.CURRENT
    assert result.maintenance.chunk_count == 0
    assert stored == ()
    assert chapters.list_versions(result.chapter.id) == []


def test_submit_creation_sanitizes_failure_and_bounded_recovery_repairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "private imported body"
    project = ProjectRepository.create(tmp_path / "novel", "Recover import")
    volume = project.list_volumes()[0]
    service = ChapterRevisionService(project)

    def fail_maintenance(
        _chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
    ) -> FormalMaintenanceResult:
        raise RuntimeError(
            f"raw failure: {project.layout.root}: {content}: "
            f"{expected_revision}: {expected_source_hash}"
        )

    monkeypatch.setattr(service, "maintain_current_revision", fail_maintenance)

    result = service.submit_creation(
        volume.id,
        "Recoverable import",
        content=content,
    )

    chapters = ChapterRepository(project)
    assert chapters.read_content_exact(result.chapter.id) == content
    assert result.maintenance.status == FormalMaintenanceStatus.PENDING
    assert result.maintenance.recovery_required is True
    assert result.maintenance.failure == FormalMaintenanceFailure(
        FormalMaintenanceFailureCode.REPAIR_FAILED
    )
    assert content not in result.maintenance.failure.message
    assert str(project.layout.root) not in result.maintenance.failure.message

    recovery = ChapterRevisionService(project).recover_current_revisions(limit=100)
    assert recovery.repaired_chapters == 1
    assert recovery.failures == ()
    assert SearchRepository(project).read_formal_manuscript_chunks(
        result.chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )


def test_submit_revision_returns_impact_and_current_formal_without_vectors(
    tmp_path: Path,
) -> None:
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content="old authoritative text",
    )

    result = ChapterRevisionService(project).submit_revision(
        chapter_id,
        "new authoritative text",
        source="manual",
        reason="coordinated save",
        expected_revision=0,
        invalidate_memory=False,
    )

    stored = SearchRepository(project).read_formal_manuscript_chunks(
        chapter_id,
        expected_revision=1,
        expected_source_hash=_source_hash("new authoritative text"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    with project.database.connect() as connection:
        embedding_count = int(
            connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
        )

    assert isinstance(result, SubmittedRevision)
    assert result.chapter == chapters.get_chapter(chapter_id)
    assert result.impact == RevisionImpact(
        ChapterMutationKind.CONTENT,
        chapter_id,
        RevisionSourceIdentity(
            0,
            _source_hash("old authoritative text"),
            is_deleted=False,
        ),
        RevisionSourceIdentity(
            1,
            _source_hash("new authoritative text"),
            is_deleted=False,
        ),
        manuscript_committed=True,
        semantic_memory_invalidated=False,
    )
    assert result.maintenance.status == FormalMaintenanceStatus.REPAIRED
    assert result.maintenance.recovery_required is False
    assert tuple(document.content for document in stored) == (
        "new authoritative text",
    )
    assert embedding_count == 0


def test_submit_revision_reports_superseded_maintenance_without_hiding_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content="revision zero",
    )
    service = ChapterRevisionService(project)
    real_maintain = service.maintain_current_revision

    def race_then_maintain(
        current_chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
    ) -> FormalMaintenanceResult:
        chapters.save_content(
            current_chapter_id,
            "revision two",
            source="concurrent",
            reason="race",
            expected_revision=expected_revision,
        )
        return real_maintain(
            current_chapter_id,
            expected_revision=expected_revision,
            expected_source_hash=expected_source_hash,
        )

    monkeypatch.setattr(
        service,
        "maintain_current_revision",
        race_then_maintain,
    )

    result = service.submit_revision(
        chapter_id,
        "revision one",
        source="manual",
        reason="first writer",
        expected_revision=0,
    )

    assert result.chapter.revision == 1
    assert result.impact.after.revision == 1
    assert result.maintenance.status == FormalMaintenanceStatus.SUPERSEDED
    assert result.maintenance.source.revision == 2
    assert chapters.get_chapter(chapter_id).revision == 2
    assert chapters.read_content_exact(chapter_id) == "revision two"


def test_submit_revision_sanitizes_post_commit_maintenance_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content="old private text",
    )
    service = ChapterRevisionService(project)

    def fail_maintenance(
        _chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
    ) -> FormalMaintenanceResult:
        raise RuntimeError(
            f"raw failure: {project.layout.root}: new private text: "
            f"{expected_revision}: {expected_source_hash}"
        )

    monkeypatch.setattr(
        service,
        "maintain_current_revision",
        fail_maintenance,
    )

    result = service.submit_revision(
        chapter_id,
        "new private text",
        source="manual",
        reason="maintenance failure",
        expected_revision=0,
    )

    assert result.chapter.revision == 1
    assert chapters.read_content_exact(chapter_id) == "new private text"
    assert result.maintenance.status == FormalMaintenanceStatus.PENDING
    assert result.maintenance.recovery_required is True
    assert result.maintenance.failure == FormalMaintenanceFailure(
        FormalMaintenanceFailureCode.REPAIR_FAILED
    )
    assert "private" not in result.maintenance.failure.message
    assert str(project.layout.root) not in result.maintenance.failure.message


def test_submit_title_revision_rebuilds_current_title_and_leaves_embedding_pending(
    tmp_path: Path,
) -> None:
    content = "Title-aware body \U0001f600\r\n"
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content=content,
    )
    chapter = chapters.get_chapter(chapter_id)
    service = ChapterRevisionService(project)
    search = SearchRepository(project)
    service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )
    prior = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0]
    embedding_source = search.embedding_source(prior.id)
    search.save_embedding(
        prior.id,
        _EMBEDDING_IDENTITY,
        (1.0, 0.0),
        expected_content_hash=embedding_source.content_hash,
    )

    result = service.submit_title_revision(chapter.id, "Storm Front")

    assert isinstance(result, SubmittedTitleRevision)
    assert result.revision is not None
    assert result.chapter.title == "Storm Front"
    assert result.chapter.revision == chapter.revision + 1
    assert result.revision.impact == RevisionImpact(
        ChapterMutationKind.RENAME,
        chapter.id,
        RevisionSourceIdentity(0, _source_hash(content), is_deleted=False),
        RevisionSourceIdentity(1, _source_hash(content), is_deleted=False),
        manuscript_committed=True,
        semantic_memory_invalidated=True,
    )
    assert result.revision.maintenance.status == FormalMaintenanceStatus.REPAIRED
    current = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=1,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    pending = search.pending_embedding_sources(_EMBEDDING_IDENTITY, limit=10)
    with project.database.connect() as connection:
        prior_current_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_documents WHERE id = ? AND status = 'CURRENT'",
                (prior.id,),
            ).fetchone()[0]
        )
        embedding_count = int(
            connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
        )
    assert current
    assert all(document.title == "Storm Front" for document in current)
    assert all(document.source_revision == 1 for document in current)
    assert {source.document_id for source in pending} == {
        document.id for document in current
    }
    assert prior_current_count == 0
    assert embedding_count == 0


def test_submit_title_revision_failure_commits_and_bounded_recovery_repairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "private title-aware body"
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content=content,
    )
    chapter = chapters.get_chapter(chapter_id)
    service = ChapterRevisionService(project)
    search = SearchRepository(project)
    service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )
    prior = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0]
    embedding_source = search.embedding_source(prior.id)
    search.save_embedding(
        prior.id,
        _EMBEDDING_IDENTITY,
        (1.0, 0.0),
        expected_content_hash=embedding_source.content_hash,
    )

    def fail_maintenance(
        _chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
    ) -> FormalMaintenanceResult:
        raise RuntimeError(
            f"raw title maintenance failure: {project.layout.root}: {content}: "
            f"{expected_revision}: {expected_source_hash}"
        )

    monkeypatch.setattr(service, "maintain_current_revision", fail_maintenance)

    result = service.submit_title_revision(chapter.id, "Private New Title")

    assert result.revision is not None
    assert result.chapter.title == "Private New Title"
    assert result.chapter.revision == 1
    assert result.revision.maintenance.status == FormalMaintenanceStatus.PENDING
    assert result.revision.maintenance.failure == FormalMaintenanceFailure(
        FormalMaintenanceFailureCode.REPAIR_FAILED
    )
    assert content not in result.revision.maintenance.failure.message
    assert str(project.layout.root) not in result.revision.maintenance.failure.message
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
                (prior.id,),
            ).fetchone()
        )
    assert statuses == ("STALE", "STALE", "STALE")

    monkeypatch.undo()
    report = service.recover_current_revisions(limit=10)
    repaired = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=1,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    assert report.repaired_chapters == 1
    assert all(document.title == "Private New Title" for document in repaired)
    assert chapters.get_chapter(chapter.id).revision == 1
    assert len(chapters.list_versions(chapter.id)) == 1


def test_submit_same_title_revision_skips_formal_maintenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content="unchanged body",
    )
    chapter = chapters.get_chapter(chapter_id)
    service = ChapterRevisionService(project)

    def unexpected_maintenance(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("same-title request must not maintain Formal projection")

    monkeypatch.setattr(service, "maintain_current_revision", unexpected_maintenance)

    result = service.submit_title_revision(chapter.id, "  Opening  ")

    assert result == SubmittedTitleRevision(chapter, revision=None)
    assert chapters.list_versions(chapter.id) == []


def test_submit_title_revision_does_not_reinstall_a_superseded_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "stable body"
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content=content,
    )
    service = ChapterRevisionService(project)
    service.maintain_current_revision(
        chapter_id,
        expected_revision=0,
        expected_source_hash=_source_hash(content),
    )
    real_maintain = service.maintain_current_revision

    def rename_again_then_maintain(
        current_chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
    ) -> FormalMaintenanceResult:
        chapters.rename_chapter(current_chapter_id, "Newest Title")
        return real_maintain(
            current_chapter_id,
            expected_revision=expected_revision,
            expected_source_hash=expected_source_hash,
        )

    monkeypatch.setattr(
        service,
        "maintain_current_revision",
        rename_again_then_maintain,
    )

    result = service.submit_title_revision(chapter_id, "Intermediate Title")

    assert result.revision is not None
    assert result.chapter.title == "Intermediate Title"
    assert result.chapter.revision == 1
    assert result.revision.maintenance.status == FormalMaintenanceStatus.SUPERSEDED
    assert result.revision.maintenance.source.revision == 2
    latest = chapters.get_chapter(chapter_id)
    assert latest.title == "Newest Title"
    assert latest.revision == 2
    with project.database.connect() as connection:
        intermediate_current = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM memory_documents
                WHERE document_type = 'FORMAL_MANUSCRIPT' AND chapter_id = ?
                  AND source_revision = 1 AND status = 'CURRENT'
                """,
                (chapter_id,),
            ).fetchone()[0]
        )
    assert intermediate_current == 0


def test_maintain_missing_projection_builds_exact_crlf_chunks_without_vectors(
    tmp_path: Path,
) -> None:
    content = "第一段😀\r\n\r\n第二段"
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content=content,
    )
    chapter = chapters.get_chapter(chapter_id)
    search = SearchRepository(project)

    result = ChapterRevisionService(project).maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )

    stored = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    pending = search.pending_embedding_sources(_EMBEDDING_IDENTITY, limit=10)
    with project.database.connect() as connection:
        embedding_count = int(
            connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
        )

    assert result.status == FormalMaintenanceStatus.REPAIRED
    assert result.chunk_count == 1
    assert result.recovery_required is False
    assert result.failure is None
    assert stored[0].content == content
    assert stored[0].source_start == 0
    assert stored[0].source_end == len(content)
    assert {source.document_id for source in pending}.issuperset(
        document.id for document in stored
    )
    assert embedding_count == 0


def test_exact_maintenance_is_noop_for_document_vector_fts_and_dependency(
    tmp_path: Path,
) -> None:
    content = "Exact current projection"
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content=content,
    )
    chapter = chapters.get_chapter(chapter_id)
    search = SearchRepository(project)
    service = ChapterRevisionService(project)
    first = service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )
    documents = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    source = search.embedding_source(documents[0].id)
    search.save_embedding(
        documents[0].id,
        _EMBEDDING_IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )
    with project.database.connect() as connection:
        before = (
            tuple(
                connection.execute(
                    "SELECT id, updated_at FROM memory_documents WHERE id = ?",
                    (documents[0].id,),
                ).fetchone()
            ),
            tuple(
                connection.execute(
                    "SELECT rowid, title, content, participants "
                    "FROM memory_fts WHERE document_id = ?",
                    (documents[0].id,),
                ).fetchone()
            ),
            tuple(
                connection.execute(
                    "SELECT id, source_revision, source_hash, status "
                    "FROM memory_dependencies "
                    "WHERE memory_type = 'SEARCH' AND memory_id = ?",
                    (documents[0].id,),
                ).fetchone()
            ),
        )

    second = service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )
    with project.database.connect() as connection:
        after = (
            tuple(
                connection.execute(
                    "SELECT id, updated_at FROM memory_documents WHERE id = ?",
                    (documents[0].id,),
                ).fetchone()
            ),
            tuple(
                connection.execute(
                    "SELECT rowid, title, content, participants "
                    "FROM memory_fts WHERE document_id = ?",
                    (documents[0].id,),
                ).fetchone()
            ),
            tuple(
                connection.execute(
                    "SELECT id, source_revision, source_hash, status "
                    "FROM memory_dependencies "
                    "WHERE memory_type = 'SEARCH' AND memory_id = ?",
                    (documents[0].id,),
                ).fetchone()
            ),
        )

    assert first.status == FormalMaintenanceStatus.REPAIRED
    assert second.status == FormalMaintenanceStatus.CURRENT
    assert after == before
    assert search.get_embedding(
        documents[0].id,
        _EMBEDDING_IDENTITY,
    ).vector == (1.0, 0.0)


@pytest.mark.parametrize(
    "corrupt",
    ["document_status", "document_content", "fts_missing", "dependency_missing"],
)
def test_maintenance_repairs_corrupt_or_incomplete_projection(
    tmp_path: Path,
    corrupt: str,
) -> None:
    content = "Repairable current projection"
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content=content,
    )
    chapter = chapters.get_chapter(chapter_id)
    search = SearchRepository(project)
    service = ChapterRevisionService(project)
    service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )
    prior = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    source = search.embedding_source(prior[0].id)
    search.save_embedding(
        prior[0].id,
        _EMBEDDING_IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )
    with project.database.connect() as connection, connection:
        if corrupt == "document_status":
            connection.execute(
                "UPDATE memory_documents SET status = 'STALE' WHERE id = ?",
                (prior[0].id,),
            )
        elif corrupt == "document_content":
            connection.execute(
                "UPDATE memory_documents SET content = 'corrupt' WHERE id = ?",
                (prior[0].id,),
            )
        elif corrupt == "fts_missing":
            connection.execute(
                "DELETE FROM memory_fts WHERE document_id = ?",
                (prior[0].id,),
            )
        else:
            connection.execute(
                "DELETE FROM memory_dependencies "
                "WHERE memory_type = 'SEARCH' AND memory_id = ?",
                (prior[0].id,),
            )

    result = service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )

    repaired = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    assert result.status == FormalMaintenanceStatus.REPAIRED
    assert repaired[0].content == content
    assert repaired[0].status.value == "CURRENT"
    assert repaired[0].id != prior[0].id
    with pytest.raises(KeyError):
        search.get_embedding(prior[0].id, _EMBEDDING_IDENTITY)


def test_repair_failure_is_sanitized_and_keeps_recovery_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "Repair failure must not expose this body"
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content=content,
    )
    chapter = chapters.get_chapter(chapter_id)
    service = ChapterRevisionService(project)
    service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )
    search = SearchRepository(project)
    prior = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0]
    source = search.embedding_source(prior.id)
    search.save_embedding(
        prior.id,
        _EMBEDDING_IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE memory_documents SET content = 'corrupt' WHERE id = ?",
            (prior.id,),
        )

    def fail_repair(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        raise RuntimeError(
            f"injected repair failure at {project.layout.root}: {content}"
        )

    monkeypatch.setattr(
        service.search,
        "repair_formal_manuscript_chunks",
        fail_repair,
    )

    result = service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )

    assert result.status == FormalMaintenanceStatus.PENDING
    assert result.recovery_required is True
    assert result.failure == FormalMaintenanceFailure(
        FormalMaintenanceFailureCode.REPAIR_FAILED
    )
    assert content not in result.failure.message
    assert str(project.layout.root) not in result.failure.message
    with project.database.connect() as connection:
        document = connection.execute(
            "SELECT status, content FROM memory_documents WHERE id = ?",
            (prior.id,),
        ).fetchone()
        dependency_status = str(
            connection.execute(
                "SELECT status FROM memory_dependencies "
                "WHERE memory_type = 'SEARCH' AND memory_id = ?",
                (prior.id,),
            ).fetchone()["status"]
        )
        embedding_status = str(
            connection.execute(
                "SELECT status FROM memory_embeddings WHERE document_id = ?",
                (prior.id,),
            ).fetchone()["status"]
        )
    assert tuple(document) == ("STALE", "corrupt")
    assert dependency_status == "STALE"
    assert embedding_status == "STALE"


def test_whitespace_maintenance_removes_only_formal_projection(
    tmp_path: Path,
) -> None:
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content="Prior formal body",
    )
    chapter = chapters.get_chapter(chapter_id)
    search = SearchRepository(project)
    service = ChapterRevisionService(project)
    service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash("Prior formal body"),
    )
    legacy = search.index_chapter(chapter.id, chapter.title, "Prior formal body")
    general = search.index_document(
        document_type="CANON",
        source_id="general-memory",
        chapter_id=None,
        title="General",
        content="General memory",
        participants=(),
        pinned_weight=0,
        review_status=legacy.review_status,
        status=legacy.status,
    )
    current = chapters.save_content(
        chapter.id,
        " \r\n\t ",
        source="manual",
        reason="clear",
    )

    result = service.maintain_current_revision(
        current.id,
        expected_revision=current.revision,
        expected_source_hash=_source_hash(" \r\n\t "),
    )

    assert result.status == FormalMaintenanceStatus.REPAIRED
    assert result.chunk_count == 0
    assert (
        search.read_formal_manuscript_chunks(
            current.id,
            expected_revision=current.revision,
            expected_source_hash=_source_hash(" \r\n\t "),
            chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
        )
        == ()
    )
    assert search.get(legacy.id).document_type == "CHAPTER"
    assert search.get(general.id) == general


def test_concurrent_newer_revision_supersedes_old_maintenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content="revision zero",
    )
    chapter = chapters.get_chapter(chapter_id)
    service = ChapterRevisionService(project)
    service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash("revision zero"),
    )
    current = chapters.save_content(
        chapter.id,
        "revision one",
        source="manual",
        reason="first rewrite",
    )
    real_repair = service.search.repair_formal_manuscript_chunks

    def race_then_repair(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        chapters.save_content(
            chapter.id,
            "revision two",
            source="manual",
            reason="concurrent rewrite",
            expected_revision=current.revision,
        )
        return real_repair(*args, **kwargs)

    monkeypatch.setattr(
        service.search,
        "repair_formal_manuscript_chunks",
        race_then_repair,
    )

    result = service.maintain_current_revision(
        current.id,
        expected_revision=current.revision,
        expected_source_hash=_source_hash("revision one"),
    )

    assert result.status == FormalMaintenanceStatus.SUPERSEDED
    assert result.failure == FormalMaintenanceFailure(
        FormalMaintenanceFailureCode.SOURCE_SUPERSEDED
    )
    with project.database.connect() as connection:
        current_formal = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_documents "
                "WHERE document_type = 'FORMAL_MANUSCRIPT' "
                "AND chapter_id = ? AND status = 'CURRENT'",
                (chapter.id,),
            ).fetchone()[0]
        )
    assert current_formal == 0


def test_bounded_recovery_cursor_reaches_later_missing_projection(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Bounded recovery")
    chapters = ChapterRepository(project)
    volume_id = project.list_volumes()[0].id
    chapter_ids = [
        chapters.create_chapter(volume_id, f"Chapter {index}", str(index), f"body {index}").id
        for index in range(3)
    ]
    ordered_ids = sorted(chapter_ids)
    exact = chapters.get_chapter(ordered_ids[0])
    service = ChapterRevisionService(project)
    search = SearchRepository(project)
    service.maintain_current_revision(
        exact.id,
        expected_revision=exact.revision,
        expected_source_hash=_source_hash(chapters.read_content_exact(exact.id)),
    )
    exact_document = search.read_formal_manuscript_chunks(
        exact.id,
        expected_revision=exact.revision,
        expected_source_hash=_source_hash(chapters.read_content_exact(exact.id)),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0]
    whitespace = chapters.save_content(
        ordered_ids[1],
        " \r\n\t ",
        source="manual",
        reason="clear",
    )
    with project.database.connect() as connection:
        exact_before = tuple(
            connection.execute(
                "SELECT id, updated_at FROM memory_documents WHERE id = ?",
                (exact_document.id,),
            ).fetchone()
        )

    first = service.recover_current_revisions(limit=1)
    second = service.recover_current_revisions(limit=1, cursor=first.next_cursor)
    third = service.recover_current_revisions(limit=1, cursor=second.next_cursor)

    with project.database.connect() as connection:
        exact_after = tuple(
            connection.execute(
                "SELECT id, updated_at FROM memory_documents WHERE id = ?",
                (exact_document.id,),
            ).fetchone()
        )
    missing = chapters.get_chapter(ordered_ids[2])
    repaired = search.read_formal_manuscript_chunks(
        missing.id,
        expected_revision=missing.revision,
        expected_source_hash=_source_hash(chapters.read_content_exact(missing.id)),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )

    assert first == first.__class__(
        scanned_chapters=1,
        current_chapters=1,
        repaired_chapters=0,
        removed_chapters=0,
        pending_chapters=0,
        failed_chapters=0,
        failures=(),
        cancelled=False,
        next_cursor=FormalRecoveryCursor(ordered_ids[0]),
    )
    assert second.current_chapters == 1
    assert second.next_cursor == FormalRecoveryCursor(whitespace.id)
    assert third.repaired_chapters == 1
    assert third.next_cursor is None
    assert exact_after == exact_before
    assert repaired


def test_recovery_cancellation_stops_between_chapter_transactions(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Recovery cancellation")
    chapters = ChapterRepository(project)
    volume_id = project.list_volumes()[0].id
    ordered_ids = sorted(
        chapters.create_chapter(volume_id, title, "", title).id
        for title in ("First", "Second")
    )
    checks = 0

    def should_cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    report = ChapterRevisionService(project).recover_current_revisions(
        limit=2,
        should_cancel=should_cancel,
    )

    assert report.scanned_chapters == 1
    assert report.repaired_chapters == 1
    assert report.cancelled is True
    assert report.next_cursor == FormalRecoveryCursor(ordered_ids[0])


@pytest.mark.parametrize("source_state", ["deleted", "missing"])
def test_recovery_removes_orphaned_formal_rows_only(
    tmp_path: Path,
    source_state: str,
) -> None:
    content = "Deleted chapter evidence"
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content=content,
    )
    chapter = chapters.get_chapter(chapter_id)
    search = SearchRepository(project)
    service = ChapterRevisionService(project)
    service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )
    formal = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0]
    legacy = search.index_chapter(chapter.id, chapter.title, content)
    if source_state == "deleted":
        chapters.delete_chapter(chapter.id)
    else:
        with project.database.connect() as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            with connection:
                connection.execute(
                    "DELETE FROM chapters WHERE id = ?",
                    (chapter.id,),
                )

    report = service.recover_current_revisions(limit=100)

    assert report.removed_chapters == 1
    assert report.failures == ()
    with pytest.raises(KeyError):
        search.get(formal.id)
    assert search.get(legacy.id).document_type == "CHAPTER"


def test_title_revision_rebuilds_projection_under_new_deterministic_identity(
    tmp_path: Path,
) -> None:
    content = "Title-aware embedding input"
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content=content,
    )
    chapter = chapters.get_chapter(chapter_id)
    search = SearchRepository(project)
    service = ChapterRevisionService(project)
    service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )
    prior = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    source = search.embedding_source(prior[0].id)
    search.save_embedding(
        prior[0].id,
        _EMBEDDING_IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )
    renamed = chapters.rename_chapter(chapter.id, "Renamed")

    result = service.maintain_current_revision(
        renamed.id,
        expected_revision=renamed.revision,
        expected_source_hash=_source_hash(content),
    )

    current = search.read_formal_manuscript_chunks(
        renamed.id,
        expected_revision=renamed.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    assert renamed.revision == chapter.revision + 1
    assert result.status == FormalMaintenanceStatus.REPAIRED
    assert current
    assert all(document.title == "Renamed" for document in current)
    assert all(document.source_revision == renamed.revision for document in current)
    assert all(document.id != prior[0].id for document in current)
    with project.database.connect() as connection:
        prior_document_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_documents WHERE id = ?",
                (prior[0].id,),
            ).fetchone()[0]
        )
        prior_dependency_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_dependencies "
                "WHERE memory_type = 'SEARCH' AND memory_id = ?",
                (prior[0].id,),
            ).fetchone()[0]
        )
        prior_embedding_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_embeddings WHERE document_id = ?",
                (prior[0].id,),
            ).fetchone()[0]
        )
    assert prior_document_count == 0
    assert prior_dependency_count == 0
    assert prior_embedding_count == 0


def test_source_race_during_pre_repair_invalidation_preserves_newer_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters, chapter_id = _project_with_chapter(
        tmp_path,
        content="revision zero",
    )
    chapter = chapters.get_chapter(chapter_id)
    service = ChapterRevisionService(project)
    service.maintain_current_revision(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash("revision zero"),
    )
    revision_one = chapters.save_content(
        chapter.id,
        "revision one",
        source="manual",
        reason="first rewrite",
    )
    service.maintain_current_revision(
        revision_one.id,
        expected_revision=revision_one.revision,
        expected_source_hash=_source_hash("revision one"),
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE memory_documents SET content = 'corrupt revision one' "
            "WHERE document_type = 'FORMAL_MANUSCRIPT' AND chapter_id = ?",
            (chapter.id,),
        )
    real_invalidate = service.search.invalidate_formal_manuscript_chunks
    newer_revision = None

    def race_then_invalidate(*args: object, **kwargs: object) -> int:
        nonlocal newer_revision
        newer_revision = chapters.save_content(
            chapter.id,
            "revision two",
            source="manual",
            reason="concurrent rewrite",
            expected_revision=revision_one.revision,
        )
        maintained = ChapterRevisionService(project).maintain_current_revision(
            chapter.id,
            expected_revision=newer_revision.revision,
            expected_source_hash=_source_hash("revision two"),
        )
        assert maintained.status == FormalMaintenanceStatus.REPAIRED
        return real_invalidate(*args, **kwargs)

    monkeypatch.setattr(
        service.search,
        "invalidate_formal_manuscript_chunks",
        race_then_invalidate,
    )

    result = service.maintain_current_revision(
        revision_one.id,
        expected_revision=revision_one.revision,
        expected_source_hash=_source_hash("revision one"),
    )

    assert result.status == FormalMaintenanceStatus.SUPERSEDED
    assert newer_revision is not None
    newer = SearchRepository(project).read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=newer_revision.revision,
        expected_source_hash=_source_hash("revision two"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    assert newer
    assert all(document.status.value == "CURRENT" for document in newer)
