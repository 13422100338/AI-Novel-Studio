import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ai_novel_studio.application.novel_note_service import NovelNoteService
from ai_novel_studio.application.novel_read_service import NovelReadService
from ai_novel_studio.infrastructure.mcp.novel_server import NovelMcpServer
from ai_novel_studio.infrastructure.storage.note_repository import NoteRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def test_live_note_tools_have_correct_permissions_and_retain_history(tmp_path):
    project = ProjectRepository.create(tmp_path / "novel", "笔记MCP验证")
    reader, writer = NovelReadService(project), NovelNoteService(project)
    server = NovelMcpServer(reader, note_writer=writer)

    async def check():
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer " + server.endpoint.token}
        ) as client:
            async with streamable_http_client(server.endpoint.url, http_client=client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = {t.name: t for t in (await session.list_tools()).tools}
                    assert tools["read_novel_notes"].annotations.readOnlyHint is True
                    assert tools["create_novel_note"].annotations.readOnlyHint is False
                    assert tools["update_novel_note"].annotations.openWorldHint is False
                    created = await session.call_tool(
                        "create_novel_note",
                        {
                            "title": "第二事件细纲",
                            "content": "先商讨，不直接生成正文。",
                            "kind": "OUTLINE",
                        },
                    )
                    assert not created.isError
                    identity = created.structuredContent["note_id"]
                    readback = await session.call_tool("read_novel_notes", {"note_ids": [identity]})
                    assert readback.structuredContent["truncated"] is False
                    assert (
                        readback.structuredContent["notes"][0]["content"]
                        == "先商讨，不直接生成正文。"
                    )
                    saved = await session.call_tool(
                        "update_novel_note",
                        {
                            "note_id": identity,
                            "expected_revision": 1,
                            "content": "商讨后形成的新细纲。",
                        },
                    )
                    assert saved.structuredContent["revision"] == 2
                    stale = await session.call_tool(
                        "update_novel_note",
                        {"note_id": identity, "expected_revision": 1, "content": "过期覆盖"},
                    )
                    assert stale.isError
                    assert (
                        NoteRepository(project).read(identity, revision=1).content
                        == "先商讨，不直接生成正文。"
                    )
                    writer.revoke()
                    revoked = await session.call_tool(
                        "create_novel_note", {"title": "不可保存", "content": "旧项目"}
                    )
                    assert revoked.isError
                    assert len(NoteRepository(project).list_notes()) == 1

    try:
        asyncio.run(check())
    finally:
        server.close()
