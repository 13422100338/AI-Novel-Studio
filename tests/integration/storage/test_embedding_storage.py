from pathlib import Path

import pytest

from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository


def _project(tmp_path: Path) -> ProjectRepository:
    return ProjectRepository.create(tmp_path / "project", "Embedding storage")


def _index_document(
    search: SearchRepository,
    *,
    source_id: str = "canon-source",
    title: str = "继承权记录",
    content: str = "公爵曾经私下指定继承人。",
    review_status: ReviewStatus = ReviewStatus.APPROVED,
    status: MemoryStatus = MemoryStatus.CURRENT,
):  # type: ignore[no-untyped-def]
    return search.index_document(
        document_type="CANON",
        source_id=source_id,
        chapter_id=None,
        title=title,
        content=content,
        participants=(),
        pinned_weight=0,
        review_status=review_status,
        status=status,
    )


def test_embedding_vector_round_trips_with_its_exact_source_hash(
    tmp_path: Path,
) -> None:
    search = SearchRepository(_project(tmp_path))
    document = _index_document(search)

    source = search.embedding_source(document.id)
    saved = search.save_embedding(
        document.id,
        "embedding-model",
        (0.25, -0.5, 0.75),
        expected_content_hash=source.content_hash,
    )

    assert source.text == "继承权记录\n\n公爵曾经私下指定继承人。"
    assert len(source.content_hash) == 64
    assert saved == search.get_embedding(document.id, "embedding-model")
    assert saved.vector == (0.25, -0.5, 0.75)
    assert saved.dimensions == 3
    assert saved.content_hash == source.content_hash
    assert saved.status == MemoryStatus.CURRENT


@pytest.mark.parametrize(
    "vector",
    [(), (True,), (float("nan"),), (float("inf"),)],
)
def test_embedding_save_rejects_invalid_vectors(
    tmp_path: Path,
    vector: tuple[float, ...],
) -> None:
    search = SearchRepository(_project(tmp_path))
    document = _index_document(search)
    source = search.embedding_source(document.id)

    with pytest.raises(ValueError, match="embedding vector"):
        search.save_embedding(
            document.id,
            "embedding-model",
            vector,
            expected_content_hash=source.content_hash,
        )


def test_embedding_save_rejects_a_vector_for_changed_source_text(tmp_path: Path) -> None:
    search = SearchRepository(_project(tmp_path))
    original = _index_document(search)
    original_source = search.embedding_source(original.id)
    updated = _index_document(search, content="公爵公开指定了另一位继承人。")

    assert updated.id == original.id
    with pytest.raises(RuntimeError, match="embedding source changed"):
        search.save_embedding(
            original.id,
            "embedding-model",
            (0.1, 0.2),
            expected_content_hash=original_source.content_hash,
        )
    with pytest.raises(KeyError):
        search.get_embedding(original.id, "embedding-model")


def test_reindex_only_stales_vectors_when_embedding_text_changes(tmp_path: Path) -> None:
    search = SearchRepository(_project(tmp_path))
    document = _index_document(search)
    source = search.embedding_source(document.id)
    search.save_embedding(
        document.id,
        "model-a",
        (0.1, 0.2),
        expected_content_hash=source.content_hash,
    )
    search.save_embedding(
        document.id,
        "model-b",
        (0.3, 0.4),
        expected_content_hash=source.content_hash,
    )

    _index_document(search)

    assert search.get_embedding(document.id, "model-a").status == MemoryStatus.CURRENT
    assert search.get_embedding(document.id, "model-b").status == MemoryStatus.CURRENT

    _index_document(search, content="继承人名单已经被公开修改。")

    assert search.get_embedding(document.id, "model-a").status == MemoryStatus.STALE
    assert search.get_embedding(document.id, "model-b").status == MemoryStatus.STALE
    pending_a = search.pending_embedding_sources("model-a", limit=10)
    assert [item.document_id for item in pending_a] == [document.id]
    assert pending_a[0].text.endswith("继承人名单已经被公开修改。")

    search.save_embedding(
        document.id,
        "model-a",
        (0.5, 0.6),
        expected_content_hash=pending_a[0].content_hash,
    )

    assert search.get_embedding(document.id, "model-a").status == MemoryStatus.CURRENT
    assert search.get_embedding(document.id, "model-b").status == MemoryStatus.STALE


