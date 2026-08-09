from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

import ai_novel_studio.infrastructure.storage.formal_manuscript_projection as formal_projection
import ai_novel_studio.infrastructure.storage.search_repository as search_module
from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.domain.embedding import EmbeddingIndexIdentity
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import (
    FormalManuscriptChunk,
    SearchRepository,
    formal_manuscript_chunk_source_id,
)

_POLICY = "paragraph-codepoint-v1"
_IDENTITY = EmbeddingIndexIdentity("provider-a", "embedding-model", 1)


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _repositories(
    tmp_path: Path,
    *,
    content: str = "甲😀乙\n第二段证据",
) -> tuple[ProjectRepository, ChapterRepository, SearchRepository, Chapter]:
    project = ProjectRepository.create(tmp_path / "project", "Formal manuscript")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        content,
    )
    return project, chapters, SearchRepository(project), chapter


def _chunk(
    chapter_id: str,
    revision: int,
    ordinal: int,
    start: int,
    end: int,
    content: str,
    *,
    source_id: str | None = None,
    policy: str = _POLICY,
) -> FormalManuscriptChunk:
    return FormalManuscriptChunk(
        source_id
        or formal_manuscript_chunk_source_id(
            chapter_id,
            revision,
            policy,
            ordinal,
        ),
        ordinal,
        start,
        end,
        content[start:end],
    )


def test_formal_chunks_round_trip_exact_unicode_ranges_without_touching_legacy_rows(
    tmp_path: Path,
) -> None:
    project, _chapters, search, chapter = _repositories(tmp_path)
    content = "甲😀乙\n第二段证据"
    legacy = search.index_chapter(chapter.id, chapter.title, content)
    chunks = (
        _chunk(chapter.id, chapter.revision, 0, 0, 3, content),
        _chunk(chapter.id, chapter.revision, 1, 2, len(content), content),
    )

    stored = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
        chunks=chunks,
    )
    reread = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
    )

    assert reread == stored
    assert [document.source_id for document in stored] == [
        chunk.source_id for chunk in chunks
    ]
    assert [
        (
            document.document_type,
            document.source_revision,
            document.source_hash,
            document.source_start,
            document.source_end,
            document.chunk_ordinal,
            document.chunk_policy_version,
            document.content,
        )
        for document in stored
    ] == [
        (
            "FORMAL_MANUSCRIPT",
            chapter.revision,
            _source_hash(content),
            0,
            3,
            0,
            _POLICY,
            "甲😀乙",
        ),
        (
            "FORMAL_MANUSCRIPT",
            chapter.revision,
            _source_hash(content),
            2,
            len(content),
            1,
            _POLICY,
            content[2:],
        ),
    ]
    assert search.get(legacy.id) == legacy
    with project.database.connect() as connection:
        fts_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT document_id FROM memory_fts WHERE memory_fts MATCH ?",
                ("第二段证据",),
            )
        }
        dependencies = {
            (str(row[0]), int(row[1]), str(row[2]))
            for row in connection.execute(
                """
                SELECT memory_id, source_revision, source_hash
                FROM memory_dependencies
                WHERE memory_type = 'SEARCH' AND memory_id IN (?, ?)
                """,
                tuple(document.id for document in stored),
            )
        }
    assert stored[1].id in fts_ids
    assert dependencies == {
        (document.id, chapter.revision, _source_hash(content)) for document in stored
    }


def test_formal_chunks_round_trip_exact_crlf_source_without_normalization(
    tmp_path: Path,
) -> None:
    content = "第一段\r\n\r\n第二段😀\r\n"
    _project, _chapters, search, chapter = _repositories(
        tmp_path,
        content=content,
    )
    chunks = (
        _chunk(chapter.id, chapter.revision, 0, 0, 8, content),
        _chunk(chapter.id, chapter.revision, 1, 6, len(content), content),
    )

    stored = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
        chunks=chunks,
    )

    assert search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
    ) == stored
    assert [document.content for document in stored] == [
        content[0:8],
        content[6:],
    ]


