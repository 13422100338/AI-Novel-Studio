import asyncio
import hashlib
from threading import Event, Lock, Thread, current_thread
from types import SimpleNamespace

import pytest

from ai_novel_studio.application.novel_read_service import NovelEditorSnapshot, NovelReadService
from ai_novel_studio.application.novel_writer_service import NovelWriterService
from ai_novel_studio.infrastructure.llm import (
    LLMStreamEvent,
    ModelCapabilities,
    ModelRoute,
    StreamEventKind,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.outline_repository import OutlineRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.writer_input_repository import WriterInputRepository


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Gateway:
    def __init__(self):
        self.calls = []
        self.capabilities = ModelCapabilities(context_window=1_000_000, max_output_tokens=32_768)
        self.route = ModelRoute("provider", "writer")
        self.configuration = SimpleNamespace(
            routes=SimpleNamespace(resolve=lambda _: self.route),
            model=lambda _: SimpleNamespace(capabilities=self.capabilities),
        )

    def stream(self, purpose, messages, output_token_limit):
        self.calls.append((purpose, messages, output_token_limit))
        yield LLMStreamEvent(StreamEventKind.TEXT, text="仅供作者审阅的候选。")
        yield LLMStreamEvent(StreamEventKind.COMPLETED)


@pytest.fixture
def work(tmp_path):
    project = ProjectRepository.create(tmp_path / "novel", "完整正文输入验证")
    chapters = ChapterRepository(project)
    items = [
        chapters.create_chapter(
            project.list_volumes()[0].id, f"第{i}章", str(i), f"正式第{i}章原文\r\n独有细节-{i}。"
        )
        for i in range(1, 6)
    ]
    target = items[2]
    outlines = OutlineRepository(project)
    raw = "\ufeff# 全书原文\r\n" + "完整剧情及因果，不应省略。\r\n" * 1800 + "OUTLINE-END\r\n"
    saved = outlines.create("全书", raw)
    outlines.create("第二部", "## 25. 政变\n分卷末尾。")
    novel = NovelReadService(project)
    novel.update_editor(
        NovelEditorSnapshot(
            target.id, target.title, target.revision, chapters.read_content_exact(target.id)
        )
    )
    gateway, events = Gateway(), []
    writer = NovelWriterService(
        project, novel, gateway_factory=lambda: gateway, on_event=events.append
    )
    writer.begin_turn()

    def ref(chapter, **extra):
        return {
            "chapter_id": chapter.id,
            "revision": chapter.revision,
            "source_hash": digest(chapters.read_content_exact(chapter.id)),
            **extra,
        }

    return SimpleNamespace(
        project=project,
        chapters=chapters,
        items=items,
        target=target,
        outlines=outlines,
        raw=raw,
        outline=saved,
        novel=novel,
        gateway=gateway,
        events=events,
        writer=writer,
        ref=ref,
    )


def prepare(work, **changes):
    params = dict(
        chapter_id=work.target.id,
        expected_revision=work.target.revision,
        instruction="从25事件展开具体场景，保留既有事实。",
        related_refs=[work.ref(work.items[0]), work.ref(work.items[4])],
        style_refs=[work.ref(work.items[1])],
        recent_chapters=2,
    )
    params.update(changes)
    return work.writer.generate(**params)


def test_confirmation_is_required_and_actual_model_receives_all_material_in_order(work):
    prepared = prepare(work)
    assert prepared["status"] == "AWAITING_CONFIRMATION"
    assert work.gateway.calls == []
    preview = work.writer.preview_input(prepared["draft_id"])
    assert preview["scope"] == "CHAPTER"
    content = "\n".join(item["content"] for item in preview["messages"])
    assert work.raw in content and "OUTLINE-END\r\n" in content
    assert "## 25. 政变\n分卷末尾。" in content
    assert content.index(work.raw) < content.index("从25事件展开具体场景")
    assert content.index("从25事件展开具体场景") < content.index("独有细节-5")
    assert content.index("独有细节-5") < content.index("独有细节-2")
    result = work.writer.confirm_input(prepared["draft_id"])
    assert result["status"] == "COMPLETED"
    assert len(work.gateway.calls) == 1
    messages = work.gateway.calls[0][1]
    assert [(m.role, m.content) for m in messages] == [
        (m["role"], m["content"]) for m in preview["messages"]
    ]
    assert "人物、知识、线索、正典和文风" not in "\n".join(m.content for m in messages)
    assert work.chapters.read_content_exact(work.target.id).startswith("正式第3章原文")
    assert WriterInputRepository(work.project).messages_for(result["run_id"]) == messages


@pytest.mark.parametrize(
    "source", ["outline", "related", "editor", "requirement", "guidance", "target_file", "model"]
)
def test_changed_source_requires_new_input_confirmation_without_calling_model(work, source):
    prepared = prepare(work)
    if source == "outline":
        work.outlines.save(
            work.outline.version.document_id, work.raw + "新前提", expected_revision=1
        )
    elif source == "related":
        chapter = work.items[4]
        work.chapters.save_content(
            chapter.id,
            "外部修订",
            source="user_edit",
            reason="test",
            expected_revision=chapter.revision,
        )
    elif source == "editor":
        target = work.target
        work.novel.update_editor(
            NovelEditorSnapshot(target.id, target.title, target.revision, "尚未保存的新正文", True)
        )
    elif source == "requirement":
        from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
            ChapterRequirementRepository,
        )

        repository = ChapterRequirementRepository(work.project)
        saved = repository.get_or_create(work.target.id)
        repository.update(
            work.target.id, "新章要求", is_locked=True, expected_revision=saved.revision
        )
    elif source == "guidance":
        from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
            ProjectGuidanceRepository,
        )

        ProjectGuidanceRepository(work.project).save_manual("新最高指导", expected_revision=0)
    elif source == "target_file":
        (work.project.layout.root / work.target.content_path).write_bytes("外部原文变更".encode())
    else:
        work.gateway.route = ModelRoute("provider", "another-writer")
    with pytest.raises(ValueError):
        work.writer.confirm_input(prepared["draft_id"])
    assert work.gateway.calls == []


