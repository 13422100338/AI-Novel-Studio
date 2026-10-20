import json

import pytest

from ai_novel_studio.application.codex_outline_context import CodexOutlineContext
from ai_novel_studio.application.codex_session_service import CodexSessionService
from ai_novel_studio.core.outline_links import chapter_markdown_link
from ai_novel_studio.infrastructure.codex.session_index import CodexSessionIndex
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.outline_link_repository import OutlineLinkRepository
from ai_novel_studio.infrastructure.storage.outline_repository import OutlineRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class OutlineClient:
    def __init__(self):
        self.calls = []
        self.events = []
        self.closed = False
        self.config = {"model_context_window": 1_000_000}
        self.turns = []
        self.compaction = False

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "config/read":
            return {"config": self.config}
        if method == "account/read":
            return {"account": {"type": "chatgpt"}}
        if method in {"thread/start", "thread/resume", "thread/fork"}:
            return {
                "thread": {"id": "owned-thread", "turns": self.turns},
                "sandbox": {"type": "readOnly"},
                "model": "fake-model",
            }
        if method == "thread/compact/start":
            self.events = [
                {
                    "method": "turn/started",
                    "params": {"threadId": "owned-thread", "turn": {"id": "compact"}},
                },
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": "owned-thread",
                        "turnId": "compact",
                        "item": {"type": "contextCompaction"},
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "owned-thread",
                        "turn": {"id": "compact", "status": "completed"},
                    },
                },
            ]
        if method == "turn/start":
            self.events = []
            if self.compaction:
                self.events.append(
                    {
                        "method": "item/started",
                        "params": {
                            "threadId": "owned-thread",
                            "turnId": "turn",
                            "item": {"type": "contextCompaction"},
                        },
                    }
                )
            self.events.extend(
                [
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": "owned-thread",
                            "turnId": "turn",
                            "item": {"type": "agentMessage", "id": "answer", "text": "讨论结果"},
                        },
                    },
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": "owned-thread",
                            "turn": {"id": "turn", "status": "completed"},
                        },
                    },
                ]
            )
            self.turns.append({"items": [{"type": "userMessage", "content": params["input"]}]})
            return {"turn": {"id": "turn"}}
        return {}

    def notification(self, timeout):
        return self.events.pop(0)

    def close(self):
        self.closed = True


@pytest.fixture
def workspace(tmp_path):
    project = ProjectRepository.create(tmp_path / "novel", "完整大纲验证")
    outlines = OutlineRepository(project)
    raw = "\ufeff# 全书\r\n" + "这是不能摘要或省略的剧情。\r\n" * 2100 + "终章唯一标记-END\r\n"
    first = outlines.create("全书总览", raw)
    second = outlines.create("第二部", "## 第二部\n25. 政变\n原始分卷末尾\n")
    client = OutlineClient()
    session = CodexSessionService(
        project.project.id,
        CodexSessionIndex(tmp_path / "sessions.json"),
        tmp_path / "codex",
        client_factory=lambda _: client,
    )
    session.bind_outline(CodexOutlineContext(project))
    yield project, outlines, first, second, raw, client, session
    session.close()


def turns(client):
    return [params for method, params in client.calls if method == "turn/start"]


def text_input(params):
    return "\n".join(p["text"] for p in params["input"] if p["type"] == "text")


def test_complete_raw_outline_reaches_each_real_turn_after_edit(workspace):
    project, outlines, first, second, raw, client, session = workspace
    assert len(raw) > 20_000
    events = []
    assert (
        session.send(
            "根据第25事件讨论", lambda *_: None, on_event=lambda m, p: events.append((m, p))
        )
        == "completed"
    )
    request = text_input(turns(client)[0])
    assert raw in request
    assert "## 第二部\n25. 政变\n原始分卷末尾\n" in request
    assert request.index(raw) < request.index("根据第25事件讨论")
    outlines.save(second.version.document_id, "更新分卷要求\n新末尾", expected_revision=1)
    session.send("下一轮", lambda *_: None)
    updated = text_input(turns(client)[1])
    assert raw in updated and "更新分卷要求\n新末尾" in updated
    assert "原始分卷末尾" not in updated
    summary = [p for m, p in events if m == "session/outlineContext"]
    assert len(summary) == 1 and summary[0]["documents"] == 2
    assert summary[0]["characters"] == len(raw) + len(second.content)
    assert raw not in json.dumps(summary, ensure_ascii=False)


