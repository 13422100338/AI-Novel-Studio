from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Literal

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

RetrievalRoute = Literal["EXACT_PHRASE", "KEYWORD", "EMBEDDING", "SUBJECT"]
MAX_RECALL_CANDIDATES = 250
MAX_SEARCH_QUERY_CHARS = 20_000

_SEARCH_TERM = re.compile(r"[a-z0-9_]{3,}|[\u3400-\u4dbf\u4e00-\u9fff]+")
_MAX_KEYWORD_TERMS = 24
_MAX_SEARCH_PARTICIPANTS = 64
_MAX_DOCUMENT_ID_CHARS = 200
_MAX_EMBEDDING_DIMENSIONS = 32_768
_MAX_EMBEDDING_JSON_CHARS = 1_000_000
_ROUTE_ORDER: dict[RetrievalRoute, int] = {
    "EXACT_PHRASE": 0,
    "KEYWORD": 1,
    "EMBEDDING": 2,
    "SUBJECT": 3,
}


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SearchDocument:
    id: str
    document_type: str
    source_id: str
    chapter_id: str | None
    volume_id: str | None
    source_revision: int
    source_hash: str
    title: str
    content: str
    participants: tuple[str, ...]
    pinned_weight: float
    review_status: ReviewStatus
    status: MemoryStatus
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EmbeddingCandidate:
    document_id: str
    similarity: float

    def __post_init__(self) -> None:
        document_id = self.document_id.strip()
        if not document_id or len(document_id) > _MAX_DOCUMENT_ID_CHARS:
            raise ValueError("embedding candidate document ID is invalid")
        if isinstance(self.similarity, bool):
            raise ValueError("embedding candidate similarity must be numeric")
        similarity = float(self.similarity)
        if not isfinite(similarity) or not 0 <= similarity <= 1:
            raise ValueError("embedding candidate similarity must be between 0 and 1")
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "similarity", similarity)


@dataclass(frozen=True, slots=True)
class EmbeddingSource:
    document_id: str
    text: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class StoredEmbedding:
    document_id: str
    model_id: str
    dimensions: int
    vector: tuple[float, ...]
    content_hash: str
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SearchRow:
    document: SearchDocument
    lexical_rank: float | None
    semantic_score: float
    excerpt: str
    chapter_distance: int | None
    retrieval_routes: tuple[RetrievalRoute, ...]


class SearchRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def index_chapter(
        self,
        chapter_id: str,
        title: str,
        content: str,
        *,
        participants: tuple[str, ...] = (),
        pinned_weight: float = 0,
    ) -> SearchDocument:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT id, volume_id, revision, content_hash FROM chapters WHERE id = ?",
                (chapter_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown chapter: {chapter_id}")
        return self.index_document(
            document_type="CHAPTER",
            source_id=chapter_id,
            chapter_id=chapter_id,
            volume_id=row["volume_id"],
            source_revision=int(row["revision"]),
            source_hash=row["content_hash"],
            title=title,
            content=content,
            participants=participants,
            pinned_weight=pinned_weight,
            review_status=ReviewStatus.APPROVED,
            status=MemoryStatus.CURRENT,
        )

    def index_document(
        self,
        *,
        document_type: str,
        source_id: str,
        chapter_id: str | None,
        title: str,
        content: str,
        participants: tuple[str, ...],
        pinned_weight: float,
        review_status: ReviewStatus,
        status: MemoryStatus,
        volume_id: str | None = None,
        source_revision: int | None = None,
        source_hash: str | None = None,
    ) -> SearchDocument:
        if not document_type.strip() or not source_id.strip() or not content.strip():
            raise ValueError("检索文档类型、来源 ID 和正文不能为空")
        if pinned_weight < 0:
            raise ValueError("人工固定权重不能为负数")
        revision = source_revision
        content_hash = source_hash
        if chapter_id is not None and (revision is None or content_hash is None):
            with self.project.database.connect() as connection:
                chapter = connection.execute(
                    "SELECT volume_id, revision, content_hash FROM chapters WHERE id = ?",
                    (chapter_id,),
                ).fetchone()
            if chapter is None:
                raise KeyError(f"unknown chapter: {chapter_id}")
            volume_id = volume_id or chapter["volume_id"]
            revision = int(chapter["revision"])
            content_hash = chapter["content_hash"]
        revision = revision or 0
        content_hash = content_hash or ""
        now = _now()
        embedding_hash = _embedding_content_hash(title, content)
        with self.project.database.connect() as connection, connection:
            existing = connection.execute(
                "SELECT id FROM memory_documents WHERE document_type = ? AND source_id = ?",
                (document_type, source_id),
            ).fetchone()
            document_id = existing["id"] if existing is not None else new_id()
            connection.execute(
                """
                INSERT INTO memory_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_type, source_id) DO UPDATE SET
                    chapter_id = excluded.chapter_id,
                    volume_id = excluded.volume_id,
                    source_revision = excluded.source_revision,
                    source_hash = excluded.source_hash,
                    title = excluded.title,
                    content = excluded.content,
                    participants = excluded.participants,
                    pinned_weight = excluded.pinned_weight,
                    review_status = excluded.review_status,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    document_type,
                    source_id,
                    chapter_id,
                    volume_id,
                    revision,
                    content_hash,
                    title,
                    content,
                    " ".join(dict.fromkeys(participants)),
                    pinned_weight,
                    review_status.value,
                    status.value,
                    now.isoformat(),
                ),
            )
            connection.execute("DELETE FROM memory_fts WHERE document_id = ?", (document_id,))
            connection.execute(
                "INSERT INTO memory_fts VALUES (?, ?, ?, ?)",
                (document_id, title, content, " ".join(participants)),
            )
            connection.execute(
                """
                UPDATE memory_embeddings
                SET status = 'STALE', updated_at = ?
                WHERE document_id = ? AND status != 'STALE'
                  AND (content_hash != ? OR ? = 'STALE')
                """,
                (now.isoformat(), document_id, embedding_hash, status.value),
            )
            if chapter_id is not None:
                connection.execute(
                    """
                    INSERT INTO memory_dependencies VALUES (?, 'SEARCH', ?, ?, ?, ?, 'CURRENT')
                    ON CONFLICT(memory_type, memory_id, source_chapter_id) DO UPDATE SET
                        source_revision = excluded.source_revision,
                        source_hash = excluded.source_hash,
                        status = 'CURRENT'
                    """,
                    (new_id(), document_id, chapter_id, revision, content_hash),
                )
        return self.get(document_id)

    def get(self, document_id: str) -> SearchDocument:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_documents WHERE id = ?", (document_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown search document: {document_id}")
        return self._document(row)

    def embedding_source(self, document_id: str) -> EmbeddingSource:
        return _embedding_source(self.get(document_id))

    def save_embedding(
        self,
        document_id: str,
        model_id: str,
        vector: tuple[float, ...],
        *,
        expected_content_hash: str,
    ) -> StoredEmbedding:
        normalized_model_id = _model_id(model_id)
        normalized_vector = _embedding_vector(vector)
        normalized_hash = _content_hash(expected_content_hash)
        vector_json = json.dumps(
            normalized_vector,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(vector_json) > _MAX_EMBEDDING_JSON_CHARS:
            raise ValueError("embedding vector JSON exceeds storage limit")
        now = _now()
        with self.project.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM memory_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown search document: {document_id}")
            source = _embedding_source(self._document(row))
            if source.content_hash != normalized_hash:
                raise RuntimeError("embedding source changed before vector save")
            connection.execute(
                """
                INSERT INTO memory_embeddings (
                    document_id, model_id, dimensions, vector_json, content_hash,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'CURRENT', ?, ?)
                ON CONFLICT(document_id, model_id) DO UPDATE SET
                    dimensions = excluded.dimensions,
                    vector_json = excluded.vector_json,
                    content_hash = excluded.content_hash,
                    status = 'CURRENT',
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    normalized_model_id,
                    len(normalized_vector),
                    vector_json,
                    normalized_hash,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return self.get_embedding(document_id, normalized_model_id)

    def get_embedding(self, document_id: str, model_id: str) -> StoredEmbedding:
        normalized_model_id = _model_id(model_id)
        with self.project.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM memory_embeddings
                WHERE document_id = ? AND model_id = ?
                """,
                (document_id, normalized_model_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown memory embedding: {document_id}/{normalized_model_id}")
        return _stored_embedding(row)

    def pending_embedding_sources(
        self,
        model_id: str,
        *,
        limit: int = 100,
    ) -> tuple[EmbeddingSource, ...]:
        normalized_model_id = _model_id(model_id)
        if limit <= 0 or limit > MAX_RECALL_CANDIDATES:
            raise ValueError(
                f"embedding rebuild limit must be between 1 and {MAX_RECALL_CANDIDATES}"
            )
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT d.* FROM memory_documents d
                LEFT JOIN memory_embeddings e
                  ON e.document_id = d.id AND e.model_id = ?
                WHERE d.status = 'CURRENT'
                  AND d.review_status IN ('APPROVED', 'LOCKED')
                  AND (e.document_id IS NULL OR e.status = 'STALE')
                ORDER BY d.pinned_weight DESC, d.updated_at DESC, d.id
                LIMIT ?
                """,
                (normalized_model_id, limit),
            ).fetchall()
        return tuple(_embedding_source(self._document(row)) for row in rows)

    def search_rows(
        self,
        query: str,
        before_chapter_id: str,
        *,
        participants: tuple[str, ...] = (),
        embedding_candidates: tuple[EmbeddingCandidate, ...] = (),
        limit: int,
    ) -> tuple[SearchRow, ...]:
        if limit <= 0:
            raise ValueError("检索数量必须大于零")
        normalized_query = query.strip()[:MAX_SEARCH_QUERY_CHARS]
        normalized_participants = tuple(
            dict.fromkeys(value.strip() for value in participants if value.strip())
        )[:_MAX_SEARCH_PARTICIPANTS]
        if not normalized_query and not normalized_participants and not embedding_candidates:
            return ()
        route_rows: list[SearchRow] = []
        candidate_limit = min(max(limit * 5, limit), MAX_RECALL_CANDIDATES)
        with self.project.database.connect() as connection:
            if normalized_query:
                phrase = '"' + normalized_query.replace('"', '""') + '"'
                route_rows.extend(
                    self._fts_rows(
                        connection,
                        before_chapter_id,
                        phrase,
                        "EXACT_PHRASE",
                        candidate_limit,
                    )
                )
                keyword_query = _keyword_query(normalized_query)
                if keyword_query:
                    route_rows.extend(
                        self._fts_rows(
                            connection,
                            before_chapter_id,
                            keyword_query,
                            "KEYWORD",
                            candidate_limit,
                        )
                    )
            if normalized_participants:
                route_rows.extend(
                    self._subject_rows(
                        connection,
                        before_chapter_id,
                        normalized_participants,
                        candidate_limit,
                    )
                )
            if embedding_candidates:
                route_rows.extend(
                    self._embedding_rows(
                        connection,
                        before_chapter_id,
                        embedding_candidates,
                        candidate_limit,
                    )
                )
        return _merge_rows(route_rows)

    def _fts_rows(
        self,
        connection: sqlite3.Connection,
        before_chapter_id: str,
        match_query: str,
        route: RetrievalRoute,
        limit: int,
    ) -> tuple[SearchRow, ...]:
        rows = connection.execute(
            """
            WITH ordered AS (
                SELECT c.id, ROW_NUMBER() OVER (
                    ORDER BY v.sort_index, c.sort_index, c.id
                ) AS ordinal
                FROM chapters c JOIN volumes v ON v.id = c.volume_id
                WHERE c.is_deleted = 0
            ), target AS (
                SELECT ordinal FROM ordered WHERE id = ?
            )
            SELECT d.*, bm25(memory_fts) AS lexical_rank,
                snippet(memory_fts, 2, '[', ']', '…', 32) AS excerpt,
                CASE WHEN source.ordinal IS NULL THEN NULL
                     ELSE target.ordinal - source.ordinal END AS chapter_distance
            FROM memory_fts
            JOIN memory_documents d ON d.id = memory_fts.document_id
            LEFT JOIN ordered source ON source.id = d.chapter_id
            CROSS JOIN target
            WHERE memory_fts MATCH ?
              AND d.review_status IN ('APPROVED', 'LOCKED')
              AND (d.chapter_id IS NULL OR source.ordinal < target.ordinal)
            ORDER BY lexical_rank, d.id
            LIMIT ?
            """,
            (before_chapter_id, match_query, limit),
        ).fetchall()
        return tuple(
            SearchRow(
                self._document(row),
                float(row["lexical_rank"]),
                0.0,
                row["excerpt"],
                _chapter_distance(row),
                (route,),
            )
            for row in rows
        )

    def _subject_rows(
        self,
        connection: sqlite3.Connection,
        before_chapter_id: str,
        participants: tuple[str, ...],
        limit: int,
    ) -> tuple[SearchRow, ...]:
        participant_match = " OR ".join(
            "instr(' ' || d.participants || ' ', ' ' || ? || ' ') > 0"
            for _ in participants
        )
        rows = connection.execute(
            f"""
            WITH ordered AS (
                SELECT c.id, ROW_NUMBER() OVER (
                    ORDER BY v.sort_index, c.sort_index, c.id
                ) AS ordinal
                FROM chapters c JOIN volumes v ON v.id = c.volume_id
                WHERE c.is_deleted = 0
            ), target AS (
                SELECT ordinal FROM ordered WHERE id = ?
            )
            SELECT d.*, substr(d.content, 1, 240) AS excerpt,
                CASE WHEN source.ordinal IS NULL THEN NULL
                     ELSE target.ordinal - source.ordinal END AS chapter_distance
            FROM memory_documents d
            LEFT JOIN ordered source ON source.id = d.chapter_id
            CROSS JOIN target
            WHERE d.review_status IN ('APPROVED', 'LOCKED')
              AND (d.chapter_id IS NULL OR source.ordinal < target.ordinal)
              AND ({participant_match})
            ORDER BY d.pinned_weight DESC, chapter_distance, d.id
            LIMIT ?
            """,
            (before_chapter_id, *participants, limit),
        ).fetchall()
        return tuple(
            SearchRow(
                self._document(row),
                None,
                0.0,
                row["excerpt"],
                _chapter_distance(row),
                ("SUBJECT",),
            )
            for row in rows
        )

    def _embedding_rows(
        self,
        connection: sqlite3.Connection,
        before_chapter_id: str,
        candidates: tuple[EmbeddingCandidate, ...],
        limit: int,
    ) -> tuple[SearchRow, ...]:
        scores: dict[str, float] = {}
        for candidate in candidates[:limit]:
            scores[candidate.document_id] = max(
                scores.get(candidate.document_id, 0.0),
                candidate.similarity,
            )
        if not scores:
            return ()
        placeholders = ", ".join("?" for _ in scores)
        rows = connection.execute(
            f"""
            WITH ordered AS (
                SELECT c.id, ROW_NUMBER() OVER (
                    ORDER BY v.sort_index, c.sort_index, c.id
                ) AS ordinal
                FROM chapters c JOIN volumes v ON v.id = c.volume_id
                WHERE c.is_deleted = 0
            ), target AS (
                SELECT ordinal FROM ordered WHERE id = ?
            )
            SELECT d.*, substr(d.content, 1, 240) AS excerpt,
                CASE WHEN source.ordinal IS NULL THEN NULL
                     ELSE target.ordinal - source.ordinal END AS chapter_distance
            FROM memory_documents d
            LEFT JOIN ordered source ON source.id = d.chapter_id
            CROSS JOIN target
            WHERE d.id IN ({placeholders})
              AND d.review_status IN ('APPROVED', 'LOCKED')
              AND (d.chapter_id IS NULL OR source.ordinal < target.ordinal)
            ORDER BY d.id
            """,
            (before_chapter_id, *scores),
        ).fetchall()
        return tuple(
            SearchRow(
                self._document(row),
                None,
                scores[row["id"]],
                row["excerpt"],
                _chapter_distance(row),
                ("EMBEDDING",),
            )
            for row in rows
        )

    @staticmethod
    def _document(row: sqlite3.Row) -> SearchDocument:
        return SearchDocument(
            row["id"],
            row["document_type"],
            row["source_id"],
            row["chapter_id"],
            row["volume_id"],
            int(row["source_revision"]),
            row["source_hash"],
            row["title"],
            row["content"],
            tuple(value for value in row["participants"].split(" ") if value),
            float(row["pinned_weight"]),
            ReviewStatus(row["review_status"]),
            MemoryStatus(row["status"]),
            datetime.fromisoformat(row["updated_at"]),
        )


def _keyword_query(query: str) -> str:
    terms: list[str] = []
    for match in _SEARCH_TERM.finditer(query.casefold()):
        value = match.group(0)
        candidates = (
            (value,)
            if value.isascii()
            else tuple(value[index : index + 3] for index in range(len(value) - 2))
        )
        for candidate in candidates:
            if candidate not in terms:
                terms.append(candidate)
            if len(terms) >= _MAX_KEYWORD_TERMS:
                break
        if len(terms) >= _MAX_KEYWORD_TERMS:
            break
    return " OR ".join(f'"{term}"' for term in terms)


def _embedding_source(document: SearchDocument) -> EmbeddingSource:
    if document.status != MemoryStatus.CURRENT or document.review_status not in {
        ReviewStatus.APPROVED,
        ReviewStatus.LOCKED,
    }:
        raise ValueError("only current reviewed memory documents can be embedded")
    text = _embedding_text(document.title, document.content)
    return EmbeddingSource(
        document.id,
        text,
        _hash_text(text),
    )


def _embedding_text(title: str, content: str) -> str:
    return f"{title.strip()}\n\n{content.strip()}"


def _embedding_content_hash(title: str, content: str) -> str:
    return _hash_text(_embedding_text(title, content))


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _model_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 200:
        raise ValueError("embedding model ID is invalid")
    return normalized


def _content_hash(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError("embedding content hash must be a SHA-256 hex digest")
    return normalized


def _embedding_vector(values: tuple[float, ...]) -> tuple[float, ...]:
    if not values or len(values) > _MAX_EMBEDDING_DIMENSIONS:
        raise ValueError("embedding vector dimensions are invalid")
    normalized: list[float] = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError("embedding vector values must be finite numbers")
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError("embedding vector values must be finite numbers") from error
        if not isfinite(number):
            raise ValueError("embedding vector values must be finite numbers")
        normalized.append(number)
    return tuple(normalized)


def _stored_embedding(row: sqlite3.Row) -> StoredEmbedding:
    try:
        decoded = json.loads(row["vector_json"])
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("stored embedding vector is invalid") from error
    if not isinstance(decoded, list):
        raise ValueError("stored embedding vector is invalid")
    try:
        vector = _embedding_vector(tuple(decoded))
    except ValueError as error:
        raise ValueError("stored embedding vector is invalid") from error
    dimensions = int(row["dimensions"])
    if dimensions != len(vector):
        raise ValueError("stored embedding dimensions do not match vector")
    return StoredEmbedding(
        row["document_id"],
        row["model_id"],
        dimensions,
        vector,
        _content_hash(row["content_hash"]),
        MemoryStatus(row["status"]),
        datetime.fromisoformat(row["created_at"]),
        datetime.fromisoformat(row["updated_at"]),
    )


def _chapter_distance(row: sqlite3.Row) -> int | None:
    value = row["chapter_distance"]
    return int(value) if value is not None else None


def _merge_rows(rows: list[SearchRow]) -> tuple[SearchRow, ...]:
    merged: dict[str, SearchRow] = {}
    for row in rows:
        current = merged.get(row.document.id)
        if current is None:
            merged[row.document.id] = row
            continue
        lexical_candidates = tuple(
            value
            for value in (current.lexical_rank, row.lexical_rank)
            if value is not None
        )
        lexical_rank = min(lexical_candidates) if lexical_candidates else None
        semantic_score = max(current.semantic_score, row.semantic_score)
        routes = tuple(
            sorted(
                set((*current.retrieval_routes, *row.retrieval_routes)),
                key=_ROUTE_ORDER.__getitem__,
            )
        )
        excerpt = current.excerpt
        if current.lexical_rank is None and row.lexical_rank is not None:
            excerpt = row.excerpt
        merged[row.document.id] = SearchRow(
            row.document,
            lexical_rank,
            semantic_score,
            excerpt,
            row.chapter_distance,
            routes,
        )
    return tuple(merged[document_id] for document_id in sorted(merged))
