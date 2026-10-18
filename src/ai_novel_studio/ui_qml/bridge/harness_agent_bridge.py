"""QML-facing bridge for the production Harness chapter-generation loop.

The bridge is a presentation adapter only. It composes the existing model
backend and Harness, runs the blocking model call outside the UI thread, and
returns a bounded projection for ``MockNovelStudioFacade``. It does not create
another run store, approval path, or source of manuscript truth.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Protocol
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ai_novel_studio.application.model_backend import ModelBackend
from ai_novel_studio.application.selection_patch import SelectionPatchCapture
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.harness.agent_loop import (
    ChapterGenerationLoop,
    ChapterGenerationResult,
    DraftBlockedError,
)
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.model_roles import ModelRole, ModelRoleBinding
from ai_novel_studio.infrastructure.llm import LLMMessage
from ai_novel_studio.infrastructure.llm.config_repository import ModelConfigError
from ai_novel_studio.infrastructure.llm.gateway import MissingCredentialError
from ai_novel_studio.infrastructure.llm.provider_adapter import ProviderRequestError
from ai_novel_studio.infrastructure.llm.provider_profile import MissingModelRouteError
from ai_novel_studio.infrastructure.llm.schemas import TaskPurpose
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bridge.dtos import AgentTimelineItemDto
from ai_novel_studio.ui_qml.bridge.models.agent_timeline_model import (
    AgentTimelineModel,
)

_DEFAULT_CONTEXT_WINDOW = 32_768
_DEFAULT_OUTPUT_LIMIT = 2_048
_DEFAULT_SAFETY_MARGIN = 512
_MAX_GOAL_CODEPOINTS = 4_000
_MAX_CHAT_CONTEXT_MESSAGES = 20
_MAX_CHAT_CONTEXT_CODEPOINTS = 20_000

_MODEL_ROUTE_ERROR = "尚未配置正文创作模型"
_MODEL_CREDENTIAL_ERROR = "当前模型连接尚未保存 API Key"
_MODEL_CONFIGURATION_ERROR = "模型配置无效，请在设置中检查模型连接"
_DRAFT_BLOCKED_ERROR = "当前章节上下文未满足生成条件"
_AGENT_EXECUTION_ERROR = "AI 任务执行失败，请检查模型配置或项目状态后重试"


@dataclass(frozen=True, slots=True)
class HarnessAgentOutcome:
    """Bounded UI projection of one completed Harness generation attempt."""

    run_id: str
    stage: str
    draft_text: str
    approval_request_id: str
    approval_summary: str
    audit_finding_count: int
    event_types: tuple[str, ...]


class _GenerationLoop(Protocol):
    def generate_candidate(
        self,
        goal: str,
        chapter_id: str,
        *,
        selection_patch: SelectionPatchCapture | None = None,
    ) -> ChapterGenerationResult: ...


LoopFactory = Callable[[ProjectRepository], _GenerationLoop]


class _AssistantChatRunner(Protocol):
    def reply(
        self,
        message: str,
        chapter_id: str,
        current_manuscript: str,
        conversation_context: tuple[LLMMessage, ...],
    ) -> str: ...


ChatRunnerFactory = Callable[[ProjectRepository], _AssistantChatRunner]


def _default_loop(project: ProjectRepository) -> ChapterGenerationLoop:
    backend = ModelBackend.create_default()
    configuration = backend.gateway.configuration
    route = configuration.routes.resolve(TaskPurpose.PROSE_GENERATION)
    model = configuration.model(route)
    context_window = model.capabilities.context_window or _DEFAULT_CONTEXT_WINDOW
    output_limit = min(
        model.capabilities.max_output_tokens or _DEFAULT_OUTPUT_LIMIT,
        _DEFAULT_OUTPUT_LIMIT,
    )
    available = context_window - output_limit - 1
    if available < 0:
        raise ModelConfigError("model context budget is invalid")
    safety_margin = min(_DEFAULT_SAFETY_MARGIN, available)
    binding = ModelRoleBinding(
        ModelRole.CHAPTER_DRAFT,
        TaskPurpose.PROSE_GENERATION,
        route.provider_id,
        route.model_id,
    )
    return ChapterGenerationLoop.for_project(
        project,
        backend.gateway,
        binding,
        budget=TokenBudget(context_window, output_limit, safety_margin),
        output_token_limit=output_limit,
    )


class _ProjectAssistantChatRunner:
    """Canonical read-only plot discussion over the existing AgentTaskService."""

    def __init__(self, project: ProjectRepository) -> None:
        from ai_novel_studio.application.agent_loop_service import AgentLoopService
        from ai_novel_studio.application.agent_task_service import AgentTaskService
        from ai_novel_studio.application.agent_tool_providers import (
            build_project_agent_registry,
        )
        from ai_novel_studio.application.project_runtime import GatewayAgentModelPort
        from ai_novel_studio.infrastructure.storage.agent_repository import (
            AgentRepository,
        )

        backend = ModelBackend.create_default()
        route = backend.gateway.configuration.routes.resolve(TaskPurpose.AGENT_ASSISTANT)
        self._provider_id = route.provider_id
        self._model_id = route.model_id
        self._project = project
        self._service = AgentTaskService(
            AgentLoopService(
                AgentRepository(project),
                build_project_agent_registry(project),
                GatewayAgentModelPort(backend.gateway),
            )
        )

    def reply(
        self,
        message: str,
        chapter_id: str,
        current_manuscript: str,
        conversation_context: tuple[LLMMessage, ...],
    ) -> str:
        from ai_novel_studio.domain.agent import AgentRunStatus
        from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
            ChapterRequirementRepository,
        )

        requirements = ChapterRequirementRepository(self._project)
        try:
            requirement_content = requirements.get(chapter_id).content
        except KeyError:
            requirement_content = ""
        result = self._service.discuss_plot_with_tools(
            user_message=message,
            current_manuscript=current_manuscript,
            chapter_requirement=requirement_content,
            conversation_context=conversation_context,
            chapter_id=chapter_id,
            model_provider_id=self._provider_id,
            model_id=self._model_id,
            output_token_limit=_DEFAULT_OUTPUT_LIMIT,
        )
        if result.status is not AgentRunStatus.COMPLETED:
            raise RuntimeError("assistant chat did not complete")
        return result.final_answer


def _default_chat_runner(project: ProjectRepository) -> _ProjectAssistantChatRunner:
    return _ProjectAssistantChatRunner(project)


class HarnessAgentPort:
    """Framework-neutral project binding around ``ChapterGenerationLoop``."""

    def __init__(
        self,
        *,
        loop_factory: LoopFactory = _default_loop,
        chat_runner_factory: ChatRunnerFactory = _default_chat_runner,
    ) -> None:
        self._loop_factory = loop_factory
        self._chat_runner_factory = chat_runner_factory
        self._project: ProjectRepository | None = None
        self._lock = Lock()

    def bind_project(self, project: ProjectRepository | None) -> None:
        with self._lock:
            self._project = project

    def generate(
        self,
        goal: str,
        chapter_id: str,
        *,
        selection_patch: SelectionPatchCapture | None = None,
    ) -> HarnessAgentOutcome:
        normalized_goal = goal.strip()
        if not normalized_goal:
            raise ValueError("Agent 任务不能为空")
        if len(normalized_goal) > _MAX_GOAL_CODEPOINTS:
            raise ValueError("Agent 任务过长")
        if not chapter_id.strip():
            raise ValueError("当前章节无效")
        with self._lock:
            project = self._project
        if project is None:
            raise RuntimeError("请先打开一个真实项目")
        try:
            loop = self._loop_factory(project)
            result = loop.generate_candidate(
                normalized_goal,
                chapter_id,
                selection_patch=selection_patch,
            )
            store = HarnessEventStore(HarnessEventRepository(project))
            run = store.get_run(result.run.id)
            events = store.replay(run.id)
            return HarnessAgentOutcome(
                run_id=run.id,
                stage=run.stage.value,
                draft_text=result.draft.text,
                approval_request_id=result.approval.request_id,
                approval_summary=result.approval.summary,
                audit_finding_count=len(result.audit.findings),
                event_types=tuple(event.event_type.value for event in events),
            )
        except MissingModelRouteError:
            raise RuntimeError(_MODEL_ROUTE_ERROR) from None
        except MissingCredentialError:
            raise RuntimeError(_MODEL_CREDENTIAL_ERROR) from None
        except ModelConfigError:
            raise RuntimeError(_MODEL_CONFIGURATION_ERROR) from None
        except DraftBlockedError:
            raise RuntimeError(_DRAFT_BLOCKED_ERROR) from None
        except ProviderRequestError:
            raise RuntimeError(_AGENT_EXECUTION_ERROR) from None
        except Exception:
            raise RuntimeError(_AGENT_EXECUTION_ERROR) from None

    def chat(
        self,
        message: str,
        chapter_id: str,
        current_manuscript: str,
        conversation_context: tuple[LLMMessage, ...],
    ) -> str:
        normalized = message.strip()
        if not normalized:
            raise ValueError("对话内容不能为空")
        if len(normalized) > _MAX_GOAL_CODEPOINTS:
            raise ValueError("对话内容过长")
        with self._lock:
            project = self._project
        if project is None:
            raise RuntimeError("请先打开一个真实项目")
        try:
            return self._chat_runner_factory(project).reply(
                normalized,
                chapter_id,
                current_manuscript,
                conversation_context,
            )
        except MissingModelRouteError:
            raise RuntimeError("尚未配置剧情商讨模型") from None
        except MissingCredentialError:
            raise RuntimeError(_MODEL_CREDENTIAL_ERROR) from None
        except ModelConfigError:
            raise RuntimeError(_MODEL_CONFIGURATION_ERROR) from None
        except Exception:
            raise RuntimeError("AI 对话失败，请检查模型配置或项目状态后重试") from None

    def resolve_approval(self, request_id: str, *, approved: bool) -> None:
        with self._lock:
            project = self._project
        if project is None:
            raise RuntimeError("请先打开一个真实项目")
        try:
            from ai_novel_studio.harness.approval_resolver import ApprovalResolver

            ApprovalResolver.for_project(project).resolve_and_commit(
                request_id,
                approved=approved,
            )
        except Exception:
            raise RuntimeError("候选稿审批失败，请重新载入章节后重试") from None


class _HarnessAgentJob(QRunnable):
    def __init__(
        self,
        port: HarnessAgentPort,
        request_id: str,
        goal: str,
        chapter_id: str,
        selection_patch: SelectionPatchCapture | None,
        coordinator: HarnessAgentCoordinator,
    ) -> None:
        super().__init__()
        self._port = port
        self._request_id = request_id
        self._goal = goal
        self._chapter_id = chapter_id
        self._selection_patch = selection_patch
        self._coordinator = coordinator

    def run(self) -> None:
        try:
            outcome = self._port.generate(
                self._goal,
                self._chapter_id,
                selection_patch=self._selection_patch,
            )
        except Exception as exc:  # noqa: BLE001 - port exposes fixed safe messages
            self._coordinator.agent_failed.emit(self._request_id, str(exc))
        else:
            self._coordinator.outcome_ready.emit(self._request_id, outcome)
        finally:
            self._coordinator._job_finished.emit(self._request_id)


class _HarnessChatJob(QRunnable):
    def __init__(
        self,
        port: HarnessAgentPort,
        request_id: str,
        message: str,
        chapter_id: str,
        current_manuscript: str,
        conversation_context: tuple[LLMMessage, ...],
        coordinator: HarnessAgentCoordinator,
    ) -> None:
        super().__init__()
        self._port = port
        self._request_id = request_id
        self._message = message
        self._chapter_id = chapter_id
        self._current_manuscript = current_manuscript
        self._conversation_context = conversation_context
        self._coordinator = coordinator

    def run(self) -> None:
        try:
            answer = self._port.chat(
                self._message,
                self._chapter_id,
                self._current_manuscript,
                self._conversation_context,
            )
        except Exception as exc:  # noqa: BLE001 - port exposes fixed safe messages
            self._coordinator.agent_failed.emit(self._request_id, str(exc))
        else:
            self._coordinator.chat_ready.emit(self._request_id, answer)
        finally:
            self._coordinator._job_finished.emit(self._request_id)


class HarnessAgentCoordinator(QObject):
    """Execute one Harness run at a time without blocking the QML thread."""

    status_changed = Signal(str, str)
    outcome_ready = Signal(str, object)
    chat_ready = Signal(str, str)
    agent_failed = Signal(str, str)
    _job_finished = Signal(str)

    def __init__(
        self,
        port: HarnessAgentPort,
        parent: QObject | None = None,
        *,
        pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)
        self._port = port
        self._pool = pool or QThreadPool.globalInstance()
        self._active_request_id: str | None = None
        self._job_finished.connect(self._finish)

    @property
    def is_running(self) -> bool:
        return self._active_request_id is not None

    def bind_project(self, project: ProjectRepository | None) -> None:
        self._port.bind_project(project)

    def start(
        self,
        request_id: str,
        goal: str,
        chapter_id: str,
        selection_patch: SelectionPatchCapture | None = None,
    ) -> None:
        if self.is_running:
            self.agent_failed.emit(request_id, "已有 Agent 任务正在运行")
            return
        self._active_request_id = request_id
        self.status_changed.emit(request_id, "RUNNING")
        self._pool.start(
            _HarnessAgentJob(
                self._port,
                request_id,
                goal,
                chapter_id,
                selection_patch,
                self,
            )
        )

    def start_chat(
        self,
        request_id: str,
        message: str,
        chapter_id: str,
        current_manuscript: str,
        conversation_context: tuple[LLMMessage, ...],
    ) -> None:
        if self.is_running:
            self.agent_failed.emit(request_id, "已有 AI 任务正在运行")
            return
        self._active_request_id = request_id
        self.status_changed.emit(request_id, "RUNNING")
        self._pool.start(
            _HarnessChatJob(
                self._port,
                request_id,
                message,
                chapter_id,
                current_manuscript,
                conversation_context,
                self,
            )
        )

    def resolve_approval(self, request_id: str, approved: bool) -> None:
        self._port.resolve_approval(request_id, approved=approved)

    @Slot(str)
    def _finish(self, request_id: str) -> None:
        if request_id != self._active_request_id:
            return
        self._active_request_id = None
        self.status_changed.emit(request_id, "IDLE")


class HarnessAgentTimelineController(QObject):
    """Own the production Harness timeline without growing the legacy facade."""

    timeline_changed = Signal()
    busy_changed = Signal()

    def __init__(
        self,
        coordinator: HarnessAgentCoordinator,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._model = AgentTimelineModel(self)
        self._request_id: str | None = None
        self._user_item_id: str | None = None
        self._status_item_id: str | None = None
        self._source_text = ""
        self._sequence = 0
        self._active_mode = ""
        self._pending_items: dict[str, str] = {}
        self._chat_context: list[LLMMessage] = []
        coordinator.status_changed.connect(self._on_status)
        coordinator.outcome_ready.connect(self._on_outcome)
        coordinator.chat_ready.connect(self._on_chat)
        coordinator.agent_failed.connect(self._on_failure)
        self._approval_requests: dict[str, str] = {}

    @property
    def model(self) -> AgentTimelineModel:
        return self._model

    @property
    def is_busy(self) -> bool:
        return self._request_id is not None

    def bind_project(self, project: ProjectRepository | None) -> None:
        self._request_id = None
        self._user_item_id = None
        self._status_item_id = None
        self._source_text = ""
        self._sequence = 0
        self._active_mode = ""
        self._pending_items.clear()
        self._approval_requests.clear()
        self._chat_context.clear()
        self._model.clear()
        self._coordinator.bind_project(project)
        self.timeline_changed.emit()
        self.busy_changed.emit()

    def start(
        self,
        goal: str,
        chapter_id: str,
        source_text: str,
        *,
        editor_clean: bool,
        selection_patch: SelectionPatchCapture | None = None,
    ) -> None:
        if self.is_busy:
            return
        if not editor_clean:
            self._model.append_item(
                AgentTimelineItemDto(
                    id=str(uuid4()),
                    kind="error",
                    text="请先保存当前章节，再启动 Harness",
                )
            )
            self.timeline_changed.emit()
            return
        request_id = str(uuid4())
        self._request_id = request_id
        self._active_mode = "selection_draft" if selection_patch else "draft"
        self._sequence = 0
        self._source_text = selection_patch.selection.text if selection_patch else source_text
        self._user_item_id = str(uuid4())
        self._status_item_id = str(uuid4())
        self._model.append_item(
            AgentTimelineItemDto(
                id=self._user_item_id,
                kind="user_text",
                text=goal,
                run_id=request_id,
                sequence_number=0,
            )
        )
        self._model.append_item(
            AgentTimelineItemDto(
                id=self._status_item_id,
                kind="run_status",
                label=(
                    "正在读取选区并生成候选稿"
                    if selection_patch
                    else "正在读取当前章节并生成候选稿"
                ),
                busy=True,
                status="RUNNING",
                state="RUNNING",
                run_id=request_id,
                sequence_number=1,
            )
        )
        self._sequence = 2
        self.busy_changed.emit()
        self.timeline_changed.emit()
        self._coordinator.start(
            request_id,
            goal,
            chapter_id,
            selection_patch,
        )

    def start_chat(
        self,
        message: str,
        chapter_id: str,
        source_text: str,
    ) -> None:
        if self.is_busy:
            return
        request_id = str(uuid4())
        conversation_context = tuple(self._chat_context)
        self._request_id = request_id
        self._user_item_id = None
        self._status_item_id = str(uuid4())
        self._active_mode = "chat"
        self._source_text = source_text
        self._model.append_item(
            AgentTimelineItemDto(
                id=str(uuid4()),
                kind="user_text",
                text=message,
                run_id=request_id,
                sequence_number=self._sequence,
            )
        )
        self._sequence += 1
        self._append_chat_context(LLMMessage("user", message))
        self._model.append_item(
            AgentTimelineItemDto(
                id=self._status_item_id,
                kind="run_status",
                label="正在读取当前章节并组织回答",
                busy=True,
                status="RUNNING",
                state="RUNNING",
                run_id=request_id,
                sequence_number=self._sequence,
            )
        )
        self._sequence += 1
        self.busy_changed.emit()
        self.timeline_changed.emit()
        self._coordinator.start_chat(
            request_id,
            message,
            chapter_id,
            source_text,
            conversation_context,
        )

    def resolve_pending(self, item_id: str, *, approved: bool) -> bool:
        approval_id = self._approval_requests.get(item_id)
        if approval_id is None:
            return False
        run_id = self._pending_items.get(item_id, "")
        try:
            self._coordinator.resolve_approval(approval_id, approved)
        except RuntimeError as error:
            self.warn(str(error))
            return False
        matching = [
            pending_item
            for pending_item, request in self._approval_requests.items()
            if request == approval_id
        ]
        state = "APPLIED" if approved else "DISCARDED"
        for pending_item in matching:
            self._model.update_item(pending_item, state=state)
            self._pending_items.pop(pending_item, None)
            self._approval_requests.pop(pending_item, None)
        self._model.append_item(
            AgentTimelineItemDto(
                id=str(uuid4()),
                kind="assistant_text",
                text=(
                    "候选稿已经应用到当前章节。" if approved else "已放弃候选稿，当前章节保持不变。"
                ),
                run_id=run_id,
                sequence_number=self._sequence,
            )
        )
        self._sequence += 1
        self.timeline_changed.emit()
        return True

    def stop(self) -> None:
        if self.is_busy:
            self.warn(
                "当前模型请求不能安全地立即中断；任务仍在后台运行，完成后会保留为待审批候选稿。"
            )

    def warn(self, message: str) -> None:
        self._model.append_item(
            AgentTimelineItemDto(
                id=str(uuid4()),
                kind="warning",
                text=message,
                run_id=self._request_id or "",
                sequence_number=self._sequence,
            )
        )
        self._sequence += 1
        self.timeline_changed.emit()

    def handles_pending_item(self, item_id: str) -> bool:
        return item_id in self._pending_items

    def notify_action_unavailable(self, item_id: str, message: str) -> None:
        run_id = self._pending_items[item_id]
        self._model.append_item(
            AgentTimelineItemDto(
                id=str(uuid4()),
                kind="assistant_text",
                text=message,
                run_id=run_id,
                sequence_number=self._sequence,
            )
        )
        self._sequence += 1
        self.timeline_changed.emit()

    @Slot(str, str)
    def _on_status(self, request_id: str, status: str) -> None:
        if request_id != self._request_id or status != "RUNNING":
            return
        if self._status_item_id is not None:
            self._model.update_item(
                self._status_item_id,
                label=(
                    "正在读取当前章节并组织回答"
                    if self._active_mode == "chat"
                    else (
                        "正在读取选区并生成候选稿"
                        if self._active_mode == "selection_draft"
                        else "正在读取当前章节并生成候选稿"
                    )
                ),
                busy=True,
                status="RUNNING",
                state="RUNNING",
            )
            self.timeline_changed.emit()

    @Slot(str, object)
    def _on_outcome(self, request_id: str, outcome: HarnessAgentOutcome) -> None:
        if request_id != self._request_id:
            return
        for item_id in (self._user_item_id, self._status_item_id):
            if item_id is not None:
                self._model.update_item(item_id, run_id=outcome.run_id)
        if self._status_item_id is not None:
            self._model.update_item(
                self._status_item_id,
                label="候选稿已生成，等待你确认",
                busy=False,
                status=outcome.stage,
                state="PENDING",
            )
        self._append_outcome(outcome)
        self._request_id = None
        self._active_mode = ""
        self.busy_changed.emit()
        self.timeline_changed.emit()

    @Slot(str, str)
    def _on_chat(self, request_id: str, answer: str) -> None:
        if request_id != self._request_id:
            return
        self._model.append_item(
            AgentTimelineItemDto(
                id=str(uuid4()),
                kind="assistant_text",
                text=answer,
                run_id=request_id,
                sequence_number=self._sequence,
            )
        )
        self._sequence += 1
        self._append_chat_context(LLMMessage("assistant", answer))
        if self._status_item_id is not None:
            self._model.update_item(
                self._status_item_id,
                label="回答完成",
                busy=False,
                status="COMPLETED",
                state="COMPLETED",
            )
        self._request_id = None
        self._active_mode = ""
        self.busy_changed.emit()
        self.timeline_changed.emit()

    def _append_chat_context(self, message: LLMMessage) -> None:
        self._chat_context.append(message)
        while (
            len(self._chat_context) > _MAX_CHAT_CONTEXT_MESSAGES
            or sum(len(item.content) for item in self._chat_context) > _MAX_CHAT_CONTEXT_CODEPOINTS
        ):
            self._chat_context.pop(0)

    def _append_outcome(self, outcome: HarnessAgentOutcome) -> None:
        diff_id = str(uuid4())
        self._model.append_item(
            AgentTimelineItemDto(
                id=diff_id,
                kind="text_diff",
                label="候选修改",
                current_text=self._source_text,
                draft_text=outcome.draft_text,
                state="PENDING",
                run_id=outcome.run_id,
                sequence_number=self._sequence,
            )
        )
        self._sequence += 1
        self._pending_items[diff_id] = outcome.run_id
        self._approval_requests[diff_id] = outcome.approval_request_id

    @Slot(str, str)
    def _on_failure(self, request_id: str, message: str) -> None:
        if request_id != self._request_id:
            return
        if self._status_item_id is not None:
            self._model.update_item(
                self._status_item_id,
                label=("AI 对话失败" if self._active_mode == "chat" else "候选稿生成失败"),
                busy=False,
                status="FAILED",
                state="FAILED",
            )
        self._model.append_item(
            AgentTimelineItemDto(
                id=str(uuid4()),
                kind="error",
                text=message,
                run_id=request_id,
                sequence_number=self._sequence,
            )
        )
        self._sequence += 1
        self._request_id = None
        self._active_mode = ""
        self.busy_changed.emit()
        self.timeline_changed.emit()


__all__ = [
    "HarnessAgentCoordinator",
    "HarnessAgentOutcome",
    "HarnessAgentPort",
    "HarnessAgentTimelineController",
]