def test_same_revision_replacement_is_idempotent_and_preserves_matching_vectors(
    tmp_path: Path,
) -> None:
    _project, _chapters, search, chapter = _repositories(tmp_path)
    content = "甲😀乙\n第二段证据"
    chunks = (
        _chunk(chapter.id, 0, 0, 0, 3, content),
        _chunk(chapter.id, 0, 1, 4, len(content), content),
    )
    first = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
        chunks=chunks,
    )
    source = search.embedding_source(first[0].id)
    search.save_embedding(
        first[0].id,
        _IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )
    with search.project.database.connect() as connection:
        prior_fts = tuple(
            connection.execute(
                """
                SELECT rowid, title, content, participants
                FROM memory_fts
                WHERE document_id = ?
                """,
                (first[0].id,),
            ).fetchone()
        )
        prior_dependency = tuple(
            connection.execute(
                """
                SELECT * FROM memory_dependencies
                WHERE memory_type = 'SEARCH' AND memory_id = ?
                """,
                (first[0].id,),
            ).fetchone()
        )

    second = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
        chunks=chunks,
    )

    assert second == first
    assert search.get_embedding(first[0].id, _IDENTITY).vector == (1.0, 0.0)
    with search.project.database.connect() as connection:
        replayed_fts = tuple(
            connection.execute(
                """
                SELECT rowid, title, content, participants
                FROM memory_fts
                WHERE document_id = ?
                """,
                (first[0].id,),
            ).fetchone()
        )
        replayed_dependency = tuple(
            connection.execute(
                """
                SELECT * FROM memory_dependencies
                WHERE memory_type = 'SEARCH' AND memory_id = ?
                """,
                (first[0].id,),
            ).fetchone()
        )
    assert replayed_fts == prior_fts
    assert replayed_dependency == prior_dependency


@pytest.mark.parametrize("projection_change", ["range", "title"])
def test_same_deterministic_chunk_identity_rejects_a_changed_projection(
    tmp_path: Path,
    projection_change: str,
) -> None:
    _project, chapters, search, chapter = _repositories(
        tmp_path,
        content="abcdefghij",
    )
    original_chunks = (_chunk(chapter.id, 0, 0, 0, 3, "abcdefghij"),)
    prior = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash("abcdefghij"),
        chunk_policy_version=_POLICY,
        chunks=original_chunks,
    )
    source = search.embedding_source(prior[0].id)
    search.save_embedding(
        prior[0].id,
        _IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )
    prior_embedding = search.get_embedding(prior[0].id, _IDENTITY)
    with search.project.database.connect() as connection:
        prior_fts = tuple(
            connection.execute(
                """
                SELECT rowid, title, content, participants
                FROM memory_fts
                WHERE document_id = ?
                """,
                (prior[0].id,),
            ).fetchone()
        )
        prior_dependency = tuple(
            connection.execute(
                """
                SELECT * FROM memory_dependencies
                WHERE memory_type = 'SEARCH' AND memory_id = ?
                """,
                (prior[0].id,),
            ).fetchone()
        )
    replacement_chunks = original_chunks
    if projection_change == "range":
        replacement_chunks = (_chunk(chapter.id, 0, 0, 3, 6, "abcdefghij"),)
    else:
        chapters.rename_chapter(chapter.id, "Renamed without a revision")

    with pytest.raises(RuntimeError, match="deterministic identity"):
        search.replace_formal_manuscript_chunks(
            chapter.id,
            expected_revision=0,
            expected_source_hash=_source_hash("abcdefghij"),
            chunk_policy_version=_POLICY,
            chunks=replacement_chunks,
        )

    assert search.get(prior[0].id) == prior[0]
    assert search.get_embedding(prior[0].id, _IDENTITY) == prior_embedding
    with search.project.database.connect() as connection:
        current_fts = tuple(
            connection.execute(
                """
                SELECT rowid, title, content, participants
                FROM memory_fts
                WHERE document_id = ?
                """,
                (prior[0].id,),
            ).fetchone()
        )
        current_dependency = tuple(
            connection.execute(
                """
                SELECT * FROM memory_dependencies
                WHERE memory_type = 'SEARCH' AND memory_id = ?
                """,
                (prior[0].id,),
            ).fetchone()
        )
    assert current_fts == prior_fts
    assert current_dependency == prior_dependency


