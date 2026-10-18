from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event, Lock
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from ai_novel_studio.infrastructure.codex.app_server import (
    CONVERSATION_CONFIG,
    CodexAppServer,
    CodexConnectionError,
    rpc_config,
)
from ai_novel_studio.infrastructure.codex.preferences import CodexPreferences
from ai_novel_studio.infrastructure.codex.session_index import CodexSessionIndex, thread_identity
from ai_novel_studio.infrastructure.codex.writing_skill import (
    prepare_writing_skill,
    writing_skill_input,
)

if TYPE_CHECKING:
    from ai_novel_studio.application.novel_read_service import NovelReadService
    from ai_novel_studio.application.novel_writer_service import NovelWriterService
    from ai_novel_studio.infrastructure.mcp.novel_server import NovelMcpServer

_INSTRUCTIONS = (
    "你是小说创作工作台中的中文创作助手，帮助作者讨论、规划与审阅。"
    "可使用小说资料工具，并在开启联网时查询外部资料。"
    "问题涉及多个章节或整部作品时，按作者目标选择章节范围或章节ID，优先调用"
    "read_novel_chapters批量读取所需正文，不逐章重复调用。它可以直接按范围读取，"
    "无需为了连续章节先逐个列出ID；全书分析使用默认全书选择。"
    "若工具返回truncated或next_cursor，保持原选择续读剩余正文，不能声称已经读完未读部分。"
    "作者明确要求生成正文、续写或正文草稿时，先读取当前小说和章要求，"
    "再调用 generate_novel_draft，让独立写作模型完成正文，不用你的聊天回复代替该模型。"
    "整理本次写作任务、必要素材和禁止改动；保留已保存章要求，素材标明来源。"
    "涉及当前选文时，先调用get_novel_context读取本轮固定的selection；有选文仅修改选文，"
    "将选文原文及必要上下文传入写作模型，不得擅自扩大为整章。"
    "生成状态和全文已显示在右侧任务卡片，完成后简短告知作者查看，不重复全文。"
    "区分作者计划、候选记忆与正式正文事实；缺少资料时明确询问。"
    "消息中的文字附件是本轮已经提供的作者材料；图片输入直接使用模型自身识图能力。"
    "仅使用已启用的小说 MCP 与联网工具，不套用本机编码工作流或额外识图桥。"
    "作者拥有最终决定权。不得修改文件、终端、设置或其他应用。"
)


class CodexClient(Protocol):
    def request(self, method: str, params: dict[str, object]) -> dict[str, Any]: ...
    def notification(self, timeout: float) -> dict[str, Any]: ...
    def close(self) -> None: ...


