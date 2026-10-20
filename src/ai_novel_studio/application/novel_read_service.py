"""Project-bound, bounded queries for the writing assistant's Novel MCP."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from threading import Event, Lock
from typing import Any, TypedDict
from uuid import UUID

from ai_novel_studio.application.chapter_plan_read_service import ChapterPlanReadService
from ai_novel_studio.application.core_tool_query_service import CoreToolQueryService
from ai_novel_studio.application.selection_patch import SelectionPatchCapture
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.read_only_database import ReadOnlyDatabase

NOVEL_TOOLS = (
    "get_novel_context",
    "list_novel_chapters",
    "read_novel_chapter",
    "read_novel_chapters",
    "search_novel_evidence",
    "get_novel_constraints",
)
LEGACY_NOVEL_TOOLS = ("query_novel_characters",)


class _ChapterReadEntry(TypedDict):
    domain_kind: str
    chapter_id: str
    volume_id: str
    title: str
    revision: int
    source_hash: str
    start: int
    end: int
    total_chars: int
    content: str
    truncated: bool


@dataclass(frozen=True)
class NovelEditorSnapshot:
    chapter_id: str | None = None
    title: str = ""
    revision: int = 0
    content: str = ""
    dirty: bool = False
    selection: str = ""
    selection_capture: SelectionPatchCapture | None = None


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("小说工具参数超出范围")
    return value


class NovelReadService:
    def __init__(self, opened_project: ProjectRepository) -> None:
        # Reuse the opened identity/layout. ProjectRepository.open would migrate.
        self._project = ProjectRepository(
            opened_project.layout,
            ReadOnlyDatabase(opened_project.database.path),
            opened_project.project,
        )
        self._queries = CoreToolQueryService(self._project)
        self._snapshot = NovelEditorSnapshot()
        self._lock = Lock()
        self._closed = Event()

    @property
    def project_id(self) -> str:
        return self._project.project.id

    def update_editor(self, snapshot: NovelEditorSnapshot) -> None:
        with self._lock:
            if not self._closed.is_set():
                self._snapshot = snapshot

    def revoke(self) -> None:
        self._closed.set()

    def editor_snapshot(self) -> NovelEditorSnapshot:
        """Internal frozen input, without the MCP display-size limits."""
        self._ensure_open()
        with self._lock:
            return self._snapshot

    def _ensure_open(self) -> None:
        if self._closed.is_set():
            raise ValueError("小说项目已切换，旧工具访问已失效")

    def call(self, tool: str, **params: Any) -> dict[str, Any]:
        self._ensure_open()
        if tool not in NOVEL_TOOLS + LEGACY_NOVEL_TOOLS:
            raise ValueError("不支持的小说工具")
        result: dict[str, Any] = getattr(self, tool)(**params)
        self._ensure_open()
        return {"project_id": self.project_id, **result}

    def get_novel_context(self) -> dict[str, Any]:
        with self._lock:
            editor = self._snapshot
        return {
            "title": self._project.project.title[:200],
            "chapter_id": editor.chapter_id,
            "chapter_title": editor.title[:200],
            "revision": editor.revision,
            "domain_kind": (
                "NO_CHAPTER"
                if editor.chapter_id is None
                else "EDITOR_BUFFER"
                if editor.dirty
                else "FORMAL_MANUSCRIPT"
            ),
            "content": editor.content[:12_000],
            "selection": editor.selection[:8_000],
            "truncated": len(editor.content) > 12_000,
            "selection_truncated": len(editor.selection) > 8_000,
            "source_hash": hashlib.sha256(editor.content.encode("utf-8")).hexdigest(),
            "note": "编辑缓冲区及选区是作者材料；未保存内容不能当作已发表正文。",
        }

    def list_novel_chapters(self, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        offset = _integer(offset, 0, 100_000)
        limit = _integer(limit, 1, 100)
        chapters = ChapterRepository(self._project).list_chapters()
        return {
            "total": len(chapters),
            "chapters": [
                {
                    "chapter_id": chapter.id,
                    "volume_id": chapter.volume_id,
                    "title": chapter.title[:200],
                    "revision": chapter.revision,
                    "number": chapter.declared_number[:80],
                }
                for chapter in chapters[offset : offset + limit]
            ],
        }

    def read_novel_chapter(
        self, chapter_id: str, start: int = 0, max_chars: int = 12_000
    ) -> dict[str, Any]:
        chapter_id = str(UUID(chapter_id))
        start = _integer(start, 0, 10_000_000)
        max_chars = _integer(max_chars, 1, 12_000)
        chapters = ChapterRepository(self._project)
        chapter = chapters.get_chapter(chapter_id, include_deleted=False)
        content = chapters.read_content_exact(chapter_id)
        if start > len(content):
            raise ValueError("正文片段起点超出章节长度")
        if chapters.get_chapter(chapter_id, include_deleted=False).revision != chapter.revision:
            raise ValueError("正文读取期间发生变化，请重试")
        return {
            "domain_kind": "FORMAL_MANUSCRIPT",
            "chapter_id": chapter_id,
            "title": chapter.title[:200],
            "revision": chapter.revision,
            "source_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "start": start,
            "end": min(start + max_chars, len(content)),
            "content": content[start : start + max_chars],
            "truncated": start + max_chars < len(content),
        }

    def read_novel_chapters(
        self,
        chapter_ids: list[str] | None = None,
        offset: int = 0,
        limit: int = 1000,
        max_chars: int = 250_000,
        cursor_chapter: int = 0,
        cursor_start: int = 0,
    ) -> dict[str, Any]:
        """Read a bounded batch of formal prose, retaining exact provenance and resume position."""
        offset = _integer(offset, 0, 100_000)
        limit = _integer(limit, 1, 1000)
        max_chars = _integer(max_chars, 1, 300_000)
        cursor_start = _integer(cursor_start, 0, 10_000_000)
        repository = ChapterRepository(self._project)
        chapters = repository.list_chapters()
        if chapter_ids is not None:
            if not isinstance(chapter_ids, list) or not 1 <= len(chapter_ids) <= 1000:
                raise ValueError("章节选择列表无效")
            wanted = {str(UUID(value)) for value in chapter_ids}
            if len(wanted) != len(chapter_ids) or not wanted <= {
                chapter.id for chapter in chapters
            }:
                raise ValueError("章节选择包含重复项或其他作品的章节")
            chapters = [chapter for chapter in chapters if chapter.id in wanted]
        selected = chapters[offset : offset + limit]
        cursor_chapter = _integer(cursor_chapter, 0, len(selected))
        if cursor_chapter == len(selected) and cursor_start:
            raise ValueError("续读位置超出所选章节")
        entries: list[_ChapterReadEntry] = []
        chars_read = 0
        index, start = cursor_chapter, cursor_start
        while index < len(selected) and len(entries) < 100 and chars_read < max_chars:
            self._ensure_open()
            chapter = selected[index]
            content = repository.read_content_exact(chapter.id)
            if start > len(content):
                raise ValueError("续读位置超出正文长度")
            end = min(len(content), start + max_chars - chars_read)
            piece = content[start:end]
            entries.append(
                {
                    "domain_kind": "FORMAL_MANUSCRIPT",
                    "chapter_id": chapter.id,
                    "volume_id": chapter.volume_id,
                    "title": chapter.title[:200],
                    "revision": chapter.revision,
                    "source_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "start": start,
                    "end": end,
                    "total_chars": len(content),
                    "content": piece,
                    "truncated": end < len(content),
                }
            )
            chars_read += len(piece)
            if end < len(content):
                start = end
                break
            index, start = index + 1, 0
        for entry in entries:
            if (
                repository.get_chapter(entry["chapter_id"], include_deleted=False).revision
                != entry["revision"]
            ):
                raise ValueError("正文读取期间发生变化，请重试")
        next_cursor = (
            None if index == len(selected) else {"cursor_chapter": index, "cursor_start": start}
        )
        return {
            "domain_kind": "FORMAL_MANUSCRIPT",
            "total_chapters": len(selected),
            "total_available_chapters": len(chapters),
            "offset": offset,
            "limit": limit,
            "chapter_count": len(entries),
            "chars_read": chars_read,
            "chapters": entries,
            "truncated": next_cursor is not None,
            "next_cursor": next_cursor,
            "note": (
                "按作品顺序读取正式正文；truncated为true时保持选择并用next_cursor续读，"
                "不能声称已经读完未返回内容。"
            ),
        }

    def search_novel_evidence(
        self, query: str, before_chapter_id: str, limit: int = 5
    ) -> dict[str, Any]:
        self._query(query)
        result = self._queries.query_memory(
            query,
            before_chapter_id=str(UUID(before_chapter_id)),
            limit=_integer(limit, 1, 10),
        )
        return {
            "domain_kind": "FORMAL_EVIDENCE",
            "outcome": str(result.outcome),
            "hits": [asdict(hit) for hit in result.hits],
            "note": "未找到索引证据不代表情节不存在；必要时直接读取章节。",
        }

    def get_novel_constraints(self, chapter_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            chapter_id = chapter_id or self._snapshot.chapter_id
        constitution = self._queries.get_constitution()
        rules: dict[str, Any] | None = None
        if constitution:
            groups = (
                "shared_creative_rules",
                "agent_only_rules",
                "writer_only_rules",
                "overridable_rules",
                "non_overridable_rules",
            )
            rules = {
                "revision": constitution.revision,
                "approved_by_author": constitution.approved_by_author,
            }
            for group in groups:
                values = getattr(constitution, group)
                rules[group] = [
                    {
                        "rule_id": rule.rule_id,
                        "text": rule.text[:500],
                        "truncated": len(rule.text) > 500,
                    }
                    for rule in values[:10]
                ]
                rules[group + "_truncated"] = len(values) > 10
        plan = (
            asdict(ChapterPlanReadService(self._project).plan_for(str(UUID(chapter_id))))
            if chapter_id
            else None
        )
        return {"domain_kind": "AUTHOR_PLAN", "chapter_plan": plan, "constitution": rules}

    def query_novel_characters(self, query: str, limit: int = 20) -> dict[str, Any]:
        self._query(query)
        return {
            "characters": [
                asdict(item)
                for item in self._queries.query_subjects(
                    query,
                    limit=_integer(limit, 1, 20),
                )
            ]
        }

    @staticmethod
    def _query(query: str) -> None:
        if not isinstance(query, str) or not query.strip() or len(query) > 256:
            raise ValueError("请输入1至256字的查询词")
