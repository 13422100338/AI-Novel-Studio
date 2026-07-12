from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import cast

from ai_novel_studio.application.agent_tools import (
    AgentTool,
    AgentToolRegistry,
    AgentToolRequest,
)
from ai_novel_studio.domain.agent import AgentSourceRef, AgentToolName, AgentToolResult
from ai_novel_studio.domain.memory import KnowledgeSubject, StyleScope
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _result(
    tool_name: AgentToolName,
    content: str,
    source_refs: Iterable[AgentSourceRef] = (),
    omitted: Iterable[str] = (),
) -> AgentToolResult:
    normalized = content.strip() or "未找到可用记录。"
    return AgentToolResult(
        tool_name,
        normalized,
        tuple(source_refs),
        tuple(omitted),
        _hash(normalized),
    )


def _int_arg(value: object, default: int, *, minimum: int = 1, maximum: int = 20) -> int:
    if value is None:
        parsed = default
    else:
        try:
            parsed = int(str(value))
        except ValueError:
            parsed = default
    return int(max(minimum, min(maximum, parsed)))


class ReadChapterExcerptTool:
    name = AgentToolName.READ_CHAPTER_EXCERPT
    required_arguments = ("chapter_id",)

    def __init__(self, chapters: ChapterRepository) -> None:
        self._chapters = chapters

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        chapter_id = str(request.arguments["chapter_id"])
        max_chars = _int_arg(request.arguments.get("max_chars"), request.max_result_chars)
        chapter = self._chapters.get_chapter(chapter_id, include_deleted=False)
        content = self._chapters.read_content(chapter_id)
        excerpt = content[:max_chars]
        omitted: tuple[str, ...] = ()
        if len(content) > len(excerpt):
            omitted = (f"chapter excerpt truncated to {len(excerpt)} characters",)
        return _result(
            self.name,
            excerpt,
            (AgentSourceRef("chapter", chapter.id, chapter.revision, _hash(content)),),
            omitted,
        )


class SearchMemoryTool:
    name = AgentToolName.SEARCH_MEMORY
    required_arguments = ("query",)

    def __init__(self, search: SearchRepository) -> None:
        self._search = search

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        before = str(request.arguments.get("before_chapter_id") or request.chapter_id or "")
        if not before:
            return _result(self.name, "未提供章节边界，未执行记忆检索。")
        rows = self._search.search_rows(
            str(request.arguments["query"]),
            before,
            limit=_int_arg(request.arguments.get("limit"), 5),
        )
        if not rows:
            return self._fallback_like_search(request)
        lines = [
            f"- {row.document.title}: {row.excerpt or row.document.content[:120]}"
            for row in rows
        ]
        refs = (
            AgentSourceRef(
                row.document.document_type.lower(),
                row.document.source_id,
                row.document.source_revision,
                row.document.source_hash or _hash(row.document.content),
            )
            for row in rows
        )
        return _result(self.name, "\n".join(lines), refs)

    def _fallback_like_search(self, request: AgentToolRequest) -> AgentToolResult:
        query = str(request.arguments["query"]).strip()
        limit = _int_arg(request.arguments.get("limit"), 5)
        with self._search.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memory_documents
                WHERE review_status IN ('APPROVED', 'LOCKED')
                  AND status = 'CURRENT'
                  AND (title LIKE ? OR content LIKE ? OR participants LIKE ?)
                ORDER BY pinned_weight DESC, updated_at DESC, id
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", f"%{query}%", limit),
            ).fetchall()
        lines = [f"- {row['title']}: {row['content'][:120]}" for row in rows]
        refs = (
            AgentSourceRef(
                row["document_type"].lower(),
                row["source_id"],
                int(row["source_revision"]),
                row["source_hash"] or _hash(row["content"]),
            )
            for row in rows
        )
        return _result(self.name, "\n".join(lines), refs)


class GetCharacterStateTool:
    name = AgentToolName.GET_CHARACTER_STATE
    required_arguments = ("character_id",)

    def __init__(self, characters: CharacterMemoryRepository) -> None:
        self._characters = characters

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        before = str(request.arguments.get("before_chapter_id") or request.chapter_id or "")
        if not before:
            return _result(self.name, "未提供章节边界，无法判断当前人物状态。")
        event = self._characters.state_before(
            str(request.arguments["character_id"]),
            before,
            inclusive=False,
        )
        if event is None:
            return _result(self.name, "未找到人物状态。")
        content = (
            f"动机：{event.motivation}\n心理：{event.psychology}\n"
            f"目标：{event.current_goal}\n关系：{event.relationships}\n"
            f"近期活动：{event.recent_activity}"
        )
        return _result(
            self.name,
            content,
            (AgentSourceRef("character_state", event.id, 0, _hash(content)),),
        )


class GetCharacterKnowledgeTool:
    name = AgentToolName.GET_CHARACTER_KNOWLEDGE
    required_arguments = ("character_id",)

    def __init__(self, characters: CharacterMemoryRepository) -> None:
        self._characters = characters

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        before = str(request.arguments.get("before_chapter_id") or request.chapter_id or "")
        if not before:
            return _result(self.name, "未提供章节边界，无法判断人物知识。")
        rows = self._characters.knowledge_before(
            KnowledgeSubject.CHARACTER,
            str(request.arguments["character_id"]),
            before,
            inclusive=False,
        )
        lines = [
            f"- {entry.item.title}: {entry.event.state.value}；{entry.item.detail}"
            for entry in rows
        ]
        refs = (
            AgentSourceRef("knowledge", entry.item.id, 0, _hash(entry.item.detail))
            for entry in rows
        )
        return _result(self.name, "\n".join(lines), refs)


