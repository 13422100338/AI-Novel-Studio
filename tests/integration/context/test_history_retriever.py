from pathlib import Path

import pytest

from ai_novel_studio.core.context.history_retriever import (
    HistoryRetriever,
    StoredEmbeddingRecallProvider,
)
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import (
    EmbeddingCandidate,
    SearchRepository,
)


class _StaticEmbeddingRecall:
    def __init__(self, candidates: tuple[EmbeddingCandidate, ...]) -> None:
        self._candidates = candidates

    def recall(self, query: str, *, limit: int) -> tuple[EmbeddingCandidate, ...]:
        return self._candidates[:limit]


class _RejectsLongEmbeddingQuery:
    def recall(self, query: str, *, limit: int) -> tuple[EmbeddingCandidate, ...]:
        if len(query) > 20_000:
            raise AssertionError("embedding query was not bounded")
        return ()


class _StaticQueryEmbeddings:
    model_id = "embedding-model"

    def __init__(self, vector: tuple[float, ...]) -> None:
        self.vector = vector
        self.queries: list[str] = []

    def embed_query(self, query: str) -> tuple[float, ...]:
        self.queries.append(query)
        return self.vector


def _project_with_four_chapters(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "检索测试")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    created = tuple(
        chapters.create_chapter(volume.id, f"第 {index} 章", str(index), f"正文 {index}")
        for index in range(1, 5)
    )
    return project, chapters, created


def test_chinese_fts_query_excludes_current_and_future_chapters(tmp_path: Path) -> None:
    project, _, chapters = _project_with_four_chapters(tmp_path)
    search = SearchRepository(project)
    search.index_chapter(
        chapters[0].id,
        "旧港来信",
        "林岚发现旧港来信没有署名，信封已经受潮。",
        participants=("character-lan",),
    )
    search.index_chapter(chapters[2].id, "当前章", "旧港来信在当前章再次出现。")
    search.index_chapter(chapters[3].id, "未来章", "未来才会解释旧港来信。")

    hits = HistoryRetriever(search).search("旧港来信", chapters[2].id)

    assert [hit.chapter_id for hit in hits] == [chapters[0].id]
    assert "旧港来信" in hits[0].excerpt
    assert hits[0].source_revision == 0
    assert hits[0].source_hash


def test_participant_and_manual_pin_boost_relevant_history(tmp_path: Path) -> None:
    project, _, chapters = _project_with_four_chapters(tmp_path)
    search = SearchRepository(project)
    ordinary = search.index_chapter(
        chapters[0].id,
        "密封来信",
        "密封来信被留在门边。",
        participants=("character-other",),
    )
    relevant = search.index_chapter(
        chapters[1].id,
        "密封来信",
        "林岚收起密封来信。",
        participants=("character-lan",),
        pinned_weight=3,
    )

    hits = HistoryRetriever(search).search(
        "密封来信",
        chapters[2].id,
        participants=("character-lan",),
    )

    assert [hit.document_id for hit in hits[:2]] == [relevant.id, ordinary.id]
    assert hits[0].participant_boost > hits[1].participant_boost
    assert hits[0].pinned_weight == 3


def test_upsert_keeps_stable_document_id_and_stale_source_is_demoted(tmp_path: Path) -> None:
    project, chapters_repository, chapters = _project_with_four_chapters(tmp_path)
    search = SearchRepository(project)
    first = search.index_chapter(chapters[0].id, "钟楼档案", "钟楼档案记载了火灾。")
    updated = search.index_chapter(chapters[0].id, "钟楼档案", "钟楼档案记载了蓝色火焰。")
    current = search.index_chapter(chapters[1].id, "钟楼档案", "钟楼档案仍然有效。")

    assert first.id == updated.id
    hits = HistoryRetriever(search).search("钟楼档案", chapters[2].id)
    assert "蓝色火焰" in next(hit.excerpt for hit in hits if hit.document_id == first.id)

    chapters_repository.save_content(
        chapters[0].id,
        "重写后的第一章",
        source="manual",
        reason="story rewrite",
    )
    stale_hits = HistoryRetriever(search).search("钟楼档案", chapters[2].id)

    assert stale_hits[0].document_id == current.id
    stale = next(hit for hit in stale_hits if hit.document_id == first.id)
    assert stale.status == MemoryStatus.STALE
    assert stale.stale_penalty < 0


