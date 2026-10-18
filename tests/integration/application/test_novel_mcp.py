import asyncio
import hashlib
import json
import sqlite3
import sys
from uuid import uuid4

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from uvicorn.config import LOGGING_CONFIG

from ai_novel_studio.application.novel_read_service import (
    NOVEL_TOOLS,
    NovelEditorSnapshot,
    NovelReadService,
)
from ai_novel_studio.infrastructure.mcp.novel_server import NovelMcpServer
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def fixture_project(tmp_path):
    project = ProjectRepository.create(tmp_path / "book", "测试小说")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "港口",
        content="陆明在港口拾到一封信。",
    )
    return project, chapter


def test_tools_read_real_chapter_and_unsaved_snapshot_without_inserting_requirements(tmp_path):
    project, chapter = fixture_project(tmp_path)
    reader = NovelReadService(project)
    reader.update_editor(
        NovelEditorSnapshot(
            chapter.id, chapter.title, chapter.revision, "尚未保存的结尾", True, "结尾"
        )
    )
    with project.database.connect() as connection:
        before = connection.execute("SELECT COUNT(*) FROM chapter_requirements").fetchone()[0]
    context = reader.call("get_novel_context")
    assert context["domain_kind"] == "EDITOR_BUFFER"
    assert context["selection"] == "结尾"
    result = reader.call("read_novel_chapter", chapter_id=chapter.id)
    assert result["content"] == "陆明在港口拾到一封信。"
    assert result["source_hash"] == hashlib.sha256(result["content"].encode()).hexdigest()
    assert "content_path" not in reader.call("list_novel_chapters")["chapters"][0]
    assert reader.call("get_novel_constraints")["chapter_plan"]["requirement"] is None
    with project.database.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM chapter_requirements").fetchone()[0] == before
        )
    with reader._project.database.connect() as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM chapters")
    assert ChapterRepository(project).read_content_exact(chapter.id) == result["content"]


def test_tools_reject_foreign_chapter_paths_bounds_and_revoked_access(tmp_path):
    project, chapter = fixture_project(tmp_path)
    reader = NovelReadService(project)
    for params in (
        {"chapter_id": "../secret"},
        {"chapter_id": str(uuid4())},
        {"chapter_id": chapter.id, "max_chars": 100_000},
    ):
        with pytest.raises((ValueError, KeyError)):
            reader.call("read_novel_chapter", **params)
    with pytest.raises(ValueError):
        reader.call("list_novel_chapters", limit=True)
    reader.revoke()
    with pytest.raises(ValueError, match="失效"):
        reader.call("get_novel_context")


def test_mcp_starts_and_reads_without_pythonw_console_streams(tmp_path, monkeypatch):
    project, chapter = fixture_project(tmp_path)
    reader = NovelReadService(project)
    server = None
    try:
        with monkeypatch.context() as context:
            context.setitem(LOGGING_CONFIG["formatters"]["default"], "use_colors", None)
            context.setitem(LOGGING_CONFIG["formatters"]["access"], "use_colors", None)
            context.setattr(sys, "stdout", None)
            context.setattr(sys, "stderr", None)
            server = NovelMcpServer(reader)

            async def check():
                headers = {"Authorization": "Bearer " + server.endpoint.token}
                async with (
                    httpx.AsyncClient(headers=headers) as client,
                    streamable_http_client(server.endpoint.url, http_client=client) as (
                        read,
                        write,
                        _,
                    ),
                    ClientSession(read, write) as session,
                ):
                    await session.initialize()
                    result = await session.call_tool(
                        "read_novel_chapter", {"chapter_id": chapter.id}
                    )
                    assert not result.isError
                    assert result.structuredContent["content"] == "陆明在港口拾到一封信。"
                    batch = await session.call_tool("read_novel_chapters", {})
                    assert not batch.isError
                    assert batch.structuredContent["chapter_count"] == 1
                    assert batch.structuredContent["chapters"][0]["chapter_id"] == chapter.id

            asyncio.run(check())
    finally:
        if server is not None:
            server.close()


def test_loopback_mcp_enforces_auth_origin_and_schema_and_shuts_down(tmp_path):
    project, chapter = fixture_project(tmp_path)
    reader = NovelReadService(project)
    server = NovelMcpServer(reader)
    endpoint = server.endpoint
    headers = {"Authorization": "Bearer " + endpoint.token}
    try:
        assert endpoint.token not in repr(endpoint)
        assert endpoint.token not in json.dumps(endpoint.config())
        with httpx.Client() as client:
            assert client.post(endpoint.url, json={}).status_code == 401
            assert (
                client.post(
                    endpoint.url, headers={**headers, "Origin": "https://foreign.test"}, json={}
                ).status_code
                == 403
            )
            assert (
                client.post(endpoint.url, headers=headers, content=b"a" * 70_000).status_code == 413
            )

        async def check():
            async with (
                httpx.AsyncClient(headers=headers) as http_client,
                streamable_http_client(
                    endpoint.url,
                    http_client=http_client,
                ) as (read, write, _),
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    assert {tool.name for tool in tools} == set(NOVEL_TOOLS)
                    assert all(tool.annotations.readOnlyHint for tool in tools)
                    result = await session.call_tool(
                        "read_novel_chapter", {"chapter_id": chapter.id}
                    )
                    assert not result.isError
                    assert result.structuredContent["content"] == "陆明在港口拾到一封信。"
                    invalid = await session.call_tool(
                        "read_novel_chapter", {"chapter_id": str(uuid4())}
                    )
                    assert invalid.isError
                    assert str(project.layout.root) not in str(invalid)
                    reader.revoke()
                    assert (await session.call_tool("get_novel_context", {})).isError

        asyncio.run(check())
    finally:
        server.close()
    assert not server._thread.is_alive()
    with pytest.raises(httpx.TransportError):
        httpx.get(endpoint.url, timeout=1)