class GetActiveCluesTool:
    name = AgentToolName.GET_ACTIVE_CLUES
    required_arguments = ()

    def __init__(self, narrative: NarrativeMemoryRepository) -> None:
        self._narrative = narrative

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        before = str(request.arguments.get("before_chapter_id") or request.chapter_id or "")
        if not before:
            return _result(self.name, "未提供章节边界，无法检索伏笔。")
        limit = _int_arg(request.arguments.get("limit"), 5)
        timelines = self._narrative.clue_timelines_before(before)[:limit]
        lines = []
        refs = []
        for timeline in timelines:
            events = "；".join(f"{event.action.value}:{event.detail}" for event in timeline.events)
            text = f"- {timeline.clue.title}: {timeline.clue.detail}"
            if events:
                text += f"（事件：{events}）"
            lines.append(text)
            refs.append(AgentSourceRef("clue", timeline.clue.id, 0, _hash(timeline.clue.detail)))
        return _result(self.name, "\n".join(lines), refs)


class GetCanonFactsTool:
    name = AgentToolName.GET_CANON_FACTS
    required_arguments = ()

    def __init__(self, narrative: NarrativeMemoryRepository) -> None:
        self._narrative = narrative

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        query = str(request.arguments.get("query") or "").strip()
        limit = _int_arg(request.arguments.get("limit"), 5)
        with self._narrative.project.database.connect() as connection:
            if query:
                rows = connection.execute(
                    """
                    SELECT * FROM canon_entries
                    WHERE status = 'CURRENT' AND review_status IN ('APPROVED', 'LOCKED')
                      AND (title LIKE ? OR detail LIKE ?)
                    ORDER BY created_at, id
                    LIMIT ?
                    """,
                    (f"%{query}%", f"%{query}%", limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM canon_entries
                    WHERE status = 'CURRENT' AND review_status IN ('APPROVED', 'LOCKED')
                    ORDER BY created_at, id
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        lines = [f"- {row['title']}: {row['detail']}" for row in rows]
        refs = (
            AgentSourceRef("canon", row["id"], 0, _hash(row["detail"]))
            for row in rows
        )
        return _result(self.name, "\n".join(lines), refs)


class GetStyleGuideTool:
    name = AgentToolName.GET_STYLE_GUIDE
    required_arguments = ("scope_type", "scope_id")

    def __init__(self, styles: StyleRepository) -> None:
        self._styles = styles

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        scope = StyleScope(str(request.arguments["scope_type"]))
        scope_id = str(request.arguments["scope_id"])
        limit = _int_arg(request.arguments.get("limit"), 5)
        rules = self._styles.rules(scope, scope_id)[:limit]
        samples = self._styles.samples(scope, scope_id)[: max(0, limit - len(rules))]
        lines = [f"- 规则/{rule.rule_type}: {rule.rule_text}" for rule in rules]
        lines.extend(f"- 样章/{sample.title}: {sample.content[:120]}" for sample in samples)
        refs = [
            AgentSourceRef("style_rule", rule.id, 0, _hash(rule.rule_text))
            for rule in rules
        ]
        refs.extend(
            AgentSourceRef("style_sample", sample.id, 0, sample.content_hash)
            for sample in samples
        )
        return _result(self.name, "\n".join(lines), refs)


class GetAuditFindingsTool:
    name = AgentToolName.GET_AUDIT_FINDINGS
    required_arguments = ("chapter_id",)

    def __init__(self, project: ProjectRepository) -> None:
        self._project = project

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        chapter_id = str(request.arguments["chapter_id"])
        severity = str(request.arguments.get("severity") or "").strip()
        limit = _int_arg(request.arguments.get("limit"), 5)
        query = """
            SELECT f.* FROM audit_findings f
            JOIN audit_runs r ON r.id = f.run_id
            WHERE r.chapter_id = ?
        """
        params: list[object] = [chapter_id]
        if severity:
            query += " AND f.severity = ?"
            params.append(severity)
        query += " ORDER BY f.created_at DESC, f.id DESC LIMIT ?"
        params.append(limit)
        with self._project.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        lines = [f"- {row['severity']}/{row['category']}: {row['explanation']}" for row in rows]
        refs = (
            AgentSourceRef("audit_finding", row["id"], 0, _hash(row["explanation"]))
            for row in rows
        )
        return _result(self.name, "\n".join(lines), refs)


def build_project_agent_registry(project: ProjectRepository) -> AgentToolRegistry:
    tools = cast(
        tuple[AgentTool, ...],
        (
            ReadChapterExcerptTool(ChapterRepository(project)),
            SearchMemoryTool(SearchRepository(project)),
            GetCharacterStateTool(CharacterMemoryRepository(project)),
            GetCharacterKnowledgeTool(CharacterMemoryRepository(project)),
            GetActiveCluesTool(NarrativeMemoryRepository(project)),
            GetCanonFactsTool(NarrativeMemoryRepository(project)),
            GetStyleGuideTool(StyleRepository(project)),
            GetAuditFindingsTool(project),
        ),
    )
    return AgentToolRegistry(
        tools
    )
