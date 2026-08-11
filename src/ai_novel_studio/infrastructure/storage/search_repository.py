from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from math import fsum, hypot, isfinite
from typing import Literal

from ai_novel_studio.domain.embedding import EmbeddingIndexIdentity
from ai_novel_studio.domain.identifiers import new_id, validate_id
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus
from ai_novel_studio.infrastructure.storage.formal_manuscript_projection import (
    FORMAL_MANUSCRIPT_DOCUMENT_TYPE,
    _chunk_policy_version,
    _nonnegative_integer,
    _same_formal_projection,
    _validated_formal_chunks,
)
from ai_novel_studio.infrastructure.storage.formal_manuscript_projection import (
    FormalManuscriptChunk as FormalManuscriptChunk,
)
from ai_novel_studio.infrastructure.storage.formal_manuscript_projection import (
    formal_manuscript_chunk_source_id as formal_manuscript_chunk_source_id,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

RetrievalRoute = Literal["EXACT_PHRASE", "KEYWORD", "EMBEDDING", "SUBJECT"]
MAX_RECALL_CANDIDATES = 250
MAX_SEARCH_QUERY_CHARS = 20_000
MAX_FORMAL_CHUNKS_PER_CHAPTER = 10_000
MAX_FORMAL_EVIDENCE_CANDIDATES = 50
MAX_FORMAL_EVIDENCE_NEIGHBOR_RADIUS = 2
MAX_FORMAL_EVIDENCE_HIT_CODEPOINTS = 8_000

_SEARCH_TERM = re.compile(r"[a-z0-9_]{3,}|[\u3400-\u4dbf\u4e00-\u9fff]+")
_MAX_KEYWORD_TERMS = 24
_MAX_SEARCH_PARTICIPANTS = 64
_MAX_DOCUMENT_ID_CHARS = 200
_MAX_EMBEDDING_DIMENSIONS = 32_768
_MAX_EMBEDDING_JSON_CHARS = 1_000_000
_MAX_EMBEDDING_SCAN_ROWS = 5_000
_MAX_EMBEDDING_SCAN_VALUES = 8_000_000
_ROUTE_ORDER: dict[RetrievalRoute, int] = {
    "EXACT_PHRASE": 0,
    "KEYWORD": 1,
    "EMBEDDING": 2,
    "SUBJECT": 3,
}
_FORMAL_STORAGE_REVIEW_STATUSES = frozenset({ReviewStatus.APPROVED})
_FORMAL_EVIDENCE_REVIEW_STATUSES = frozenset(
    {ReviewStatus.APPROVED, ReviewStatus.LOCKED}
)


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
    source_start: int | None = None
    source_end: int | None = None
    chunk_ordinal: int | None = None
    chunk_policy_version: str | None = None


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
    identity: EmbeddingIndexIdentity
    dimensions: int
    vector: tuple[float, ...]
    content_hash: str
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime

    @property
    def provider_id(self) -> str:
        return self.identity.provider_id

    @property
    def model_id(self) -> str:
        return self.identity.model_id

    @property
    def embedding_schema_version(self) -> int:
        return self.identity.embedding_schema_version


@dataclass(frozen=True, slots=True)
class SearchRow:
    document: SearchDocument
    lexical_rank: float | None
    semantic_score: float
    excerpt: str
    chapter_distance: int | None
    retrieval_routes: tuple[RetrievalRoute, ...]


@dataclass(frozen=True, slots=True)
class FormalManuscriptEvidenceProjection:
    document_id: str
    source_id: str
    chapter_id: str
    volume_id: str
    source_revision: int
    source_hash: str
    title: str
    source_start: int
    source_end: int
    text: str
    expanded_document_ids: tuple[str, ...]


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
        if document_type.strip() == FORMAL_MANUSCRIPT_DOCUMENT_TYPE:
            raise ValueError(
                "FORMAL_MANUSCRIPT rows require the dedicated revision-aware operation"
            )
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
                INSERT INTO memory_documents (
                    id, document_type, source_id, chapter_id, volume_id,
                    source_revision, source_hash, title, content, participants,
                    pinned_weight, review_status, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def replace_formal_manuscript_chunks(
        self,
        chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
        chunk_policy_version: str,
        chunks: tuple[FormalManuscriptChunk, ...],
    ) -> tuple[SearchDocument, ...]:
        return self._write_formal_manuscript_chunks(
            chapter_id,
            expected_revision=expected_revision,
            expected_source_hash=expected_source_hash,
            chunk_policy_version=chunk_policy_version,
            chunks=chunks,
            repair=False,
        )

    def repair_formal_manuscript_chunks(
        self,
        chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
        chunk_policy_version: str,
        chunks: tuple[FormalManuscriptChunk, ...],
    ) -> tuple[SearchDocument, ...]:
        return self._write_formal_manuscript_chunks(
            chapter_id,
            expected_revision=expected_revision,
            expected_source_hash=expected_source_hash,
            chunk_policy_version=chunk_policy_version,
            chunks=chunks,
            repair=True,
        )

    def invalidate_formal_manuscript_chunks(
        self,
        chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
    ) -> int:
        canonical_chapter_id = validate_id(chapter_id)
        revision = _nonnegative_integer(expected_revision, "chapter revision")
        source_hash = _source_hash(expected_source_hash)
        now = _now().isoformat()
        try:
            with self.project.database.connect() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                self._current_formal_source(
                    connection,
                    canonical_chapter_id,
                    revision,
                    source_hash,
                )
                rows = connection.execute(
                    """
                    SELECT id FROM memory_documents
                    WHERE document_type = ? AND chapter_id = ?
                    ORDER BY id
                    """,
                    (FORMAL_MANUSCRIPT_DOCUMENT_TYPE, canonical_chapter_id),
                ).fetchall()
                connection.execute(
                    """
                    UPDATE memory_dependencies SET status = 'STALE'
                    WHERE memory_type = 'SEARCH'
                      AND memory_id IN (
                          SELECT id FROM memory_documents
                          WHERE document_type = ? AND chapter_id = ?
                      )
                    """,
                    (FORMAL_MANUSCRIPT_DOCUMENT_TYPE, canonical_chapter_id),
                )
                connection.execute(
                    """
                    UPDATE memory_embeddings
                    SET status = 'STALE', updated_at = ?
                    WHERE status != 'STALE'
                      AND document_id IN (
                          SELECT id FROM memory_documents
                          WHERE document_type = ? AND chapter_id = ?
                      )
                    """,
                    (
                        now,
                        FORMAL_MANUSCRIPT_DOCUMENT_TYPE,
                        canonical_chapter_id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE memory_documents SET status = 'STALE'
                    WHERE document_type = ? AND chapter_id = ?
                      AND status != 'STALE'
                    """,
                    (FORMAL_MANUSCRIPT_DOCUMENT_TYPE, canonical_chapter_id),
                )
                self._current_formal_source(
                    connection,
                    canonical_chapter_id,
                    revision,
                    source_hash,
                )
        except sqlite3.Error:
            raise RuntimeError(
                "formal manuscript projection invalidation failed"
            ) from None
        return len(rows)

    def _write_formal_manuscript_chunks(
        self,
        chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
        chunk_policy_version: str,
        chunks: tuple[FormalManuscriptChunk, ...],
        repair: bool,
    ) -> tuple[SearchDocument, ...]:
        canonical_chapter_id = validate_id(chapter_id)
        revision = _nonnegative_integer(expected_revision, "chapter revision")
        source_hash = _source_hash(expected_source_hash)
        policy_version = _chunk_policy_version(chunk_policy_version)
        if not isinstance(chunks, tuple):
            raise ValueError("formal manuscript chunks must be a tuple")
        if len(chunks) > MAX_FORMAL_CHUNKS_PER_CHAPTER:
            raise ValueError("formal manuscript chunk count exceeds storage limit")
        now = _now()
        with self.project.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            chapter, current_content = self._current_formal_source(
                connection,
                canonical_chapter_id,
                revision,
                source_hash,
            )
            normalized_chunks = _validated_formal_chunks(
                canonical_chapter_id,
                revision,
                policy_version,
                current_content,
                chunks,
            )
            existing_rows = connection.execute(
                """
                SELECT * FROM memory_documents
                WHERE document_type = ? AND chapter_id = ?
                ORDER BY chunk_ordinal, id
                """,
                (FORMAL_MANUSCRIPT_DOCUMENT_TYPE, canonical_chapter_id),
            ).fetchall()
            if repair:
                expected_source_ids = {
                    chunk.source_id for chunk in normalized_chunks
                }
                if any(
                    str(row["source_id"]) in expected_source_ids
                    and (
                        str(row["title"]) != str(chapter["title"])
                        or str(row["volume_id"]) != str(chapter["volume_id"])
                    )
                    for row in existing_rows
                ):
                    raise RuntimeError(
                        "formal manuscript source metadata requires a new revision"
                    )
                _delete_formal_document_rows(connection, existing_rows)
                existing_rows = []
            existing_by_source = {
                str(row["source_id"]): row for row in existing_rows
            }
            retained_ids: set[str] = set()
            for chunk in normalized_chunks:
                existing = existing_by_source.get(chunk.source_id)
                if existing is not None:
                    if not _same_formal_projection(
                        existing,
                        chapter_id=canonical_chapter_id,
                        chapter_volume_id=str(chapter["volume_id"]),
                        chapter_title=str(chapter["title"]),
                        revision=revision,
                        source_hash=source_hash,
                        policy_version=policy_version,
                        chunk=chunk,
                    ):
                        raise RuntimeError(
                            "formal manuscript deterministic identity changed projection"
                        )
                    retained_ids.add(str(existing["id"]))
                    continue
                document_id = new_id()
                retained_ids.add(document_id)
                cursor = connection.execute(
                    """
                    INSERT INTO memory_documents (
                        id, document_type, source_id, chapter_id, volume_id,
                        source_revision, source_hash, title, content, participants,
                        pinned_weight, review_status, status, updated_at,
                        source_start, source_end, chunk_ordinal, chunk_policy_version
                    ) VALUES (
                        ?, 'FORMAL_MANUSCRIPT', ?, ?, ?, ?, ?, ?, ?, '',
                        0, 'APPROVED', 'CURRENT', ?, ?, ?, ?, ?
                    )
                    ON CONFLICT(document_type, source_id) DO UPDATE SET
                        chapter_id = excluded.chapter_id,
                        volume_id = excluded.volume_id,
                        source_revision = excluded.source_revision,
                        source_hash = excluded.source_hash,
                        title = excluded.title,
                        content = excluded.content,
                        participants = '',
                        pinned_weight = 0,
                        review_status = 'APPROVED',
                        status = 'CURRENT',
                        updated_at = excluded.updated_at,
                        source_start = excluded.source_start,
                        source_end = excluded.source_end,
                        chunk_ordinal = excluded.chunk_ordinal,
                        chunk_policy_version = excluded.chunk_policy_version
                    WHERE memory_documents.chapter_id = excluded.chapter_id
                    """,
                    (
                        document_id,
                        chunk.source_id,
                        canonical_chapter_id,
                        chapter["volume_id"],
                        revision,
                        source_hash,
                        chapter["title"],
                        chunk.content,
                        now.isoformat(),
                        chunk.source_start,
                        chunk.source_end,
                        chunk.ordinal,
                        policy_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "formal manuscript source ID belongs to another chapter"
                    )
                connection.execute(
                    "DELETE FROM memory_fts WHERE document_id = ?",
                    (document_id,),
                )
                connection.execute(
                    "INSERT INTO memory_fts VALUES (?, ?, ?, '')",
                    (document_id, chapter["title"], chunk.content),
                )
                connection.execute(
                    """
                    UPDATE memory_embeddings
                    SET status = 'STALE', updated_at = ?
                    WHERE document_id = ? AND status != 'STALE'
                      AND content_hash != ?
                    """,
                    (
                        now.isoformat(),
                        document_id,
                        _embedding_content_hash(chapter["title"], chunk.content),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO memory_dependencies
                    VALUES (?, 'SEARCH', ?, ?, ?, ?, 'CURRENT')
                    ON CONFLICT(memory_type, memory_id, source_chapter_id)
                    DO UPDATE SET
                        source_revision = excluded.source_revision,
                        source_hash = excluded.source_hash,
                        status = 'CURRENT'
                    """,
                    (
                        new_id(),
                        document_id,
                        canonical_chapter_id,
                        revision,
                        source_hash,
                    ),
                )
            obsolete_ids = {
                str(row["id"]) for row in existing_rows
            }.difference(retained_ids)
            for document_id in sorted(obsolete_ids):
                connection.execute(
                    """
                    DELETE FROM memory_dependencies
                    WHERE memory_type = 'SEARCH' AND memory_id = ?
                    """,
                    (document_id,),
                )
                connection.execute(
                    "DELETE FROM memory_fts WHERE document_id = ?",
                    (document_id,),
                )
                connection.execute(
                    "DELETE FROM memory_documents WHERE id = ?",
                    (document_id,),
                )
            self._current_formal_source(
                connection,
                canonical_chapter_id,
                revision,
                source_hash,
            )
        return self.read_formal_manuscript_chunks(
            canonical_chapter_id,
            expected_revision=revision,
            expected_source_hash=source_hash,
            chunk_policy_version=policy_version,
        )

    def formal_manuscript_recovery_chapter_ids(
        self,
        *,
        after_chapter_id: str | None = None,
        limit: int,
    ) -> tuple[str, ...]:
        if after_chapter_id is not None:
            after_chapter_id = validate_id(after_chapter_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 101:
            raise ValueError("formal manuscript recovery limit must be between 1 and 101")
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT chapter_id
                FROM (
                    SELECT id AS chapter_id FROM chapters
                    UNION
                    SELECT chapter_id FROM memory_documents
                    WHERE document_type = 'FORMAL_MANUSCRIPT'
                      AND chapter_id IS NOT NULL
                )
                WHERE (? IS NULL OR chapter_id > ?)
                ORDER BY chapter_id
                LIMIT ?
                """,
                (after_chapter_id, after_chapter_id, limit),
            ).fetchall()
        return tuple(str(row["chapter_id"]) for row in rows)

    def remove_orphaned_formal_manuscript_chunks(self, chapter_id: str) -> int:
        canonical_chapter_id = validate_id(chapter_id)
        with self.project.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            source_row = connection.execute(
                "SELECT is_deleted FROM chapters WHERE id = ?",
                (canonical_chapter_id,),
            ).fetchone()
            if source_row is not None and int(source_row["is_deleted"]) == 0:
                raise RuntimeError("current chapter formal projection cannot be removed")
            existing_rows = connection.execute(
                """
                SELECT * FROM memory_documents
                WHERE document_type = ? AND chapter_id = ?
                ORDER BY chunk_ordinal, id
                """,
                (FORMAL_MANUSCRIPT_DOCUMENT_TYPE, canonical_chapter_id),
            ).fetchall()
            _delete_formal_document_rows(connection, existing_rows)
            source_row = connection.execute(
                "SELECT is_deleted FROM chapters WHERE id = ?",
                (canonical_chapter_id,),
            ).fetchone()
            if source_row is not None and int(source_row["is_deleted"]) == 0:
                raise RuntimeError("chapter became current during formal removal")
        return len(existing_rows)

    def read_formal_manuscript_chunks(
        self,
        chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
        chunk_policy_version: str,
    ) -> tuple[SearchDocument, ...]:
        canonical_chapter_id = validate_id(chapter_id)
        revision = _nonnegative_integer(expected_revision, "chapter revision")
        source_hash = _source_hash(expected_source_hash)
        policy_version = _chunk_policy_version(chunk_policy_version)
        with self.project.database.connect() as connection:
            chapter, current_content = self._current_formal_source(
                connection,
                canonical_chapter_id,
                revision,
                source_hash,
            )
            rows = connection.execute(
                """
                SELECT * FROM memory_documents
                WHERE document_type = ? AND chapter_id = ?
                ORDER BY chunk_ordinal, id
                """,
                (FORMAL_MANUSCRIPT_DOCUMENT_TYPE, canonical_chapter_id),
            ).fetchall()
            documents = tuple(self._document(row) for row in rows)
            _validate_stored_formal_documents(
                connection,
                documents,
                chapter_title=str(chapter["title"]),
                chapter_volume_id=str(chapter["volume_id"]),
                chapter_id=canonical_chapter_id,
                revision=revision,
                source_hash=source_hash,
                policy_version=policy_version,
                current_content=current_content,
            )
        return documents

    def hydrate_formal_manuscript_candidates(
        self,
        target_chapter_id: str,
        candidate_document_ids: tuple[str, ...],
        *,
        neighbor_radius: int,
        max_codepoints_per_hit: int,
    ) -> tuple[FormalManuscriptEvidenceProjection, ...]:
        canonical_target_id = validate_id(target_chapter_id)
        if (
            not isinstance(candidate_document_ids, tuple)
            or len(candidate_document_ids) > MAX_FORMAL_EVIDENCE_CANDIDATES
        ):
            raise ValueError("formal evidence candidate set is invalid")
        canonical_document_ids = tuple(
            validate_id(document_id) for document_id in candidate_document_ids
        )
        if (
            isinstance(neighbor_radius, bool)
            or not isinstance(neighbor_radius, int)
            or not 0 <= neighbor_radius <= MAX_FORMAL_EVIDENCE_NEIGHBOR_RADIUS
        ):
            raise ValueError("formal evidence neighbor radius is invalid")
        if (
            isinstance(max_codepoints_per_hit, bool)
            or not isinstance(max_codepoints_per_hit, int)
            or not 1
            <= max_codepoints_per_hit
            <= MAX_FORMAL_EVIDENCE_HIT_CODEPOINTS
        ):
            raise ValueError("formal evidence per-hit limit is invalid")

        hydrated: list[FormalManuscriptEvidenceProjection] = []
        with self.project.database.connect() as connection:
            connection.execute("BEGIN")
            target = _active_chapter_order(connection, canonical_target_id)
            if target is None:
                raise KeyError("formal evidence target chapter is unavailable")
            chapter_cache: dict[
                str,
                tuple[sqlite3.Row, str, tuple[SearchDocument, ...]],
            ] = {}
            for document_id in canonical_document_ids:
                row = connection.execute(
                    "SELECT * FROM memory_documents WHERE id = ?",
                    (document_id,),
                ).fetchone()
                if row is None or not _eligible_formal_evidence_row(row):
                    continue
                chapter_id = str(row["chapter_id"])
                source_chapter = _active_chapter_order(connection, chapter_id)
                if source_chapter is None or _chapter_order_key(
                    source_chapter
                ) >= _chapter_order_key(target):
                    continue
                if int(row["source_revision"]) != int(source_chapter["revision"]):
                    continue
                if str(row["source_hash"]) != str(source_chapter["content_hash"]):
                    raise RuntimeError("formal manuscript evidence source hash is invalid")
                policy_version = _chunk_policy_version(
                    str(row["chunk_policy_version"])
                )
                revision = int(source_chapter["revision"])
                source_hash = _source_hash(str(source_chapter["content_hash"]))
                cached = chapter_cache.get(chapter_id)
                if cached is None:
                    chapter, current_content = self._current_formal_source(
                        connection,
                        chapter_id,
                        revision,
                        source_hash,
                    )
                    rows = connection.execute(
                        """
                        SELECT * FROM memory_documents
                        WHERE document_type = ? AND chapter_id = ?
                        ORDER BY chunk_ordinal, id
                        """,
                        (FORMAL_MANUSCRIPT_DOCUMENT_TYPE, chapter_id),
                    ).fetchall()
                    documents = tuple(self._document(item) for item in rows)
                    _validate_stored_formal_documents(
                        connection,
                        documents,
                        chapter_title=str(chapter["title"]),
                        chapter_volume_id=str(chapter["volume_id"]),
                        chapter_id=chapter_id,
                        revision=revision,
                        source_hash=source_hash,
                        policy_version=policy_version,
                        current_content=current_content,
                        allowed_review_statuses=_FORMAL_EVIDENCE_REVIEW_STATUSES,
                    )
                    chapter_cache[chapter_id] = (chapter, current_content, documents)
                else:
                    chapter, current_content, documents = cached
                documents_by_id = {document.id: document for document in documents}
                primary = documents_by_id.get(document_id)
                if primary is None or primary.chunk_ordinal is None:
                    raise RuntimeError("formal manuscript evidence candidate is invalid")
                selected = _expanded_formal_evidence_documents(
                    documents,
                    primary.chunk_ordinal,
                    neighbor_radius=neighbor_radius,
                    max_codepoints=max_codepoints_per_hit,
                )
                source_start = min(
                    _required_projection_integer(document.source_start) for document in selected
                )
                source_end = max(
                    _required_projection_integer(document.source_end) for document in selected
                )
                text = current_content[source_start:source_end]
                hydrated.append(
                    FormalManuscriptEvidenceProjection(
                        primary.id,
                        primary.source_id,
                        chapter_id,
                        str(chapter["volume_id"]),
                        revision,
                        source_hash,
                        str(chapter["title"]),
                        source_start,
                        source_end,
                        text,
                        tuple(document.id for document in selected),
                    )
                )
            for chapter_id, (chapter, current_content, _documents) in chapter_cache.items():
                _chapter_after, current_content_after = self._current_formal_source(
                    connection,
                    chapter_id,
                    int(chapter["revision"]),
                    _source_hash(str(chapter["content_hash"])),
                )
                if current_content_after != current_content:
                    raise RuntimeError(
                        "formal manuscript source changed during evidence hydrate"
                    )
        return tuple(hydrated)

    def _current_formal_source(
        self,
        connection: sqlite3.Connection,
        chapter_id: str,
        expected_revision: int,
        expected_source_hash: str,
    ) -> tuple[sqlite3.Row, str]:
        chapter = connection.execute(
            """
            SELECT id, volume_id, title, content_path, revision, content_hash
            FROM chapters
            WHERE id = ? AND is_deleted = 0
            """,
            (chapter_id,),
        ).fetchone()
        if chapter is None:
            raise KeyError(f"unknown or deleted chapter: {chapter_id}")
        if int(chapter["revision"]) != expected_revision:
            raise RuntimeError("formal manuscript chapter revision changed")
        if _source_hash(str(chapter["content_hash"])) != expected_source_hash:
            raise RuntimeError("formal manuscript chapter hash changed")
        manuscript_root = self.project.layout.manuscript.resolve()
        source_path = (
            self.project.layout.root / str(chapter["content_path"])
        ).resolve()
        try:
            source_path.relative_to(manuscript_root)
        except ValueError as error:
            raise RuntimeError(
                "formal manuscript source path is outside manuscript directory"
            ) from error
        if not source_path.is_file():
            raise RuntimeError("formal manuscript source file is missing")
        try:
            with source_path.open("r", encoding="utf-8", newline="") as stream:
                current_content = stream.read()
        except (OSError, UnicodeError):
            raise RuntimeError(
                "formal manuscript source file cannot be read as UTF-8"
            ) from None
        if _hash_text(current_content) != expected_source_hash:
            raise RuntimeError("formal manuscript source file does not match current chapter")
        return chapter, current_content

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
        identity: EmbeddingIndexIdentity,
        vector: tuple[float, ...],
        *,
        expected_content_hash: str,
    ) -> StoredEmbedding:
        normalized_identity = _embedding_identity(identity)
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
            dimensions_mismatch = connection.execute(
                """
                SELECT 1 FROM memory_embeddings
                WHERE provider_id = ? AND model_id = ?
                  AND embedding_schema_version = ?
                  AND dimensions != ?
                LIMIT 1
                """,
                (
                    normalized_identity.provider_id,
                    normalized_identity.model_id,
                    normalized_identity.embedding_schema_version,
                    len(normalized_vector),
                ),
            ).fetchone()
            if dimensions_mismatch is not None:
                raise ValueError("embedding dimensions changed for the same identity")
            connection.execute(
                """
                INSERT INTO memory_embeddings (
                    document_id, provider_id, model_id, embedding_schema_version,
                    dimensions, vector_json, content_hash, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'CURRENT', ?, ?)
                ON CONFLICT(
                    document_id, provider_id, model_id, embedding_schema_version
                ) DO UPDATE SET
                    dimensions = excluded.dimensions,
                    vector_json = excluded.vector_json,
                    content_hash = excluded.content_hash,
                    status = 'CURRENT',
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    normalized_identity.provider_id,
                    normalized_identity.model_id,
                    normalized_identity.embedding_schema_version,
                    len(normalized_vector),
                    vector_json,
                    normalized_hash,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return self.get_embedding(document_id, normalized_identity)

    def get_embedding(
        self,
        document_id: str,
        identity: EmbeddingIndexIdentity,
    ) -> StoredEmbedding:
        normalized_identity = _embedding_identity(identity)
        with self.project.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM memory_embeddings
                WHERE document_id = ?
                  AND provider_id = ?
                  AND model_id = ?
                  AND embedding_schema_version = ?
                """,
                (
                    document_id,
                    normalized_identity.provider_id,
                    normalized_identity.model_id,
                    normalized_identity.embedding_schema_version,
                ),
            ).fetchone()
        if row is None:
            raise KeyError(
                "unknown memory embedding: "
                f"{document_id}/{normalized_identity.provider_id}/"
                f"{normalized_identity.model_id}/"
                f"{normalized_identity.embedding_schema_version}"
            )
        stored = _stored_embedding(row)
        if stored.identity != normalized_identity:
            raise RuntimeError("stored embedding identity mismatch")
        return stored

    def pending_embedding_sources(
        self,
        identity: EmbeddingIndexIdentity,
        *,
        limit: int = 100,
    ) -> tuple[EmbeddingSource, ...]:
        normalized_identity = _embedding_identity(identity)
        if limit <= 0 or limit > MAX_RECALL_CANDIDATES:
            raise ValueError(
                f"embedding rebuild limit must be between 1 and {MAX_RECALL_CANDIDATES}"
            )
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT d.* FROM memory_documents d
                LEFT JOIN memory_embeddings e
                  ON e.document_id = d.id
                 AND e.provider_id = ?
                 AND e.model_id = ?
                 AND e.embedding_schema_version = ?
                WHERE d.status = 'CURRENT'
                  AND d.review_status IN ('APPROVED', 'LOCKED')
                  AND (e.document_id IS NULL OR e.status = 'STALE')
                ORDER BY d.pinned_weight DESC, d.updated_at DESC, d.id
                LIMIT ?
                """,
                (
                    normalized_identity.provider_id,
                    normalized_identity.model_id,
                    normalized_identity.embedding_schema_version,
                    limit,
                ),
            ).fetchall()
        return tuple(_embedding_source(self._document(row)) for row in rows)

    def recall_embeddings(
        self,
        identity: EmbeddingIndexIdentity,
        query_vector: tuple[float, ...],
        *,
        limit: int,
    ) -> tuple[EmbeddingCandidate, ...]:
        normalized_identity = _embedding_identity(identity)
        if limit <= 0 or limit > MAX_RECALL_CANDIDATES:
            raise ValueError(
                f"embedding recall limit must be between 1 and {MAX_RECALL_CANDIDATES}"
            )
        try:
            normalized_query = _embedding_vector(query_vector)
        except ValueError as error:
            raise ValueError("embedding query vector is invalid") from error
        query_unit = _unit_vector(normalized_query)
        if query_unit is None:
            raise ValueError("embedding query vector cannot be zero")
        scan_limit = min(
            _MAX_EMBEDDING_SCAN_ROWS,
            max(limit, _MAX_EMBEDDING_SCAN_VALUES // len(query_unit)),
        )
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.*, d.title AS source_title, d.content AS source_content
                FROM memory_embeddings e
                JOIN memory_documents d ON d.id = e.document_id
                WHERE e.provider_id = ?
                  AND e.model_id = ?
                  AND e.embedding_schema_version = ?
                  AND e.status = 'CURRENT'
                  AND d.status = 'CURRENT'
                  AND d.review_status IN ('APPROVED', 'LOCKED')
                ORDER BY d.pinned_weight DESC, d.updated_at DESC, d.id
                LIMIT ?
                """,
                (
                    normalized_identity.provider_id,
                    normalized_identity.model_id,
                    normalized_identity.embedding_schema_version,
                    scan_limit,
                ),
            ).fetchall()
        candidates: list[EmbeddingCandidate] = []
        for row in rows:
            if row["content_hash"] != _embedding_content_hash(
                row["source_title"],
                row["source_content"],
            ):
                continue
            try:
                stored = _stored_embedding(row)
            except (TypeError, ValueError):
                continue
            if stored.identity != normalized_identity:
                continue
            similarity = _cosine_similarity(query_unit, stored.vector)
            if similarity is not None:
                candidates.append(EmbeddingCandidate(stored.document_id, similarity))
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (-candidate.similarity, candidate.document_id),
            )[:limit]
        )

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
            _optional_integer(row["source_start"]),
            _optional_integer(row["source_end"]),
            _optional_integer(row["chunk_ordinal"]),
            (
                str(row["chunk_policy_version"])
                if row["chunk_policy_version"] is not None
                else None
            ),
        )


def _validate_stored_formal_documents(
    connection: sqlite3.Connection,
    documents: tuple[SearchDocument, ...],
    *,
    chapter_title: str,
    chapter_volume_id: str,
    chapter_id: str,
    revision: int,
    source_hash: str,
    policy_version: str,
    current_content: str,
    allowed_review_statuses: frozenset[ReviewStatus] = _FORMAL_STORAGE_REVIEW_STATUSES,
) -> None:
    dependency_rows = connection.execute(
        """
        SELECT memory_id, source_revision, source_hash, status
        FROM memory_dependencies
        WHERE memory_type = 'SEARCH' AND source_chapter_id = ?
        """,
        (chapter_id,),
    ).fetchall()
    dependencies_by_document: dict[str, list[sqlite3.Row]] = {}
    for row in dependency_rows:
        dependencies_by_document.setdefault(str(row["memory_id"]), []).append(row)
    fts_rows = connection.execute(
        """
        SELECT f.document_id, f.title, f.content, f.participants
        FROM memory_fts f
        JOIN memory_documents d ON d.id = f.document_id
        WHERE d.document_type = ? AND d.chapter_id = ?
        """,
        (FORMAL_MANUSCRIPT_DOCUMENT_TYPE, chapter_id),
    ).fetchall()
    fts_by_document: dict[str, list[sqlite3.Row]] = {}
    for row in fts_rows:
        fts_by_document.setdefault(str(row["document_id"]), []).append(row)
    ordinals: list[int] = []
    for document in documents:
        metadata = (
            document.source_start,
            document.source_end,
            document.chunk_ordinal,
            document.chunk_policy_version,
        )
        if any(value is None for value in metadata):
            raise RuntimeError("formal manuscript projection metadata is incomplete")
        source_start = _nonnegative_integer(
            document.source_start,
            "chunk range start",
        )
        source_end = _nonnegative_integer(document.source_end, "chunk range end")
        ordinal = _nonnegative_integer(document.chunk_ordinal, "chunk ordinal")
        stored_policy = _chunk_policy_version(str(document.chunk_policy_version))
        if not 0 <= source_start < source_end <= len(current_content):
            raise RuntimeError("stored formal manuscript range is invalid")
        if current_content[source_start:source_end] != document.content:
            raise RuntimeError("stored formal manuscript slice does not match current source")
        expected_source_id = formal_manuscript_chunk_source_id(
            chapter_id,
            revision,
            policy_version,
            ordinal,
        )
        if (
            document.document_type != FORMAL_MANUSCRIPT_DOCUMENT_TYPE
            or document.source_id != expected_source_id
            or document.chapter_id != chapter_id
            or document.volume_id != chapter_volume_id
            or document.source_revision != revision
            or document.source_hash != source_hash
            or document.title != chapter_title
            or document.participants
            or document.pinned_weight != 0
            or document.review_status not in allowed_review_statuses
            or document.status != MemoryStatus.CURRENT
            or stored_policy != policy_version
        ):
            raise RuntimeError("stored formal manuscript identity is invalid")
        dependencies = dependencies_by_document.get(document.id, [])
        if len(dependencies) != 1 or tuple(dependencies[0])[1:] != (
            revision,
            source_hash,
            "CURRENT",
        ):
            raise RuntimeError("stored formal manuscript dependency is invalid")
        document_fts_rows = fts_by_document.get(document.id, [])
        if len(document_fts_rows) != 1 or tuple(document_fts_rows[0])[1:] != (
            chapter_title,
            document.content,
            "",
        ):
            raise RuntimeError("stored formal manuscript FTS projection is invalid")
        ordinals.append(ordinal)
    if ordinals != list(range(len(documents))):
        raise RuntimeError("stored formal manuscript ordinal set is invalid")


def _delete_formal_document_rows(
    connection: sqlite3.Connection,
    rows: tuple[sqlite3.Row, ...] | list[sqlite3.Row],
) -> None:
    for row in rows:
        document_id = str(row["id"])
        connection.execute(
            """
            DELETE FROM memory_dependencies
            WHERE memory_type = 'SEARCH' AND memory_id = ?
            """,
            (document_id,),
        )
        connection.execute(
            "DELETE FROM memory_fts WHERE document_id = ?",
            (document_id,),
        )
        connection.execute(
            "DELETE FROM memory_documents WHERE id = ?",
            (document_id,),
        )


def _active_chapter_order(
    connection: sqlite3.Connection,
    chapter_id: str,
) -> sqlite3.Row | None:
    row: sqlite3.Row | None = connection.execute(
        """
        SELECT c.id, c.volume_id, c.title, c.revision, c.content_hash,
               v.sort_index AS volume_sort_index,
               c.sort_index AS chapter_sort_index
        FROM chapters c
        JOIN volumes v ON v.id = c.volume_id
        WHERE c.id = ? AND c.is_deleted = 0
        """,
        (chapter_id,),
    ).fetchone()
    return row


def _chapter_order_key(row: sqlite3.Row) -> tuple[int, int, str]:
    return (
        int(row["volume_sort_index"]),
        int(row["chapter_sort_index"]),
        str(row["id"]),
    )


def _eligible_formal_evidence_row(row: sqlite3.Row) -> bool:
    return (
        row["document_type"] == FORMAL_MANUSCRIPT_DOCUMENT_TYPE
        and row["status"] == MemoryStatus.CURRENT.value
        and row["review_status"]
        in {ReviewStatus.APPROVED.value, ReviewStatus.LOCKED.value}
        and row["chapter_id"] is not None
    )


def _expanded_formal_evidence_documents(
    documents: tuple[SearchDocument, ...],
    primary_ordinal: int,
    *,
    neighbor_radius: int,
    max_codepoints: int,
) -> tuple[SearchDocument, ...]:
    if not 0 <= primary_ordinal < len(documents):
        raise RuntimeError("formal manuscript evidence ordinal is invalid")
    primary = documents[primary_ordinal]
    source_start = _required_projection_integer(primary.source_start)
    source_end = _required_projection_integer(primary.source_end)
    if source_end - source_start > max_codepoints:
        raise RuntimeError("formal manuscript evidence primary chunk exceeds limit")
    selected: dict[int, SearchDocument] = {primary_ordinal: primary}
    for distance in range(1, neighbor_radius + 1):
        for ordinal in (primary_ordinal - distance, primary_ordinal + distance):
            if not 0 <= ordinal < len(documents):
                continue
            neighbor = documents[ordinal]
            expanded_start = min(
                source_start,
                _required_projection_integer(neighbor.source_start),
            )
            expanded_end = max(
                source_end,
                _required_projection_integer(neighbor.source_end),
            )
            if expanded_end - expanded_start <= max_codepoints:
                selected[ordinal] = neighbor
                source_start = expanded_start
                source_end = expanded_end
    return tuple(selected[ordinal] for ordinal in sorted(selected))


def _required_projection_integer(value: int | None) -> int:
    if value is None:
        raise RuntimeError("formal manuscript evidence range is incomplete")
    return value


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


def _source_hash(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("formal manuscript source hash is invalid")
    try:
        return _content_hash(value)
    except ValueError as error:
        raise ValueError("formal manuscript source hash is invalid") from error


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("stored projection integer is invalid")
    return value


def _embedding_identity(value: EmbeddingIndexIdentity) -> EmbeddingIndexIdentity:
    if not isinstance(value, EmbeddingIndexIdentity):
        raise TypeError("embedding index identity is invalid")
    return value


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


def _unit_vector(vector: tuple[float, ...]) -> tuple[float, ...] | None:
    norm = hypot(*vector)
    if not isfinite(norm) or norm <= 0:
        return None
    return tuple(value / norm for value in vector)


def _cosine_similarity(
    query_unit: tuple[float, ...],
    stored_vector: tuple[float, ...],
) -> float | None:
    if len(query_unit) != len(stored_vector):
        return None
    stored_unit = _unit_vector(stored_vector)
    if stored_unit is None:
        return None
    similarity = fsum(
        query_value * stored_value
        for query_value, stored_value in zip(query_unit, stored_unit, strict=True)
    )
    if not isfinite(similarity) or similarity <= 0:
        return None
    return min(1.0, similarity)


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
        EmbeddingIndexIdentity(
            row["provider_id"],
            row["model_id"],
            int(row["embedding_schema_version"]),
        ),
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