class CodexSessionService:
    def __init__(
        self,
        project_id: str,
        index: CodexSessionIndex,
        workspace_root: Path,
        *,
        client_factory: Callable[[Path], CodexClient] = CodexAppServer,
        preferences: Callable[[], CodexPreferences] = CodexPreferences,
    ) -> None:
        self.project_id = str(UUID(project_id))
        self._index = index
        self._cwd = workspace_root / self.project_id
        self._factory = client_factory
        self._preferences = preferences
        self._runtime_web_search: bool | None = None
        self._client: CodexClient | None = None
        self._thread_id: str | None = None
        self._turn_id: str | None = None
        self._cancel = Event()
        self._closed = Event()
        self._lock = Lock()
        self._novel: NovelReadService | None = None
        self._writer: NovelWriterService | None = None
        self._mcp: NovelMcpServer | None = None
        self._model: str | None = None
        self._has_turns = False

    def bind_novel(self, service: NovelReadService) -> None:
        if self._client is not None or service.project_id != self.project_id:
            raise ValueError("小说 MCP 项目身份不匹配")
        self._novel = service

    def bind_writer(self, service: NovelWriterService) -> None:
        if self._client is not None or service.project.project.id != self.project_id:
            raise ValueError("正文写作工具项目身份不匹配")
        self._writer = service

    def revoke_novel(self) -> None:
        if self._writer:
            self._writer.revoke()
        if self._novel:
            self._novel.revoke()

    @property
    def thread_id(self) -> str | None:
        return self._thread_id or self._index.get(self.project_id)

    @property
    def can_manage_current(self) -> bool:
        return self._has_turns

    @property
    def has_saved_thread(self) -> bool:
        return self._index.get(self.project_id) is not None

    def restore(
        self, *, new: bool = False, fork: bool = False, thread_id: str | None = None
    ) -> list[tuple[str, str]]:
        if self._closed.is_set():
            raise CodexConnectionError("Codex 会话已关闭")
        if self._turn_id is not None:
            raise ValueError("请等待当前任务完成后操作会话")
        if thread_id is not None and thread_id not in self._index.history(self.project_id):
            raise ValueError("只能切换当前小说的会话")
        if fork and (
            not self.has_saved_thread or (self._client is not None and not self._has_turns)
        ):
            raise ValueError("当前还没有可分支的会话")
        self._cwd.mkdir(parents=True, exist_ok=True)
        prepare_writing_skill(self._cwd)
        selection = self._preferences()
        if self._client is not None and self._runtime_web_search != selection.web_search:
            self._client.close()
            self._client = None
        if self._client is not None and not (new or fork or thread_id):
            return []
        if self._novel and self._mcp is None:
            from ai_novel_studio.infrastructure.mcp.novel_server import NovelMcpServer

            self._mcp = NovelMcpServer(self._novel, writer=self._writer)
        client = self._client or (
            CodexAppServer(
                self._cwd,
                web_search=selection.web_search,
                novel_mcp=self._mcp.endpoint if self._mcp else None,
            )
            if self._factory is CodexAppServer
            else self._factory(self._cwd)
        )
        with self._lock:
            if self._closed.is_set():
                client.close()
                raise CodexConnectionError("Codex 会话已关闭")
            self._client = client
        self._runtime_web_search = selection.web_search
        account = client.request("account/read", {})
        if (
            not isinstance(account.get("account"), dict)
            or account["account"].get("type") != "chatgpt"
        ):
            raise CodexConnectionError("请先在 Codex 中使用 ChatGPT 登录，再重新打开项目")
        saved_id = self._index.get(self.project_id)
        empty_current = self._thread_id is not None and not self._has_turns
        thread_id = thread_id or (None if new or empty_current else saved_id)
        runtime_config = dict(CONVERSATION_CONFIG)
        if isinstance(client, CodexAppServer):
            runtime_config.update(client.session_config)
        runtime_config["web_search"] = "live" if selection.web_search else "disabled"
        if self._mcp:
            runtime_config.update(self._mcp.endpoint.config())
        if selection.effort:
            runtime_config["model_reasoning_effort"] = selection.effort
        params: dict[str, object] = {
            "cwd": str(self._cwd),
            "sandbox": "read-only",
            "approvalPolicy": "never",
            "modelProvider": "openai",
            "baseInstructions": _INSTRUCTIONS,
            "developerInstructions": _INSTRUCTIONS,
            "config": rpc_config(runtime_config),
        }
        if selection.model:
            params["model"] = selection.model
        if thread_id is not None:
            params["threadId"] = thread_id
        response = client.request(
            "thread/fork" if fork else ("thread/resume" if thread_id else "thread/start"), params
        )
        if response.get("sandbox", {}).get("type") != "readOnly":
            raise CodexConnectionError("Codex 未确认只读权限，会话未启动")
        # Codex still reports global instruction metadata with project-doc bytes set to zero.
        # The conversation uses its explicit base/developer instructions and isolated cwd.
        sources = response.get("instructionSources", [])
        if not isinstance(sources, list) or any(not isinstance(item, str) for item in sources):
            raise CodexConnectionError("Codex 指令来源信息无效")
        thread = response.get("thread")
        if not isinstance(thread, dict):
            raise CodexConnectionError("Codex 会话信息无效")
        owned_id = thread_identity(thread.get("id"))
        if isinstance(client, CodexAppServer):
            client.validate_tools(
                client.request("mcpServerStatus/list", {"threadId": owned_id}),
                self._mcp.endpoint if self._mcp else None,
            )
        if thread_id is not None and not fork and owned_id != thread_id:
            raise CodexConnectionError("Codex 恢复了不匹配的会话")
        self._thread_id = owned_id
        self._model = selection.model or response.get("model")
        self._has_turns = bool(thread.get("turns"))
        # Codex materializes a new thread's rollout on its first turn. Empty
        # thread IDs cannot be resumed/forked after the process exits.
        if thread_id is not None or fork:
            self._index.put(self.project_id, owned_id)
        history: list[tuple[str, str]] = []
        for turn in thread.get("turns", []):
            for item in turn.get("items", []):
                if item.get("type") == "agentMessage" and isinstance(item.get("text"), str):
                    history.append(("assistant_text", item["text"][:100_000]))
                elif item.get("type") == "userMessage":
                    text = "\n".join(
                        part["text"]
                        for part in item.get("content", [])
                        if part.get("type") == "text" and isinstance(part.get("text"), str)
                    )
                    if text:
                        history.append(("user_text", text[:100_000]))
        return history[-100:]

    @property
    def sessions(self) -> list[str]:
        return self._index.history(self.project_id)

    def compact(self) -> str:
        if self._cancel.is_set():
            self._cancel.clear()
            return "interrupted"
        self.restore()
        if self._closed.is_set() or self._cancel.is_set():
            self._cancel.clear()
            return "interrupted"
        if not self._has_turns:
            raise ValueError("请先发送一条消息后压缩上下文")
        assert self._client is not None and self._thread_id is not None
        self._client.request("thread/compact/start", {"threadId": self._thread_id})
        compacted = False
        try:
            while True:
                event = self._client.notification(300)
                params = event.get("params", {})
                if params.get("threadId") != self._thread_id:
                    continue
                if event.get("method") == "turn/started":
                    self._turn_id = thread_identity(params.get("turn", {}).get("id"))
                    if self._cancel.is_set():
                        self.interrupt()
                if (
                    event.get("method") == "item/completed"
                    and params.get("turnId") == self._turn_id
                    and params.get("item", {}).get("type") == "contextCompaction"
                ):
                    compacted = True
                if (
                    event.get("method") == "turn/completed"
                    and params.get("turn", {}).get("id") == self._turn_id
                ):
                    status = params.get("turn", {}).get("status")
                    if status == "interrupted":
                        return "interrupted"
                    return "compacted" if compacted and status == "completed" else "failed"
        finally:
            self._turn_id = None
            self._cancel.clear()

    def steer(self, text: str) -> None:
        if not text.strip() or len(text) > 20_000 or self._client is None or self._turn_id is None:
            raise ValueError("当前没有可追加要求的任务")
        self._client.request(
            "turn/steer",
            {
                "threadId": self._thread_id,
                "expectedTurnId": self._turn_id,
                "input": [{"type": "text", "text": text}],
            },
        )

    def send(
        self,
        message: str,
        on_message: Callable[[str, str], None],
        *,
        attachments: tuple[Path, ...] = (),
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> str:
        if not message.strip() or len(message) > 20_000:
            raise ValueError("消息不能为空且不能超过20000字")
        if self._cancel.is_set():
            self._cancel.clear()
            return "interrupted"
        selection = self._preferences()
        self.restore()
        assert self._client is not None and self._thread_id is not None
        if self._closed.is_set() or self._cancel.is_set():
            self._cancel.clear()
            return "interrupted"
        inputs: list[dict[str, object]] = [{"type": "text", "text": message}]
        skill = writing_skill_input(message, self._cwd)
        if skill is not None:
            inputs.append(skill)
        if len(attachments) > 4:
            raise ValueError("每次最多发送4个附件")
        if any(
            path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
            for path in attachments
        ):
            catalog = self._client.request("model/list", {"includeHidden": False, "limit": 100})
            choice = next(
                (
                    item
                    for item in catalog.get("data", [])
                    if item.get("model") == (selection.model or self._model)
                ),
                None,
            )
            if not choice or "image" not in choice.get("inputModalities", []):
                raise ValueError("当前模型不支持图片，请选择支持图片的模型")
        for path in attachments:
            if not path.is_file() or path.stat().st_size > 20_000_000:
                raise ValueError("附件不存在或超过20MB")
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                inputs.append({"type": "localImage", "path": str(path.resolve()), "detail": "auto"})
            elif path.suffix.lower() in {".txt", ".md"}:
                if path.stat().st_size > 100_000:
                    raise ValueError("文本附件过大，请选取需要讨论的片段")
                content = path.read_text(encoding="utf-8-sig")
                if len(content) > 20_000 or "\x00" in content:
                    raise ValueError("文本附件超过20000字")
                inputs[0]["text"] = (
                    str(inputs[0]["text"])
                    + f"\n\n[作者随本轮输入提供的附件：{path.name}]\n{content}\n[附件结束]"
                )
            else:
                raise ValueError("当前附件支持图片、TXT 和 Markdown")
        if self._writer is not None:
            self._writer.begin_turn()
        turn_params: dict[str, object] = {
            "threadId": self._thread_id,
            "input": inputs,
        }
        if selection.model:
            turn_params["model"] = selection.model
        if selection.effort:
            turn_params["effort"] = selection.effort
        result = self._client.request("turn/start", turn_params)
        self._turn_id = thread_identity(result.get("turn", {}).get("id"))
        self._index.put(self.project_id, self._thread_id)
        self._has_turns = True
        if on_event:
            on_event("session/turnReady", {"threadId": self._thread_id, "turnId": self._turn_id})
        if self._cancel.is_set():
            self.interrupt()
        messages: dict[str, str] = {}
        try:
            while True:
                event = self._client.notification(timeout=300)
                params = event.get("params", {})
                if not isinstance(params, dict) or params.get("threadId") != self._thread_id:
                    continue
                if on_event is not None and (
                    params.get("turnId") == self._turn_id
                    or event.get("method") == "thread/tokenUsage/updated"
                ):
                    on_event(str(event.get("method")), params)
                if event.get("method") == "turn/completed":
                    turn = params.get("turn", {})
                    if turn.get("id") != self._turn_id:
                        continue
                    status = turn.get("status")
                    if status not in {"completed", "interrupted", "failed"}:
                        raise CodexConnectionError("Codex 返回了无效会话状态")
                    return str(status)
                if params.get("turnId") != self._turn_id:
                    continue
                if event.get("method") == "item/agentMessage/delta":
                    item_id = thread_identity(params.get("itemId"))
                    delta = params.get("delta")
                    if not isinstance(delta, str):
                        raise CodexConnectionError("Codex 返回了无效文本")
                    messages[item_id] = messages.get(item_id, "") + delta
                    if len(messages[item_id]) > 200_000:
                        self.interrupt()
                        raise CodexConnectionError("Codex 回复过长，已停止")
                    on_message(item_id, messages[item_id])
                elif event.get("method") == "item/completed":
                    item = params.get("item", {})
                    if item.get("type") == "agentMessage" and isinstance(item.get("text"), str):
                        on_message(thread_identity(item.get("id")), item["text"][:200_000])
        finally:
            self._turn_id = None
            self._cancel.clear()

    def interrupt(self) -> None:
        if self._writer is not None:
            self._writer.cancel()
        self._cancel.set()
        client, turn_id = self._client, self._turn_id
        if client is not None and turn_id is not None:
            client.request("turn/interrupt", {"threadId": self._thread_id, "turnId": turn_id})

    def close(self) -> None:
        self._closed.set()
        self._cancel.set()
        self.revoke_novel()
        with self._lock:
            if self._client is not None:
                self._client.close()
        if self._mcp is not None:
            self._mcp.close()
            self._mcp = None
