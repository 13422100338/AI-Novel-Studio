from collections.abc import Iterator

import pytest

from ai_novel_studio.infrastructure.llm import (
    ContractValidationError,
    EmbeddingRequest,
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
    MissingProviderAdapterError,
    ModelConfiguration,
    ModelProfile,
    ModelRoute,
    ModelSamplingParameters,
    OpenAICompatibleAdapter,
    ProviderAdapter,
    ProviderProfile,
    ProviderProtocolError,
    ProviderRequestError,
    RetryPolicy,
    StreamEventKind,
    TaskPurpose,
    TaskRoutes,
    TransportResponse,
    UsageTracker,
)


class FakeAdapter:
    def __init__(self) -> None:
        self.complete_results: list[LLMResponse | Exception] = []
        self.embedding_results: list[tuple[tuple[float, ...], ...] | Exception] = []
        self.stream_events: list[LLMStreamEvent] = []
        self.complete_calls = []
        self.embedding_calls: list[tuple[EmbeddingRequest, ProviderProfile, str]] = []
        self.stream_calls = 0

    def list_models(self, profile, api_key):  # type: ignore[no-untyped-def]
        return ()

    def complete(self, request, profile, api_key):  # type: ignore[no-untyped-def]
        self.complete_calls.append((request, profile, api_key))
        result = self.complete_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def embed(self, request, profile, api_key):  # type: ignore[no-untyped-def]
        self.embedding_calls.append((request, profile, api_key))
        result = self.embedding_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def stream(self, request, profile, api_key) -> Iterator[LLMStreamEvent]:  # type: ignore[no-untyped-def]
        self.stream_calls += 1
        yield from self.stream_events


class LegacyTextAdapter:
    def __init__(self) -> None:
        self.complete_calls = 0

    def list_models(self, profile, api_key):  # type: ignore[no-untyped-def]
        return ()

    def complete(self, request, profile, api_key):  # type: ignore[no-untyped-def]
        self.complete_calls += 1
        return LLMResponse("legacy-ok", request.model_id, LLMUsage(2, 1))

    def stream(self, request, profile, api_key) -> Iterator[LLMStreamEvent]:  # type: ignore[no-untyped-def]
        yield LLMStreamEvent(StreamEventKind.COMPLETED)


class SequencedTransport:
    def __init__(self, responses: list[TransportResponse]) -> None:
        self.responses = list(responses)
        self.request_calls = 0

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: int,
    ) -> TransportResponse:
        self.request_calls += 1
        return self.responses.pop(0)

    def stream(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: int,
    ) -> Iterator[bytes]:
        return iter(())


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
        routes=TaskRoutes(
            plot=route,
            prose=route,
            overrides=((TaskPurpose.MEMORY_EMBEDDING, route),),
        ),
    )


def _gateway(
    adapter: ProviderAdapter,
    credentials: MemoryCredentialStore | None = None,
) -> LLMGateway:
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


def test_legacy_text_adapter_remains_usable_for_completion() -> None:
    adapter = LegacyTextAdapter()
    gateway = _gateway(adapter)

    response = gateway.complete(
        TaskPurpose.PROSE_GENERATION,
        (LLMMessage("user", "request"),),
        100,
    )

    assert response.text == "legacy-ok"
    assert adapter.complete_calls == 1


def test_embedding_route_rejects_legacy_text_adapter_before_provider_call() -> None:
    adapter = LegacyTextAdapter()
    gateway = _gateway(adapter)

    with pytest.raises(MissingProviderAdapterError, match="Embedding"):
        gateway.embed(TaskPurpose.MEMORY_EMBEDDING, ("text",))

    assert adapter.complete_calls == 0


def test_gateway_embeds_with_the_explicit_route_without_recording_completion_usage() -> None:
    adapter = FakeAdapter()
    adapter.embedding_results = [((0.1, 0.2), (0.3, 0.4))]
    gateway = _gateway(adapter)

    vectors = gateway.embed(
        TaskPurpose.MEMORY_EMBEDDING,
        ("first", "second"),
    )

    assert vectors == ((0.1, 0.2), (0.3, 0.4))
    request, profile, api_key = adapter.embedding_calls[0]
    assert request == EmbeddingRequest("novel-pro", ("first", "second"))
    assert profile.id == "relay"
    assert api_key == "secret"
    assert gateway.usage_tracker.records == ()


def test_gateway_retries_embedding_provider_request_errors_only() -> None:
    adapter = FakeAdapter()
    adapter.embedding_results = [
        ProviderRequestError("temporary"),
        ((0.1, 0.2),),
    ]
    gateway = _gateway(adapter)

    vectors = gateway.embed(TaskPurpose.MEMORY_EMBEDDING, ("text",))

    assert vectors == ((0.1, 0.2),)
    assert len(adapter.embedding_calls) == 2
    assert gateway.usage_tracker.records == ()


