import json
from pathlib import Path

from ai_novel_studio.application.project_runtime import ProjectRuntime
from ai_novel_studio.domain.agent import AgentRunStatus
from ai_novel_studio.infrastructure.llm import (
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
    StreamEventKind,
    TaskRoutes,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository


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
        return LLMResponse(
            json.dumps({"action": "final", "final_answer": "检索建议"}),
            request.model_id,
        )

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
    assert runtime.generation_runtime.project is runtime.project
    assert callable(runtime.generation_runtime.recover)
    recovery_errors: list[str] = []
    runtime.generation_runtime.failed.connect(recovery_errors.append)
    runtime.generation_runtime.recover()
    assert recovery_errors == ["当前章节没有可恢复的正文草稿"]
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