def test_ascii_query_and_deterministic_tie_breaking_need_no_vector_database(
    tmp_path: Path,
) -> None:
    project, _, chapters = _project_with_four_chapters(tmp_path)
    search = SearchRepository(project)
    first = search.index_document(
        document_type="CANON",
        source_id="canon-a",
        chapter_id=chapters[0].id,
        title="sealed letter",
        content="sealed letter evidence alpha",
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )
    second = search.index_document(
        document_type="CANON",
        source_id="canon-b",
        chapter_id=chapters[0].id,
        title="sealed letter",
        content="sealed letter evidence gamma",
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )

    hits = HistoryRetriever(search).search("sealed letter", chapters[1].id)

    assert {hit.document_id for hit in hits} == {first.id, second.id}
    assert [hit.document_id for hit in hits] == sorted(hit.document_id for hit in hits)


def test_keyword_route_recalls_history_without_an_exact_phrase_match(
    tmp_path: Path,
) -> None:
    project, _, chapters = _project_with_four_chapters(tmp_path)
    search = SearchRepository(project)
    document = search.index_chapter(
        chapters[0].id,
        "sealed archive",
        "The sealed object was hidden. Later, the letter was burned as evidence.",
    )

    hits = HistoryRetriever(search).search(
        "sealed letter evidence",
        chapters[1].id,
    )

    assert [hit.document_id for hit in hits] == [document.id]
    assert hits[0].retrieval_routes == ("KEYWORD",)


def test_subject_route_respects_review_and_chapter_boundaries(tmp_path: Path) -> None:
    project, _, chapters = _project_with_four_chapters(tmp_path)
    search = SearchRepository(project)
    visible = search.index_document(
        document_type="CHARACTER_STATE",
        source_id="state-visible",
        chapter_id=chapters[0].id,
        title="林岚的旧伤",
        content="她在雨夜里再次感觉到左肩疼痛。",
        participants=("character-lan",),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )
    search.index_document(
        document_type="CHARACTER_STATE",
        source_id="state-review",
        chapter_id=chapters[1].id,
        title="未审核状态",
        content="这条候选状态仍需人工确认。",
        participants=("character-lan",),
        pinned_weight=0,
        review_status=ReviewStatus.REVIEW,
        status=MemoryStatus.CURRENT,
    )
    search.index_document(
        document_type="CHARACTER_STATE",
        source_id="state-future",
        chapter_id=chapters[3].id,
        title="未来状态",
        content="未来章节才会发生的变化。",
        participants=("character-lan",),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )

    hits = HistoryRetriever(search).search(
        "unrelated lighthouse clue",
        chapters[2].id,
        participants=("character-lan",),
    )

    assert [hit.document_id for hit in hits] == [visible.id]
    assert hits[0].lexical_score == 0
    assert hits[0].retrieval_routes == ("SUBJECT",)


def test_multi_route_recall_merges_duplicate_documents(tmp_path: Path) -> None:
    project, _, chapters = _project_with_four_chapters(tmp_path)
    search = SearchRepository(project)
    document = search.index_chapter(
        chapters[0].id,
        "钟楼档案",
        "林岚在钟楼档案中找到了火灾记录。",
        participants=("character-lan",),
    )

    hits = HistoryRetriever(search).search(
        "钟楼档案",
        chapters[1].id,
        participants=("character-lan",),
    )

    assert [hit.document_id for hit in hits] == [document.id]
    assert hits[0].retrieval_routes == ("EXACT_PHRASE", "KEYWORD", "SUBJECT")


def test_stronger_bm25_match_receives_the_higher_lexical_score(tmp_path: Path) -> None:
    project, _, chapters = _project_with_four_chapters(tmp_path)
    search = SearchRepository(project)
    weaker = search.index_document(
        document_type="CANON",
        source_id="canon-weaker",
        chapter_id=chapters[0].id,
        title="archive note",
        content=(
            "sealed letter evidence appears once among unrelated archive filler " * 4
        ),
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )
    stronger = search.index_document(
        document_type="CANON",
        source_id="canon-stronger",
        chapter_id=chapters[0].id,
        title="archive proof",
        content="sealed letter evidence " * 3,
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )

    hits = HistoryRetriever(search).search(
        "sealed letter evidence",
        chapters[1].id,
    )

    assert [hit.document_id for hit in hits[:2]] == [stronger.id, weaker.id]
    assert hits[0].lexical_score > hits[1].lexical_score


