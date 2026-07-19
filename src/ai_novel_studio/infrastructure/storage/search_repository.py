from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

RetrievalRoute = Literal["EXACT_PHRASE", "KEYWORD", "SUBJECT"]

_SEARCH_TERM = re.compile(r"[a-z0-9_]{3,}|[\u3400-\u4dbf\u4e00-\u9fff]+")
_MAX_KEYWORD_TERMS = 24
_MAX_SEARCH_QUERY_CHARS = 20_000
_MAX_SEARCH_PARTICIPANTS = 64
_ROUTE_ORDER: dict[RetrievalRoute, int] = {
    "EXACT_PHRASE": 0,
    "KEYWORD": 1,
    "SUBJECT": 2,
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
class SearchRow:
    document: SearchDocument
    lexical_rank: float | None
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

    def search_rows(
        self,
        query: str,
        before_chapter_id: str,
        *,
        participants: tuple[str, ...] = (),
        limit: int,
    ) -> tuple[SearchRow, ...]:
        normalized_query = query.strip()[:_MAX_SEARCH_QUERY_CHARS]
        normalized_participants = tuple(
            dict.fromkeys(value.strip() for value in participants if value.strip())
        )[:_MAX_SEARCH_PARTICIPANTS]
        if not normalized_query and not normalized_participants:
            return ()
        route_rows: list[SearchRow] = []
        candidate_limit = max(limit * 5, limit)
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
                row["excerpt"],
                _chapter_distance(row),
                ("SUBJECT",),
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
            excerpt,
            row.chapter_distance,
            routes,
        )
    return tuple(merged[document_id] for document_id in sorted(merged))
