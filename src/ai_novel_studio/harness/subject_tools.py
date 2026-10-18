from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.subject_inspection_service import (
    SubjectInspection,
    SubjectInspectionRequest,
    SubjectInspectionService,
)
from ai_novel_studio.application.subject_merge_service import (
    SubjectMergePreview,
    SubjectMergeService,
)
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approval_resolver import subject_merge_to_payload
from ai_novel_studio.harness.approval_service import ApprovalService
from ai_novel_studio.harness.approvals import ApprovalKind
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.tool_registry import (
    ToolDefinition,
    ToolRegistry,
    ToolRiskLevel,
    ToolScope,
    WriteEffect,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository

TOOL_SUBJECT_INSPECT = "subject.inspect"
TOOL_SUBJECT_COMPARE = "subject.compare"
TOOL_SUBJECT_PROPOSE_MERGE = "subject.propose_merge"
TOOL_SUBJECT_PREVIEW_MERGE = "subject.preview_merge"


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


def _string_property() -> dict[str, object]:
    return {"type": "string", "minLength": 1}


_SUBJECT_IDS: dict[str, object] = {
    "subject_ids": {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
        "minItems": 1,
        "maxItems": 100,
    }
}

_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "tool_id": {"type": "string"},
        "content": {"type": "string"},
        "approval_request_id": {"type": ["string", "null"]},
    },
}

SUBJECT_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        TOOL_SUBJECT_INSPECT,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.READ_ONLY,
        WriteEffect.NONE,
        False,
        _schema(_SUBJECT_IDS, ("subject_ids",)),
        _OUTPUT_SCHEMA,
    ),
    ToolDefinition(
        TOOL_SUBJECT_COMPARE,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.READ_ONLY,
        WriteEffect.NONE,
        False,
        _schema(
            {
                "source_subject_id": _string_property(),
                "target_subject_id": _string_property(),
            },
            ("source_subject_id", "target_subject_id"),
        ),
        _OUTPUT_SCHEMA,
    ),
    ToolDefinition(
        TOOL_SUBJECT_PREVIEW_MERGE,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.READ_ONLY,
        WriteEffect.NONE,
        False,
        _schema(
            {
                "source_subject_id": _string_property(),
                "target_subject_id": _string_property(),
            },
            ("source_subject_id", "target_subject_id"),
        ),
        _OUTPUT_SCHEMA,
    ),
    ToolDefinition(
        TOOL_SUBJECT_PROPOSE_MERGE,
        1,
        ToolScope.PROJECT,
        ToolRiskLevel.PROPOSAL,
        WriteEffect.PROPOSAL_ONLY,
        False,
        _schema(
            {
                "source_subject_id": _string_property(),
                "target_subject_id": _string_property(),
                "reason": _string_property(),
                "idempotency_key": _string_property(),
            },
            ("source_subject_id", "target_subject_id", "reason", "idempotency_key"),
        ),
        _OUTPUT_SCHEMA,
    ),
)


def register_subject_tools(registry: ToolRegistry) -> None:
    for definition in SUBJECT_TOOL_DEFINITIONS:
        registry.register(definition)


@dataclass(frozen=True, slots=True)
class SubjectToolResult:
    """Rendered result of one subject tool call (design v0.3 §27.1.1)."""

    tool_id: str
    content: str
    approval_request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tool_id.strip():
            raise ValueError("subject tool id cannot be empty")
        if not self.content.strip():
            raise ValueError("subject tool content cannot be empty")


