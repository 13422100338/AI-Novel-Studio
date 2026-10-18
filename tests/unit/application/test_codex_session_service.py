from pathlib import Path
from uuid import uuid4

import pytest

from ai_novel_studio.application.codex_session_service import CodexSessionService
from ai_novel_studio.infrastructure.codex.preferences import CodexPreferences
from ai_novel_studio.infrastructure.codex.session_index import CodexSessionIndex


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.events: list[dict] = []
        self.closed = False

    def request(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        if method == "account/read":
            return {"account": {"type": "chatgpt"}}
        if method in {"thread/start", "thread/resume", "thread/fork"}:
            return {
                "thread": {"id": "thread-owned", "turns": []},
                "sandbox": {"type": "readOnly"},
                "instructionSources": [],
            }
        if method == "turn/start":
            self.events = [
                {
                    "method": "item/agentMessage/delta",
                    "params": {
                        "threadId": "other-project",
                        "turnId": "turn-1",
                        "itemId": "a",
                        "delta": "泄漏",
                    },
                },
                {
                    "method": "item/agentMessage/delta",
                    "params": {
                        "threadId": "thread-owned",
                        "turnId": "turn-1",
                        "itemId": "a",
                        "delta": "你好",
                    },
                },
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": "thread-owned",
                        "turnId": "turn-1",
                        "item": {"type": "agentMessage", "id": "a", "text": "你好，作者"},
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-owned",
                        "turn": {"id": "turn-1", "status": "completed"},
                    },
                },
            ]
            return {"turn": {"id": "turn-1"}}
        return {}

    def notification(self, timeout: float) -> dict:
        return self.events.pop(0)

    def close(self) -> None:
        self.closed = True


def service(tmp_path: Path, client: FakeClient, project_id: str) -> CodexSessionService:
    return CodexSessionService(
        project_id,
        CodexSessionIndex(tmp_path / "index.json"),
        tmp_path / "workspaces",
        client_factory=lambda _cwd: client,
    )


def test_stream_uses_owned_thread_and_authoritative_final_text(tmp_path: Path) -> None:
    client = FakeClient()
    session = service(tmp_path, client, str(uuid4()))
    updates: list[tuple[str, str]] = []
    assert session.send("你好", lambda item, text: updates.append((item, text))) == "completed"
    assert updates == [("a", "你好"), ("a", "你好，作者")]
    start = next(params for method, params in client.calls if method == "thread/start")
    assert start["sandbox"] == "read-only"
    assert start["approvalPolicy"] == "never"
    assert start["config"]["features"]["shell_tool"] is False
    assert start["config"]["mcp_servers"] == {}
    assert str(tmp_path / "workspaces" / session.project_id) == start["cwd"]


def test_native_skill_is_a_structured_turn_input_with_original_guards(tmp_path):
    from ai_novel_studio.application.novel_writing_commands import writing_request
    from ai_novel_studio.infrastructure.codex.writing_skill import writing_skill_input

    client = FakeClient()
    session = service(tmp_path, client, str(uuid4()))
    request = writing_request("/润色")[1]
    assert session.send(request, lambda *_: None) == "completed"
    turn = next(params for method, params in client.calls if method == "turn/start")
    assert turn["input"][0] == {"type": "text", "text": request}
    assert turn["input"][1] == writing_skill_input(request, session._cwd)
    start = next(params for method, params in client.calls if method == "thread/start")
    assert start["approvalPolicy"] == "never"
    assert start["config"]["features"]["shell_tool"] is False
    session.close()


def test_saved_thread_is_resumed_in_a_new_service(tmp_path: Path) -> None:
    project_id = str(uuid4())
    first = service(tmp_path, FakeClient(), project_id)
    first.send("第一轮", lambda *_: None)
    first.close()
    second_client = FakeClient()
    second = service(tmp_path, second_client, project_id)
    second.restore()
    assert "thread/resume" in [method for method, _ in second_client.calls]
    assert "thread/start" not in [method for method, _ in second_client.calls]