@pytest.mark.parametrize("operation", ["resume", "new", "fork", "compact"])
def test_session_operations_always_reinject_current_outline(workspace, operation):
    project, outlines, first, second, raw, client, session = workspace
    session.send("第一轮", lambda *_: None)
    if operation == "compact":
        assert session.compact() == "compacted"
    elif operation == "resume":
        session.restore(thread_id="owned-thread")
    else:
        session.restore(**{operation: True})
    session.send("新的创作要求", lambda *_: None)
    assert raw in text_input(turns(client)[-1])
    assert "原始分卷末尾" in text_input(turns(client)[-1])


@pytest.mark.parametrize("window", [None, True, 10_000])
def test_unknown_or_insufficient_capacity_sends_no_turn(workspace, window):
    *_, client, session = workspace
    client.config["model_context_window"] = window
    with pytest.raises(ValueError, match="容量|预算"):
        session.send("创作", lambda *_: None)
    assert turns(client) == []


def test_external_outline_conflict_sends_no_stale_outline(workspace):
    project, outlines, first, second, raw, client, session = workspace
    path = project.layout.root / "outlines" / (first.version.document_id + ".md")
    path.write_text("尚未登记的外部改纲", encoding="utf-8")
    with pytest.raises(ValueError, match="大纲"):
        session.send("讨论", lambda *_: None)
    assert turns(client) == []


def test_only_confirmed_and_current_chapter_links_are_sent(workspace):
    project, outlines, first, second, raw, client, session = workspace
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id, "政治铺垫", "12", "不应自动送入的正式正文"
    )
    token = chapter_markdown_link(chapter.title, chapter.content_path)
    outlines.save(second.version.document_id, "## 政变\n" + token, expected_revision=1)
    links = OutlineLinkRepository(project)
    current = links.scan(second.version.document_id)
    links.confirm(
        second.version.document_id,
        (current.items[0].link.id,),
        expected_fingerprint=current.fingerprint,
    )
    session.send("参考事件链接", lambda *_: None)
    assert chapter.id in text_input(turns(client)[-1])
    assert "不应自动送入的正式正文" not in text_input(turns(client)[-1])
    manifest = [
        p["text"]
        for p in turns(client)[-1]["input"]
        if "CONFIRMED_OUTLINE_LINKS" in p.get("text", "")
    ]
    assert len(manifest) == 1 and chapter.id in manifest[0]
    outlines.save(first.version.document_id, raw + "新前提", expected_revision=1)
    session.send("再查链接", lambda *_: None)
    manifest = [
        p["text"]
        for p in turns(client)[-1]["input"]
        if "CONFIRMED_OUTLINE_LINKS" in p.get("text", "")
    ]
    assert chapter.id not in manifest[0]


def test_active_compaction_stops_before_post_compaction_output(workspace):
    *_, client, session = workspace
    client.compaction = True
    messages = []
    with pytest.raises(ValueError, match="压缩"):
        session.send("创作", lambda *args: messages.append(args))
    assert client.closed
    assert messages == []


def test_restore_does_not_dump_hidden_outline_into_chat(workspace):
    *_, raw, client, session = workspace
    session.send("作者实际问题", lambda *_: None)
    history = session.restore(thread_id="owned-thread")
    assert history == [("user_text", "作者实际问题")]
    assert raw not in str(history)