def test_embedding_route_recalls_semantic_history_without_lexical_overlap(
    tmp_path: Path,
) -> None:
    project, _, chapters = _project_with_four_chapters(tmp_path)
    search = SearchRepository(project)
    document = search.index_document(
        document_type="CANON",
        source_id="canon-hidden-heir",
        chapter_id=chapters[0].id,
        title="harbor succession",
        content="The duke privately named his youngest child as the heir.",
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )
    embedding = _StaticEmbeddingRecall((EmbeddingCandidate(document.id, 0.91),))

    hits = HistoryRetriever(search, embedding).search(
        "secret inheritance claim",
        chapters[1].id,
    )

    assert [hit.document_id for hit in hits] == [document.id]
    assert hits[0].semantic_score == pytest.approx(0.91)
    assert hits[0].retrieval_routes == ("EMBEDDING",)


def test_stored_embedding_provider_uses_existing_history_retrieval_path(
    tmp_path: Path,
) -> None:
    project, _, chapters = _project_with_four_chapters(tmp_path)
    search = SearchRepository(project)
    document = search.index_document(
        document_type="CANON",
        source_id="canon-stored-hidden-heir",
        chapter_id=chapters[0].id,
        title="harbor succession",
        content="The duke privately named his youngest child as the heir.",
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )
    source = search.embedding_source(document.id)
    search.save_embedding(
        document.id,
        "embedding-model",
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )
    query_embeddings = _StaticQueryEmbeddings((1.0, 0.0))

    hits = HistoryRetriever(
        search,
        StoredEmbeddingRecallProvider(search, query_embeddings),
    ).search("secret inheritance claim", chapters[1].id)

    assert query_embeddings.queries == ["secret inheritance claim"]
    assert [hit.document_id for hit in hits] == [document.id]
    assert hits[0].semantic_score == pytest.approx(1.0)
    assert hits[0].retrieval_routes == ("EMBEDDING",)


def test_embedding_candidates_are_rechecked_against_hard_filters(tmp_path: Path) -> None:
    project, _, chapters = _project_with_four_chapters(tmp_path)
    search = SearchRepository(project)
    visible = search.index_document(
        document_type="CANON",
        source_id="canon-visible-semantic",
        chapter_id=chapters[0].id,
        title="visible record",
        content="An approved fact from the first chapter.",
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )
    review = search.index_document(
        document_type="CANON",
        source_id="canon-review-semantic",
        chapter_id=chapters[1].id,
        title="review record",
        content="A model candidate still awaiting review.",
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.REVIEW,
        status=MemoryStatus.CURRENT,
    )
    future = search.index_document(
        document_type="CANON",
        source_id="canon-future-semantic",
        chapter_id=chapters[3].id,
        title="future record",
        content="A fact that only becomes available later.",
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )
    embedding = _StaticEmbeddingRecall(
        (
            EmbeddingCandidate(review.id, 0.99),
            EmbeddingCandidate(future.id, 0.98),
            EmbeddingCandidate("missing-document", 0.97),
            EmbeddingCandidate(visible.id, 0.80),
        )
    )

    hits = HistoryRetriever(search, embedding).search(
        "semantic-only-query",
        chapters[2].id,
    )

    assert [hit.document_id for hit in hits] == [visible.id]
    assert hits[0].retrieval_routes == ("EMBEDDING",)


def test_embedding_route_merges_with_existing_recall_routes(tmp_path: Path) -> None:
    project, _, chapters = _project_with_four_chapters(tmp_path)
    search = SearchRepository(project)
    document = search.index_chapter(
        chapters[0].id,
        "钟楼档案",
        "钟楼档案记录了蓝色火焰。",
    )
    embedding = _StaticEmbeddingRecall((EmbeddingCandidate(document.id, 0.88),))

    hits = HistoryRetriever(search, embedding).search("钟楼档案", chapters[1].id)

    assert [hit.document_id for hit in hits] == [document.id]
    assert hits[0].retrieval_routes == ("EXACT_PHRASE", "KEYWORD", "EMBEDDING")


@pytest.mark.parametrize("score", [True, float("nan"), float("inf"), -0.01, 1.01])
def test_embedding_candidate_rejects_invalid_similarity(score: float) -> None:
    with pytest.raises(ValueError, match="similarity"):
        EmbeddingCandidate("document-id", score)


@pytest.mark.parametrize("document_id", ["  ", "x" * 201])
def test_embedding_candidate_rejects_an_invalid_document_id(document_id: str) -> None:
    with pytest.raises(ValueError, match="document ID"):
        EmbeddingCandidate(document_id, 0.5)


def test_embedding_provider_receives_the_bounded_search_query(tmp_path: Path) -> None:
    project, _, chapters = _project_with_four_chapters(tmp_path)

    hits = HistoryRetriever(
        SearchRepository(project),
        _RejectsLongEmbeddingQuery(),
    ).search("x" * 20_001, chapters[1].id)

    assert hits == ()
