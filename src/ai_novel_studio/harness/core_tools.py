from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ai_novel_studio.application.compile_context_service import (
    CompileContextRequest,
    CompileContextService,
    CompiledContext,
    EvidenceNeed,
    EvidenceNeedKind,
)
from ai_novel_studio.application.core_tool_query_service import (
    CoreToolQueryService,
)
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.harness.artifacts import ArtifactStore, ProjectArtifactBackend
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.tool_registry import (
    ToolDefinition,
    ToolRegistry,
    ToolRiskLevel,
    ToolScope,
    WriteEffect,
)

TOOL_CONTEXT_COMPILE = "context.compile"
TOOL_MANUSCRIPT_READ = "manuscript.read"
TOOL_MANUSCRIPT_GET_SELECTION = "manuscript.get_selection"
TOOL_SUBJECT_QUERY = "subject.query"
TOOL_PLAN_QUERY = "plan.query"
TOOL_MEMORY_QUERY = "memory.query"
TOOL_PROJECT_CONSTITUTION_READ = "project_constitution.read"
TOOL_ARTIFACT_READ = "artifact.read"
TOOL_TOOL_SEARCH = "tool.search"

_DEFAULT_MAX_CHARS = 4_000
_MAX_MAX_CHARS = 20_000

_ARTIFACT_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _schema(
    properties: dict[str, object], required: tuple[str, ...]
) -> dict[str, object]:
    result: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }
    return result


def _string() -> dict[str, object]:
    return {"type": "string", "minLength": 1}


def _output_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "tool_id": {"type": "string"},
            "content": {"type": "string"},
        },
    }


CORE_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        TOOL_CONTEXT_COMPILE,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.READ_ONLY,
        WriteEffect.NONE,
        False,
        _schema(
            {
                "chapter_id": _string(),
                "requirement": _string(),
                "recent_chapter_texts": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "participant_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "pov_character_id": _string(),
                "evidence_requests": {"type": "array", "items": {"type": "object"}},
            },
            ("chapter_id",),
        ),
        _output_schema(),
    ),
    ToolDefinition(
        TOOL_MANUSCRIPT_READ,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.READ_ONLY,
        WriteEffect.NONE,
        False,
        _schema(
            {"chapter_id": _string(), "max_chars": {"type": "integer", "minimum": 1}},
            ("chapter_id",),
        ),
        _output_schema(),
    ),
    ToolDefinition(
        TOOL_MANUSCRIPT_GET_SELECTION,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.READ_ONLY,
        WriteEffect.NONE,
        False,
        _schema(
            {
                "chapter_id": _string(),
                "start_offset": {"type": "integer", "minimum": 0},
                "end_offset": {"type": "integer", "minimum": 0},
            },
            (),
        ),
        _output_schema(),
    ),
    ToolDefinition(
        TOOL_SUBJECT_QUERY,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.READ_ONLY,
        WriteEffect.NONE,
        False,
        _schema(
            {
                "query": _string(),
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            ("query",),
        ),
        _output_schema(),
    ),
    ToolDefinition(
        TOOL_PLAN_QUERY,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.READ_ONLY,
        WriteEffect.NONE,
        False,
        _schema({"chapter_id": _string()}, ("chapter_id",)),
        _output_schema(),
    ),
    ToolDefinition(
        TOOL_MEMORY_QUERY,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.READ_ONLY,
        WriteEffect.NONE,
        False,
        _schema(
            {
                "query": _string(),
                "before_chapter_id": _string(),
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            ("query",),
        ),
        _output_schema(),
    ),
    ToolDefinition(
        TOOL_PROJECT_CONSTITUTION_READ,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.READ_ONLY,
        WriteEffect.NONE,
        False,
        _schema({}, ()),
        _output_schema(),
    ),
    ToolDefinition(
        TOOL_ARTIFACT_READ,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.READ_ONLY,
        WriteEffect.NONE,
        False,
        _schema(
            {"artifact_id": _string(), "max_chars": {"type": "integer", "minimum": 1}},
            ("artifact_id",),
        ),
        _output_schema(),
    ),
    ToolDefinition(
        TOOL_TOOL_SEARCH,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.READ_ONLY,
        WriteEffect.NONE,
        False,
        _schema({"query": _string()}, ("query",)),
        _output_schema(),
    ),
)


def register_core_tools(registry: ToolRegistry) -> None:
    for definition in CORE_TOOL_DEFINITIONS:
        registry.register(definition)


@dataclass(frozen=True, slots=True)
class CoreToolResult:
    """Rendered result of one core tool call (design v0.3 §29)."""

    tool_id: str
    content: str

    def __post_init__(self) -> None:
        if not self.tool_id.strip():
            raise ValueError("core tool id cannot be empty")
        if not self.content.strip():
            raise ValueError("core tool content cannot be empty")


def _required_text(arguments: dict[str, object], field: str) -> str:
    value = arguments.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空文本")
    return value.strip()


def _optional_text(arguments: dict[str, object], field: str) -> str | None:
    value = arguments.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是文本")
    return value.strip() or None


def _required_id(arguments: dict[str, object], field: str) -> str:
    try:
        return validate_id(_required_text(arguments, field))
    except ValueError:
        raise ValueError(f"{field} 不是合法的 ID") from None


def _optional_id(arguments: dict[str, object], field: str) -> str | None:
    value = _optional_text(arguments, field)
    if value is None:
        return None
    try:
        return validate_id(value)
    except ValueError:
        raise ValueError(f"{field} 不是合法的 ID") from None


def _int_arg(
    arguments: dict[str, object],
    field: str,
    default: int,
    *,
    maximum: int,
    minimum: int = 1,
) -> int:
    value = arguments.get(field)
    if value is None:
        return max(minimum, min(maximum, default))
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} 必须是整数")
    return max(minimum, min(maximum, value))


