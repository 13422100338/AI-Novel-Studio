import asyncio
from types import SimpleNamespace

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ai_novel_studio.application.novel_read_service import NovelEditorSnapshot, NovelReadService
from ai_novel_studio.application.novel_writer_service import NovelWriterService
from ai_novel_studio.infrastructure.llm import (
    LLMStreamEvent,
    ModelCapabilities,
    ModelRoute,
    StreamEventKind,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.mcp.novel_server import NovelMcpServer
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.outline_repository import OutlineRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class WriterGateway:
    def __init__(self):
        self.calls = []
        self.error = False
        self.route = ModelRoute("test-provider", "independent-writer")
        self.configuration = SimpleNamespace(
            routes=SimpleNamespace(resolve=lambda _purpose: self.route),
            model=lambda _route: SimpleNamespace(
                capabilities=ModelCapabilities(context_window=64000)
            ),
        )

    def stream(self, purpose, messages, output_token_limit):
        self.calls.append((purpose, messages, output_token_limit))
        if self.error:
            raise RuntimeError("private-provider-payload")
        yield LLMStreamEvent(StreamEventKind.REASONING, text="内部思考")
        yield LLMStreamEvent(StreamEventKind.TEXT, text="灯塔亮起。")
        yield LLMStreamEvent(StreamEventKind.TEXT, text="潮水退去了。")
        yield LLMStreamEvent(StreamEventKind.COMPLETED)


@pytest.fixture
def workspace(tmp_path):
    project = ProjectRepository.create(tmp_path / "novel", "写作工具测试")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(project.list_volumes()[0].id, "灯塔", "1", "原始正文。")
    OutlineRepository(project).create("全书", "# 全书大纲\n灯塔亮起，潮水退去，保留寄信人的悬念。")
    novel = NovelReadService(project)
    novel.update_editor(
        NovelEditorSnapshot(chapter.id, chapter.title, chapter.revision, "原始正文。")
    )
    gateway, events = WriterGateway(), []
    writer = NovelWriterService(
        project, novel, gateway_factory=lambda: gateway, on_event=events.append
    )
    writer.begin_turn()
    return SimpleNamespace(
        project=project,
        chapters=chapters,
        chapter=chapter,
        gateway=gateway,
        events=events,
        writer=writer,
    )


def generate(workspace, **changes):
    params = dict(
        chapter_id=workspace.chapter.id,
        expected_revision=workspace.chapter.revision,
        instruction="写灯塔亮起后的场景，保留原有悬念。",
        target_words=800,
        output_token_limit=8192,
    )
    params.update(changes)
    proposal = workspace.writer.generate(**params)
    assert proposal["status"] == "AWAITING_CONFIRMATION"
    return workspace.writer.confirm_input(proposal["draft_id"])


def test_chat_task_reaches_independent_writer_without_overwriting_author_content(workspace):
    requirements = ChapterRequirementRepository(workspace.project)
    empty = requirements.get_or_create(workspace.chapter.id)
    saved = requirements.update(
        workspace.chapter.id, "不可揭晓寄信人", is_locked=True, expected_revision=empty.revision
    )
    result = generate(workspace)
    assert result["domain_kind"] == "CANDIDATE_DRAFT"
    assert result["status"] == "COMPLETED"
    assert result["content"] == "灯塔亮起。潮水退去了。"
    purpose, messages, limit = workspace.gateway.calls[0]
    assert purpose == TaskPurpose.PROSE_GENERATION and limit == 8192
    assert "不可揭晓寄信人" in "\n".join(item.content for item in messages)
    assert "写灯塔亮起后的场景" in "\n".join(item.content for item in messages)
    assert requirements.get(workspace.chapter.id) == saved
    assert workspace.chapters.read_content(workspace.chapter.id) == "原始正文。"
    assert workspace.events[0]["status"] == "AWAITING_CONFIRMATION"
    assert any(
        event["status"] == "GENERATING" and event.get("word_count", 0) > 0
        for event in workspace.events
    )
    assert workspace.events[-1]["draft_text"] == result["content"]


def test_new_chapter_can_generate_with_an_ephemeral_task_only(workspace):
    generate(workspace)
    with pytest.raises(KeyError):
        ChapterRequirementRepository(workspace.project).get(workspace.chapter.id)


@pytest.mark.parametrize(
    "changes",
    [
        dict(target_words=True),
        dict(output_token_limit=1000000),
        dict(instruction="x" * 20001),
        dict(instruction="坏\x00文本"),
        dict(expected_revision=999),
    ],
)
def test_invalid_or_stale_requests_do_not_call_model(workspace, changes):
    with pytest.raises(ValueError):
        generate(workspace, **changes)
    assert workspace.gateway.calls == []


def test_one_generation_per_author_turn_and_revoked_project_are_enforced(workspace):
    generate(workspace)
    with pytest.raises(ValueError):
        generate(workspace)
    workspace.writer.begin_turn()
    workspace.writer.revoke()
    with pytest.raises(ValueError):
        generate(workspace)
    assert len(workspace.gateway.calls) == 1


def test_provider_failure_is_safe_and_leaves_formal_text_unchanged(workspace):
    workspace.gateway.error = True
    result = generate(workspace)
    assert result["status"] == "FAILED"
    assert "private-provider-payload" not in str(result) + str(workspace.events)
    assert workspace.chapters.read_content(workspace.chapter.id) == "原始正文。"


def test_cancellation_keeps_partial_candidate_and_never_accepts_it(workspace):
    def on_event(event):
        workspace.events.append(event)
        if event.get("word_count", 0) > 0:
            workspace.writer.cancel()

    workspace.writer.on_event = on_event
    result = generate(workspace)
    assert result["status"] == "CANCELLED"
    assert result["content"] == "灯塔亮起。"
    assert workspace.chapters.read_content(workspace.chapter.id) == "原始正文。"


def test_authenticated_mcp_can_generate_a_candidate_with_write_annotations(workspace):
    server = NovelMcpServer(workspace.writer.novel, writer=workspace.writer)
    config = server.endpoint.config()
    assert (
        config["mcp_servers.novel_workspace.tools.generate_novel_draft.approval_mode"] == "approve"
    )
    assert config["mcp_servers.novel_workspace.tool_timeout_sec"] == 300
    assert config["mcp_servers.novel_workspace.enabled_tools"] == list(server.endpoint.tools)

    async def check():
        async with (
            httpx.AsyncClient(
                headers={"Authorization": "Bearer " + server.endpoint.token}
            ) as client,
            streamable_http_client(server.endpoint.url, http_client=client) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tool = next(
                item
                for item in (await session.list_tools()).tools
                if item.name == "generate_novel_draft"
            )
            assert tool.annotations.readOnlyHint is False
            assert tool.annotations.destructiveHint is False
            result = await session.call_tool(
                "generate_novel_draft",
                dict(
                    chapter_id=workspace.chapter.id,
                    expected_revision=workspace.chapter.revision,
                    instruction="写灯塔亮起后的场景。",
                    target_words=800,
                ),
            )
            assert not result.isError
            assert result.structuredContent["status"] == "AWAITING_CONFIRMATION"
            assert workspace.gateway.calls == []
            generated = workspace.writer.confirm_input(result.structuredContent["draft_id"])
            assert generated["status"] == "COMPLETED"
            assert generated["domain_kind"] == "CANDIDATE_DRAFT"
            invalid = await session.call_tool(
                "generate_novel_draft",
                dict(
                    chapter_id=workspace.chapter.id,
                    expected_revision=True,
                    instruction="这个参数应被拒绝",
                    target_words=800,
                ),
            )
            assert invalid.isError
            assert len(workspace.gateway.calls) == 1

    try:
        asyncio.run(check())
        assert workspace.chapters.read_content(workspace.chapter.id) == "原始正文。"
    finally:
        server.close()