def test_selection_is_frozen_without_truncation_or_whole_chapter_expansion(work):
    selection = "选文中不能添加未来事件。" * 700
    body = "开头\n" + selection + "\n未选中的结尾。"
    target = work.target
    work.novel.update_editor(
        NovelEditorSnapshot(target.id, target.title, target.revision, body, True, selection)
    )
    prepared = prepare(work, related_refs=[], style_refs=[], recent_chapters=0)
    preview = work.writer.preview_input(prepared["draft_id"])
    text = "\n".join(p["content"] for p in preview["messages"])
    assert preview["scope"] == "SELECTION"
    assert selection in text
    assert "未选中的结尾。" not in text
    assert "仅处理选文" in text
    work.writer.confirm_input(prepared["draft_id"])
    assert work.chapters.read_content_exact(target.id).startswith("正式第3章原文")


@pytest.mark.parametrize(
    "change",
    [
        {"revision": True},
        {"source_hash": "0" * 64},
        {"start": 20, "end": 1},
        {"chapter_id": "../outside"},
        {"path": "C:/secret.md"},
    ],
)
def test_invalid_model_reference_is_rejected_before_preparation(work, change):
    invalid = {**work.ref(work.items[0]), **change}
    with pytest.raises(ValueError):
        prepare(work, related_refs=[invalid])
    assert work.gateway.calls == []


@pytest.mark.parametrize("window", [None, 10_000])
def test_unknown_or_insufficient_model_capacity_does_not_summarize_outline(work, window):
    work.gateway.capabilities = ModelCapabilities(context_window=window)
    with pytest.raises(ValueError, match="容量|预算"):
        prepare(work)
    assert work.gateway.calls == []


def test_rejection_and_duplicate_confirmation_do_not_run_twice(work):
    prepared = prepare(work)
    assert work.writer.reject_input(prepared["draft_id"])
    assert work.gateway.calls == []
    with pytest.raises(ValueError):
        work.writer.confirm_input(prepared["draft_id"])
    work.writer.begin_turn()
    newer = prepare(work)
    work.writer.confirm_input(newer["draft_id"])
    with pytest.raises(ValueError):
        work.writer.confirm_input(newer["draft_id"])
    assert len(work.gateway.calls) == 1


def test_cancel_waiting_on_confirmation_lock_cannot_be_cleared(work):
    prepared = prepare(work)
    engine = work.writer.outline_writer
    start_cancel, attempted_lock, cancel_done = Event(), Event(), Event()
    mutex = Lock()
    first = True

    class InterleavedLock:
        def __enter__(self):
            nonlocal first
            if current_thread() is cancel_thread:
                attempted_lock.set()
            mutex.acquire()
            if first:
                first = False
                start_cancel.set()
                assert attempted_lock.wait(2)
            return self

        def __exit__(self, *args):
            mutex.release()

    def cancel():
        assert start_cancel.wait(2)
        engine.cancel()
        cancel_done.set()

    cancel_thread = Thread(target=cancel, daemon=True)
    engine._state_lock = InterleavedLock()

    def gateway():
        assert cancel_done.wait(2)
        return work.gateway

    engine.gateway_factory = gateway
    cancel_thread.start()
    try:
        result = work.writer.confirm_input(prepared["draft_id"])
        assert result["status"] in {"CANCELLED", "FAILED"}
        assert work.gateway.calls == []
    finally:
        cancel_thread.join(2)


