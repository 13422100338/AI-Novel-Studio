from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import cast

from ai_novel_studio.application.agent_tools import (
    AgentTool,
    AgentToolRegistry,
    AgentToolRequest,
    AgentToolValidationError,
)
from ai_novel_studio.domain.agent import AgentSourceRef, AgentToolName, AgentToolResult
from ai_novel_studio.domain.memory import Character, KnowledgeSubject, StyleScope
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


class ListChaptersTool:
    name = AgentToolName.LIST_CHAPTERS
    required_arguments: tuple[str, ...] = ()

    def __init__(self, chapters: ChapterRepository) -> None:
        self._chapters = chapters

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        limit = _int_arg(request.arguments.get("limit"), 50, maximum=100)
        offset = _int_arg(
            request.arguments.get("offset"),
            0,
            minimum=0,
            maximum=10_000,
        )
        all_chapters = self._chapters.list_chapters()
        selected = all_chapters[offset : offset + limit]
        lines = [
            f"项目章节目录（offset={offset}, returned={len(selected)}, "
            f"total={len(all_chapters)}）："
        ]
        refs: list[AgentSourceRef] = []
        for chapter in selected:
            content = self._chapters.read_content_exact(chapter.id)
            preview = "".join(content.split())[:32] or "（空章）"
            lines.append(
                f"- chapter_id={chapter.id} | {chapter.declared_number or '未编号'} "
                f"| {chapter.title} | revision={chapter.revision} "
                f"| chars={len(content)} | preview={preview}"
            )
            refs.append(
                AgentSourceRef(
                    "chapter",
                    chapter.id,
                    chapter.revision,
                    _hash(content),
                )
            )
        omitted: tuple[str, ...] = ()
        if offset + len(selected) < len(all_chapters):
            omitted = (
                f"more chapters available from offset {offset + len(selected)}",
            )
        return _result(self.name, "\n".join(lines), refs, omitted)


class ReadChapterExcerptTool:
    name = AgentToolName.READ_CHAPTER_EXCERPT
    required_arguments = ("chapter_id",)

    def __init__(self, chapters: ChapterRepository) -> None:
        self._chapters = chapters

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        chapter_id = str(request.arguments["chapter_id"])
        max_chars = _int_arg(
            request.arguments.get("max_chars"),
            request.max_result_chars,
            maximum=request.max_result_chars,
        )
        chapter = self._chapters.get_chapter(chapter_id, include_deleted=False)
        content = self._chapters.read_content_exact(chapter_id)
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


