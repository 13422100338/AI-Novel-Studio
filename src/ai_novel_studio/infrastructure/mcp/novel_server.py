"""Authenticated loopback MCP. A fresh server belongs to one open novel."""

from __future__ import annotations

import asyncio
import secrets
import socket
from dataclasses import dataclass, field
from threading import Thread
from time import monotonic, sleep
from typing import Annotated, Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.types import ASGIApp, Receive, Scope, Send

from ai_novel_studio.application.novel_read_service import (
    LEGACY_NOVEL_TOOLS,
    NOVEL_TOOLS,
    NovelReadService,
)
from ai_novel_studio.application.novel_writer_service import WRITER_TOOL, NovelWriterService
from ai_novel_studio.application.outline_writer_input import OutlineRequiredError


@dataclass(frozen=True)
class NovelMcpEndpoint:
    url: str
    token: str = field(repr=False)
    server_name: str = "novel_workspace"
    tools: tuple[str, ...] = NOVEL_TOOLS

    def config(self) -> dict[str, object]:
        prefix = f"mcp_servers.{self.server_name}"
        config: dict[str, object] = {
            f"{prefix}.url": self.url,
            f"{prefix}.enabled": True,
            f"{prefix}.env_http_headers.Authorization": "AI_NOVEL_MCP_AUTH",
            f"{prefix}.enabled_tools": list(self.tools),
        }
        if "read_novel_chapters" in self.tools:
            config[f"{prefix}.tools.read_novel_chapters.output_token_limit"] = 200_000
        if WRITER_TOOL in self.tools:
            # The author explicitly requested chat-driven drafting. Approval is
            # scoped to this bounded candidate-only tool, never to file or shell tools.
            config[f"{prefix}.tools.{WRITER_TOOL}.approval_mode"] = "approve"
            config[f"{prefix}.tool_timeout_sec"] = 300
        return config

    def environment(self) -> dict[str, str]:
        return {"AI_NOVEL_MCP_AUTH": "Bearer " + self.token}


class _LoopbackAuth:
    def __init__(self, app: ASGIApp, endpoint: NovelMcpEndpoint, host: str) -> None:
        self.app, self.endpoint, self.host = app, endpoint, host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        expected = ("Bearer " + self.endpoint.token).encode()
        status = 0
        if not secrets.compare_digest(headers.get(b"authorization", b""), expected):
            status = 401
        elif headers.get(b"host", b"").decode("latin-1") != self.host:
            status = 403
        elif b"origin" in headers and headers[b"origin"].decode("latin-1") != f"http://{self.host}":
            status = 403
        body = b""
        if not status:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body += message.get("body", b"")
                if len(body) > 65_536:
                    status = 413
                    break
                if not message.get("more_body"):
                    break
        if status:
            await send({"type": "http.response.start", "status": status, "headers": []})
            await send({"type": "http.response.body", "body": b"Novel MCP request rejected"})
            return
        delivered = False

        async def bounded_receive() -> Any:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, bounded_receive, send)


