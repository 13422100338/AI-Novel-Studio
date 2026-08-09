from pathlib import Path

import pytest

from ai_novel_studio.domain.embedding import EmbeddingIndexIdentity
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import (
    SearchDocument,
    SearchRepository,
)

_IDENTITY = EmbeddingIndexIdentity("provider-a", "embedding-model", 1)


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
) -> SearchDocument:
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
        _IDENTITY,
        (0.25, -0.5, 0.75),
        expected_content_hash=source.content_hash,
    )

    assert source.text == "继承权记录\n\n公爵曾经私下指定继承人。"
    assert len(source.content_hash) == 64
    assert saved == search.get_embedding(document.id, _IDENTITY)
    assert saved.identity == _IDENTITY
    assert saved.provider_id == "provider-a"
    assert saved.model_id == "embedding-model"
    assert saved.embedding_schema_version == 1
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
            _IDENTITY,
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
            _IDENTITY,
            (0.1, 0.2),
            expected_content_hash=original_source.content_hash,
        )
    with pytest.raises(KeyError):
        search.get_embedding(original.id, _IDENTITY)


def test_embedding_save_rejects_dimension_drift_for_the_same_model(
    tmp_path: Path,
) -> None:
    search = SearchRepository(_project(tmp_path))
    first = _index_document(search, source_id="first")
    second = _index_document(search, source_id="second")
    first_source = search.embedding_source(first.id)
    second_source = search.embedding_source(second.id)
    search.save_embedding(
        first.id,
        _IDENTITY,
        (1.0, 0.0),
        expected_content_hash=first_source.content_hash,
    )

    with pytest.raises(ValueError, match="dimensions"):
        search.save_embedding(
            second.id,
            _IDENTITY,
            (1.0, 0.0, 0.0),
            expected_content_hash=second_source.content_hash,
        )

    with pytest.raises(KeyError):
        search.get_embedding(second.id, _IDENTITY)


def test_embedding_save_rejects_dimension_drift_for_the_same_document_identity(
    tmp_path: Path,
) -> None:
    search = SearchRepository(_project(tmp_path))
    document = _index_document(search)
    source = search.embedding_source(document.id)
    prior = search.save_embedding(
        document.id,
        _IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )

    with pytest.raises(ValueError, match="dimensions"):
        search.save_embedding(
            document.id,
            _IDENTITY,
            (1.0, 0.0, 0.0),
            expected_content_hash=source.content_hash,
        )

    assert search.get_embedding(document.id, _IDENTITY) == prior


def test_embedding_save_rejects_dimension_drift_when_identity_has_only_stale_rows(
    tmp_path: Path,
) -> None:
    search = SearchRepository(_project(tmp_path))
    stale_document = _index_document(search, source_id="stale-dimensions")
    stale_source = search.embedding_source(stale_document.id)
    search.save_embedding(
        stale_document.id,
        _IDENTITY,
        (1.0, 0.0),
        expected_content_hash=stale_source.content_hash,
    )
    _index_document(
        search,
        source_id="stale-dimensions",
        content="source changed after the original two-dimensional vector",
    )
    stale_embedding = search.get_embedding(stale_document.id, _IDENTITY)
    assert stale_embedding.status == MemoryStatus.STALE
    current_document = _index_document(search, source_id="current-dimensions")
    current_source = search.embedding_source(current_document.id)

    with pytest.raises(ValueError, match="dimensions"):
        search.save_embedding(
            current_document.id,
            _IDENTITY,
            (1.0, 0.0, 0.0),
            expected_content_hash=current_source.content_hash,
        )

    assert search.get_embedding(stale_document.id, _IDENTITY) == stale_embedding
    with pytest.raises(KeyError):
        search.get_embedding(current_document.id, _IDENTITY)