def test_failed_or_interrupted_turn_is_not_completed(tmp_path: Path) -> None:
    client = FakeClient()
    original = client.request

    def request(method: str, params: dict) -> dict:
        result = original(method, params)
        if method == "turn/start":
            client.events[-1]["params"]["turn"]["status"] = "interrupted"
        return result

    client.request = request  # type: ignore[method-assign]
    session = service(tmp_path, client, str(uuid4()))
    assert session.send("停止", lambda *_: None) == "interrupted"


def test_corrupt_session_index_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    path.write_text("not valid json", encoding="utf-8")
    with pytest.raises(ValueError):
        CodexSessionIndex(path).get(str(uuid4()))
    assert path.read_text(encoding="utf-8") == "not valid json"


def test_thread_identity_is_validated_before_saving(tmp_path: Path) -> None:
    index = CodexSessionIndex(tmp_path / "index.json")
    with pytest.raises(ValueError):
        index.put(str(uuid4()), "../untrusted")
    assert not index.path.exists()


def test_boolean_index_version_is_rejected_without_overwriting(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    content = '{"version": true, "threads": {}}'
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        CodexSessionIndex(path).put(str(uuid4()), "thread-owned")
    assert path.read_text(encoding="utf-8") == content


def test_stop_before_worker_starts_does_not_send_a_turn(tmp_path: Path) -> None:
    client = FakeClient()
    session = service(tmp_path, client, str(uuid4()))
    session.interrupt()
    assert session.send("尚未开始的请求", lambda *_: None) == "interrupted"
    assert client.calls == []


def test_unexpected_write_permissions_are_rejected_before_saving(tmp_path: Path) -> None:
    client = FakeClient()
    original = client.request

    def request(method: str, params: dict) -> dict:
        result = original(method, params)
        if method == "thread/start":
            result["sandbox"] = {"type": "workspaceWrite"}
        return result

    client.request = request  # type: ignore[method-assign]
    session = service(tmp_path, client, str(uuid4()))
    with pytest.raises(RuntimeError, match="只读"):
        session.send("你好", lambda *_: None)
    assert not (tmp_path / "index.json").exists()


def test_active_turn_stop_uses_matching_thread_and_turn(tmp_path: Path) -> None:
    client = FakeClient()
    session = service(tmp_path, client, str(uuid4()))
    session.send("停止", lambda *_: session.interrupt())
    stops = [params for method, params in client.calls if method == "turn/interrupt"]
    assert stops
    assert all(params == {"threadId": "thread-owned", "turnId": "turn-1"} for params in stops)


def test_selected_model_and_effort_are_sent_to_real_turn_parameters(tmp_path: Path) -> None:
    client = FakeClient()
    session = CodexSessionService(
        str(uuid4()),
        CodexSessionIndex(tmp_path / "index.json"),
        tmp_path / "workspaces",
        client_factory=lambda _root: client,
        preferences=lambda: CodexPreferences("chosen-model", "custom-effort", True),
    )
    session.send("模型选择验收", lambda *_: None)
    params = next(params for method, params in client.calls if method == "turn/start")
    assert params["model"] == "chosen-model"
    assert params["effort"] == "custom-effort"
    start = next(params for method, params in client.calls if method == "thread/start")
    assert start["config"]["web_search"] == "live"
    assert start["config"]["model_reasoning_effort"] == "custom-effort"


def test_new_and_fork_preserve_history_and_foreign_thread_is_rejected(tmp_path):
    client = FakeClient()
    original = client.request
    ids = iter(["thread-first", "thread-new", "thread-fork"])

    def request(method, params):
        result = original(method, params)
        if method in {"thread/start", "thread/fork"}:
            result["thread"]["id"] = next(ids)
        elif method == "thread/resume":
            result["thread"]["id"] = params["threadId"]
        elif method == "turn/start":
            for event in client.events:
                if event["params"]["threadId"] == "thread-owned":
                    event["params"]["threadId"] = params["threadId"]
        return result

    client.request = request
    session = service(tmp_path, client, str(uuid4()))
    session.restore()
    session.send("第一会话", lambda *_: None)
    session.restore(new=True)
    session.send("新会话", lambda *_: None)
    session.restore(fork=True)
    assert session.sessions == ["thread-first", "thread-new", "thread-fork"]
    fork = next(params for method, params in client.calls if method == "thread/fork")
    assert fork["threadId"] == "thread-new"
    session.restore(thread_id="thread-first")
    assert session.thread_id == "thread-first"
    count = len(client.calls)
    with pytest.raises(ValueError, match="当前小说"):
        session.restore(thread_id="other-project")
    assert len(client.calls) == count


def test_text_attachment_contents_are_sent_and_unsupported_files_never_start_turn(tmp_path):
    client = FakeClient()
    session = service(tmp_path, client, str(uuid4()))
    path = tmp_path / "资料.md"
    path.write_text("年代设定：1920年", encoding="utf-8")
    session.send("参考资料", lambda *_: None, attachments=(path,))
    inputs = next(params["input"] for method, params in client.calls if method == "turn/start")
    assert "年代设定：1920年" in inputs[0]["text"]
    other = tmp_path / "资料.pdf"
    other.write_bytes(b"data")
    count = sum(method == "turn/start" for method, _ in client.calls)
    with pytest.raises(ValueError, match="附件支持"):
        session.send("无效附件", lambda *_: None, attachments=(other,))
    assert sum(method == "turn/start" for method, _ in client.calls) == count


def test_compaction_waits_for_matching_item_and_completed_turn(tmp_path):
    client = FakeClient()
    original = client.request

    def request(method, params):
        if method == "thread/compact/start":
            client.events = [
                {
                    "method": "turn/started",
                    "params": {"threadId": "thread-owned", "turn": {"id": "compact-1"}},
                },
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-owned",
                        "turn": {"id": "stale-turn", "status": "completed"},
                    },
                },
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": "thread-owned",
                        "turnId": "compact-1",
                        "item": {"type": "contextCompaction"},
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-owned",
                        "turn": {"id": "compact-1", "status": "completed"},
                    },
                },
            ]
            return {}
        return original(method, params)

    client.request = request
    session = service(tmp_path, client, str(uuid4()))
    session.send("先形成会话", lambda *_: None)
    assert session.compact() == "compacted"