def test_manual_highest_guidance_is_preserved_as_system_input(work):
    from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
        ProjectGuidanceRepository,
    )

    guidance = "作者原样指导\r\n不允许擅改视角。\r\n"
    ProjectGuidanceRepository(work.project).save_manual(guidance, expected_revision=0)
    prepared = prepare(work)
    messages = work.writer.preview_input(prepared["draft_id"])["messages"]
    assert any(m["role"] == "system" and guidance in m["content"] for m in messages)


def test_prepare_has_no_generation_rows_or_durable_confirmation_receipt(work):
    prepare(work)
    assert not (work.project.layout.pipeline / "writer_inputs").exists()
    with work.project.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM generation_runs").fetchone()[0] == 0


def test_snapshot_corruption_or_cross_project_copy_cannot_rebuild_new_input(work, tmp_path):
    prepared = prepare(work)
    result = work.writer.confirm_input(prepared["draft_id"])
    repository = WriterInputRepository(work.project)
    path = work.project.layout.pipeline / "writer_inputs" / f"{result['run_id']}.json"
    original = path.read_bytes()
    work.outlines.save(work.outline.version.document_id, work.raw + "后来改纲", expected_revision=1)
    assert work.raw in "\n".join(m.content for m in repository.messages_for(result["run_id"]))
    path.write_bytes(original.replace(b"OUTLINE-END", b"CORRUPT-END"))
    with pytest.raises(ValueError, match="快照"):
        repository.messages_for(result["run_id"])
    other = ProjectRepository.create(tmp_path / "other-novel", "其他小说")
    target = other.layout.pipeline / "writer_inputs" / path.name
    target.parent.mkdir()
    target.write_bytes(original)
    with pytest.raises(ValueError, match="快照"):
        WriterInputRepository(other).messages_for(result["run_id"])


def test_cancelled_generation_preserves_partial_checkpoint_and_original_input(work):
    prepared = prepare(work)

    def stream(*args):
        work.gateway.calls.append(args)
        yield LLMStreamEvent(StreamEventKind.TEXT, text="已经生成的部分。")
        work.writer.cancel()
        yield LLMStreamEvent(StreamEventKind.TEXT, text="不应追加的部分。")
        yield LLMStreamEvent(StreamEventKind.COMPLETED)

    work.gateway.stream = stream
    result = work.writer.confirm_input(prepared["draft_id"])
    assert result["status"] == "CANCELLED"
    from ai_novel_studio.infrastructure.storage.checkpoint_repository import CheckpointRepository
    from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository

    checkpoints = CheckpointRepository(work.project, GenerationRepository(work.project))
    assert checkpoints.read(checkpoints.latest(result["run_id"]).id) == "已经生成的部分。"
    assert work.raw in "\n".join(
        m.content for m in WriterInputRepository(work.project).messages_for(result["run_id"])
    )
    assert work.chapters.read_content_exact(work.target.id).startswith("正式第3章原文")


