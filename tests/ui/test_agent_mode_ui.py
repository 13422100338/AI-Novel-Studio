from ai_novel_studio.application.agent_loop_service import AgentLoopResult
from ai_novel_studio.domain.agent import (
    AgentRunStatus,
    AgentToolCallStatus,
    AgentToolName,
)
from ai_novel_studio.infrastructure.llm import LLMMessage
from ai_novel_studio.ui.main_window import MainWindow
from ai_novel_studio.ui.pages.agent_trace_window import AgentTraceWindow


class FakeCoordinator:
    def __init__(self) -> None:
        self.chat_calls = []
        self.chat_chunk = _Signal()
        self.chat_finished = _Signal()
        self.requirement_ready = _Signal()
        self.brief_ready = _Signal()
        self.audit_ready = _Signal()
        self.task_failed = _Signal()
        self.usage_changed = _Signal()

    def start_chat(self, conversation, manuscript, limit):  # type: ignore[no-untyped-def]
        self.chat_calls.append((conversation, manuscript, limit))


class _Signal:
    def connect(self, _callback):  # type: ignore[no-untyped-def]
        return None


class FakeRuntime:
    def __init__(self) -> None:
        self.coordinator = FakeCoordinator()
        self.settings_controller = None


class FakeAgentRuntime:
    def __init__(self) -> None:
        self.calls = []

    def discuss_plot_with_tools(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return AgentLoopResult("run-1", AgentRunStatus.COMPLETED, "Agent 回答")


def test_coordinator_only_runtime_keeps_memory_build_available_offline(qtbot):  # type: ignore[no-untyped-def]
    window = MainWindow(model_runtime=FakeRuntime())
    qtbot.addWidget(window)

    assert window.manuscript_memory_build_service.analyzer is None


def test_agent_mode_toggle_defaults_off(qtbot):  # type: ignore[no-untyped-def]
    window = MainWindow(model_runtime=FakeRuntime())
    qtbot.addWidget(window)

    assert not window.plot_chat_panel.agent_mode_enabled()
    assert window.plot_chat_panel.agent_mode_toggle.text() == "工具检索"
    assert window.plot_chat_panel.agent_trace_button.text() == "证据追踪"
    assert window.plot_chat_panel.agent_trace_button.accessibleName() == "查看证据追踪"


def test_normal_plot_chat_still_uses_existing_coordinator(qtbot):  # type: ignore[no-untyped-def]
    runtime = FakeRuntime()
    window = MainWindow(model_runtime=runtime)
    qtbot.addWidget(window)

    window.plot_chat_panel.composer.setPlainText("普通讨论")
    window.plot_chat_panel.send_button.click()

    assert runtime.coordinator.chat_calls


def test_agent_mode_sends_current_text_and_requirement_to_agent_runtime(qtbot):  # type: ignore[no-untyped-def]
    runtime = FakeRuntime()
    agent_runtime = FakeAgentRuntime()
    window = MainWindow(model_runtime=runtime, agent_runtime=agent_runtime)
    qtbot.addWidget(window)
    window.plot_chat_panel.agent_mode_toggle.setChecked(True)
    window.manuscript_panel.editor.setPlainText("当前正文")
    window.manuscript_panel.chapter_requirement.setPlainText("当前章要求")

    window.plot_chat_panel.composer.setPlainText("Agent 讨论")
    window.plot_chat_panel.send_button.click()

    assert not runtime.coordinator.chat_calls
    assert agent_runtime.calls[0]["current_manuscript"] == "当前正文"
    assert agent_runtime.calls[0]["chapter_requirement"] == "当前章要求"
    assert window.plot_chat_panel.message_bubbles[-1].text() == "Agent 回答"


def test_trace_window_displays_turns_tool_calls_and_omissions(qtbot):  # type: ignore[no-untyped-def]
    run = AgentLoopResult("run-1", AgentRunStatus.COMPLETED, "done")
    turns = (LLMMessage("user", "问题"), LLMMessage("tool", "工具结果"),)
    tool_calls = (
        {
            "tool_name": AgentToolName.SEARCH_MEMORY.value,
            "status": AgentToolCallStatus.EXECUTED.value,
            "result_chars": 20,
            "omitted": "truncated",
        },
    )

    window = AgentTraceWindow(run, turns, tool_calls)
    qtbot.addWidget(window)

    assert window.windowTitle() == "证据追踪"
    assert window.turn_table.rowCount() == 2
    assert window.tool_table.rowCount() == 1
    assert "COMPLETED" in window.status_label.text()