def test_empty_thread_is_not_saved_as_an_unresumable_history_entry(tmp_path):
    client = FakeClient()
    session = service(tmp_path, client, str(uuid4()))
    session.restore(new=True)
    assert not session.has_saved_thread
    assert session.sessions == []
    assert not session.can_manage_current
    with pytest.raises(ValueError, match="分支"):
        session.restore(fork=True)


def test_cancel_during_connection_does_not_cancel_the_next_request(tmp_path):
    client = FakeClient()
    session = service(tmp_path, client, str(uuid4()))
    original = client.request

    def request(method, params):
        if method == "account/read":
            session.interrupt()
        return original(method, params)

    client.request = request
    assert session.send("连接期间取消", lambda *_: None) == "interrupted"
    assert not any(method == "turn/start" for method, _ in client.calls)
    client.request = original
    assert session.send("下一次正常请求", lambda *_: None) == "completed"


def test_running_steer_uses_expected_turn_and_tool_events_are_project_filtered(tmp_path):
    client = FakeClient()
    session = service(tmp_path, client, str(uuid4()))
    events = []
    session.send(
        "讨论",
        lambda *_: None,
        on_event=lambda method, params: (
            events.append(method),
            session.steer("保留悬念") if method == "session/turnReady" else None,
        ),
    )
    steer = next(params for method, params in client.calls if method == "turn/steer")
    assert steer["expectedTurnId"] == "turn-1"
    assert steer["threadId"] == "thread-owned"
    assert steer["input"][0]["text"] == "保留悬念"
    assert events.count("item/agentMessage/delta") == 1