@pytest.mark.parametrize("status", [429, 503])
def test_gateway_retries_retryable_http_embedding_failures(status: int) -> None:
    transport = SequencedTransport(
        [
            TransportResponse(status, b""),
            TransportResponse(200, b'{"data":[{"index":0,"embedding":[0.1]}]}'),
        ]
    )
    gateway = _gateway(OpenAICompatibleAdapter(transport))

    vectors = gateway.embed(TaskPurpose.MEMORY_EMBEDDING, ("text",))

    assert vectors == ((0.1,),)
    assert transport.request_calls == 2


def test_gateway_raises_the_final_embedding_request_error_after_retries() -> None:
    adapter = FakeAdapter()
    error = ProviderRequestError("safe final error")
    adapter.embedding_results = [error, error]
    gateway = _gateway(adapter)

    with pytest.raises(ProviderRequestError) as captured:
        gateway.embed(TaskPurpose.MEMORY_EMBEDDING, ("text",))

    assert captured.value is error
    assert len(adapter.embedding_calls) == 2
    assert gateway.usage_tracker.records == ()


def test_gateway_does_not_retry_embedding_protocol_errors() -> None:
    adapter = FakeAdapter()
    error = ProviderProtocolError("damaged embedding response")
    adapter.embedding_results = [error]
    gateway = _gateway(adapter)

    with pytest.raises(ProviderProtocolError) as captured:
        gateway.embed(TaskPurpose.MEMORY_EMBEDDING, ("text",))

    assert captured.value is error
    assert len(adapter.embedding_calls) == 1


def test_gateway_rejects_empty_embedding_input_before_resolution_or_network() -> None:
    adapter = FakeAdapter()
    gateway = LLMGateway(
        ModelConfiguration.empty(),
        MemoryCredentialStore(),
        {"openai_compatible": adapter},
        UsageTracker(),
    )

    with pytest.raises(ValueError, match="input"):
        gateway.embed(TaskPurpose.MEMORY_EMBEDDING, ())

    assert adapter.embedding_calls == []


def test_gateway_embedding_rejects_non_embedding_purposes() -> None:
    adapter = FakeAdapter()
    gateway = _gateway(adapter)

    with pytest.raises(ValueError, match="MEMORY_EMBEDDING"):
        gateway.embed(TaskPurpose.PROSE_GENERATION, ("text",))

    assert adapter.embedding_calls == []


def test_gateway_embedding_requires_an_explicit_route() -> None:
    adapter = FakeAdapter()
    configuration = _configuration()
    gateway = LLMGateway(
        ModelConfiguration(
            providers=configuration.providers,
            models=configuration.models,
            routes=TaskRoutes(
                plot=configuration.routes.plot,
                prose=configuration.routes.prose,
            ),
        ),
        MemoryCredentialStore(),
        {"openai_compatible": adapter},
        UsageTracker(),
    )

    with pytest.raises(LookupError, match="Embedding"):
        gateway.embed(TaskPurpose.MEMORY_EMBEDDING, ("text",))

    assert adapter.embedding_calls == []


def test_gateway_embedding_reports_missing_credential_without_calling_adapter() -> None:
    adapter = FakeAdapter()
    gateway = LLMGateway(
        _configuration(),
        MemoryCredentialStore(),
        {"openai_compatible": adapter},
        UsageTracker(),
    )

    with pytest.raises(MissingCredentialError, match="API Key"):
        gateway.embed(TaskPurpose.MEMORY_EMBEDDING, ("text",))

    assert adapter.embedding_calls == []


def test_gateway_applies_per_model_sampling_overrides() -> None:
    adapter = FakeAdapter()
    adapter.complete_results = [LLMResponse("ok", "novel-pro")]
    configuration = _configuration()
    configured_model = ModelProfile(
        provider_id="relay",
        model_id="novel-pro",
        sampling=ModelSamplingParameters(
            temperature=1.1,
            top_p=0.9,
            frequency_penalty=0.2,
            presence_penalty=-0.1,
        ),
    )
    credentials = MemoryCredentialStore()
    credentials.set("credential-relay", "secret")
    gateway = LLMGateway(
        ModelConfiguration(
            providers=configuration.providers,
            models=(configured_model,),
            routes=configuration.routes,
        ),
        credentials,
        {"openai_compatible": adapter},
        UsageTracker(),
    )

    gateway.complete(
        TaskPurpose.PLOT_DISCUSSION,
        (LLMMessage("user", "请求"),),
        100,
        temperature=0.3,
    )

    request = adapter.complete_calls[0][0]
    assert request.temperature == 1.1
    assert request.top_p == 0.9
    assert request.frequency_penalty == 0.2
    assert request.presence_penalty == -0.1


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