class NovelMcpServer:
    def __init__(
        self,
        service: NovelReadService,
        *,
        writer: NovelWriterService | None = None,
        include_legacy_tools: bool = False,
    ) -> None:
        self.service = service
        self.writer = writer
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("127.0.0.1", 0))
        port = self._socket.getsockname()[1]
        host = f"127.0.0.1:{port}"
        tools = NOVEL_TOOLS + ((WRITER_TOOL,) if writer is not None else ())
        if include_legacy_tools:
            tools += LEGACY_NOVEL_TOOLS
        self.endpoint = NovelMcpEndpoint(
            f"http://{host}/mcp", secrets.token_urlsafe(32), tools=tools
        )
        mcp = FastMCP(
            "AI Novel Studio",
            host="127.0.0.1",
            port=port,
            json_response=True,
            stateless_http=True,
            log_level="ERROR",
        )
        annotation = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

        def call(name: str, **params: Any) -> dict[str, Any]:
            try:
                return service.call(name, **params)
            except Exception as exc:
                # Tool errors must not reveal database paths or driver payloads.
                raise ValueError("小说资料不可用或参数无效；请检查项目和章节后重试") from exc

        @mcp.tool(annotations=annotation)
        def get_novel_context() -> dict[str, Any]:
            """获取当前小说、章节、作者编辑缓冲区和选区；区分未保存材料与正文事实。"""
            return call("get_novel_context")

        @mcp.tool(annotations=annotation)
        def list_novel_chapters(offset: int = 0, limit: int = 100) -> dict[str, Any]:
            """按作品顺序列出章节 ID 和修订；limit 最大100，可分页。"""
            return call("list_novel_chapters", offset=offset, limit=limit)

        @mcp.tool(annotations=annotation)
        def read_novel_chapter(
            chapter_id: str, start: int = 0, max_chars: int = 12_000
        ) -> dict[str, Any]:
            """读取正式正文片段，带修订、哈希和字符位置；max_chars 最大12000。"""
            return call(
                "read_novel_chapter", chapter_id=chapter_id, start=start, max_chars=max_chars
            )

        @mcp.tool(annotations=annotation)
        def read_novel_chapters(
            chapter_ids: list[str] | None = None,
            offset: Annotated[int, Field(strict=True, ge=0, le=100_000)] = 0,
            limit: Annotated[int, Field(strict=True, ge=1, le=1000)] = 1000,
            max_chars: Annotated[int, Field(strict=True, ge=1, le=300_000)] = 250_000,
            cursor_chapter: Annotated[int, Field(strict=True, ge=0, le=1000)] = 0,
            cursor_start: Annotated[int, Field(strict=True, ge=0, le=10_000_000)] = 0,
        ) -> dict[str, Any]:
            """一次读取所需多章正式正文，每章包含修订、哈希和字符位置。

            多章节分析优先使用此工具，不要逐章重复调用。默认选择全书；offset为0开始的章节
            索引，limit为所需章数；非连续选择使用chapter_ids，返回仍按作品顺序。
            每批最多100章、300000字符；truncated时保持原选择并传next_cursor继续读取。
            不读取编辑缓冲区或其他作品文件，不把未读部分当成已读。
            """
            return call(
                "read_novel_chapters",
                chapter_ids=chapter_ids,
                offset=offset,
                limit=limit,
                max_chars=max_chars,
                cursor_chapter=cursor_chapter,
                cursor_start=cursor_start,
            )

        @mcp.tool(annotations=annotation)
        def search_novel_evidence(
            query: str, before_chapter_id: str, limit: int = 5
        ) -> dict[str, Any]:
            """检索目标章节之前的正式正文证据，返回来源位置；索引缺失不表示事实不存在。"""
            return call(
                "search_novel_evidence",
                query=query,
                before_chapter_id=before_chapter_id,
                limit=limit,
            )

        @mcp.tool(annotations=annotation)
        def get_novel_constraints(chapter_id: str | None = None) -> dict[str, Any]:
            """读取作者计划、章节要求和创作规则，不能把计划当作已发生的事实。"""
            return call("get_novel_constraints", chapter_id=chapter_id)

        if include_legacy_tools:

            @mcp.tool(annotations=annotation)
            def query_novel_characters(query: str, limit: int = 20) -> dict[str, Any]:
                """只读查询旧人物记录，不代表当前大纲或正式正文；query 最长256字。"""
                return call("query_novel_characters", query=query, limit=limit)

        if writer is not None:

            @mcp.tool(
                annotations=ToolAnnotations(
                    readOnlyHint=False,
                    destructiveHint=False,
                    openWorldHint=True,
                    idempotentHint=False,
                )
            )
            async def generate_novel_draft(
                chapter_id: str,
                expected_revision: Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)],
                instruction: Annotated[str, Field(min_length=1, max_length=20_000)],
                target_words: Annotated[int, Field(strict=True, ge=100, le=30_000)] = 800,
                output_token_limit: Annotated[int, Field(strict=True, ge=1024, le=32_768)] = 8192,
                related_refs: Annotated[list[dict[str, Any]], Field(max_length=64)] | None = None,
                style_refs: Annotated[list[dict[str, Any]], Field(max_length=64)] | None = None,
                recent_chapters: Annotated[int, Field(strict=True, ge=0, le=10)] = 3,
            ) -> dict[str, Any]:
                """准备独立正文模型的完整输入，作者确认后生成候选，不覆盖正文。

                仅在作者明确要求写作时调用，每轮最多一次。先读取当前小说和章要求，
                expected_revision 使用当前上下文修订。instruction 整理作者目标、必要素材、
                接续位置和禁止改动；素材注明来源。目标100-30000字，输出1024-32768 tokens。
                完整大纲是基础输入；尚未登记时须先请作者在大纲页导入或新建并保存。
                此工具只准备输入提案，作者在软件中确认后才调用正文模型，不自动开始生成。
                related_refs、style_refs 显式传章节原文引用：chapter_id、revision、source_hash，
                可选 start/end 半开字符区间，均取自正文读取结果。Codex 读过不代表写作模型收到。
                范章由作者指定，recent_chapters 是目标前面近期原文章数，默认3，可为0。
                返回 AWAITING_CONFIRMATION 时应提示作者审阅输入，不能声称草稿已生成。
                完成后简短告知作者查看任务卡片，不重复粘贴整篇草稿。
                """
                try:
                    return await asyncio.to_thread(
                        writer.generate,
                        chapter_id,
                        expected_revision,
                        instruction,
                        target_words,
                        output_token_limit,
                        related_refs,
                        style_refs,
                        recent_chapters,
                    )
                except asyncio.CancelledError:
                    writer.cancel()
                    raise
                except OutlineRequiredError as exc:
                    raise ValueError(str(exc)) from exc
                except Exception as exc:
                    raise ValueError("正文任务未启动，请重新读取当前章节并检查写作参数") from exc

        app = _LoopbackAuth(mcp.streamable_http_app(), self.endpoint, host)
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                access_log=False,
                log_level="error",
                # pythonw has no stdout; Uvicorn's automatic colour probe calls isatty on it.
                use_colors=False,
                proxy_headers=False,
                lifespan="on",
                timeout_graceful_shutdown=3,
            )
        )
        self._thread = Thread(
            target=self._server.run,
            kwargs={"sockets": [self._socket]},
            name="novel-mcp",
            daemon=True,
        )
        self._thread.start()
        deadline = monotonic() + 5
        while not self._server.started and self._thread.is_alive() and monotonic() < deadline:
            sleep(0.01)
        if not self._server.started:
            self.close()
            raise RuntimeError("小说 MCP 服务未能启动")

    def close(self) -> None:
        if self.writer is not None:
            self.writer.revoke()
        self.service.revoke()
        self._server.should_exit = True
        self._thread.join(timeout=5)
        self._socket.close()
