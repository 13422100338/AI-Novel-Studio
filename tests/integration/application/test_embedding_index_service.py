from pathlib import Path

import pytest

from ai_novel_studio.application.embedding_index_service import EmbeddingIndexService
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository


class RecordingEmbeddingProvider:
    model_id = "embedding-model"

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def embed_documents(
        self,
        texts: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        return tuple((float(len(text)), 1.0) for text in texts)


class WrongCardinalityProvider:
    model_id = "embedding-model"

    def embed_documents(
        self,
        texts: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]:
        return ((1.0, 0.0),)


class PartlyInvalidProvider:
    model_id = "embedding-model"

    def embed_documents(
        self,
        texts: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]:
        return ((float("nan"), 0.0), (1.0, 0.0))


class MixedDimensionsProvider:
    model_id = "embedding-model"

    def embed_documents(
        self,
        texts: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]:
        return ((1.0, 0.0), (1.0, 0.0, 0.0))


class FirstBatchFailsProvider(RecordingEmbeddingProvider):
    def embed_documents(
        self,
        texts: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        if len(self.calls) == 1:
            raise RuntimeError("temporary provider failure")
        return tuple((1.0, 0.0) for _text in texts)


class FirstBatchHasEmptyVectorProvider(RecordingEmbeddingProvider):
    def embed_documents(
        self,
        texts: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        if len(self.calls) == 1:
            return ((),)
        return tuple((1.0, 0.0) for _text in texts)


class SourceChangingProvider:
    model_id = "embedding-model"

    def __init__(self, search: SearchRepository) -> None:
        self.search = search

    def embed_documents(
        self,
        texts: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]:
        _index_document(
            self.search,
            source_id="changing-source",
            content="模型调用期间来源已经被修改。",
        )
        return tuple((1.0, 0.0) for _text in texts)


def _search(tmp_path: Path) -> SearchRepository:
    project = ProjectRepository.create(tmp_path / "project", "Embedding index")
    return SearchRepository(project)


def _index_document(
    search: SearchRepository,
    *,
    source_id: str,
    content: str = "公爵曾经私下指定继承人。",
    pinned_weight: float = 0,
):  # type: ignore[no-untyped-def]
    return search.index_document(
        document_type="CANON",
        source_id=source_id,
        chapter_id=None,
        title=f"记录 {source_id}",
        content=content,
        participants=(),
        pinned_weight=pinned_weight,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )


def test_rebuild_pending_batches_sources_and_persists_each_valid_vector(
    tmp_path: Path,
) -> None:
    search = _search(tmp_path)
    documents = tuple(
        _index_document(
            search,
            source_id=f"source-{index}",
            pinned_weight=float(3 - index),
        )
        for index in range(3)
    )
    provider = RecordingEmbeddingProvider()

    report = EmbeddingIndexService(search, provider).rebuild_pending(
        limit=10,
        batch_size=2,
    )

    assert report.model_id == "embedding-model"
    assert report.selected_sources == 3
    assert report.indexed_embeddings == 3
    assert report.failures == ()
    assert [len(call) for call in provider.calls] == [2, 1]
    assert search.pending_embedding_sources("embedding-model", limit=10) == ()
    assert all(
        search.get_embedding(document.id, "embedding-model").status
        == MemoryStatus.CURRENT
        for document in documents
    )


def test_rebuild_pending_rejects_a_batch_with_the_wrong_output_count(
    tmp_path: Path,
) -> None:
    search = _search(tmp_path)
    documents = tuple(
        _index_document(
            search,
            source_id=f"source-{index}",
            pinned_weight=float(2 - index),
        )
        for index in range(2)
    )

    report = EmbeddingIndexService(search, WrongCardinalityProvider()).rebuild_pending(
        limit=10,
        batch_size=2,
    )

    assert report.indexed_embeddings == 0
    assert [failure.document_id for failure in report.failures] == [
        document.id for document in documents
    ]
    assert all("output count" in failure.message for failure in report.failures)


def test_rebuild_pending_keeps_valid_items_when_one_vector_is_invalid(
    tmp_path: Path,
) -> None:
    search = _search(tmp_path)
    documents = tuple(
        _index_document(
            search,
            source_id=f"source-{index}",
            pinned_weight=float(2 - index),
        )
        for index in range(2)
    )

    report = EmbeddingIndexService(search, PartlyInvalidProvider()).rebuild_pending(
        limit=10,
        batch_size=2,
    )

    assert report.indexed_embeddings == 1
    assert len(report.failures) == 1
    assert report.failures[0].document_id == documents[0].id
    with pytest.raises(KeyError):
        search.get_embedding(documents[0].id, "embedding-model")
    assert search.get_embedding(documents[1].id, "embedding-model").status == (
        MemoryStatus.CURRENT
    )


def test_rebuild_pending_rejects_mixed_dimensions_for_one_model(
    tmp_path: Path,
) -> None:
    search = _search(tmp_path)
    documents = tuple(
        _index_document(
            search,
            source_id=f"source-{index}",
            pinned_weight=float(2 - index),
        )
        for index in range(2)
    )

    report = EmbeddingIndexService(search, MixedDimensionsProvider()).rebuild_pending(
        limit=10,
        batch_size=2,
    )

    assert report.indexed_embeddings == 0
    assert [failure.document_id for failure in report.failures] == [
        document.id for document in documents
    ]
    assert all("dimensions" in failure.message for failure in report.failures)


def test_rebuild_pending_reports_source_race_without_saving_the_old_vector(
    tmp_path: Path,
) -> None:
    search = _search(tmp_path)
    document = _index_document(search, source_id="changing-source")

    report = EmbeddingIndexService(search, SourceChangingProvider(search)).rebuild_pending(
        limit=10,
        batch_size=1,
    )

    assert report.indexed_embeddings == 0
    assert [failure.document_id for failure in report.failures] == [document.id]
    assert "source changed" in report.failures[0].message
    with pytest.raises(KeyError):
        search.get_embedding(document.id, "embedding-model")
    pending = search.pending_embedding_sources("embedding-model", limit=10)
    assert [source.document_id for source in pending] == [document.id]
    assert pending[0].text.endswith("模型调用期间来源已经被修改。")


def test_rebuild_pending_continues_after_one_provider_batch_fails(
    tmp_path: Path,
) -> None:
    search = _search(tmp_path)
    for index in range(3):
        _index_document(
            search,
            source_id=f"source-{index}",
            pinned_weight=float(3 - index),
        )
    provider = FirstBatchFailsProvider()

    report = EmbeddingIndexService(search, provider).rebuild_pending(
        limit=10,
        batch_size=1,
    )

    assert len(provider.calls) == 3
    assert report.indexed_embeddings == 2
    assert len(report.failures) == 1
    assert "temporary provider failure" in report.failures[0].message


def test_invalid_first_vector_does_not_poison_later_batch_dimensions(
    tmp_path: Path,
) -> None:
    search = _search(tmp_path)
    for index in range(2):
        _index_document(
            search,
            source_id=f"source-{index}",
            pinned_weight=float(2 - index),
        )
    provider = FirstBatchHasEmptyVectorProvider()

    report = EmbeddingIndexService(search, provider).rebuild_pending(
        limit=10,
        batch_size=1,
    )

    assert report.indexed_embeddings == 1
    assert len(report.failures) == 1
    assert "dimensions" in report.failures[0].message


@pytest.mark.parametrize(
    ("limit", "batch_size"),
    [(0, 1), (251, 1), (True, 1), (1, 0), (1, 65), (1, True)],
)
def test_rebuild_pending_rejects_invalid_work_bounds(
    tmp_path: Path,
    limit: int,
    batch_size: int,
) -> None:
    search = _search(tmp_path)

    with pytest.raises(ValueError):
        EmbeddingIndexService(search, RecordingEmbeddingProvider()).rebuild_pending(
            limit=limit,
            batch_size=batch_size,
        )