class ReadChaptersBatchTool:
    name = AgentToolName.READ_CHAPTERS_BATCH
    required_arguments = ("chapter_ids",)
    _MAX_CHAPTERS_PER_CALL = 100

    def __init__(self, chapters: ChapterRepository) -> None:
        self._chapters = chapters

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        raw_ids = request.arguments["chapter_ids"]
        if not isinstance(raw_ids, list) or not raw_ids:
            raise AgentToolValidationError("chapter_ids must be a non-empty list")
        if len(raw_ids) > self._MAX_CHAPTERS_PER_CALL:
            raise AgentToolValidationError(
                f"chapter_ids accepts at most {self._MAX_CHAPTERS_PER_CALL} chapters"
            )
        chapter_ids = tuple(str(value).strip() for value in raw_ids)
        if any(not value for value in chapter_ids):
            raise AgentToolValidationError("chapter_ids contains an invalid chapter id")
        if len(set(chapter_ids)) != len(chapter_ids):
            raise AgentToolValidationError("chapter_ids must be unique")
        requested_per_chapter = _int_arg(
            request.arguments.get("max_chars_per_chapter"),
            600,
            maximum=request.max_result_chars,
        )
        section_budget = max(1, request.max_result_chars // len(chapter_ids))
        sections: list[str] = []
        refs: list[AgentSourceRef] = []
        omitted: list[str] = []
        for index, chapter_id in enumerate(chapter_ids, start=1):
            try:
                chapter = self._chapters.get_chapter(chapter_id, include_deleted=False)
                content = self._chapters.read_content_exact(chapter_id)
            except (KeyError, RuntimeError):
                # RC-4: a bad ID must become an omission, not kill the batch.
                omitted.append(f"chapter {chapter_id} not found or unavailable")
                continue
            header = (
                f"[{index}] {chapter.declared_number or '未编号'} {chapter.title} "
                f"| chapter_id={chapter.id}"
            )
            excerpt_budget = max(0, section_budget - len(header) - 1)
            excerpt = content[: min(requested_per_chapter, excerpt_budget)]
            sections.append(header + ("\n" + excerpt if excerpt else ""))
            refs.append(
                AgentSourceRef(
                    "chapter",
                    chapter.id,
                    chapter.revision,
                    _hash(content),
                )
            )
            if len(excerpt) < len(content):
                omitted.append(f"chapter {chapter.id} excerpt truncated")
        return _result(self.name, "\n\n".join(sections), refs, omitted)


class ReadNovelOverviewTool:
    """High-level tool for novel-wide reads without manual chapter_id assembly.

    Defaults cover 34+ chapters in one call; pagination metadata is always
    returned so the model can continue reading if needed.
    """

    name = AgentToolName.READ_NOVEL_OVERVIEW
    required_arguments: tuple[str, ...] = ()
    _MAX_CHAPTERS_PER_CALL = 100

    def __init__(self, chapters: ChapterRepository) -> None:
        self._chapters = chapters

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        offset = _int_arg(
            request.arguments.get("offset"), 0, minimum=0, maximum=10_000
        )
        chapter_count = _int_arg(
            request.arguments.get("chapter_count"),
            50,
            minimum=1,
            maximum=self._MAX_CHAPTERS_PER_CALL,
        )
        total_char_budget = _int_arg(
            request.arguments.get("total_char_budget"),
            min(16_000, request.max_result_chars),
            minimum=200,
            maximum=request.max_result_chars,
        )

        all_chapters = self._chapters.list_chapters()
        total_chapters = len(all_chapters)
        selected = all_chapters[offset : offset + chapter_count]

        # Pre-compute headers to know exactly how many chapters fit in budget.
        per_chapter_budget = max(1, total_char_budget // max(len(selected), 1))
        rendered: list[tuple[int, str, AgentSourceRef]] = []
        omitted: list[str] = []
        used_chars = 0
        for index, chapter in enumerate(selected):
            seq = offset + index + 1
            header = (
                f"[seq={seq}] "
                f"{chapter.declared_number or '未编号'} {chapter.title}"
            )
            try:
                content = self._chapters.read_content_exact(chapter.id)
            except (KeyError, RuntimeError):
                omitted.append(f"chapter seq={seq} unavailable")
                continue
            available = per_chapter_budget - len(header) - 1
            if available <= 0:
                omitted.append(f"chapter seq={seq} skipped (budget exhausted)")
                continue
            excerpt = content[:available]
            truncated = len(excerpt) < len(content)
            body = header + ("\n" + excerpt if excerpt else "（空）")
            if used_chars + len(body) > total_char_budget:
                omitted.append(f"chapter seq={seq} skipped (total budget exhausted)")
                continue
            used_chars += len(body)
            ref = AgentSourceRef(
                "chapter", chapter.id, chapter.revision, _hash(content),
            )
            rendered.append((index, body, ref))
            if truncated:
                omitted.append(f"chapter seq={seq} content truncated")

        next_offset = (
            offset + len(selected)
            if offset + len(selected) < total_chapters
            else None
        )
        # Only emit refs for chapters whose content is actually visible.
        refs = tuple(ref for _, _, ref in rendered)

        summary = (
            f"全书概览：total_chapters={total_chapters}, "
            f"returned_chapters={len(rendered)}, "
            f"next_offset={next_offset if next_offset is not None else '无'}, "
            f"char_budget={total_char_budget}"
        )
        parts = [summary]
        parts.extend(body for _, body, _ in rendered)
        parts.extend(f"[omitted] {o}" for o in omitted)
        return _result(self.name, "\n\n".join(parts), refs, tuple(omitted))


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
    required_arguments = ()

    def __init__(self, characters: CharacterMemoryRepository) -> None:
        self._characters = characters

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        before = str(request.arguments.get("before_chapter_id") or request.chapter_id or "")
        if not before:
            return _result(self.name, "未提供章节边界，无法判断当前人物状态。")
        character_id, error = _resolve_character_reference(
            self._characters, request.arguments
        )
        if error:
            return _result(self.name, error)
        event = self._characters.state_before(
            character_id,
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
    required_arguments = ()

    def __init__(self, characters: CharacterMemoryRepository) -> None:
        self._characters = characters

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        before = str(request.arguments.get("before_chapter_id") or request.chapter_id or "")
        if not before:
            return _result(self.name, "未提供章节边界，无法判断人物知识。")
        character_id, error = _resolve_character_reference(
            self._characters, request.arguments
        )
        if error:
            return _result(self.name, error)
        rows = self._characters.knowledge_before(
            KnowledgeSubject.CHARACTER,
            character_id,
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


def _resolve_character_reference(
    repository: CharacterMemoryRepository,
    arguments: dict[str, object],
) -> tuple[str, str]:
    character_id = str(arguments.get("character_id") or "").strip()
    if character_id:
        try:
            return repository.get_character(character_id).id, ""
        except KeyError:
            return "", f"未找到人物 ID：{character_id}。请改用 character_name 查询。"

    character_name = str(arguments.get("character_name") or "").strip()
    if not character_name:
        return "", "请提供 character_name（人物正式名或别名）。"
    matches = tuple(
        character
        for character in repository.list_characters()
        if character_name in {character.canonical_name, *character.aliases}
    )
    if not matches:
        return "", f"未找到人物：{character_name}。"
    if len(matches) > 1:
        candidates = "；".join(
            f"{character.canonical_name}（character_id={character.id}）"
            for character in matches
        )
        return "", f"人物名称存在歧义，请使用 character_id 指定：{candidates}"
    return matches[0].id, ""


class ProposeCharacterIdentityMergeTool:
    name = AgentToolName.PROPOSE_CHARACTER_IDENTITY_MERGE
    required_arguments = (
        "source_character_name",
        "target_character_name",
        "reason",
    )

    def __init__(self, characters: CharacterMemoryRepository) -> None:
        self._characters = characters

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        source_name = self._required_text(request, "source_character_name")
        target_name = self._required_text(request, "target_character_name")
        reason = self._required_text(request, "reason")
        source_id, source_error = _resolve_character_reference(
            self._characters, {"character_name": source_name}
        )
        target_id, target_error = _resolve_character_reference(
            self._characters, {"character_name": target_name}
        )
        if source_error or target_error:
            raise AgentToolValidationError(source_error or target_error)
        if source_id == target_id:
            raise AgentToolValidationError("不能提议把同一张人物卡归并到自身")
        source = self._characters.get_character(source_id)
        target = self._characters.get_character(target_id)
        content = (
            "人物身份归并提案已验证，但尚未修改记忆库。\n"
            f"来源卡：{source.canonical_name}（character_id={source.id}）\n"
            f"建议主卡：{target.canonical_name}（character_id={target.id}）\n"
            f"理由：{reason}\n"
            "状态：需要用户确认"
        )
        return _result(
            self.name,
            content,
            (self._character_ref(source), self._character_ref(target)),
        )

    @staticmethod
    def _required_text(request: AgentToolRequest, field: str) -> str:
        value = request.arguments.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AgentToolValidationError(f"{field} 必须是非空文本")
        return value.strip()

    @staticmethod
    def _character_ref(character: Character) -> AgentSourceRef:
        content = "\n".join(
            (character.canonical_name, *character.aliases, character.profile)
        )
        return AgentSourceRef(
            "character_identity_card", character.id, 0, _hash(content)
        )


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
            ListChaptersTool(ChapterRepository(project)),
            ReadChapterExcerptTool(ChapterRepository(project)),
            ReadChaptersBatchTool(ChapterRepository(project)),
            ReadNovelOverviewTool(ChapterRepository(project)),
            SearchMemoryTool(SearchRepository(project)),
            GetCharacterStateTool(CharacterMemoryRepository(project)),
            GetCharacterKnowledgeTool(CharacterMemoryRepository(project)),
            GetActiveCluesTool(NarrativeMemoryRepository(project)),
            GetCanonFactsTool(NarrativeMemoryRepository(project)),
            GetStyleGuideTool(StyleRepository(project)),
            GetAuditFindingsTool(project),
            ProposeCharacterIdentityMergeTool(CharacterMemoryRepository(project)),
        ),
    )
    return AgentToolRegistry(
        tools
    )