class SubjectToolService:
    """A12 Agent-side subject tools (design v0.3 §27.1.1, contract §8.2).

    inspect / compare / preview_merge are read-only views over the backend
    facades. propose_merge validates the pair through a deterministic
    preview, then creates a SUBJECT_MERGE approval request; the merge itself
    only runs through the ApprovalResolver (B3). No domain write happens
    from any tool here.
    """

    def __init__(
        self,
        inspections: SubjectInspectionService,
        merges: SubjectMergeService,
        approvals: ApprovalService,
    ) -> None:
        self._inspections = inspections
        self._merges = merges
        self._approvals = approvals

    @classmethod
    def for_project(cls, project: ProjectRepository) -> SubjectToolService:
        store = HarnessEventStore(HarnessEventRepository(project))
        approvals = ApprovalService(store, ApprovalRepository(project))
        return cls(
            SubjectInspectionService(SubjectRepository(project)),
            SubjectMergeService(project),
            approvals,
        )

    def execute(
        self, tool_id: str, arguments: dict[str, object], *, run_id: str
    ) -> SubjectToolResult:
        if tool_id == TOOL_SUBJECT_INSPECT:
            return self._inspect(arguments)
        if tool_id == TOOL_SUBJECT_COMPARE:
            return self._compare(arguments)
        if tool_id == TOOL_SUBJECT_PREVIEW_MERGE:
            return self._preview_merge(arguments)
        if tool_id == TOOL_SUBJECT_PROPOSE_MERGE:
            return self._propose_merge(arguments, run_id)
        raise KeyError(f"unknown subject tool: {tool_id}")

    def _inspect(self, arguments: dict[str, object]) -> SubjectToolResult:
        raw_ids = arguments.get("subject_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ValueError("subject.inspect subject_ids 必须是非空数组")
        request = SubjectInspectionRequest(
            tuple(str(value) for value in raw_ids)
        )
        inspections = self._inspections.inspect(request)
        lines = ["subject.inspect 结果:"]
        lines.extend(_render_inspection(item) for item in inspections)
        return SubjectToolResult(TOOL_SUBJECT_INSPECT, "\n".join(lines))

    def _compare(self, arguments: dict[str, object]) -> SubjectToolResult:
        source_id, target_id = self._pair(arguments)
        inspections = self._inspections.inspect(
            SubjectInspectionRequest((source_id, target_id))
        )
        preview = self._merges.preview(source_id, target_id)
        lines = [
            "subject.compare 结果:",
            "来源卡 " + _render_inspection(inspections[0]),
            "目标卡 " + _render_inspection(inspections[1]),
            _render_preview(preview),
        ]
        return SubjectToolResult(TOOL_SUBJECT_COMPARE, "\n".join(lines))

    def _preview_merge(self, arguments: dict[str, object]) -> SubjectToolResult:
        source_id, target_id = self._pair(arguments)
        preview = self._merges.preview(source_id, target_id)
        return SubjectToolResult(
            TOOL_SUBJECT_PREVIEW_MERGE,
            "subject.preview_merge 结果:\n" + _render_preview(preview),
        )

    def _propose_merge(
        self, arguments: dict[str, object], run_id: str
    ) -> SubjectToolResult:
        source_id, target_id = self._pair(arguments)
        reason = arguments.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("subject.propose_merge reason 必须是非空文本")
        idempotency_key = arguments.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("subject.propose_merge idempotency_key 必须是非空文本")
        preview = self._merges.preview(source_id, target_id)
        payload = subject_merge_to_payload(
            source_id, target_id, reason=reason.strip()
        )
        payload["preview_snapshot"] = {
            "source_canonical_name": preview.source_canonical_name,
            "target_canonical_name": preview.target_canonical_name,
            "aliases_to_preserve": list(preview.aliases_to_preserve),
            "state_event_count": preview.state_event_count,
            "shared_chapter_conflict_count": preview.shared_chapter_conflict_count,
        }
        approval = self._approvals.request_approval(
            run_id=run_id,
            kind=ApprovalKind.SUBJECT_MERGE,
            summary=_merge_summary(preview),
            payload=payload,
            expected_revisions=(
                (
                    f"subject.state_events:{preview.source_character_id}",
                    preview.state_event_count,
                ),
            ),
            idempotency_key=idempotency_key.strip(),
        )
        lines = [
            "subject.propose_merge 结果:合并提案已创建,等待作者审批。",
            _render_preview(preview),
            f"理由:{reason.strip()}",
            f"approval_request_id:{approval.request_id}",
        ]
        return SubjectToolResult(
            TOOL_SUBJECT_PROPOSE_MERGE,
            "\n".join(lines),
            approval_request_id=approval.request_id,
        )

    def _pair(self, arguments: dict[str, object]) -> tuple[str, str]:
        source = arguments.get("source_subject_id")
        target = arguments.get("target_subject_id")
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError("subject tool 需要 source_subject_id 与 target_subject_id")
        validate_id(source)
        validate_id(target)
        if source == target:
            raise ValueError("不能把同一主体归并到自身")
        return source, target


def _render_inspection(inspection: SubjectInspection) -> str:
    aliases = "、".join(inspection.aliases) if inspection.aliases else "无"
    return (
        f"{inspection.canonical_name}(subject_id={inspection.subject_id},"
        f"type={inspection.subject_type.value},active={inspection.active})"
        f"别名:{aliases}"
    )


def _render_preview(preview: SubjectMergePreview) -> str:
    aliases = "、".join(preview.aliases_to_preserve) or "无"
    return (
        f"合并预览:来源卡 {preview.source_canonical_name}(subject_id="
        f"{preview.source_character_id})→ 目标卡 {preview.target_canonical_name}"
        f"(subject_id={preview.target_character_id});待保留别名:{aliases};"
        f"状态事件数 {preview.state_event_count};共享章节冲突 "
        f"{preview.shared_chapter_conflict_count};可逆:{preview.reversible}"
    )


def _merge_summary(preview: SubjectMergePreview) -> str:
    return (
        f"人物合并:{preview.source_canonical_name} → "
        f"{preview.target_canonical_name}"
    )
