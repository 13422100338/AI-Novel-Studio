from pathlib import Path
from threading import Event
from uuid import uuid4

from ai_novel_studio.ui_qml.bridge.codex_session_bridge import CodexSessionController
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.models.agent_timeline_model import AgentTimelineModel


class FakeSession:
    def __init__(self, *, saved=False, wait=False, error=False):
        self.has_saved_thread = saved
        self.wait = wait
        self.error = error
        self.started = Event()
        self.stopped = Event()
        self.closed = Event()
        self.steered = []

    def restore(self):
        return [("user_text", "旧问题"), ("assistant_text", "旧回答")]

    def send(self, message, callback, **kwargs):
        self.started.set()
        if kwargs.get("on_event"):
            kwargs["on_event"]("session/turnReady", {})
        if self.error:
            raise RuntimeError("secret-provider-payload")
        callback("item-1", "第一段")
        if self.wait:
            self.stopped.wait(5)
            return "interrupted"
        callback("item-1", "第一段，第二段")
        return "completed"

    def interrupt(self):
        self.stopped.set()

    def steer(self, text):
        self.steered.append(text)

    def close(self):
        self.stopped.set()
        self.closed.set()


def make_controller(session):
    model = AgentTimelineModel()
    controller = CodexSessionController(session_factory=lambda _project: session)
    controller.bind_model(model)
    controller.bind_project(str(uuid4()))
    return controller, model


def test_stream_updates_one_row_and_completes(qtbot):
    controller, model = make_controller(FakeSession())
    controller.start("讨论情节")
    qtbot.waitUntil(lambda: not controller.is_busy)
    assistants = [row for row in model.items() if row.kind == "assistant_text"]
    assert len(assistants) == 1
    assert assistants[0].text == "第一段，第二段"
    assert controller.status_text == "回复完成"
    assert not any(row.kind == "text_diff" for row in model.items())


def test_writer_progress_updates_one_card_and_preserves_candidate(qtbot):
    controller, model = make_controller(FakeSession())
    event = {
        "id": "writer-test",
        "status": "PREPARING",
        "model": "independent-writer",
        "message": "准备上下文",
        "word_count": 0,
        "target_words": 800,
        "draft_text": "",
    }
    controller._on_writer_event(controller._epoch, event)
    controller._on_writer_event(
        controller._epoch, {**event, "status": "GENERATING", "word_count": 120}
    )
    controller._on_writer_event(
        controller._epoch, {**event, "status": "COMPLETED", "draft_text": "候选正文"}
    )
    rows = [row for row in model.items() if row.kind == "writer_task"]
    assert len(rows) == 1 and rows[0].draft_text == "候选正文"
    assert rows[0].state == "COMPLETED" and not rows[0].busy


def test_many_chapter_reads_have_one_summary_and_no_duplicate_chapter_count(qtbot):
    controller, model = make_controller(FakeSession())
    for index in range(34):
        item = dict(
            type="mcpToolCall",
            id=f"read-{index}",
            tool="read_novel_chapter",
            arguments={"chapter_id": f"chapter-{index}"},
            status="inProgress",
        )
        controller._on_event(controller._epoch, "item/started", {"item": item})
        controller._on_event(
            controller._epoch, "item/completed", {"item": {**item, "status": "completed"}}
        )
        controller._on_event(
            controller._epoch, "item/completed", {"item": {**item, "status": "completed"}}
        )
    rows = [row for row in model.items() if row.kind == "tool_call"]
    assert len(rows) == 1
    assert "34 章" in rows[0].text
    assert not rows[0].busy


def test_bulk_read_summary_counts_actual_returned_chapters_and_new_turn_gets_new_summary(qtbot):
    controller, model = make_controller(FakeSession())
    item = dict(
        type="mcpToolCall",
        id="bulk-1",
        tool="read_novel_chapters",
        status="completed",
        result={
            "structuredContent": {"chapters": [{"chapter_id": f"chapter-{i}"} for i in range(8)]}
        },
    )
    controller._on_event(controller._epoch, "item/completed", {"item": item})
    first = next(row for row in model.items() if row.kind == "tool_call")
    assert "8 章" in first.text
    controller.start("第二个问题")
    qtbot.waitUntil(lambda: not controller.is_busy)
    controller._on_event(controller._epoch, "item/completed", {"item": {**item, "id": "bulk-2"}})
    assert len([row for row in model.items() if row.kind == "tool_call"]) == 2


def test_interrupted_read_summary_stops_showing_busy(qtbot):
    controller, model = make_controller(FakeSession())
    item = dict(
        type="mcpToolCall", id="read-pending", tool="read_novel_chapters", status="inProgress"
    )
    controller._on_event(controller._epoch, "item/started", {"item": item})
    controller._on_finished(controller._epoch, "interrupted")
    row = next(row for row in model.items() if row.kind == "tool_call")
    assert not row.busy and row.state == "CANCELLED"


