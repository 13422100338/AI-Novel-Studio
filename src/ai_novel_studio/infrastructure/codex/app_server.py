"""Bounded JSON-RPC stdio transport for Codex app-server.

Protocol: https://learn.chatgpt.com/docs/app-server
No shell invocation, credential file access, or raw stderr is exposed to the UI.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
from pathlib import Path
from threading import Lock, Thread
from typing import TYPE_CHECKING, Any

from .writing_skill import session_skill_path

if TYPE_CHECKING:
    from ai_novel_studio.infrastructure.mcp.novel_server import NovelMcpEndpoint


class CodexConnectionError(RuntimeError):
    # Diagnostics for acceptance scripts; __str__ remains fixed UI copy.
    rpc_error: dict[str, Any] | None = None


MAX_RPC_FRAME_BYTES = 8_000_000


def encode_rpc_message(message: dict[str, object]) -> bytes:
    payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
    if len(payload) > MAX_RPC_FRAME_BYTES:
        raise ValueError("Codex 单次传输超过 8MB，未发送或截断；请减少可选资料或新建会话。")
    return payload


def resolve_codex_executable() -> str:
    executable = shutil.which("codex.exe") or shutil.which("codex")
    if executable:
        return executable
    # Explorer-launched apps do not inherit Codex desktop's injected PATH.
    # Inspect only the desktop app's known runtime directory, one level deep.
    local = os.environ.get("LOCALAPPDATA")
    if sys.platform == "win32" and local:
        root = Path(local) / "OpenAI" / "Codex" / "bin"
        try:
            if root.is_dir():
                candidates = [
                    folder / "codex.exe"
                    for folder in root.iterdir()
                    if folder.is_dir() and (folder / "codex.exe").is_file()
                ]
                if candidates:
                    return str(max(candidates, key=lambda path: path.stat().st_mtime).resolve())
        except OSError as error:
            raise CodexConnectionError("无法读取 Codex 安装目录，请检查目录权限") from error
    raise CodexConnectionError("没有找到 Codex，请安装 Codex 桌面版或 CLI 后重试")


CONVERSATION_CONFIG: dict[str, object] = {
    "features.shell_tool": False,
    "features.unified_exec": False,
    # Current Codex models route MCP/web tools through this bounded JS dispatcher.
    "features.code_mode_host": True,
    "features.apps": False,
    "features.plugins": False,
    "features.multi_agent": False,
    "features.browser_use": False,
    "features.computer_use": False,
    "features.in_app_browser": False,
    "features.image_generation": False,
    "features.memories": False,
    "tools.view_image": False,
    "web_search": "disabled",
    "project_doc_max_bytes": 0,
    "mcp_servers": {},
    "hooks": {},
    "features.hooks": False,
}


def rpc_config(flat: dict[str, object]) -> dict[str, Any]:
    """Thread RPC accepts nested config; only CLI -c understands dotted keys."""
    result: dict[str, Any] = {}
    for key, value in flat.items():
        target = result
        parts = key.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = dict(value) if isinstance(value, dict) else value
    return result


class CodexAppServer:
    def __init__(
        self,
        cwd: Path,
        command: list[str] | None = None,
        *,
        web_search: bool = False,
        novel_mcp: NovelMcpEndpoint | None = None,
    ) -> None:
        production = command is None
        self.session_config = dict(CONVERSATION_CONFIG)
        self.session_config["web_search"] = "live" if web_search else "disabled"
        if command is None:
            executable = resolve_codex_executable()
            command = [executable, "app-server", "--listen", "stdio://"]
            config = dict(CONVERSATION_CONFIG)
            config["web_search"] = "live" if web_search else "disabled"
            for key, value in config.items():
                command.extend(["-c", f"{key}={json.dumps(value)}"])
        self._write_lock = Lock()
        self._pending_lock = Lock()
        self._pending: dict[int, queue.Queue[Any]] = {}
        self._events: queue.Queue[Any] = queue.Queue(maxsize=4096)
        self._sequence = 0
        self._closed = False
        self._process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._reader = Thread(target=self._read, name="novel-codex-reader", daemon=True)
        self._reader.start()
        try:
            self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "ai_novel_studio",
                        "title": "AI Novel Studio",
                        "version": "0.7.0",
                    }
                },
            )
            self._write({"method": "initialized", "params": {}})
            if production:
                config = self.request("config/read", {}).get("config", {})
                servers = config.get("mcp_servers", {})
                if not isinstance(servers, dict):
                    raise CodexConnectionError("Codex MCP 配置信息无效")
                if any(not re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in servers):
                    raise CodexConnectionError("Codex MCP 配置名称不受当前接入支持")
                overrides = [f"mcp_servers.{name}.enabled=false" for name in servers]
                self.session_config.update(
                    {f"mcp_servers.{name}.enabled": False for name in servers}
                )
                if overrides or novel_mcp:
                    self.close()
                    if self._reader.is_alive():
                        raise CodexConnectionError("Codex 旧连接未能关闭")
                    self._closed = False
                    self._events = queue.Queue(maxsize=4096)
                    for override in overrides:
                        command.extend(["-c", override])
                    environment = None
                    if novel_mcp:
                        self.session_config.update(novel_mcp.config())
                        for key, value in novel_mcp.config().items():
                            command.extend(["-c", f"{key}={json.dumps(value)}"])
                        environment = {**os.environ, **novel_mcp.environment()}
                    self._process = subprocess.Popen(
                        command,
                        env=environment,
                        cwd=cwd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    self._reader = Thread(target=self._read, name="novel-codex-reader", daemon=True)
                    self._reader.start()
                    self.request(
                        "initialize",
                        {
                            "clientInfo": {
                                "name": "ai_novel_studio",
                                "title": "AI Novel Studio",
                                "version": "0.7.0",
                            }
                        },
                    )
                    self._write({"method": "initialized", "params": {}})
                statuses = self.request("mcpServerStatus/list", {})
                self.validate_tools(statuses, novel_mcp)
                # Coding skills can demand unavailable tools or misdescribe
                # image capability. Disable them in this writing session only.
                catalog = self.request("skills/list", {"cwds": [str(cwd)]})
                owned_skill = session_skill_path(cwd)
                disabled_skills: list[dict[str, object]] = []
                for entry in catalog.get("data", []):
                    for skill in entry.get("skills", []):
                        path = skill.get("path")
                        if isinstance(path, str):
                            folder = Path(path)
                            if folder.name.lower() == "skill.md":
                                folder = folder.parent
                            if folder.resolve() == owned_skill.parent.resolve():
                                continue
                            disabled_skills.append({"path": str(folder), "enabled": False})
                if owned_skill.is_file():
                    disabled_skills.append({"path": str(owned_skill.parent), "enabled": True})
                self.session_config["skills.config"] = disabled_skills
        except BaseException:
            self.close()
            raise

    @staticmethod
    def validate_tools(statuses: dict[str, Any], endpoint: NovelMcpEndpoint | None) -> None:
        data = statuses.get("data")
        if not isinstance(data, list) or statuses.get("nextCursor"):
            raise CodexConnectionError("Codex MCP 工具信息无效")
        found = False
        for server in data:
            if (
                not isinstance(server, dict)
                or server.get("resources")
                or server.get("resourceTemplates")
            ):
                raise CodexConnectionError("Codex 仍有额外 MCP 工具，创作会话未启动")
            tools = server.get("tools")
            if endpoint and server.get("name") == endpoint.server_name:
                if not isinstance(tools, dict) or any(
                    not isinstance(tool, dict) for tool in tools.values()
                ):
                    raise CodexConnectionError("小说 MCP 工具信息无效")
                names = {tool.get("name") for tool in tools.values()}
                if names != set(endpoint.tools):
                    raise CodexConnectionError("小说 MCP 连接失败或工具目录不匹配")
                found = True
            elif tools:
                raise CodexConnectionError("Codex 仍有额外 MCP 工具，创作会话未启动")
        if endpoint and not found:
            raise CodexConnectionError("小说 MCP 未连接，请重新打开项目")

    def _write(self, message: dict[str, object]) -> None:
        payload = encode_rpc_message(message)
        with self._write_lock:
            if self._closed or self._process.stdin is None:
                raise CodexConnectionError("Codex 连接已关闭")
            try:
                self._process.stdin.write(payload)
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise CodexConnectionError("Codex 连接中断") from exc

    def request(self, method: str, params: dict[str, object]) -> dict[str, Any]:
        with self._pending_lock:
            self._sequence += 1
            request_id = self._sequence
            result_queue: queue.Queue[Any] = queue.Queue(maxsize=1)
            self._pending[request_id] = result_queue
        try:
            self._write({"id": request_id, "method": method, "params": params})
            result = result_queue.get(timeout=45)
            if isinstance(result, Exception):
                raise result
            if not isinstance(result, dict) or "error" in result:
                error = CodexConnectionError("Codex 请求失败，请检查登录、用量或连接状态")
                if isinstance(result, dict) and isinstance(result.get("error"), dict):
                    error.rpc_error = result["error"]
                raise error
            value = result.get("result")
            if not isinstance(value, dict):
                raise CodexConnectionError("Codex 返回了无效结果")
            return value
        except queue.Empty as exc:
            raise CodexConnectionError("Codex 连接超时，请重试") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def notification(self, timeout: float) -> dict[str, Any]:
        try:
            event = self._events.get(timeout=timeout)
        except queue.Empty as exc:
            raise CodexConnectionError("Codex 回复超时，请停止后重试") from exc
        if isinstance(event, Exception):
            raise event
        return dict(event)

    def _read(self) -> None:
        error = CodexConnectionError("Codex 进程已退出或连接中断")
        try:
            assert self._process.stdout is not None
            while frame := self._process.stdout.readline(MAX_RPC_FRAME_BYTES + 1):
                if len(frame) > MAX_RPC_FRAME_BYTES:
                    raise CodexConnectionError("Codex 单条响应超过 8MB，无法完整载入；请新建会话。")
                message = json.loads(frame)
                if not isinstance(message, dict):
                    raise ValueError
                if "method" in message and "id" in message:
                    # Writing conversations never grant terminal or file-write permissions.
                    if message["method"] in {
                        "item/commandExecution/requestApproval",
                        "item/fileChange/requestApproval",
                    }:
                        self._write({"id": message["id"], "result": {"decision": "decline"}})
                    else:
                        self._write(
                            {
                                "id": message["id"],
                                "error": {
                                    "code": -32601,
                                    "message": "This client does not support this request",
                                },
                            }
                        )
                elif "id" in message:
                    with self._pending_lock:
                        target = self._pending.get(message["id"])
                        if target is not None and target.empty():
                            target.put_nowait(message)
                elif isinstance(message.get("method"), str):
                    self._events.put_nowait(message)
        except CodexConnectionError as exc:
            error = exc
        except (OSError, ValueError, TypeError, queue.Full):
            error = CodexConnectionError("Codex 协议或连接异常，请重新连接")
        finally:
            with self._pending_lock:
                for target in self._pending.values():
                    if target.empty():
                        target.put_nowait(error)
            try:
                self._events.put_nowait(error)
            except queue.Full:
                pass

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(self._process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        timeout=5,
                        check=False,
                    )
                else:
                    self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)
            self._reader.join(timeout=1)
            pipes = [self._process.stdin]
            # A descendant retaining stdout must not deadlock the UI's shutdown.
            if not self._reader.is_alive():
                pipes.append(self._process.stdout)
            for pipe in pipes:
                if pipe is not None:
                    pipe.close()