def _string_list(arguments: dict[str, object], field: str) -> tuple[str, ...]:
    value = arguments.get(field)
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} 必须是字符串数组")
    return tuple(value)


class CoreToolService:
    """The 9 resident core tools as thin facades over backend services
    (design v0.3 §30, ticket B9).

    Every tool is deterministic and read-only; direct query tools serve
    answering and diagnosis only - formal generation context enters through
    context.compile alone (§22). Run facts (active chapter) come from the
    event store, never from model arguments.
    """

    def __init__(
        self,
        store: HarnessEventStore,
        compile_service: CompileContextService,
        budget: TokenBudget,
        queries: CoreToolQueryService,
        artifacts: ArtifactStore,
        registry: ToolRegistry,
    ) -> None:
        self._store = store
        self._compile = compile_service
        self._budget = budget
        self._queries = queries
        self._artifacts = artifacts
        self._registry = registry

    @classmethod
    def for_project(
        cls,
        project: Any,
        *,
        budget: TokenBudget,
        registry: ToolRegistry,
        artifacts: ArtifactStore | None = None,
    ) -> CoreToolService:
        return cls(
            HarnessEventStore(HarnessEventRepository(project)),
            CompileContextService.for_project(project),
            budget,
            CoreToolQueryService(project),
            artifacts or ArtifactStore(ProjectArtifactBackend(project)),
            registry,
        )

    def execute(
        self, tool_id: str, arguments: dict[str, object], *, run_id: str
    ) -> CoreToolResult:
        if tool_id == TOOL_CONTEXT_COMPILE:
            return self._compile_context(arguments, run_id)
        if tool_id == TOOL_MANUSCRIPT_READ:
            return self._manuscript_read(arguments)
        if tool_id == TOOL_MANUSCRIPT_GET_SELECTION:
            return self._manuscript_selection(arguments, run_id)
        if tool_id == TOOL_SUBJECT_QUERY:
            return self._subject_query(arguments)
        if tool_id == TOOL_PLAN_QUERY:
            return self._plan_query(arguments)
        if tool_id == TOOL_MEMORY_QUERY:
            return self._memory_query(arguments, run_id)
        if tool_id == TOOL_PROJECT_CONSTITUTION_READ:
            return self._constitution_read()
        if tool_id == TOOL_ARTIFACT_READ:
            return self._artifact_read(arguments)
        if tool_id == TOOL_TOOL_SEARCH:
            return self._tool_search(arguments)
        raise KeyError(f"unknown core tool: {tool_id}")

    def _compile_context(
        self, arguments: dict[str, object], run_id: str
    ) -> CoreToolResult:
        chapter_id = _required_id(arguments, "chapter_id")
        request = CompileContextRequest(
            chapter_id=chapter_id,
            budget=self._budget,
            run_id=run_id,
            requirement=_optional_text(arguments, "requirement") or "",
            recent_chapter_texts=_string_list(arguments, "recent_chapter_texts"),
            participant_ids=_string_list(arguments, "participant_ids"),
            pov_character_id=_optional_id(arguments, "pov_character_id"),
            evidence_requests=self._evidence_needs(arguments),
        )
        compiled = self._compile.build(request)
        return CoreToolResult(
            TOOL_CONTEXT_COMPILE,
            self._render_compiled(compiled),
        )

    def _manuscript_read(self, arguments: dict[str, object]) -> CoreToolResult:
        chapter_id = _required_id(arguments, "chapter_id")
        max_chars = _int_arg(
            arguments, "max_chars", _DEFAULT_MAX_CHARS, maximum=_MAX_MAX_CHARS
        )
        excerpt = self._queries.read_manuscript(
            chapter_id,
            max_chars=max_chars,
        )
        truncated = "（已截断）" if excerpt.truncated else ""
        return CoreToolResult(
            TOOL_MANUSCRIPT_READ,
            f"章节：{excerpt.title}（revision={excerpt.revision}）\n"
            f"正文{truncated}：\n{excerpt.content}",
        )

    def _manuscript_selection(
        self, arguments: dict[str, object], run_id: str
    ) -> CoreToolResult:
        chapter_id = _optional_id(arguments, "chapter_id")
        if chapter_id is None:
            chapter_id = self._store.get_run(run_id).active_chapter_id
        if chapter_id is None:
            raise ValueError("manuscript.get_selection 需要 chapter_id 或活动章节")
        content_length = self._queries.manuscript_length(chapter_id)
        start = _int_arg(
            arguments, "start_offset", 0, maximum=content_length, minimum=0
        )
        end = _int_arg(
            arguments,
            "end_offset",
            content_length,
            maximum=content_length,
            minimum=0,
        )
        if start > end:
            raise ValueError("start_offset 不能大于 end_offset")
        return CoreToolResult(
            TOOL_MANUSCRIPT_GET_SELECTION,
            self._queries.read_selection(chapter_id, start=start, end=end),
        )

    def _subject_query(self, arguments: dict[str, object]) -> CoreToolResult:
        query = _required_text(arguments, "query")
        limit = _int_arg(arguments, "limit", 10, maximum=50)
        matches = self._queries.query_subjects(query, limit=limit)
        lines = [
            f"- {subject.canonical_name}（subject_id={subject.subject_id},"
            f"type={subject.subject_type.value},active={subject.active}）"
            for subject in matches
        ]
        return CoreToolResult(
            TOOL_SUBJECT_QUERY, "\n".join(lines) or "未找到匹配的主体。"
        )

    def _plan_query(self, arguments: dict[str, object]) -> CoreToolResult:
        chapter_id = _required_id(arguments, "chapter_id")
        result = self._queries.query_plan(chapter_id)
        requirement_line = (
            f"当前章要求（revision={result.requirement.revision},"
            f"locked={result.requirement.is_locked}）：\n{result.requirement.content}"
            if result.requirement is not None
            else "当前章要求：无"
        )
        return CoreToolResult(
            TOOL_PLAN_QUERY,
            f"{result.domain_kind}（计划，不是正典）\n{requirement_line}\n"
            f"项目指引 v{result.guidance_revision}：\n{result.guidance_text or '（空）'}",
        )

    def _memory_query(
        self, arguments: dict[str, object], run_id: str
    ) -> CoreToolResult:
        query = _required_text(arguments, "query")
        before = _optional_id(arguments, "before_chapter_id")
        if before is None:
            before = self._store.get_run(run_id).active_chapter_id
        if before is None:
            raise ValueError(
                "memory.query 需要 before_chapter_id 或活动章节（叙事边界）"
            )
        limit = _int_arg(arguments, "limit", 5, maximum=20)
        evidence = self._queries.query_memory(
            query,
            before_chapter_id=before,
            limit=limit,
        )
        lines = [
            f"- {hit.title}: {hit.text[:120]}"
            for hit in evidence.hits
        ]
        return CoreToolResult(
            TOOL_MEMORY_QUERY, "\n".join(lines) or "未找到相关记录。"
        )

    def _constitution_read(self) -> CoreToolResult:
        constitution = self._queries.get_constitution()
        if constitution is None:
            return CoreToolResult(
                TOOL_PROJECT_CONSTITUTION_READ, "项目尚未确立小说最高提示词。"
            )
        labels = {
            "shared_creative_rules": "共享创作规则",
            "agent_only_rules": "Agent 专用规则",
            "writer_only_rules": "正文模型专用规则",
            "overridable_rules": "可覆盖规则",
            "non_overridable_rules": "不可覆盖规则",
        }
        lines = [f"小说最高提示词 v{constitution.revision}："]
        for field, label in labels.items():
            rules = sorted(getattr(constitution, field), key=lambda rule: rule.rule_id)
            if not rules:
                continue
            lines.append(f"{label}:")
            lines.extend(f"- {rule.rule_id}: {rule.text}" for rule in rules)
        return CoreToolResult(TOOL_PROJECT_CONSTITUTION_READ, "\n".join(lines))

    def _artifact_read(self, arguments: dict[str, object]) -> CoreToolResult:
        artifact_id = _required_text(arguments, "artifact_id")
        if not _ARTIFACT_ID_PATTERN.fullmatch(artifact_id):
            raise ValueError("artifact_id 必须是 sha256: 内容地址")
        max_chars = _int_arg(
            arguments, "max_chars", _DEFAULT_MAX_CHARS, maximum=_MAX_MAX_CHARS
        )
        artifact = self._artifacts.get(artifact_id)
        text = artifact.content.decode("utf-8")
        excerpt = text[:max_chars]
        truncated = "（已截断）" if len(text) > len(excerpt) else ""
        return CoreToolResult(
            TOOL_ARTIFACT_READ,
            f"工件 {artifact_id}（kind={artifact.kind.value},"
            f"run={artifact.run_id}）{truncated}：\n{excerpt}",
        )

    def _tool_search(self, arguments: dict[str, object]) -> CoreToolResult:
        query = _required_text(arguments, "query")
        matches = [
            definition
            for definition in self._registry.snapshot()
            if query in definition.id
        ]
        lines = [
            f"- {definition.id} v{definition.version}（risk="
            f"{definition.risk_level.value},write={definition.write_effect.value},"
            f"approval={definition.requires_approval}）"
            for definition in matches
        ]
        return CoreToolResult(TOOL_TOOL_SEARCH, "\n".join(lines) or "未找到匹配的工具。")

    @staticmethod
    def _evidence_needs(
        arguments: dict[str, object],
    ) -> tuple[EvidenceNeed, ...]:
        raw = arguments.get("evidence_requests")
        if raw is None:
            return ()
        if not isinstance(raw, list):
            raise ValueError("evidence_requests 必须是数组")
        needs: list[EvidenceNeed] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("evidence_requests 条目必须是对象")
            try:
                kind = EvidenceNeedKind(str(item.get("kind", "")))
            except ValueError:
                raise ValueError("evidence_requests kind 非法") from None
            query = item.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("evidence_requests query 必须是非空文本")
            needs.append(
                EvidenceNeed(
                    kind=kind,
                    query=query.strip(),
                    participants=_string_list(item, "subject_ids"),
                    limit=_int_arg(item, "limit", 20, maximum=50),
                    required_hits=(
                        _int_arg(item, "required_hits", 1, maximum=50)
                        if item.get("required_hits") is not None
                        else None
                    ),
                )
            )
        return tuple(needs)

    @staticmethod
    def _render_compiled(compiled: CompiledContext) -> str:
        projection = compiled.projection
        categories = "、".join(
            f"{category}={count}" for category, count in projection.included_categories
        )
        return (
            "context.compile 完成：\n"
            f"manifest_id={projection.manifest_id}\n"
            f"estimated_input_tokens={projection.estimated_input_tokens}\n"
            f"evidence_hit_count={projection.evidence_hit_count}\n"
            f"类别构成：{categories or '（无）'}\n"
            "编译文本：\n" + projection.text
        )