def test_old_project_writer_events_are_ignored(qtbot):
    controller, model = make_controller(FakeSession())
    epoch = controller._epoch
    controller.bind_project(None)
    controller._on_writer_event(
        epoch, {"id": "old-writer", "status": "COMPLETED", "draft_text": "旧项目候选"}
    )
    assert model.rowCount() == 0


def test_stop_sends_interrupt_and_keeps_partial_text(qtbot):
    session = FakeSession(wait=True)
    controller, model = make_controller(session)
    controller.start("讨论情节")
    qtbot.waitUntil(lambda: session.started.is_set())
    controller.stop()
    qtbot.waitUntil(lambda: not controller.is_busy)
    assert session.stopped.is_set()
    assert controller.status_text == "已停止"
    assert any(row.text == "第一段" for row in model.items())


def test_running_chat_accepts_steer_without_starting_another_turn(qtbot):
    session = FakeSession(wait=True)
    controller, model = make_controller(session)
    controller.start("讨论剧情")
    qtbot.waitUntil(lambda: controller.can_steer)
    controller.steer("保留伏笔")
    qtbot.waitUntil(lambda: session.steered == ["保留伏笔"])
    qtbot.waitUntil(lambda: any(row.text == "追加要求：保留伏笔" for row in model.items()))
    controller.stop()
    qtbot.waitUntil(lambda: not controller.is_busy)
    assert not controller.can_steer


def test_attachment_validation_and_remove_leave_source_unchanged(qtbot, tmp_path: Path):
    controller, model = make_controller(FakeSession())
    text = tmp_path / "资料.md"
    text.write_text("作者材料", encoding="utf-8")
    controller.add_attachment(text)
    assert controller.attachments[0]["name"] == "资料.md"
    controller.remove_attachment(0)
    assert controller.attachments == []
    assert text.read_text(encoding="utf-8") == "作者材料"
    bad = tmp_path / "资料.pdf"
    bad.write_bytes(b"data")
    controller.add_attachment(bad)
    assert controller.attachments == []
    assert any(row.kind == "warning" for row in model.items())


def test_progress_events_update_cards_and_do_not_treat_total_tokens_as_context(qtbot):
    controller, model = make_controller(FakeSession())
    epoch = controller._epoch
    controller._on_event(
        epoch,
        "turn/plan/updated",
        {
            "plan": [{"step": "核对人物", "status": "inProgress"}],
        },
    )
    controller._on_event(
        epoch,
        "turn/plan/updated",
        {
            "plan": [{"step": "核对人物", "status": "completed"}],
        },
    )
    controller._on_event(
        epoch,
        "item/completed",
        {
            "item": {
                "type": "mcpToolCall",
                "id": "tool-1",
                "tool": "read_novel_chapter",
                "status": "completed",
            },
        },
    )
    controller._on_event(
        epoch,
        "thread/tokenUsage/updated",
        {
            "tokenUsage": {
                "last": {"inputTokens": 1234, "outputTokens": 56},
                "total": {"inputTokens": 900000},
                "modelContextWindow": 1000000,
            },
        },
    )
    assert len([row for row in model.items() if row.label == "创作计划"]) == 1
    assert any(row.text == "完成 · 核对人物" for row in model.items())
    assert "1,234" in controller.usage_text and "900,000" not in controller.usage_text
    controller._on_event(
        epoch, "thread/tokenUsage/updated", {"tokenUsage": {"last": {"inputTokens": "bad"}}}
    )


def test_restore_loads_previous_user_and_assistant_messages(qtbot):
    controller, model = make_controller(FakeSession(saved=True))
    qtbot.waitUntil(lambda: not controller.is_busy)
    assert [row.text for row in model.items()] == ["旧问题", "旧回答"]


def test_project_switch_discards_late_chunks(qtbot):
    session = FakeSession(wait=True)
    controller, model = make_controller(session)
    controller.start("旧项目")
    epoch = controller._epoch
    qtbot.waitUntil(lambda: session.started.is_set())
    controller.bind_project(None)
    controller._on_message(epoch, "old-item", "旧项目的迟到消息")
    qtbot.waitUntil(lambda: session.closed.is_set())
    assert model.items() == ()
    assert not controller.is_busy


def test_raw_errors_do_not_reach_the_ui(qtbot):
    controller, model = make_controller(FakeSession(error=True))
    controller.start("讨论")
    qtbot.waitUntil(lambda: not controller.is_busy)
    assert controller.status_text == "回复失败"
    assert "secret-provider-payload" not in str(model.items())


