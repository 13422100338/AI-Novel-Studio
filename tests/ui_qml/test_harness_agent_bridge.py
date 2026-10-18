from __future__ import annotations

import hashlib
import json
import time
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtQml import QQmlApplicationEngine

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
)
from ai_novel_studio.application.selection_patch import (
    ANCHOR_CODEPOINTS,
    SCHEMA_VERSION,
    SelectionPatchCapture,
    parse_selection_patch_capture,
)
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.harness.agent_loop import ChapterGenerationLoop
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.model_roles import ModelRole, ModelRoleBinding
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMStreamEvent,
    StreamEventKind,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bootstrap import register_frontend_types
from ai_novel_studio.ui_qml.bridge.harness_agent_bridge import (
    HarnessAgentCoordinator,
    HarnessAgentOutcome,
    HarnessAgentPort,
)
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import (
    MockNovelStudioFacade,
)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _selection_payload(
    source: str,
    selected: str,
    *,
    chapter_id: str = "chapter-1",
    revision: int = 3,
) -> str:
    start = source.index(selected)
    end = start + len(selected)

    def span(span_start: int, span_end: int) -> dict[str, object]:
        text = source[span_start:span_end]
        return {
            "start": span_start,
            "end": span_end,
            "text": text,
            "text_hash": _hash(text),
        }

    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "chapter_id": chapter_id,
            "base_revision": revision,
            "base_source_hash": _hash(source),
            "selection": span(start, end),
            "before_anchor": span(max(0, start - ANCHOR_CODEPOINTS), start),
            "after_anchor": span(
                end,
                min(len(source), end + ANCHOR_CODEPOINTS),
            ),
        },
        ensure_ascii=False,
    )


class _FakeLoop:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project
        self.calls: list[tuple[str, str, SelectionPatchCapture | None]] = []

    def generate_candidate(
        self,
        goal: str,
        chapter_id: str,
        *,
        selection_patch: SelectionPatchCapture | None = None,
    ) -> object:
        self.calls.append((goal, chapter_id, selection_patch))
        store = HarnessEventStore(HarnessEventRepository(self.project))
        run, _ = store.start_run(goal=goal, active_chapter_id=chapter_id)
        store.append(run.id, RunEventType.CONTEXT_COMPILATION_STARTED)
        store.append(run.id, RunEventType.CONTEXT_COMPILED)
        store.append(run.id, RunEventType.GENERATION_PACKAGE_READY)
        store.append(run.id, RunEventType.CHAPTER_STREAM_STARTED)
        store.append(run.id, RunEventType.CHAPTER_STREAM_COMPLETED)
        store.append(run.id, RunEventType.AUDIT_COMPLETED)
        store.append(run.id, RunEventType.CHANGESET_READY)
        store.append(run.id, RunEventType.APPROVAL_REQUESTED)
        store.transition(run.id, RunStage.WAITING_APPROVAL)
        return SimpleNamespace(
            run=run,
            draft=SimpleNamespace(text="真实 Harness 候选稿"),
            audit=SimpleNamespace(findings=()),
            approval=SimpleNamespace(
                request_id="approval-1",
                summary="候选稿替换章节(14 字)",
            ),
        )


def _project(tmp_path) -> tuple[ProjectRepository, str]:
    project = ProjectRepository.create(tmp_path / "project", "Harness QML")
    volume = project.list_volumes()[0]
    chapter = (
        ChapterRevisionService(project)
        .submit_creation(volume.id, "第一章", content="旧正文")
        .chapter
    )
    return project, chapter.id


def test_harness_agent_port_projects_persisted_run_facts(tmp_path) -> None:
    project, chapter_id = _project(tmp_path)
    loop = _FakeLoop(project)
    port = HarnessAgentPort(loop_factory=lambda bound: loop)
    port.bind_project(project)

    outcome = port.generate("续写当前章节", chapter_id)

    assert loop.calls == [("续写当前章节", chapter_id, None)]
    assert outcome.stage == RunStage.WAITING_APPROVAL.value
    assert outcome.draft_text == "真实 Harness 候选稿"
    assert outcome.approval_request_id == "approval-1"
    assert outcome.event_types[0] == RunEventType.RUN_CREATED.value
    assert outcome.event_types[-1] == RunEventType.APPROVAL_REQUESTED.value