def test_no_outline_preserves_legacy_conversation_without_budget_config(workspace):
    *_, client, session = workspace
    standalone = CodexSessionService(
        session.project_id,
        session._index,
        session._cwd.parent,
        client_factory=lambda _: client,
    )
    client.config.clear()
    assert standalone.send("旧项目对话", lambda *_: None) == "completed"
    assert turns(client)[-1]["input"] == [{"type": "text", "text": "旧项目对话"}]


def test_text_attachment_and_running_steer_keep_the_frozen_complete_outline(workspace, tmp_path):
    project, outlines, first, second, raw, client, session = workspace
    attachment = tmp_path / "作者补充.md"
    attachment.write_text("附件里的限制", encoding="utf-8")

    def event(method, params):
        if method == "session/turnReady":
            outlines.save(second.version.document_id, "改纲应在下一轮生效", expected_revision=1)
            session.steer("保留悬念")

    session.send("展开场景", lambda *_: None, attachments=(attachment,), on_event=event)
    assert raw in text_input(turns(client)[0])
    assert "附件里的限制" in text_input(turns(client)[0])
    steer = next(p for m, p in client.calls if m == "turn/steer")
    assert raw in text_input(steer) and "原始分卷末尾" in text_input(steer)
    assert "改纲应在下一轮生效" not in text_input(steer)
    assert steer["expectedTurnId"] == "turn"
    session.send("下一轮", lambda *_: None)
    assert "改纲应在下一轮生效" in text_input(turns(client)[-1])


def test_history_is_included_in_budget_instead_of_silently_dropped(workspace):
    *_, client, session = workspace
    client.config["model_context_window"] = 220_000
    session.send("第一轮", lambda *_: None)
    with pytest.raises(ValueError, match="历史"):
        session.send("第二轮", lambda *_: None)
    assert len(turns(client)) == 1


def test_model_reported_smaller_window_cannot_be_overridden_by_config(workspace):
    *_, client, session = workspace
    session.send("第一轮", lambda *_: None)
    session._record_usage(
        {"tokenUsage": {"last": {"totalTokens": 100}, "modelContextWindow": 20_000}}
    )
    with pytest.raises(ValueError, match="预算"):
        session.send("新一轮", lambda *_: None)
    assert len(turns(client)) == 1


def test_broken_optional_link_index_does_not_replace_full_outline(workspace):
    project, outlines, first, second, raw, client, session = workspace
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id, "引用", "1", "正文"
    )
    token = chapter_markdown_link(chapter.title, chapter.content_path)
    outlines.save(second.version.document_id, token, expected_revision=1)
    OutlineLinkRepository(project).scan(second.version.document_id)
    with project.database.connect() as connection, connection:
        connection.execute("UPDATE outline_chapter_links SET reviews_json='{}'")
    events = []
    session.send("按大纲讨论", lambda *_: None, on_event=lambda m, p: events.append((m, p)))
    assert raw in text_input(turns(client)[0])
    assert next(p for m, p in events if m == "session/outlineContext")["pendingLinks"] == -1


def test_transport_cap_rejects_whole_outline_instead_of_truncating(workspace):
    project, outlines, first, second, raw, client, session = workspace
    outlines.save(first.version.document_id, "汉" * 2_700_000, expected_revision=1)
    client.config["model_context_window"] = 100_000_000
    with pytest.raises(ValueError, match="8MB"):
        session.send("讨论", lambda *_: None)
    assert turns(client) == []


def test_provider_context_limit_error_is_explicit_instead_of_login_error(workspace):
    *_, client, session = workspace
    original = client.request

    def request(method, params):
        result = original(method, params)
        if method == "turn/start":
            client.events = [
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "owned-thread",
                        "turn": {
                            "id": "turn",
                            "status": "failed",
                            "error": {"codexErrorInfo": "contextWindowExceeded"},
                        },
                    },
                }
            ]
        return result

    client.request = request
    with pytest.raises(ValueError, match="容量|预算"):
        session.send("讨论", lambda *_: None)