def test_facade_routes_chat_and_stop_to_codex(qtbot):
    session = FakeSession(wait=True)
    controller = CodexSessionController(session_factory=lambda _project: session)
    facade = MockNovelStudioFacade(codex_controller=controller)
    controller.bind_project(str(uuid4()))
    facade.startAssistantChat("讨论")
    qtbot.waitUntil(lambda: session.started.is_set())
    assert facade.agentBusy
    facade.stopAgentTurn()
    qtbot.waitUntil(lambda: not facade.agentBusy)
    assert session.stopped.is_set()


def test_empty_project_snapshot_does_not_expose_previous_editor_content(qtbot):
    controller = CodexSessionController(session_factory=lambda _: FakeSession())
    facade = MockNovelStudioFacade(codex_controller=controller)
    facade._body_text = "前一部小说的正文"
    facade._sync_codex_editor()
    assert controller._editor.chapter_id is None
    assert controller._editor.content == ""


def test_outline_context_has_one_compact_summary_per_turn(qtbot):
    controller, model = make_controller(FakeSession())
    summary = {
        "documents": 3,
        "characters": 102_345,
        "fingerprint": "a" * 64,
        "confirmedLinks": 8,
        "pendingLinks": 2,
        "estimatedTokens": 350_000,
        "contextLimit": 900_000,
    }
    controller._on_event(controller._epoch, "session/outlineContext", summary)
    controller._on_event(controller._epoch, "session/outlineContext", summary)
    rows = [row for row in model.items() if row.label == "本轮完整大纲"]
    assert len(rows) == 1
    assert "102,345" in rows[0].text and "350,000" in rows[0].text
    assert "8" in rows[0].text and "2" in rows[0].text


def test_outline_save_conflict_prevents_codex_send(tmp_path, qtbot):
    from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

    project = ProjectRepository.create(tmp_path / "novel", "发送保护")
    session = FakeSession()
    controller = CodexSessionController(session_factory=lambda _: session)
    facade = MockNovelStudioFacade(codex_controller=controller)
    assert facade.openProject(str(project.layout.root)) == ""
    outline = facade.property("outline")
    assert outline.newDocument("全书")
    outline.edit("未保存的新大纲")
    path = project.layout.root / "outlines" / (outline.state["currentId"] + ".md")
    path.write_bytes("外部修改".encode())
    facade.startAssistantChat("按最新大纲讨论")
    assert not session.started.is_set()
    assert outline.state["text"] == "未保存的新大纲"
    assert any("大纲" in row.text for row in controller._model.items() if row.kind == "warning")
    assert outline.previewDisk() and outline.applyPreview()
    facade.closeProject()


def test_real_session_wiring_flushes_outline_and_delivers_summary(tmp_path, qtbot):
    from ai_novel_studio.application.codex_session_service import CodexSessionService
    from ai_novel_studio.infrastructure.codex.session_index import CodexSessionIndex
    from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

    class Client:
        def __init__(self):
            self.inputs = []

        def request(self, method, params):
            if method == "account/read":
                return {"account": {"type": "chatgpt"}}
            if method == "config/read":
                return {"config": {"model_context_window": 1_000_000}}
            if method == "thread/start":
                return {"thread": {"id": "thread", "turns": []}, "sandbox": {"type": "readOnly"}}
            if method == "turn/start":
                self.inputs = params["input"]
                return {"turn": {"id": "turn"}}
            return {}

        def notification(self, timeout):
            return {
                "method": "turn/completed",
                "params": {"threadId": "thread", "turn": {"id": "turn", "status": "completed"}},
            }

        def close(self):
            pass

    project = ProjectRepository.create(tmp_path / "novel", "接线验证")
    client = Client()
    port = CodexSessionService(
        project.project.id,
        CodexSessionIndex(tmp_path / "sessions.json"),
        tmp_path / "codex",
        client_factory=lambda _: client,
    )
    controller = CodexSessionController(session_factory=lambda _: port)
    facade = MockNovelStudioFacade(codex_controller=controller)
    assert facade.openProject(str(project.layout.root)) == ""
    outline = facade.property("outline")
    assert outline.newDocument("全书")
    outline.edit("# 最新未自动保存的大纲\n完整尾部")
    facade.startAssistantChat("按大纲讨论")
    qtbot.waitUntil(lambda: not controller.is_busy)
    assert not outline.state["dirty"]
    assert any("# 最新未自动保存的大纲\n完整尾部" in p.get("text", "") for p in client.inputs)
    assert any(row.label == "本轮完整大纲" for row in controller._model.items())
    port.close()
    facade.closeProject()