def test_harness_agent_port_requires_real_project() -> None:
    port = HarnessAgentPort(loop_factory=lambda _project: object())

    try:
        port.generate("续写", "chapter")
    except RuntimeError as exc:
        assert str(exc) == "请先打开一个真实项目"
    else:
        raise AssertionError("missing project must fail closed")


def test_harness_agent_port_bounds_goal_before_project_access() -> None:
    port = HarnessAgentPort(loop_factory=lambda _project: object())

    try:
        port.generate("x" * 4001, "chapter")
    except ValueError as exc:
        assert str(exc) == "Agent 任务过长"
    else:
        raise AssertionError("oversized goal must fail closed")


def test_harness_agent_port_chat_receives_exact_current_manuscript(tmp_path) -> None:
    project, chapter_id = _project(tmp_path)

    class _ChatRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str, object]] = []

        def reply(
            self,
            message: str,
            current_chapter_id: str,
            current_manuscript: str,
            conversation_context: object,
        ) -> str:
            self.calls.append(
                (
                    message,
                    current_chapter_id,
                    current_manuscript,
                    conversation_context,
                )
            )
            return "基于当前正文的回答"

    runner = _ChatRunner()
    port = HarnessAgentPort(chat_runner_factory=lambda _project: runner)
    port.bind_project(project)

    answer = port.chat("概括当前章节", chapter_id, "旧正文", ())

    assert answer == "基于当前正文的回答"
    assert runner.calls == [("概括当前章节", chapter_id, "旧正文", ())]


def test_harness_agent_port_suppresses_raw_execution_error(tmp_path) -> None:
    project, chapter_id = _project(tmp_path)

    def failing_factory(_project: ProjectRepository) -> object:
        raise RuntimeError("secret-provider-payload")

    port = HarnessAgentPort(loop_factory=failing_factory)  # type: ignore[arg-type]
    port.bind_project(project)

    try:
        port.generate("生成", chapter_id)
    except RuntimeError as exc:
        assert str(exc) == "AI 任务执行失败，请检查模型配置或项目状态后重试"
        assert "secret-provider-payload" not in str(exc)
        assert exc.__cause__ is None
    else:
        raise AssertionError("raw model errors must not reach the UI")


def test_harness_agent_port_drives_real_generation_chain(tmp_path) -> None:
    project, chapter_id = _project(tmp_path)

    class _Gateway:
        def complete(self, *args: object, **kwargs: object) -> object:
            raise NotImplementedError

        def stream(
            self,
            purpose: TaskPurpose,
            messages: object,
            output_token_limit: int,
            **kwargs: object,
        ):
            yield LLMStreamEvent(StreamEventKind.TEXT, text="真实候选稿")
            yield LLMStreamEvent(StreamEventKind.COMPLETED)

    def loop_factory(bound: ProjectRepository) -> ChapterGenerationLoop:
        return ChapterGenerationLoop.for_project(
            bound,
            _Gateway(),  # type: ignore[arg-type]
            ModelRoleBinding(
                ModelRole.CHAPTER_DRAFT,
                TaskPurpose.PROSE_GENERATION,
                "provider",
                "model",
            ),
            budget=TokenBudget(4096, 512, 128),
            output_token_limit=512,
        )

    port = HarnessAgentPort(loop_factory=loop_factory)
    port.bind_project(project)

    outcome = port.generate("生成当前章节候选稿", chapter_id)

    assert outcome.stage == RunStage.WAITING_APPROVAL.value
    assert outcome.draft_text == "真实候选稿"
    assert RunEventType.CONTEXT_COMPILED.value in outcome.event_types
    assert RunEventType.CHAPTER_STREAM_COMPLETED.value in outcome.event_types
    assert RunEventType.APPROVAL_REQUESTED.value in outcome.event_types
    assert ChapterRepository(project).read_content(chapter_id) == "旧正文"


