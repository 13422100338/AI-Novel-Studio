from collections.abc import Iterator

import pytest

from ai_novel_studio.infrastructure.llm import (
    ContractValidationError,
    JsonField,
    JsonObjectContract,
    LLMContractRunner,
    LLMGateway,
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
    MemoryCredentialStore,
    MissingCredentialError,
    ModelConfiguration,
    ModelProfile,
    ModelRoute,
    ProviderProfile,
    ProviderRequestError,
    RetryPolicy,
    StreamEventKind,
    TaskPurpose,
    TaskRoutes,
    UsageTracker,
)


class FakeAdapter:
    def __init__(self) -> None:
        self.complete_results: list[LLMResponse | Exception] = []
        self.stream_events: list[LLMStreamEvent] = []
        self.complete_calls = []
        self.stream_calls = 0

    def list_models(self, profile, api_key):  # type: ignore[no-untyped-def]
        return ()

    def complete(self, request, profile, api_key):  # type: ignore[no-untyped-def]
        self.complete_calls.append((request, profile, api_key))
        result = self.complete_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def stream(self, request, profile, api_key) -> Iterator[LLMStreamEvent]:  # type: ignore[no-untyped-def]
        self.stream_calls += 1
        yield from self.stream_events


def _configuration() -> ModelConfiguration:
    provider = ProviderProfile(
        id="relay",
        name="中转",
        base_url="https://relay.example/v1",
        credential_id="credential-relay",
    )
    model = ModelProfile(provider_id="relay", model_id="novel-pro")
    route = ModelRoute("relay", "novel-pro")
    return ModelConfiguration(
        providers=(provider,),
        models=(model,),
        routes=TaskRoutes(plot=route, prose=route),
    )


def _gateway(adapter: FakeAdapter, credentials: MemoryCredentialStore | None = None) -> LLMGateway:
    secrets = credentials or MemoryCredentialStore()
    if secrets.get("credential-relay") is None:
        secrets.set("credential-relay", "secret")
    return LLMGateway(
        _configuration(),
        secrets,
        {"openai_compatible": adapter},
        UsageTracker(),
        RetryPolicy(max_attempts=2, base_delay_seconds=0),
    )


def test_gateway_resolves_exact_route_and_passes_secret_only_to_adapter() -> None:
    adapter = FakeAdapter()
    adapter.complete_results = [LLMResponse("ok", "novel-pro", LLMUsage(10, 4))]
    gateway = _gateway(adapter)

    response = gateway.complete(
        TaskPurpose.CHAPTER_REQUIREMENT,
        (LLMMessage("user", "请求"),),
        12_345,
    )

    assert response.text == "ok"
    request, profile, api_key = adapter.complete_calls[0]
    assert request.model_id == "novel-pro"
    assert request.output_token_limit == 12_345
    assert profile.id == "relay"
    assert api_key == "secret"


def test_gateway_retries_once_only_before_any_content() -> None:
    adapter = FakeAdapter()
    adapter.complete_results = [
        ProviderRequestError("temporary"),
        LLMResponse("ok", "novel-pro", LLMUsage(10, 4)),
    ]
    gateway = _gateway(adapter)

    gateway.complete(TaskPurpose.PLOT_DISCUSSION, (LLMMessage("user", "请求"),), 100)

    assert len(adapter.complete_calls) == 2
    assert gateway.usage_tracker.snapshot().retry_count == 1


def test_gateway_does_not_retry_stream_after_partial_content() -> None:
    adapter = FakeAdapter()
    adapter.stream_events = [
        LLMStreamEvent(StreamEventKind.TEXT, text="partial"),
        LLMStreamEvent(StreamEventKind.PARTIAL_FAILURE, error="连接中断"),
    ]
    gateway = _gateway(adapter)

    events = tuple(
        gateway.stream(
            TaskPurpose.PLOT_DISCUSSION,
            (LLMMessage("user", "请求"),),
            100,
        )
    )

    assert events[-1].kind == StreamEventKind.PARTIAL_FAILURE
    assert adapter.stream_calls == 1


def test_gateway_reports_missing_credential_without_calling_adapter() -> None:
    adapter = FakeAdapter()
    credentials = MemoryCredentialStore()
    gateway = LLMGateway(
        _configuration(),
        credentials,
        {"openai_compatible": adapter},
        UsageTracker(),
    )

    with pytest.raises(MissingCredentialError, match="API Key"):
        gateway.complete(
            TaskPurpose.PLOT_DISCUSSION,
            (LLMMessage("user", "请求"),),
            100,
        )

    assert adapter.complete_calls == []


class ContractGateway:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[tuple[LLMMessage, ...]] = []

    def complete(self, purpose, messages, output_token_limit, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(messages)
        return LLMResponse(self.responses.pop(0), "model")


def test_json_contract_uses_one_specific_correction_request() -> None:
    gateway = ContractGateway(['{"title": 3}', '```json\n{"title":"正式要求"}\n```'])
    runner = LLMContractRunner(gateway)  # type: ignore[arg-type]
    contract = JsonObjectContract((JsonField("title", str),))

    result = runner.run_json(
        TaskPurpose.BRIEF_NORMALIZATION,
        (LLMMessage("user", "整理"),),
        1000,
        contract,
    )

    assert result == {"title": "正式要求"}
    assert len(gateway.calls) == 2
    assert "字段 title 必须是 str" in gateway.calls[1][-1].content


def test_second_invalid_contract_response_stops_without_guessing() -> None:
    gateway = ContractGateway(['{"title": 3}', '{"title": false}'])
    runner = LLMContractRunner(gateway)  # type: ignore[arg-type]
    contract = JsonObjectContract((JsonField("title", str),))

    with pytest.raises(ContractValidationError, match="两次"):
        runner.run_json(
            TaskPurpose.BRIEF_NORMALIZATION,
            (LLMMessage("user", "整理"),),
            1000,
            contract,
        )

    assert len(gateway.calls) == 2


def test_empty_first_json_response_can_issue_correction_without_empty_assistant() -> None:
    gateway = ContractGateway(["", '{"title":"正式要求"}'])
    runner = LLMContractRunner(gateway)  # type: ignore[arg-type]
    contract = JsonObjectContract((JsonField("title", str),))

    result = runner.run_json(
        TaskPurpose.BRIEF_NORMALIZATION,
        (LLMMessage("user", "整理"),),
        1000,
        contract,
    )

    assert result == {"title": "正式要求"}
    assert [message.role for message in gateway.calls[1]] == ["user", "user"]