def test_new_revision_replaces_only_formal_rows_and_their_embeddings(
    tmp_path: Path,
) -> None:
    project, chapters, search, chapter = _repositories(tmp_path, content="旧正文证据")
    legacy = search.index_chapter(chapter.id, chapter.title, "旧正文证据")
    general = search.index_document(
        document_type="CANON",
        source_id="general-canon",
        chapter_id=None,
        title="General",
        content="General memory",
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )
    old_chunks = (
        _chunk(chapter.id, 0, 0, 0, len("旧正文证据"), "旧正文证据"),
    )
    old_formal = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash("旧正文证据"),
        chunk_policy_version=_POLICY,
        chunks=old_chunks,
    )
    for document in (old_formal[0], general):
        source = search.embedding_source(document.id)
        search.save_embedding(
            document.id,
            _IDENTITY,
            (1.0, 0.0),
            expected_content_hash=source.content_hash,
        )

    updated = chapters.save_content(
        chapter.id,
        "新正文证据",
        source="manual",
        reason="rewrite",
    )
    new_chunks = (
        _chunk(updated.id, updated.revision, 0, 0, len("新正文证据"), "新正文证据"),
    )
    current = search.replace_formal_manuscript_chunks(
        updated.id,
        expected_revision=updated.revision,
        expected_source_hash=_source_hash("新正文证据"),
        chunk_policy_version=_POLICY,
        chunks=new_chunks,
    )

    assert current[0].content == "新正文证据"
    with pytest.raises(KeyError):
        search.get(old_formal[0].id)
    with pytest.raises(KeyError):
        search.get_embedding(old_formal[0].id, _IDENTITY)
    assert search.get(legacy.id).document_type == "CHAPTER"
    assert search.get(general.id) == general
    assert search.get_embedding(general.id, _IDENTITY).status == MemoryStatus.CURRENT
    with project.database.connect() as connection:
        formal_count = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM memory_documents
                WHERE document_type = 'FORMAL_MANUSCRIPT' AND chapter_id = ?
                """,
                (chapter.id,),
            ).fetchone()[0]
        )
    assert formal_count == 1


@pytest.mark.parametrize(
    ("chunks", "policy", "message"),
    [
        (
            (
                FormalManuscriptChunk("wrong-source-id", 0, 0, 1, "甲"),
            ),
            _POLICY,
            "source ID",
        ),
        (
            (
                FormalManuscriptChunk("duplicate", 0, 0, 1, "甲"),
                FormalManuscriptChunk("duplicate", 1, 1, 2, "😀"),
            ),
            _POLICY,
            "source ID",
        ),
        (
            (
                FormalManuscriptChunk("ordinal-zero", 0, 0, 1, "甲"),
                FormalManuscriptChunk("ordinal-zero-again", 0, 1, 2, "😀"),
            ),
            _POLICY,
            "ordinal",
        ),
        (
            (
                FormalManuscriptChunk("ordinal-one", 1, 0, 1, "甲"),
            ),
            _POLICY,
            "ordinal",
        ),
        (
            (
                FormalManuscriptChunk("bad-range", 0, 2, 2, ""),
            ),
            _POLICY,
            "range",
        ),
        (
            (
                FormalManuscriptChunk("bad-slice", 0, 0, 1, "乙"),
            ),
            _POLICY,
            "slice",
        ),
        (
            (
                FormalManuscriptChunk("bad-policy", 0, 0, 1, "甲"),
            ),
            " ",
            "policy",
        ),
    ],
)
def test_formal_chunk_replacement_rejects_invalid_projection_without_losing_prior_set(
    tmp_path: Path,
    chunks: tuple[FormalManuscriptChunk, ...],
    policy: str,
    message: str,
) -> None:
    _project, _chapters, search, chapter = _repositories(tmp_path)
    content = "甲😀乙\n第二段证据"
    valid_chunks = (_chunk(chapter.id, 0, 0, 0, 3, content),)
    prior = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
        chunks=valid_chunks,
    )

    with pytest.raises((ValueError, RuntimeError), match=message):
        search.replace_formal_manuscript_chunks(
            chapter.id,
            expected_revision=0,
            expected_source_hash=_source_hash(content),
            chunk_policy_version=policy,
            chunks=chunks,
        )

    assert search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
    ) == prior


def test_formal_chunk_operations_fail_closed_for_stale_hash_deleted_or_changed_source(
    tmp_path: Path,
) -> None:
    project, chapters, search, chapter = _repositories(tmp_path)
    content = chapters.read_content(chapter.id)
    chunks = (_chunk(chapter.id, 0, 0, 0, len(content), content),)
    stored = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
        chunks=chunks,
    )

    with pytest.raises(RuntimeError, match="revision"):
        search.replace_formal_manuscript_chunks(
            chapter.id,
            expected_revision=1,
            expected_source_hash=_source_hash(content),
            chunk_policy_version=_POLICY,
            chunks=chunks,
        )
    with pytest.raises(RuntimeError, match="hash"):
        search.read_formal_manuscript_chunks(
            chapter.id,
            expected_revision=0,
            expected_source_hash="a" * 64,
            chunk_policy_version=_POLICY,
        )

    manuscript_path = project.layout.root / chapter.content_path
    manuscript_path.write_text("tampered outside repository", encoding="utf-8")
    with pytest.raises(RuntimeError, match="source"):
        search.read_formal_manuscript_chunks(
            chapter.id,
            expected_revision=0,
            expected_source_hash=_source_hash(content),
            chunk_policy_version=_POLICY,
        )
    assert search.get(stored[0].id).id == stored[0].id

    manuscript_path.write_text(content, encoding="utf-8")
    chapters.delete_chapter(chapter.id)
    with pytest.raises(KeyError, match="deleted"):
        search.read_formal_manuscript_chunks(
            chapter.id,
            expected_revision=0,
            expected_source_hash=_source_hash(content),
            chunk_policy_version=_POLICY,
        )


@pytest.mark.parametrize("operation", ["replace", "read"])
def test_formal_chunk_operations_reject_files_outside_manuscript_directory(
    tmp_path: Path,
    operation: str,
) -> None:
    project, _chapters, search, chapter = _repositories(tmp_path)
    outside_content = "private project asset must not become manuscript evidence"
    outside_path = project.layout.assets / "not-manuscript.txt"
    outside_path.write_text(outside_content, encoding="utf-8")
    outside_hash = _source_hash(outside_content)
    with project.database.connect() as connection, connection:
        connection.execute(
            """
            UPDATE chapters
            SET content_path = ?, content_hash = ?
            WHERE id = ?
            """,
            (
                outside_path.relative_to(project.layout.root).as_posix(),
                outside_hash,
                chapter.id,
            ),
        )

    with pytest.raises(RuntimeError, match="manuscript") as captured:
        if operation == "replace":
            search.replace_formal_manuscript_chunks(
                chapter.id,
                expected_revision=0,
                expected_source_hash=outside_hash,
                chunk_policy_version=_POLICY,
                chunks=(
                    _chunk(
                        chapter.id,
                        0,
                        0,
                        0,
                        len(outside_content),
                        outside_content,
                    ),
                ),
            )
        else:
            search.read_formal_manuscript_chunks(
                chapter.id,
                expected_revision=0,
                expected_source_hash=outside_hash,
                chunk_policy_version=_POLICY,
            )

    assert outside_content not in str(captured.value)


@pytest.mark.parametrize(
    ("statement", "value"),
    [
        ("UPDATE memory_documents SET source_start = ? WHERE id = ?", None),
        ("UPDATE memory_documents SET source_end = ? WHERE id = ?", 999),
        ("UPDATE memory_documents SET source_revision = ? WHERE id = ?", 1),
        ("UPDATE memory_documents SET source_hash = ? WHERE id = ?", "a" * 64),
        ("UPDATE memory_documents SET source_id = ? WHERE id = ?", "corrupted"),
        ("UPDATE memory_documents SET content = ? WHERE id = ?", "wrong slice"),
        ("UPDATE memory_documents SET status = ? WHERE id = ?", "STALE"),
    ],
)
def test_formal_chunk_reads_reject_corrupted_persisted_projection(
    tmp_path: Path,
    statement: str,
    value: object,
) -> None:
    project, chapters, search, chapter = _repositories(tmp_path)
    content = chapters.read_content(chapter.id)
    stored = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
        chunks=(_chunk(chapter.id, 0, 0, 0, len(content), content),),
    )
    with project.database.connect() as connection, connection:
        connection.execute(statement, (value, stored[0].id))

    with pytest.raises(RuntimeError, match="formal manuscript"):
        search.read_formal_manuscript_chunks(
            chapter.id,
            expected_revision=0,
            expected_source_hash=_source_hash(content),
            chunk_policy_version=_POLICY,
        )


def test_generic_index_cannot_create_incomplete_formal_rows(tmp_path: Path) -> None:
    _project, _chapters, search, chapter = _repositories(tmp_path)

    with pytest.raises(ValueError, match="FORMAL_MANUSCRIPT"):
        search.index_document(
            document_type="FORMAL_MANUSCRIPT",
            source_id="incomplete",
            chapter_id=chapter.id,
            title=chapter.title,
            content="body",
            participants=(),
            pinned_weight=0,
            review_status=ReviewStatus.APPROVED,
            status=MemoryStatus.CURRENT,
        )


def test_formal_chunk_replacement_enforces_a_per_chapter_storage_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, _chapters, search, chapter = _repositories(tmp_path)
    content = "甲😀乙\n第二段证据"
    chunks = (
        _chunk(chapter.id, 0, 0, 0, 3, content),
        _chunk(chapter.id, 0, 1, 4, len(content), content),
    )
    monkeypatch.setattr(search_module, "MAX_FORMAL_CHUNKS_PER_CHAPTER", 1)

    with pytest.raises(ValueError, match="count exceeds"):
        search.replace_formal_manuscript_chunks(
            chapter.id,
            expected_revision=0,
            expected_source_hash=_source_hash(content),
            chunk_policy_version=_POLICY,
            chunks=chunks,
        )

    assert search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
    ) == ()


@pytest.mark.parametrize(
    ("absolute_cap", "amplification_cap"),
    [(10, 100), (1_000, 1)],
)
def test_formal_chunk_replacement_bounds_aggregate_stored_codepoints_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    absolute_cap: int,
    amplification_cap: int,
) -> None:
    _project, _chapters, search, chapter = _repositories(
        tmp_path,
        content="abcdefghij",
    )
    prior = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash("abcdefghij"),
        chunk_policy_version=_POLICY,
        chunks=(_chunk(chapter.id, 0, 0, 0, 3, "abcdefghij"),),
    )
    source = search.embedding_source(prior[0].id)
    search.save_embedding(
        prior[0].id,
        _IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )
    prior_embedding = search.get_embedding(prior[0].id, _IDENTITY)
    monkeypatch.setattr(
        formal_projection,
        "MAX_FORMAL_STORED_CODEPOINTS",
        absolute_cap,
        raising=False,
    )
    monkeypatch.setattr(
        formal_projection,
        "MAX_FORMAL_STORAGE_AMPLIFICATION",
        amplification_cap,
        raising=False,
    )
    replacement_policy = "overlap-storage-v2"
    oversized = (
        _chunk(
            chapter.id,
            0,
            0,
            0,
            8,
            "abcdefghij",
            policy=replacement_policy,
        ),
        _chunk(
            chapter.id,
            0,
            1,
            2,
            10,
            "abcdefghij",
            policy=replacement_policy,
        ),
    )

    with pytest.raises(ValueError, match="stored code-point"):
        search.replace_formal_manuscript_chunks(
            chapter.id,
            expected_revision=0,
            expected_source_hash=_source_hash("abcdefghij"),
            chunk_policy_version=replacement_policy,
            chunks=oversized,
        )

    assert search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=0,
        expected_source_hash=_source_hash("abcdefghij"),
        chunk_policy_version=_POLICY,
    ) == prior
    assert search.get_embedding(prior[0].id, _IDENTITY) == prior_embedding


def test_formal_orphan_cleanup_refuses_a_current_source(tmp_path: Path) -> None:
    _project, _chapters, search, chapter = _repositories(
        tmp_path,
        content="current source",
    )
    content = "current source"
    stored = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
        chunks=(_chunk(chapter.id, 0, 0, 0, len(content), content),),
    )

    with pytest.raises(RuntimeError, match="current chapter"):
        search.remove_orphaned_formal_manuscript_chunks(chapter.id)

    assert search.get(stored[0].id) == stored[0]


def test_formal_invalidation_is_idempotent_and_leaves_legacy_rows_current(
    tmp_path: Path,
) -> None:
    project, _chapters, search, chapter = _repositories(
        tmp_path,
        content="current formal source",
    )
    content = "current formal source"
    legacy = search.index_chapter(chapter.id, chapter.title, content)
    formal = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
        chunks=(_chunk(chapter.id, 0, 0, 0, len(content), content),),
    )
    source = search.embedding_source(formal[0].id)
    search.save_embedding(
        formal[0].id,
        _IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )

    first = search.invalidate_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )
    second = search.invalidate_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
    )

    with project.database.connect() as connection:
        formal_status = str(
            connection.execute(
                "SELECT status FROM memory_documents WHERE id = ?",
                (formal[0].id,),
            ).fetchone()["status"]
        )
        dependency_status = str(
            connection.execute(
                "SELECT status FROM memory_dependencies "
                "WHERE memory_type = 'SEARCH' AND memory_id = ?",
                (formal[0].id,),
            ).fetchone()["status"]
        )
        embedding_status = str(
            connection.execute(
                "SELECT status FROM memory_embeddings WHERE document_id = ?",
                (formal[0].id,),
            ).fetchone()["status"]
        )

    assert first == second == 1
    assert (formal_status, dependency_status, embedding_status) == (
        "STALE",
        "STALE",
        "STALE",
    )
    assert search.get(legacy.id).status.value == "CURRENT"


def test_formal_invalidation_rolls_back_when_exact_source_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _chapters, search, chapter = _repositories(
        tmp_path,
        content="stable source",
    )
    content = "stable source"
    formal = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
        chunks=(_chunk(chapter.id, 0, 0, 0, len(content), content),),
    )
    source = search.embedding_source(formal[0].id)
    search.save_embedding(
        formal[0].id,
        _IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )
    manuscript_path = project.layout.root / chapter.content_path
    real_source_check = search._current_formal_source
    source_checks = 0

    def change_source_before_commit(
        connection: sqlite3.Connection,
        chapter_id: str,
        revision: int,
        source_hash: str,
    ) -> tuple[sqlite3.Row, str]:
        nonlocal source_checks
        source_checks += 1
        if source_checks == 2:
            with manuscript_path.open("w", encoding="utf-8", newline="") as stream:
                stream.write("changed source")
        return real_source_check(
            connection,
            chapter_id,
            revision,
            source_hash,
        )

    monkeypatch.setattr(
        search,
        "_current_formal_source",
        change_source_before_commit,
    )

    try:
        with pytest.raises(RuntimeError, match="source file does not match"):
            search.invalidate_formal_manuscript_chunks(
                chapter.id,
                expected_revision=chapter.revision,
                expected_source_hash=_source_hash(content),
            )
    finally:
        with manuscript_path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(content)

    with project.database.connect() as connection:
        statuses = (
            str(
                connection.execute(
                    "SELECT status FROM memory_documents WHERE id = ?",
                    (formal[0].id,),
                ).fetchone()["status"]
            ),
            str(
                connection.execute(
                    "SELECT status FROM memory_dependencies "
                    "WHERE memory_type = 'SEARCH' AND memory_id = ?",
                    (formal[0].id,),
                ).fetchone()["status"]
            ),
            str(
                connection.execute(
                    "SELECT status FROM memory_embeddings WHERE document_id = ?",
                    (formal[0].id,),
                ).fetchone()["status"]
            ),
        )
    assert source_checks == 2
    assert statuses == ("CURRENT", "CURRENT", "CURRENT")


def test_formal_invalidation_normalizes_storage_errors_and_rolls_back(
    tmp_path: Path,
) -> None:
    project, _chapters, search, chapter = _repositories(
        tmp_path,
        content="private manuscript body",
    )
    content = "private manuscript body"
    formal = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
        chunks=(_chunk(chapter.id, 0, 0, 0, len(content), content),),
    )
    source = search.embedding_source(formal[0].id)
    search.save_embedding(
        formal[0].id,
        _IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )
    raw_error = f"raw storage failure: {project.layout.root}: {content}"
    with project.database.connect() as connection, connection:
        connection.execute(
            f"""
            CREATE TRIGGER fail_formal_invalidation
            BEFORE UPDATE OF status ON memory_documents
            WHEN OLD.document_type = 'FORMAL_MANUSCRIPT'
            BEGIN
                SELECT RAISE(ABORT, '{raw_error}');
            END
            """
        )

    with pytest.raises(RuntimeError) as captured:
        search.invalidate_formal_manuscript_chunks(
            chapter.id,
            expected_revision=chapter.revision,
            expected_source_hash=_source_hash(content),
        )

    assert str(captured.value) == "formal manuscript projection invalidation failed"
    assert content not in str(captured.value)
    assert str(project.layout.root) not in str(captured.value)
    with project.database.connect() as connection:
        statuses = (
            str(
                connection.execute(
                    "SELECT status FROM memory_documents WHERE id = ?",
                    (formal[0].id,),
                ).fetchone()["status"]
            ),
            str(
                connection.execute(
                    "SELECT status FROM memory_dependencies "
                    "WHERE memory_type = 'SEARCH' AND memory_id = ?",
                    (formal[0].id,),
                ).fetchone()["status"]
            ),
            str(
                connection.execute(
                    "SELECT status FROM memory_embeddings WHERE document_id = ?",
                    (formal[0].id,),
                ).fetchone()["status"]
            ),
        )
    assert statuses == ("CURRENT", "CURRENT", "CURRENT")


def test_formal_chunk_repair_rolls_back_deleted_rows_when_insert_fails(
    tmp_path: Path,
) -> None:
    project, _chapters, search, chapter = _repositories(
        tmp_path,
        content="repair rollback body",
    )
    content = "repair rollback body"
    prior = search.replace_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
        chunks=(_chunk(chapter.id, 0, 0, 0, len(content), content),),
    )
    source = search.embedding_source(prior[0].id)
    prior_embedding = search.save_embedding(
        prior[0].id,
        _IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            """
            CREATE TRIGGER fail_formal_repair_insert
            BEFORE INSERT ON memory_documents
            WHEN NEW.document_type = 'FORMAL_MANUSCRIPT'
            BEGIN
                SELECT RAISE(ABORT, 'injected formal repair failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected formal repair"):
        search.repair_formal_manuscript_chunks(
            chapter.id,
            expected_revision=chapter.revision,
            expected_source_hash=_source_hash(content),
            chunk_policy_version=_POLICY,
            chunks=(_chunk(chapter.id, 0, 0, 0, len(content), content),),
        )

    assert search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=_POLICY,
    ) == prior
    assert search.get_embedding(prior[0].id, _IDENTITY) == prior_embedding