class _FakeCoordinator(QObject):
    status_changed = Signal(str, str)
    outcome_ready = Signal(str, object)
    chat_ready = Signal(str, str)
    agent_failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.bound_project: object | None = None
        self.started: list[tuple[str, str, str, SelectionPatchCapture | None]] = []
        self.chat_started: list[tuple[str, str, str, str]] = []
        self.resolutions: list[tuple[str, bool]] = []
        self.is_running = False

    def bind_project(self, project: object | None) -> None:
        self.bound_project = project

    def start(
        self,
        request_id: str,
        goal: str,
        chapter_id: str,
        selection_patch: SelectionPatchCapture | None = None,
    ) -> None:
        self.is_running = True
        self.started.append((request_id, goal, chapter_id, selection_patch))

    def start_chat(
        self,
        request_id: str,
        message: str,
        chapter_id: str,
        current_manuscript: str,
        conversation_context: object,
    ) -> None:
        self.is_running = True
        self.chat_started.append((request_id, message, chapter_id, current_manuscript))

    def resolve_approval(self, request_id: str, approved: bool) -> None:
        self.resolutions.append((request_id, approved))


def test_facade_projects_real_harness_outcome_into_timeline() -> None:
    coordinator = _FakeCoordinator()
    facade = MockNovelStudioFacade(agent_coordinator=coordinator, demo_mode=True)

    facade.startAgentTurn("续写当前章节")
    assert len(coordinator.started) == 1
    request_id, goal, chapter_id, selection_patch = coordinator.started[0]
    assert goal == "续写当前章节"
    assert chapter_id == "chapter-1"
    assert selection_patch is None

    coordinator.outcome_ready.emit(
        request_id,
        HarnessAgentOutcome(
            run_id="real-run",
            stage=RunStage.WAITING_APPROVAL.value,
            draft_text="真实候选稿",
            approval_request_id="approval-1",
            approval_summary="候选稿替换章节",
            audit_finding_count=0,
            event_types=(
                RunEventType.RUN_CREATED.value,
                RunEventType.APPROVAL_REQUESTED.value,
            ),
        ),
    )

    items = facade.property("agentTimeline").items()
    assert facade.property("agentBusy") is False
    assert {item.run_id for item in items} == {"real-run"}
    assert [item.kind for item in items] == [
        "user_text",
        "run_status",
        "text_diff",
    ]
    assert items[1].status == RunStage.WAITING_APPROVAL.value
    assert items[2].draft_text == "真实候选稿"

    facade.approveAgentItem(items[2].id)
    assert coordinator.resolutions == [("approval-1", True)]
    updated = facade.property("agentTimeline").items()
    assert updated[2].state == "APPLIED"
    assert updated[-1].kind == "assistant_text"
    assert "已经应用" in updated[-1].text


def test_real_harness_quick_action_passes_complete_selection_patch_for_diff() -> None:
    coordinator = _FakeCoordinator()
    facade = MockNovelStudioFacade(agent_coordinator=coordinator, demo_mode=True)
    selected = "清晨的雾港"
    source = str(facade.property("currentChapterBody"))
    payload = _selection_payload(source, selected)
    facade.setSelectionReferenceJson(payload)

    facade.startAgentTurn("润色")

    assert coordinator.started[0][3] == parse_selection_patch_capture(json.loads(payload))
    request_id = coordinator.started[0][0]
    coordinator.outcome_ready.emit(
        request_id,
        HarnessAgentOutcome(
            run_id="selection-run",
            stage=RunStage.WAITING_APPROVAL.value,
            draft_text="雾港的清晨",
            approval_request_id="approval-selection",
            approval_summary="候选稿替换选区",
            audit_finding_count=0,
            event_types=(RunEventType.APPROVAL_REQUESTED.value,),
        ),
    )

    diff = next(
        item for item in facade.property("agentTimeline").items() if item.kind == "text_diff"
    )
    assert diff.current_text == selected
    assert diff.draft_text == "雾港的清晨"


def test_selection_quick_actions_require_selection_but_chapter_draft_does_not() -> None:
    coordinator = _FakeCoordinator()
    facade = MockNovelStudioFacade(agent_coordinator=coordinator, demo_mode=True)

    for command in ("重写", "润色", "精简", "扩写"):
        facade.startAgentTurn(command)

    assert coordinator.started == []
    assert facade.property("agentTimeline").items()[-1].text == "请先选择要修改的正文"

    facade.startAgentTurn("生成章节草稿")
    assert len(coordinator.started) == 1
    assert coordinator.started[0][3] is None