def test_mcp_exposes_reference_preparation_but_no_author_confirmation_tool(work):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from ai_novel_studio.infrastructure.mcp.novel_server import NovelMcpServer

    server = NovelMcpServer(work.novel, writer=work.writer)

    async def check():
        async with (
            httpx.AsyncClient(
                headers={"Authorization": "Bearer " + server.endpoint.token}
            ) as client,
            streamable_http_client(server.endpoint.url, http_client=client) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = (await session.list_tools()).tools
            assert not any("confirm" in tool.name for tool in tools)
            tool = next(tool for tool in tools if tool.name == "generate_novel_draft")
            assert {"related_refs", "style_refs", "recent_chapters"} <= tool.inputSchema[
                "properties"
            ].keys()
            result = await session.call_tool(
                "generate_novel_draft",
                {
                    "chapter_id": work.target.id,
                    "expected_revision": work.target.revision,
                    "instruction": "整理完整输入。",
                    "related_refs": [work.ref(work.items[4])],
                    "recent_chapters": 0,
                },
            )
            assert not result.isError
            assert result.structuredContent["status"] == "AWAITING_CONFIRMATION"
            assert work.gateway.calls == []

    try:
        asyncio.run(check())
    finally:
        server.close()


def test_final_adapter_request_is_the_reviewed_input_and_never_reads_old_memory(work, monkeypatch):
    from ai_novel_studio.application.generation_memory_context_provider import (
        GenerationMemoryContextProvider,
    )
    from ai_novel_studio.infrastructure.llm import LLMGateway, ModelProfile
    from ai_novel_studio.infrastructure.llm.config_repository import ModelConfiguration
    from ai_novel_studio.infrastructure.llm.provider_profile import ProviderProfile, TaskRoutes
    from ai_novel_studio.infrastructure.llm.usage_tracker import UsageTracker

    def forbidden(*args, **kwargs):
        raise AssertionError("outline mode must not compile old memory")

    monkeypatch.setattr(GenerationMemoryContextProvider, "blocks", forbidden)
    requests = []

    class Adapter:
        def stream(self, request, profile, api_key):
            requests.append(request)
            yield LLMStreamEvent(StreamEventKind.TEXT, text="假适配器的候选。")
            yield LLMStreamEvent(StreamEventKind.COMPLETED)

    route = work.gateway.route
    configuration = ModelConfiguration(
        (ProviderProfile(route.provider_id, "测试连接", "https://example.invalid", "test-only"),),
        (ModelProfile(route.provider_id, route.model_id, capabilities=work.gateway.capabilities),),
        TaskRoutes(plot=None, prose=route),
    )
    gateway = LLMGateway(
        configuration,
        SimpleNamespace(get=lambda _: "test-only"),
        {"openai_compatible": Adapter()},
        UsageTracker(),
    )
    work.writer.outline_writer.gateway_factory = lambda: gateway
    proposal = prepare(work)
    preview = work.writer.preview_input(proposal["draft_id"])
    assert requests == []
    result = work.writer.confirm_input(proposal["draft_id"])
    assert result["status"] == "COMPLETED"
    assert len(requests) == 1
    assert [(m.role, m.content) for m in requests[0].messages] == [
        (m["role"], m["content"]) for m in preview["messages"]
    ]
    assert work.raw in "\n".join(m.content for m in requests[0].messages)


def test_fragment_and_multiple_purposes_are_explicit_without_duplicate_body(work):
    chapter = work.items[0]
    reference = work.ref(chapter, start=0, end=5)
    proposal = prepare(work, related_refs=[reference], style_refs=[reference], recent_chapters=0)
    preview = work.writer.preview_input(proposal["draft_id"])
    source = next(s for s in preview["sources"] if s["source_id"] == chapter.id)
    assert source["start"] == 0 and source["end"] == 5
    assert source["purposes"] == ["RELATED", "STYLE"]
    messages = [m for m in preview["messages"] if "用途=RELATED,STYLE" in m["content"]]
    assert len(messages) == 1
    assert messages[0]["content"].endswith(work.chapters.read_content_exact(chapter.id)[:5])


def test_cancellation_during_prepare_cannot_publish_a_pending_plan(work, monkeypatch):
    compiler = work.writer.outline_writer.inputs
    original = compiler.prepare

    def prepare_then_cancel(*args, **kwargs):
        plan = original(*args, **kwargs)
        work.writer.cancel()
        return plan

    monkeypatch.setattr(compiler, "prepare", prepare_then_cancel)
    with pytest.raises(ValueError, match="取消"):
        prepare(work)
    assert not any(event["status"] == "AWAITING_CONFIRMATION" for event in work.events)
    assert work.gateway.calls == []


def test_same_model_id_with_changed_connection_requires_new_confirmation(work):
    provider = SimpleNamespace(
        base_url="https://first.invalid",
        interface_type="openai_compatible",
        credential_id="test-reference",
        timeout_seconds=90,
    )
    work.gateway.configuration.provider = lambda _: provider
    proposal = prepare(work)
    provider.base_url = "https://second.invalid"
    with pytest.raises(ValueError, match="配置"):
        work.writer.confirm_input(proposal["draft_id"])
    assert work.gateway.calls == []


def test_changed_chapter_order_invalidates_the_recent_chapter_selection(work):
    proposal = prepare(work)
    with work.project.database.connect() as connection, connection:
        connection.execute("UPDATE chapters SET sort_index=9999 WHERE id=?", (work.target.id,))
    with pytest.raises(ValueError):
        work.writer.confirm_input(proposal["draft_id"])
    assert work.gateway.calls == []


def test_failed_snapshot_load_leaves_no_active_writer_or_false_candidate(work, monkeypatch):
    from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository

    proposal = prepare(work)

    def damaged_snapshot(_):
        raise ValueError("snapshot unavailable")

    monkeypatch.setattr(work.writer.outline_writer.snapshots, "messages_for", damaged_snapshot)
    result = work.writer.confirm_input(proposal["draft_id"])
    assert result["status"] == "FAILED"
    assert work.gateway.calls == []
    assert str(GenerationRepository(work.project).get(result["run_id"]).status) == "FAILED"
    assert work.events[-1]["status"] == "FAILED"
    assert "已保存在检查点" not in work.events[-1]["message"]
