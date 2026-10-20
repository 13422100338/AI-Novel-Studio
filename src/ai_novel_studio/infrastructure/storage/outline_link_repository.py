from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from ai_novel_studio.core.outline_links import (
    MarkdownChapterLink,
    registered_chapter_path,
    scan_chapter_links,
)
from ai_novel_studio.core.outline_markdown import editor_text, outline_headings
from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.domain.identifiers import new_id, validate_id
from ai_novel_studio.domain.outline import (
    OutlineSnapshot,
    outline_bundle_fingerprint,
    validate_outline_hash,
)
from ai_novel_studio.domain.outline_link import (
    OutlineChapterLink,
    OutlineLinkItem,
    OutlineLinkReview,
    OutlineLinkSnapshot,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.outline_repository import (
    OutlineConflictError,
    OutlineIntegrityError,
    OutlineRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _Bundle:
    fingerprint: str
    sources: dict[str, OutlineSnapshot]
    matches: dict[str, tuple[MarkdownChapterLink, ...]]
    chapters: tuple[Chapter, ...]


class OutlineLinkRepository:
    """Lightweight source associations; no chapter text extraction or story graph."""

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project
        self.outlines = OutlineRepository(project)

    def _bundle(self, document_id: str, expected: str | None = None) -> _Bundle:
        validate_id(document_id)
        documents = self.outlines.list_documents()
        if document_id not in {doc.id for doc in documents}:
            raise KeyError("找不到当前项目的大纲")
        sources = {doc.id: self.outlines.read(doc.id) for doc in documents}
        if any(
            sources[d.id].version.revision != d.revision
            or sources[d.id].version.content_hash != d.content_hash
            for d in documents
        ):
            raise OutlineConflictError("大纲在读取期间已变更，请重新检查")
        fingerprint = outline_bundle_fingerprint(self.project.project.id, documents)
        if expected is not None:
            validate_outline_hash(expected)
            if expected != fingerprint:
                raise OutlineConflictError("大纲版本已变更，请重新检查关联后再确认")
        chapters = tuple(ChapterRepository(self.project).list_chapters())
        paths: dict[Path, str] = {}
        for chapter in chapters:
            path = registered_chapter_path(self.project.layout.root, chapter.content_path)
            if path is not None:
                paths[path] = chapter.id
        matches = {
            doc.id: scan_chapter_links(
                sources[doc.id].content,
                self.project.layout.root / "outlines" / f"{doc.id}.md",
                paths,
            )
            for doc in documents
        }
        return _Bundle(fingerprint, sources, matches, chapters)

    def scan(self, document_id: str) -> OutlineLinkSnapshot:
        with closing(self.project.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            bundle = self._bundle(document_id)
            existing = self._rows(connection, document_id)
            counts = Counter(
                (link.chapter_id, link.source_quote) for link in existing if link.active
            )
            positions = {
                (link.source_line, link.source_column, link.chapter_id, link.source_quote)
                for link in existing
                if link.active
            }
            found = bundle.matches[document_id]
            needed = Counter((m.chapter_id, m.quote) for m in found) - counts
            titles = {chapter.id: chapter.title for chapter in bundle.chapters}
            for match in found:
                key = (match.chapter_id, match.quote)
                if needed[key] <= 0 or (match.line, match.column, *key) in positions:
                    continue
                link = OutlineChapterLink(
                    new_id(),
                    document_id,
                    match.chapter_id,
                    titles[match.chapter_id],
                    bundle.sources[document_id].version.revision,
                    match.line,
                    match.column,
                    match.quote,
                    None,
                    True,
                    (),
                )
                link = replace(link, reviews=(self._review("DISCOVERED", link, bundle),))
                self._insert(connection, link)
                needed[key] -= 1
            return self._snapshot(connection, document_id, bundle)

    def read(self, document_id: str) -> OutlineLinkSnapshot:
        """Read registered associations without discovering, confirming or changing records."""
        with closing(self.project.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._snapshot(connection, document_id, self._bundle(document_id))

    def list_registered(self) -> tuple[OutlineChapterLink, ...]:
        """Read existing records only; also works on a query-only database connection."""
        with closing(self.project.database.connect()) as connection:
            return self._rows(connection)

    def confirm(
        self, document_id: str, link_ids: tuple[str, ...], *, expected_fingerprint: str
    ) -> OutlineLinkSnapshot:
        if not link_ids or len(set(link_ids)) != len(link_ids):
            raise ValueError("请选择不重复的关联")
        for link_id in link_ids:
            validate_id(link_id)
        with closing(self.project.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            bundle = self._bundle(document_id, expected_fingerprint)
            items = {
                item.link.id: item for item in self._snapshot(connection, document_id, bundle).items
            }
            if any(
                link_id not in items or items[link_id].status not in {"PENDING", "CONFIRMED"}
                for link_id in link_ids
            ):
                raise OutlineConflictError("所选关联存在无效位置或不可用章节，请先定位或确认移除")
            for link_id in link_ids:
                item = items[link_id]
                if item.status == "CONFIRMED":
                    continue
                assert item.line is not None and item.column is not None
                updated = replace(
                    item.link,
                    source_line=item.line,
                    source_column=item.column,
                    source_revision=bundle.sources[document_id].version.revision,
                    confirmed_fingerprint=bundle.fingerprint,
                )
                updated = replace(
                    updated, reviews=(*updated.reviews, self._review("CONFIRMED", updated, bundle))
                )
                self._update(connection, updated)
            return self._snapshot(connection, document_id, bundle)

    def relocate(
        self, document_id: str, link_id: str, source_line: int, *, expected_fingerprint: str
    ) -> OutlineLinkSnapshot:
        if type(source_line) is not int or source_line < 1:
            raise ValueError("请选择有效的大纲行")
        with closing(self.project.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            bundle = self._bundle(document_id, expected_fingerprint)
            links = self._rows(connection, document_id)
            link = self._find(links, link_id)
            matches = [
                m
                for m in bundle.matches[document_id]
                if m.line == source_line and m.chapter_id == link.chapter_id
            ]
            if len(matches) != 1:
                raise OutlineConflictError("当前行必须有一个指向该章节的链接；多个相同链接请先分行")
            match = matches[0]
            if any(
                other.id != link.id
                and other.active
                and other.source_line == match.line
                and other.source_column == match.column
                and other.chapter_id == link.chapter_id
                for other in links
            ):
                raise OutlineConflictError("该位置已有同一章节的关联，请检查现有记录")
            updated = replace(
                link,
                source_line=match.line,
                source_column=match.column,
                source_quote=match.quote,
                source_revision=bundle.sources[document_id].version.revision,
                confirmed_fingerprint=None,
                active=True,
                reviews=(*link.reviews, self._review("RELOCATED", link, bundle)),
            )
            self._update(connection, updated)
            return self._snapshot(connection, document_id, bundle)

    def retire(
        self, document_id: str, link_id: str, *, expected_fingerprint: str
    ) -> OutlineLinkSnapshot:
        with closing(self.project.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            bundle = self._bundle(document_id, expected_fingerprint)
            item = next(
                (
                    i
                    for i in self._snapshot(connection, document_id, bundle).items
                    if i.link.id == validate_id(link_id)
                ),
                None,
            )
            if item is None:
                raise KeyError("找不到当前文档的关联")
            if item.status == "REMOVED":
                return self._snapshot(connection, document_id, bundle)
            if item.status not in {"MISSING_SOURCE", "MISSING_CHAPTER"}:
                raise OutlineConflictError("请先从大纲移除链接，再确认移除关联")
            link = replace(
                item.link,
                active=False,
                confirmed_fingerprint=None,
                reviews=(*item.link.reviews, self._review("REMOVED", item.link, bundle)),
            )
            self._update(connection, link)
            return self._snapshot(connection, document_id, bundle)

    @staticmethod
    def _locations(
        links: tuple[OutlineChapterLink, ...], matches: tuple[MarkdownChapterLink, ...]
    ) -> dict[str, MarkdownChapterLink]:
        groups: dict[tuple[str, str], list[OutlineChapterLink]] = defaultdict(list)
        candidates: dict[tuple[str, str], list[MarkdownChapterLink]] = defaultdict(list)
        for link in links:
            if link.active:
                groups[(link.chapter_id, link.source_quote)].append(link)
        for match in matches:
            candidates[(match.chapter_id, match.quote)].append(match)
        result: dict[str, MarkdownChapterLink] = {}
        for key, records in groups.items():
            unused = list(candidates[key])
            for link in records:
                exact = next(
                    (
                        m
                        for m in unused
                        if (m.line, m.column) == (link.source_line, link.source_column)
                    ),
                    None,
                )
                if exact:
                    result[link.id] = exact
                    unused.remove(exact)
            remaining = [link for link in records if link.id not in result]
            if len(remaining) == 1 and len(unused) == 1:
                result[remaining[0].id] = unused[0]
        return result

    def _snapshot(
        self, connection: sqlite3.Connection, document_id: str, bundle: _Bundle
    ) -> OutlineLinkSnapshot:
        all_links = self._rows(connection)
        chapters = {chapter.id: chapter for chapter in bundle.chapters}
        items: list[OutlineLinkItem] = []
        for source_id, source in bundle.sources.items():
            links = tuple(link for link in all_links if link.document_id == source_id)
            locations = self._locations(links, bundle.matches[source_id])
            headings = outline_headings(source.content)
            lines = source.content.splitlines(keepends=True)
            starts: list[int] = []
            offset = 0
            for line in editor_text(source.content).splitlines(keepends=True):
                starts.append(offset)
                offset += len(line.encode("utf-16-le")) // 2
            for link in links:
                match = locations.get(link.id)
                status = (
                    "REMOVED"
                    if not link.active
                    else (
                        "MISSING_CHAPTER"
                        if link.chapter_id not in chapters
                        else "MISSING_SOURCE"
                        if match is None
                        else "CONFIRMED"
                        if link.confirmed_fingerprint == bundle.fingerprint
                        else "PENDING"
                    )
                )
                caption, position = "", None
                if match:
                    for heading in headings:
                        if int(heading["line"]) <= match.line:
                            caption = str(heading["title"])
                    prefix = lines[match.line - 1][: match.column]
                    if match.line == 1:
                        prefix = prefix.removeprefix("\ufeff")
                    position = starts[match.line - 1] + len(prefix.encode("utf-16-le")) // 2
                chapter = chapters.get(link.chapter_id)
                items.append(
                    OutlineLinkItem(
                        link,
                        status,
                        match.line if match else None,
                        match.column if match else None,
                        position,
                        caption,
                        chapter.title if chapter else link.chapter_title,
                    )
                )
        return OutlineLinkSnapshot(
            bundle.fingerprint,
            bundle.sources[document_id].version.revision,
            bundle.sources[document_id].version.content_hash,
            tuple(i for i in items if i.link.document_id == document_id),
            sum(i.status not in {"CONFIRMED", "REMOVED"} for i in items),
            bundle.chapters,
        )

    def _rows(
        self, connection: sqlite3.Connection, document_id: str | None = None
    ) -> tuple[OutlineChapterLink, ...]:
        query = (
            "SELECT l.* FROM outline_chapter_links l JOIN outline_documents d "
            "ON d.id=l.document_id WHERE d.project_id=?"
        )
        params: tuple[str, ...] = (self.project.project.id,)
        if document_id is not None:
            query += " AND l.document_id=?"
            params += (document_id,)
        query += " ORDER BY d.sort_index, l.source_line, l.source_column, l.id"
        return tuple(self._row(row) for row in connection.execute(query, params))

    @staticmethod
    def _find(links: tuple[OutlineChapterLink, ...], link_id: str) -> OutlineChapterLink:
        validate_id(link_id)
        for link in links:
            if link.id == link_id:
                return link
        raise KeyError("找不到当前文档的关联")

    @staticmethod
    def _review(action: str, link: OutlineChapterLink, bundle: _Bundle) -> OutlineLinkReview:
        return OutlineLinkReview(
            action,
            bundle.fingerprint,
            link.source_revision,
            link.source_line,
            link.source_column,
            _hash(link.source_quote),
            datetime.now(UTC),
        )

    @staticmethod
    def _history(link: OutlineChapterLink) -> str:
        return json.dumps(
            [
                asdict(review) | {"created_at": review.created_at.isoformat()}
                for review in link.reviews
            ],
            ensure_ascii=False,
        )

    def _insert(self, connection: sqlite3.Connection, link: OutlineChapterLink) -> None:
        connection.execute(
            "INSERT INTO outline_chapter_links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                link.id,
                link.document_id,
                link.chapter_id,
                link.chapter_title,
                link.source_revision,
                link.source_line,
                link.source_column,
                link.source_quote,
                link.confirmed_fingerprint,
                int(link.active),
                self._history(link),
            ),
        )

    def _update(self, connection: sqlite3.Connection, link: OutlineChapterLink) -> None:
        connection.execute(
            "UPDATE outline_chapter_links SET source_revision=?, source_line=?, source_column=?, "
            "source_quote=?, confirmed_fingerprint=?, is_active=?, reviews_json=? "
            "WHERE id=? AND document_id=?",
            (
                link.source_revision,
                link.source_line,
                link.source_column,
                link.source_quote,
                link.confirmed_fingerprint,
                int(link.active),
                self._history(link),
                link.id,
                link.document_id,
            ),
        )

    @staticmethod
    def _row(row: sqlite3.Row) -> OutlineChapterLink:
        try:
            history = json.loads(row["reviews_json"])
            if not isinstance(history, list) or row["is_active"] not in (0, 1):
                raise ValueError("invalid link record")
            reviews: list[OutlineLinkReview] = []
            keys = set(OutlineLinkReview.__dataclass_fields__)
            for entry in history:
                if not isinstance(entry, dict) or set(entry) != keys:
                    raise ValueError("invalid review record")
                for name in ("source_revision", "source_line", "source_column"):
                    if type(entry[name]) is not int:
                        raise ValueError("invalid review source")
                for name in ("action", "fingerprint", "source_hash", "created_at"):
                    if not isinstance(entry[name], str):
                        raise ValueError("invalid review text")
                reviews.append(
                    OutlineLinkReview(
                        **(entry | {"created_at": datetime.fromisoformat(entry["created_at"])})
                    )
                )
            if not reviews:
                raise ValueError("missing discovery record")
            return OutlineChapterLink(
                row["id"],
                row["document_id"],
                row["chapter_id"],
                row["chapter_title"],
                row["source_revision"],
                row["source_line"],
                row["source_column"],
                row["source_quote"],
                row["confirmed_fingerprint"],
                bool(row["is_active"]),
                tuple(reviews),
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise OutlineIntegrityError("章节关联记录损坏，已停止更新；大纲原文未改写") from exc
