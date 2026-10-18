from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.harness.core_tools import CoreToolResult, CoreToolService
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.permission_gateway import (
    GateContext,
    GateDecision,
    PermissionGateway,
)
from ai_novel_studio.harness.run_state import CLOSED_STAGES, RunEventType
from ai_novel_studio.harness.subject_tools import SubjectToolResult, SubjectToolService


class ToolCallDeniedError(RuntimeError):
    """The gateway denied this tool call before execution."""


class ToolCallRequiresApprovalError(RuntimeError):
    """The gateway classified this call as formal-write; execution never ran."""


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """Outcome of one gated tool call (design §31, §63)."""

    decision: GateDecision
    tool_id: str
    version: int
    result: CoreToolResult | SubjectToolResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.decision, GateDecision):
            raise ValueError("decision must be a GateDecision")
        if not self.tool_id.strip():
            raise ValueError("tool_id cannot be empty")
        if self.version < 1:
            raise ValueError("version must be positive")


class ToolExecutor:
    """Gated execution path for every tool call (design §31, contract §3/§14).

    The gateway runs before any dispatch: DENIED calls never execute and
    raise ToolCallDeniedError; REQUIRES_APPROVAL calls (FORMAL_WRITE) never
    execute and raise ToolCallRequiresApprovalError for the caller to build
    an approval through the existing approval kinds; ALLOWED calls dispatch
    to the core or subject tool services with TOOL_CALL_STARTED /
    TOOL_CALL_COMPLETED / TOOL_CALL_FAILED events (design §63). Prompts and
    skills cannot bypass this path - there is no other execute().
    """

    def __init__(
        self,
        store: HarnessEventStore,
        gateway: PermissionGateway,
        core: CoreToolService,
        subjects: SubjectToolService,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._core = core
        self._subjects = subjects

    def execute(
        self,
        run_id: str,
        tool_id: str,
        arguments: dict[str, object],
        *,
        idempotency_key: str | None = None,
        expected_revision: int | None = None,
        version: int | None = None,
    ) -> ToolExecution:
        run = self._store.get_run(run_id)
        if run.stage in CLOSED_STAGES:
            raise ToolCallDeniedError(
                f"run {run_id} is closed at stage {run.stage.value}"
            )
        decision = self._gateway.evaluate(
            tool_id,
            version=version,
            context=GateContext(
                run_stage=run.stage,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                project_scope_enabled=True,
                run_scope_enabled=True,
            ),
        )
        if decision.decision is GateDecision.DENIED:
            self._store.append(
                run_id,
                RunEventType.TOOL_CALL_FAILED,
                {"tool_id": tool_id, "reason": decision.reason or "denied"},
            )
            raise ToolCallDeniedError(decision.reason or "tool call denied")
        if decision.decision is GateDecision.REQUIRES_APPROVAL:
            self._store.append(
                run_id,
                RunEventType.TOOL_CALL_FAILED,
                {
                    "tool_id": tool_id,
                    "reason": "formal writes require author approval",
                },
            )
            raise ToolCallRequiresApprovalError(
                f"tool {tool_id} requires author approval before execution"
            )
        self._store.append(
            run_id,
            RunEventType.TOOL_CALL_STARTED,
            {"tool_id": tool_id, "version": decision.tool_version},
        )
        try:
            result = self._dispatch(tool_id, arguments, run_id)
        except Exception as error:
            self._store.append(
                run_id,
                RunEventType.TOOL_CALL_FAILED,
                {"tool_id": tool_id, "reason": str(error)[:200]},
            )
            raise
        self._store.append(
            run_id,
            RunEventType.TOOL_CALL_COMPLETED,
            {"tool_id": tool_id},
        )
        return ToolExecution(
            decision=decision.decision,
            tool_id=tool_id,
            version=decision.tool_version,
            result=result,
        )

    def _dispatch(
        self, tool_id: str, arguments: dict[str, object], run_id: str
    ) -> CoreToolResult | SubjectToolResult:
        if tool_id.startswith("subject."):
            return self._subjects.execute(tool_id, arguments, run_id=run_id)
        return self._core.execute(tool_id, arguments, run_id=run_id)
