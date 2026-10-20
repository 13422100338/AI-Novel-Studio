import asyncio
from types import SimpleNamespace

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ai_novel_studio.application.generation_memory_context_provider import (
    GenerationMemoryContextProvider,
)
from ai_novel_studio.application.memory_analysis_service import MemoryAnalysisService
from ai_novel_studio.application.novel_read_service import (
    NOVEL_TOOLS,
    NovelEditorSnapshot,
    NovelReadService,
)
from ai_novel_studio.application.novel_writer_service import NovelWriterService
from ai_novel_studio.infrastructure.llm import (
    LLMStreamEvent,
    ModelCapabilities,
    ModelRoute,
    StreamEventKind,
)
from ai_novel_studio.infrastructure.mcp.novel_server import NovelMcpServer
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.outline_repository import OutlineRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class Gateway:
    def __init__(self):
        self.calls = []
        route = ModelRoute("provider", "writer")
        self.configuration = SimpleNamespace(
            routes=SimpleNamespace(resolve=lambda _: route),
            model=lambda _: SimpleNamespace(capabilities=ModelCapabilities(context_window=1000000)),
        )

    def stream(self, purpose, messages, output_token_limit):
        self.calls.append((purpose, messages, output_token_limit))
        yield LLMStreamEvent(StreamEventKind.TEXT, text="仅供作者审阅的候选。 OUTLINESEARCHMARKER")
        yield LLMStreamEvent(StreamEventKind.COMPLETED)


def no_legacy_work(*args, **kwargs):
    raise AssertionError("default workflow must not schedule legacy memory/model work")


@pytest.fixture
def old_project(tmp_path):
    project = ProjectRepository.create(tmp_path / "old-project", "未登记大纲的旧小说")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id, "第一章", "1", "原文😀。\r\n旧细节。"
    )
    reader = NovelReadService(project)
    reader.update_editor(
        NovelEditorSnapshot(
            chapter.id, chapter.title, chapter.revision, chapters.read_content_exact(chapter.id)
        )
    )
    return project, chapters, chapter, reader


def test_missing_outline_stops_before_gateway_or_legacy_compiler(old_project, monkeypatch):
    project, chapters, chapter, reader = old_project
    monkeypatch.setattr(GenerationMemoryContextProvider, "blocks", no_legacy_work)
    writer = NovelWriterService(
        project, reader, gateway_factory=no_legacy_work, on_event=lambda _: None
    )
    writer.begin_turn()
    with pytest.raises(ValueError, match="完整大纲"):
        writer.generate(chapter.id, chapter.revision, "开始正文创作")
    with project.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM generation_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM chapter_requirements").fetchone()[0] == 0
    assert chapters.read_content_exact(chapter.id) == "原文😀。\r\n旧细节。"


def test_old_project_uses_outline_confirmation_and_preserves_search_and_revision(
    old_project, monkeypatch
):
    project, chapters, chapter, reader = old_project
    monkeypatch.setattr(GenerationMemoryContextProvider, "blocks", no_legacy_work)
    monkeypatch.setattr(MemoryAnalysisService, "__init__", no_legacy_work)
    OutlineRepository(project).create("全书", "# 全书剧情\n人物与事件因果的完整原文。\nOUTLINE-END")
    gateway, events = Gateway(), []
    writer = NovelWriterService(
        project, reader, gateway_factory=lambda: gateway, on_event=events.append
    )
    writer.begin_turn()
    pending = writer.generate(chapter.id, chapter.revision, "展开新场景", recent_chapters=0)
    assert pending["status"] == "AWAITING_CONFIRMATION"
    assert gateway.calls == []
    generated = writer.confirm_input(pending["draft_id"])
    assert generated["status"] == "COMPLETED"
    assert "OUTLINE-END" in "\n".join(m.content for m in gateway.calls[0][1])
    assert chapters.read_content_exact(chapter.id) == "原文😀。\r\n旧细节。"
    event = events[-1]
    writer.adopt_candidate(generated["run_id"], event["checkpoint_id"], event["candidate_hash"])
    assert chapters.get_chapter(chapter.id).revision == chapter.revision + 1
    # The formal manuscript projection remains searchable after adoption.
    next_chapter = chapters.create_chapter(project.list_volumes()[0].id, "第二章", "2", "下一章。")
    evidence = reader.call(
        "search_novel_evidence", query="OUTLINESEARCHMARKER", before_chapter_id=next_chapter.id
    )
    assert evidence["hits"]
    assert len(gateway.calls) == 1
    with project.database.connect() as connection:
        for table in ("character_state_events", "canon_entries", "summary_nodes", "occurrences"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("legacy", [False, True])
def test_default_mcp_omits_legacy_character_tool_but_explicit_compatibility_can_read(
    old_project, legacy
):
    _, _, _, reader = old_project
    server = NovelMcpServer(reader, include_legacy_tools=True) if legacy else NovelMcpServer(reader)

    async def check():
        async with (
            httpx.AsyncClient(
                headers={"Authorization": "Bearer " + server.endpoint.token}
            ) as client,
            streamable_http_client(server.endpoint.url, http_client=client) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert names == set(server.endpoint.tools)
            response = await session.call_tool("query_novel_characters", {"query": "不存在的人物"})
            assert response.isError is not legacy

    try:
        assert "query_novel_characters" not in NOVEL_TOOLS
        assert ("query_novel_characters" in server.endpoint.tools) == legacy
        asyncio.run(check())
        assert reader.call("query_novel_characters", query="不存在的人物")["characters"] == []
    finally:
        server.close()


def test_mcp_missing_outline_error_explains_how_to_continue(old_project):
    project, _, chapter, reader = old_project
    writer = NovelWriterService(
        project, reader, gateway_factory=no_legacy_work, on_event=lambda _: None
    )
    writer.begin_turn()
    server = NovelMcpServer(reader, writer=writer)

    async def check():
        async with (
            httpx.AsyncClient(
                headers={"Authorization": "Bearer " + server.endpoint.token}
            ) as client,
            streamable_http_client(server.endpoint.url, http_client=client) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "generate_novel_draft",
                {
                    "chapter_id": chapter.id,
                    "expected_revision": chapter.revision,
                    "instruction": "展开场景",
                },
            )
            assert result.isError
            assert "完整大纲" in str(result.content)

    try:
        asyncio.run(check())
    finally:
        server.close()
