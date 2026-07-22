import json
from pathlib import Path

import pytest

from ai_novel_studio.application.project_runtime import ProjectRuntime
from ai_novel_studio.core.context.history_retriever import (
    StoredEmbeddingRecallProvider,
)
from ai_novel_studio.domain.agent import AgentRunStatus
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus
from ai_novel_studio.infrastructure.llm import (
    EmbeddingRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
    MemoryCredentialStore,
    ModelCapabilities,
    ModelConfigRepository,
    ModelConfiguration,
    ModelProfile,
    ModelRoute,
    ProviderAdapter,
    ProviderProfile,
    ProviderProtocolError,
    StreamEventKind,
    TaskPurpose,
    TaskRoutes,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository


class JsonAdapter(ProviderAdapter):
    def list_models(self, profile, api_key):  # type: ignore[no-untyped-def]
        return ("agent-model",)

    def complete(self, request, profile, api_key):  # type: ignore[no-untyped-def]
        assert request.json_mode is True
        if any("findings" in message.content for message in request.messages):
            return LLMResponse(
                json.dumps({"summary": "ok", "findings": []}),
                request.model_id,
            )
        if any("只读工具返回" in message.content for message in request.messages):
            payload = {"action": "final", "final_answer": "检索建议"}
        else:
            payload = {
                "action": "tool",
                "tool_calls": [
                    {"tool_name": "SEARCH_MEMORY", "arguments": {"query": "old letter"}}
                ],
            }
        return LLMResponse(json.dumps(payload), request.model_id)

    def stream(self, request, profile, api_key):  # type: ignore[no-untyped-def]
        yield LLMStreamEvent(StreamEventKind.TEXT, text="模型生成正文")
        yield LLMStreamEvent(
            StreamEventKind.USAGE,
            usage=LLMUsage(input_tokens=120, output_tokens=30, cached_input_tokens=20),
        )
        yield LLMStreamEvent(StreamEventKind.COMPLETED)


class FakeModelRuntime:
    def __init__(self, tmp_path: Path) -> None:
        credentials = MemoryCredentialStore()
        provider = ProviderProfile(
            "relay",
            "Relay",
            "https://relay.example/v1",
            "credential-relay",
        )
        model = ModelProfile(
            "relay",
            "agent-model",
            capabilities=ModelCapabilities(
                context_window=128_000,
                max_output_tokens=32_000,
                streaming=True,
                strict_json=True,
            ),
        )
        route = ModelRoute("relay", "agent-model")
        repository = ModelConfigRepository(tmp_path / "models.json", credentials)
        repository.save(
            ModelConfiguration(
                providers=(provider,),
                models=(model,),
                routes=TaskRoutes(plot=route, prose=route),
            ),
            {"credential-relay": "secret"},
        )
        from ai_novel_studio.infrastructure.llm import LLMGateway, UsageTracker

        configuration = repository.load()
        self.gateway = LLMGateway(
            configuration,
            credentials,
            {"openai_compatible": JsonAdapter()},
            UsageTracker(),
        )


class EmbeddingJsonAdapter(JsonAdapter):
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.embedding_requests: list[EmbeddingRequest] = []

    def embed(self, request, profile, api_key):  # type: ignore[no-untyped-def]
        self.embedding_requests.append(request)
        if self.error is not None:
            raise self.error
        return tuple((1.0, 0.0) for _text in request.texts)


class EmbeddingModelRuntime:
    def __init__(self, tmp_path: Path, *, error: Exception | None = None) -> None:
        credentials = MemoryCredentialStore()
        provider = ProviderProfile(
            "relay",
            "Relay",
            "https://relay.example/v1",
            "credential-relay",
        )
        model = ModelProfile(
            "relay",
            "embedding-model",
            capabilities=ModelCapabilities(
                context_window=128_000,
                max_output_tokens=32_000,
                streaming=True,
                strict_json=True,
            ),
        )
        route = ModelRoute("relay", "embedding-model")
        repository = ModelConfigRepository(tmp_path / "models.json", credentials)
        repository.save(
            ModelConfiguration(
                providers=(provider,),
                models=(model,),
                routes=TaskRoutes(
                    plot=route,
                    prose=route,
                    overrides=((TaskPurpose.MEMORY_EMBEDDING, route),),
                ),
            ),
            {"credential-relay": "unit-secret"},
        )
        from ai_novel_studio.infrastructure.llm import LLMGateway, UsageTracker

        self.adapter = EmbeddingJsonAdapter(error)
        self.gateway = LLMGateway(
            repository.load(),
            credentials,
            {"openai_compatible": self.adapter},
            UsageTracker(),
        )


def test_project_runtime_creates_workspace_and_agent_runtime(tmp_path: Path) -> None:
    runtime = ProjectRuntime.create(
        tmp_path / "novel",
        "Runtime Novel",
        FakeModelRuntime(tmp_path),
    )
    chapter = ChapterRepository(runtime.project).create_chapter(
        runtime.project.list_volumes()[0].id,
        "Opening",
        "1",
        "old letter",
    )

    result = runtime.agent_runtime.discuss_plot_with_tools(
        user_message="怎么处理旧信？",
        current_manuscript="old letter",
        chapter_requirement="保持悬念",
        chapter_id=chapter.id,
        model_provider_id="ignored",
        model_id="ignored",
        output_token_limit=200,
    )

    assert runtime.workspace.summary().title == "Runtime Novel"
    assert runtime.generation_session.project is runtime.project
    assert callable(runtime.generation_session.recover_current)
    assert callable(runtime.generation_session.prepare_pre_accept_audit)
    assert runtime.generation_session.recover_current() is None
    assert result.status == AgentRunStatus.COMPLETED
    assert runtime.agent_repository.list_turns(result.run_id)
    runtime.close()


def test_project_runtime_opens_existing_project(tmp_path: Path) -> None:
    created = ProjectRuntime.create(
        tmp_path / "novel",
        "Runtime Novel",
        FakeModelRuntime(tmp_path),
    )
    created.close()

    opened = ProjectRuntime.open(tmp_path / "novel", FakeModelRuntime(tmp_path))

    assert opened.project.project.title == "Runtime Novel"
    assert opened.workspace.summary().root == (tmp_path / "novel").resolve()
    opened.close()


def test_project_runtime_shares_one_semantic_path_for_brief_and_prose(
    tmp_path: Path,
) -> None:
    model_runtime = EmbeddingModelRuntime(tmp_path)
    runtime = ProjectRuntime.create(
        tmp_path / "semantic-novel",
        "Semantic Novel",
        model_runtime,
    )
    chapters = ChapterRepository(runtime.project)
    volume = runtime.project.list_volumes()[0]
    previous = chapters.create_chapter(volume.id, "Opening", "1", "Earlier chapter")
    current = chapters.create_chapter(volume.id, "Visit", "2", "")
    requirements = ChapterRequirementRepository(runtime.project)
    requirement = requirements.get_or_create(current.id)
    requirements.update(
        current.id,
        "secret inheritance claim",
        is_locked=True,
        expected_revision=requirement.revision,
    )
    document = SearchRepository(runtime.project).index_document(
        document_type="CANON",
        source_id="canon-hidden-heir",
        chapter_id=previous.id,
        title="harbor succession",
        content="The duke privately named his youngest child as the heir.",
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )

    report = runtime.rebuild_pending_embeddings(limit=10, batch_size=2)
    brief = runtime.brief_service.load_or_compile(current.id, 1_000)
    prose_blocks = runtime.generation_session.context.memory_context.blocks(
        current.id,
        "secret inheritance claim",
        (),
    )

    brief_history = runtime.brief_service.compiler.context_provider.history
    prose_history = runtime.generation_session.context.memory_context.history
    assert brief_history is prose_history
    assert isinstance(brief_history.embedding_recall, StoredEmbeddingRecallProvider)
    assert brief_history.embedding_recall.query_embeddings is runtime.embedding_index.provider
    assert report.model_id == "embedding-model"
    assert report.selected_sources == report.indexed_embeddings == 1
    assert report.failures == ()
    assert document.source_id in {
        source.source_id
        for source in runtime.brief_service.repository.list_sources(brief.id)
    }
    assert any("harbor succession" in rule for rule in brief.style_rules)
    assert any("harbor succession" in block.content for block in prose_blocks)
    assert {request.model_id for request in model_runtime.adapter.embedding_requests} == {
        "embedding-model"
    }


def test_project_runtime_without_embedding_route_keeps_lexical_and_subject_recall(
    tmp_path: Path,
) -> None:
    runtime = ProjectRuntime.create(
        tmp_path / "lexical-novel",
        "Lexical Novel",
        FakeModelRuntime(tmp_path),
    )
    chapters = ChapterRepository(runtime.project)
    volume = runtime.project.list_volumes()[0]
    previous = chapters.create_chapter(volume.id, "Opening", "1", "Earlier chapter")
    current = chapters.create_chapter(volume.id, "Visit", "2", "")
    requirements = ChapterRequirementRepository(runtime.project)
    requirement = requirements.get_or_create(current.id)
    requirements.update(
        current.id,
        "钟楼档案",
        is_locked=True,
        expected_revision=requirement.revision,
    )
    character = CharacterMemoryRepository(runtime.project).create_character("林岚")
    search = SearchRepository(runtime.project)
    lexical = search.index_document(
        document_type="CANON",
        source_id="canon-clocktower",
        chapter_id=previous.id,
        title="钟楼档案",
        content="钟楼档案记录了蓝色火焰。",
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )
    subject = search.index_document(
        document_type="CHARACTER_STATE",
        source_id="state-lan-injury",
        chapter_id=previous.id,
        title="林岚的旧伤",
        content="她在雨夜里再次感觉到左肩疼痛。",
        participants=(character.id,),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )

    brief = runtime.brief_service.load_or_compile(current.id, 1_000)
    prose_blocks = runtime.generation_session.context.memory_context.blocks(
        current.id,
        "钟楼档案",
        (),
        (character.id,),
    )

    brief_source_ids = {
        source.source_id
        for source in runtime.brief_service.repository.list_sources(brief.id)
    }
    prose_source_ids = {block.source_id for block in prose_blocks}
    assert lexical.source_id in brief_source_ids
    assert {lexical.source_id, subject.source_id} <= prose_source_ids


@pytest.mark.parametrize(
    ("limit", "batch_size"),
    [(0, 16), (251, 16), (10, 0), (10, 65)],
)
def test_project_runtime_embedding_rebuild_reuses_existing_bounds(
    tmp_path: Path,
    limit: int,
    batch_size: int,
) -> None:
    runtime = ProjectRuntime.create(
        tmp_path / f"bounded-{limit}-{batch_size}",
        "Bounded Novel",
        EmbeddingModelRuntime(tmp_path / f"model-{limit}-{batch_size}"),
    )

    with pytest.raises(ValueError, match="embedding"):
        runtime.rebuild_pending_embeddings(limit=limit, batch_size=batch_size)


def test_project_runtime_embedding_rebuild_reports_safe_provider_failure(
    tmp_path: Path,
) -> None:
    model_runtime = EmbeddingModelRuntime(
        tmp_path,
        error=ProviderProtocolError("unit-secret raw manuscript provider response"),
    )
    runtime = ProjectRuntime.create(
        tmp_path / "failed-rebuild",
        "Failed Rebuild",
        model_runtime,
    )
    SearchRepository(runtime.project).index_document(
        document_type="CANON",
        source_id="canon-sensitive",
        chapter_id=None,
        title="Sensitive title",
        content="Sensitive manuscript body",
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )

    report = runtime.rebuild_pending_embeddings(limit=10, batch_size=2)

    assert report.indexed_embeddings == 0
    assert len(report.failures) == 1
    assert report.failures[0].message == "Embedding 暂不可用"
    assert "unit-secret" not in report.failures[0].message
    assert "Sensitive" not in report.failures[0].message
    assert "provider response" not in report.failures[0].message