def test_plain_assistant_chat_returns_bubbles_without_diff() -> None:
    coordinator = _FakeCoordinator()
    facade = MockNovelStudioFacade(agent_coordinator=coordinator, demo_mode=True)

    facade.startAssistantChat("你好")

    assert len(coordinator.chat_started) == 1
    request_id, message, chapter_id, manuscript = coordinator.chat_started[0]
    assert message == "你好"
    assert chapter_id == "chapter-1"
    assert manuscript == facade.property("currentChapterBody")

    coordinator.chat_ready.emit(request_id, "你好，我已经读取了当前章节。")

    items = facade.property("agentTimeline").items()
    assert [item.kind for item in items] == [
        "user_text",
        "run_status",
        "assistant_text",
    ]
    assert items[1].label == "回答完成"
    assert items[1].status == "COMPLETED"
    assert items[-1].text == "你好，我已经读取了当前章节。"
    assert all(item.kind not in {"text_diff", "confirmation"} for item in items)


def test_facade_real_harness_failure_is_sanitized() -> None:
    coordinator = _FakeCoordinator()
    facade = MockNovelStudioFacade(agent_coordinator=coordinator, demo_mode=True)

    facade.startAgentTurn("生成")
    request_id = coordinator.started[0][0]
    coordinator.agent_failed.emit(request_id, "AI 任务执行失败，请检查模型配置后重试")

    items = facade.property("agentTimeline").items()
    assert facade.property("agentBusy") is False
    assert items[-1].kind == "error"
    assert items[-1].text == "AI 任务执行失败，请检查模型配置后重试"


def test_facade_binds_open_project_and_rejects_dirty_editor(tmp_path) -> None:
    project, _chapter_id = _project(tmp_path)
    coordinator = _FakeCoordinator()
    facade = MockNovelStudioFacade(agent_coordinator=coordinator, demo_mode=True)

    assert facade.openProject(str(project.layout.root)) == ""
    assert isinstance(coordinator.bound_project, ProjectRepository)

    facade.editorTextChanged("未保存的正文")
    facade.startAgentTurn("生成")

    assert coordinator.started == []
    items = facade.property("agentTimeline").items()
    assert items[-1].kind == "error"
    assert items[-1].text == "请先保存当前章节，再启动 Harness"

    facade.closeProject()
    assert coordinator.bound_project is None


def test_project_binding_clears_old_agent_messages_and_distinguishes_no_chapter(
    tmp_path,
) -> None:
    coordinator = _FakeCoordinator()
    facade = MockNovelStudioFacade(agent_coordinator=coordinator)

    facade.startAgentTurn("生成")
    assert facade.property("agentTimeline").items()[-1].text == ("未打开项目，无法运行 Agent")

    assert facade.createProject(str(tmp_path), "空项目") == ""
    assert facade.property("agentTimeline").items() == ()

    facade.startAgentTurn("生成")
    assert facade.property("agentTimeline").items()[-1].text == ("当前项目还没有章节，请先新建章节")
    assert coordinator.started == []

    assert facade.createChapter("第一章", "第1章") == ""
    facade.startAgentTurn("生成")

    assert len(coordinator.started) == 1
    assert coordinator.started[0][2] == facade.property("currentChapterId")


def test_production_coordinator_runs_port_off_ui_thread(qapp, tmp_path) -> None:
    project, chapter_id = _project(tmp_path)
    loop = _FakeLoop(project)
    port = HarnessAgentPort(loop_factory=lambda bound: loop)
    port.bind_project(project)
    coordinator = HarnessAgentCoordinator(port)
    outcomes: list[HarnessAgentOutcome] = []
    coordinator.outcome_ready.connect(lambda _request, outcome: outcomes.append(outcome))

    coordinator.start("request-1", "续写", chapter_id)
    deadline = time.monotonic() + 5
    while coordinator.is_running and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.001)

    assert outcomes and outcomes[0].draft_text == "真实 Harness 候选稿"


def test_default_qml_registration_uses_real_harness_boundary(qapp) -> None:
    engine = QQmlApplicationEngine()
    facade, _theme = register_frontend_types(engine, demo_mode=True)

    facade.startAgentTurn("生成")
    deadline = time.monotonic() + 5
    while facade.property("agentBusy") and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.001)

    items = facade.property("agentTimeline").items()
    assert facade.property("agentBusy") is False
    assert items[-1].kind == "error"
    assert items[-1].text == "请先打开一个真实项目"