def test_embedding_identity_scopes_cache_and_dimensions_by_provider_and_schema(
    tmp_path: Path,
) -> None:
    search = SearchRepository(_project(tmp_path))
    first = _index_document(search, source_id="first")
    second = _index_document(search, source_id="second")
    first_source = search.embedding_source(first.id)
    second_source = search.embedding_source(second.id)
    provider_a_v1 = EmbeddingIndexIdentity("provider-a", "shared-model", 1)
    provider_b_v1 = EmbeddingIndexIdentity("provider-b", "shared-model", 1)
    provider_a_v2 = EmbeddingIndexIdentity("provider-a", "shared-model", 2)

    search.save_embedding(
        first.id,
        provider_a_v1,
        (1.0, 0.0),
        expected_content_hash=first_source.content_hash,
    )
    search.save_embedding(
        first.id,
        provider_b_v1,
        (1.0, 0.0, 0.0),
        expected_content_hash=first_source.content_hash,
    )
    search.save_embedding(
        first.id,
        provider_a_v2,
        (1.0, 0.0, 0.0, 0.0),
        expected_content_hash=first_source.content_hash,
    )

    with pytest.raises(ValueError, match="dimensions"):
        search.save_embedding(
            second.id,
            provider_a_v1,
            (1.0, 0.0, 0.0),
            expected_content_hash=second_source.content_hash,
        )

    assert search.get_embedding(first.id, provider_a_v1).dimensions == 2
    assert search.get_embedding(first.id, provider_b_v1).dimensions == 3
    assert search.get_embedding(first.id, provider_a_v2).dimensions == 4
    with pytest.raises(KeyError):
        search.get_embedding(first.id, EmbeddingIndexIdentity("provider-c", "shared-model", 1))


def test_reindex_only_stales_vectors_when_embedding_text_changes(tmp_path: Path) -> None:
    search = SearchRepository(_project(tmp_path))
    document = _index_document(search)
    source = search.embedding_source(document.id)
    identity_a = EmbeddingIndexIdentity("provider-a", "model-a", 1)
    identity_b = EmbeddingIndexIdentity("provider-a", "model-b", 1)
    search.save_embedding(
        document.id,
        identity_a,
        (0.1, 0.2),
        expected_content_hash=source.content_hash,
    )
    search.save_embedding(
        document.id,
        identity_b,
        (0.3, 0.4),
        expected_content_hash=source.content_hash,
    )

    _index_document(search)

    assert search.get_embedding(document.id, identity_a).status == MemoryStatus.CURRENT
    assert search.get_embedding(document.id, identity_b).status == MemoryStatus.CURRENT

    _index_document(search, content="继承人名单已经被公开修改。")

    assert search.get_embedding(document.id, identity_a).status == MemoryStatus.STALE
    assert search.get_embedding(document.id, identity_b).status == MemoryStatus.STALE
    pending_a = search.pending_embedding_sources(identity_a, limit=10)
    assert [item.document_id for item in pending_a] == [document.id]
    assert pending_a[0].text.endswith("继承人名单已经被公开修改。")

    search.save_embedding(
        document.id,
        identity_a,
        (0.5, 0.6),
        expected_content_hash=pending_a[0].content_hash,
    )

    assert search.get_embedding(document.id, identity_a).status == MemoryStatus.CURRENT
    assert search.get_embedding(document.id, identity_b).status == MemoryStatus.STALE


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
        _IDENTITY,
        (0.1, 0.2),
        expected_content_hash=source.content_hash,
    )

    chapters.save_content(
        chapter.id,
        "重写后的正文",
        source="manual",
        reason="rewrite",
    )

    assert search.get_embedding(document.id, _IDENTITY).status == (
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

    pending = search.pending_embedding_sources(_IDENTITY, limit=10)

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
        (wrong_dimensions, (1.0, 0.0)),
    ):
        source = search.embedding_source(document.id)
        search.save_embedding(
            document.id,
            _IDENTITY,
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
        connection.execute(
            "UPDATE memory_embeddings SET dimensions = 3, vector_json = '[1,0,0]' "
            "WHERE document_id = ?",
            (wrong_dimensions.id,),
        )

    candidates = search.recall_embeddings(
        _IDENTITY,
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
            _IDENTITY,
            query_vector,
            limit=10,
        )