def test_chapter_revision_invalidates_its_stored_embedding(tmp_path: Path) -> None:
    project = _project(tmp_path)
    chapters = ChapterRepository(project)
    volume = project.list_volumes()[0]
    chapter = chapters.create_chapter(volume.id, "第一章", "1", "旧正文")
    search = SearchRepository(project)
    document = search.index_chapter(chapter.id, chapter.title, "旧正文")
    source = search.embedding_source(document.id)
    search.save_embedding(
        document.id,
        "embedding-model",
        (0.1, 0.2),
        expected_content_hash=source.content_hash,
    )

    chapters.save_content(
        chapter.id,
        "重写后的正文",
        source="manual",
        reason="rewrite",
    )

    assert search.get_embedding(document.id, "embedding-model").status == (
        MemoryStatus.STALE
    )


def test_pending_rebuild_only_returns_current_reviewed_documents(tmp_path: Path) -> None:
    search = SearchRepository(_project(tmp_path))
    approved = _index_document(search, source_id="approved")
    _index_document(
        search,
        source_id="review",
        review_status=ReviewStatus.REVIEW,
    )
    _index_document(
        search,
        source_id="stale",
        status=MemoryStatus.STALE,
    )

    pending = search.pending_embedding_sources("embedding-model", limit=10)

    assert [item.document_id for item in pending] == [approved.id]


def test_embedding_recall_ranks_valid_current_vectors_by_cosine_similarity(
    tmp_path: Path,
) -> None:
    search = SearchRepository(_project(tmp_path))
    best = _index_document(search, source_id="best")
    weaker = _index_document(search, source_id="weaker")
    opposite = _index_document(search, source_id="opposite")
    stale = _index_document(search, source_id="stale")
    awaiting_review = _index_document(search, source_id="review")
    corrupted = _index_document(search, source_id="corrupted")
    mismatched_hash = _index_document(search, source_id="mismatched-hash")
    wrong_dimensions = _index_document(search, source_id="wrong-dimensions")

    for document, vector in (
        (best, (1.0, 0.0)),
        (weaker, (0.5, 0.8660254038)),
        (opposite, (-1.0, 0.0)),
        (stale, (0.9, 0.1)),
        (awaiting_review, (0.8, 0.2)),
        (corrupted, (0.7, 0.3)),
        (mismatched_hash, (0.6, 0.4)),
        (wrong_dimensions, (1.0, 0.0, 0.0)),
    ):
        source = search.embedding_source(document.id)
        search.save_embedding(
            document.id,
            "embedding-model",
            vector,
            expected_content_hash=source.content_hash,
        )

    _index_document(search, source_id="stale", content="来源已经变化。")
    _index_document(
        search,
        source_id="review",
        review_status=ReviewStatus.REVIEW,
    )
    with search.project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE memory_embeddings SET vector_json = '[broken]' WHERE document_id = ?",
            (corrupted.id,),
        )
        connection.execute(
            "UPDATE memory_embeddings SET content_hash = ? WHERE document_id = ?",
            ("a" * 64, mismatched_hash.id),
        )

    candidates = search.recall_embeddings(
        "embedding-model",
        (1.0, 0.0),
        limit=10,
    )

    assert [candidate.document_id for candidate in candidates] == [best.id, weaker.id]
    assert candidates[0].similarity == pytest.approx(1.0)
    assert candidates[1].similarity == pytest.approx(0.5)


@pytest.mark.parametrize(
    "query_vector",
    [(), (0.0, 0.0), (float("nan"), 0.0), (float("inf"), 0.0)],
)
def test_embedding_recall_rejects_an_invalid_query_vector(
    tmp_path: Path,
    query_vector: tuple[float, ...],
) -> None:
    search = SearchRepository(_project(tmp_path))

    with pytest.raises(ValueError, match="embedding query vector"):
        search.recall_embeddings(
            "embedding-model",
            query_vector,
            limit=10,
        )
