from collections.abc import Iterator

import pytest

from ai_novel_studio.application.embedding_index_service import (
    DocumentEmbeddingProvider,
)
from ai_novel_studio.application.gateway_embedding_provider import (
    GatewayEmbeddingProvider,
)
from ai_novel_studio.core.context.history_retriever import (
    EmbeddingUnavailableError,
    QueryEmbeddingProvider,
)
from ai_novel_studio.infrastructure.llm import (
    EmbeddingRequest,
    LLMGateway,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    MemoryCredentialStore,
    ModelConfiguration,
    ModelProfile,
    ModelRoute,
    ProviderAdapter,
    ProviderProfile,
    ProviderProtocolError,
    ProviderRequestError,
    RetryPolicy,
    TaskPurpose,
    TaskRoutes,
    UsageTracker,
)


class _EmbeddingAdapter:
    def __init__(
        self,
        results: list[tuple[tuple[float, ...], ...] | Exception],
    ) -> None:
        self.results = list(results)
        self.calls: list[tuple[EmbeddingRequest, ProviderProfile, str]] = []

    def list_models(self, profile: ProviderProfile, api_key: str) -> tuple[str, ...]:
        return ()

    def complete(
        self,
        request: LLMRequest,
        profile: ProviderProfile,
        api_key: str,
    ) -> LLMResponse:
        raise AssertionError("completion must not be used for embeddings")

    def stream(
        self,
        request: LLMRequest,
        profile: ProviderProfile,
        api_key: str,
    ) -> Iterator[LLMStreamEvent]:
        return iter(())

    def embed(
        self,
        request: EmbeddingRequest,
        profile: ProviderProfile,
        api_key: str,
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append((request, profile, api_key))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _configuration(*, embedding_route: bool = True) -> ModelConfiguration:
    provider = ProviderProfile(
        id="relay",
        name="Relay",
        base_url="https://relay.example/v1",
        credential_id="credential-relay",
    )
    route = ModelRoute("relay", "embedding-model")
    return ModelConfiguration(
        providers=(provider,),
        models=(ModelProfile(provider_id="relay", model_id="embedding-model"),),
        routes=TaskRoutes(
            plot=route,
            prose=route,
            overrides=(
                ((TaskPurpose.MEMORY_EMBEDDING, route),)
                if embedding_route
                else ()
            ),
        ),
    )


def _gateway(
    adapter: ProviderAdapter | None,
    *,
    embedding_route: bool = True,
    credential: bool = True,
) -> LLMGateway:
    credentials = MemoryCredentialStore()
    if credential:
        credentials.set("credential-relay", "unit-secret")
    adapters = {"openai_compatible": adapter} if adapter is not None else {}
    return LLMGateway(
        _configuration(embedding_route=embedding_route),
        credentials,
        adapters,
        UsageTracker(),
        RetryPolicy(max_attempts=1, base_delay_seconds=0),
    )


def test_gateway_embedding_provider_uses_one_route_for_documents_and_query() -> None:
    adapter = _EmbeddingAdapter(
        [
            ((0.1, 0.2), (0.3, 0.4)),
            ((0.5, 0.6),),
        ]
    )
    provider = GatewayEmbeddingProvider(_gateway(adapter))
    document_provider: DocumentEmbeddingProvider = provider
    query_provider: QueryEmbeddingProvider = provider

    document_vectors = document_provider.embed_documents(("first", "second"))
    query_vector = query_provider.embed_query("question")

    assert document_provider.model_id == query_provider.model_id == "embedding-model"
    assert document_vectors == ((0.1, 0.2), (0.3, 0.4))
    assert query_vector == (0.5, 0.6)
    assert [call[0] for call in adapter.calls] == [
        EmbeddingRequest("embedding-model", ("first", "second")),
        EmbeddingRequest("embedding-model", ("question",)),
    ]


def test_gateway_embedding_provider_normalizes_missing_route() -> None:
    provider = GatewayEmbeddingProvider(
        _gateway(_EmbeddingAdapter([]), embedding_route=False)
    )

    with pytest.raises(EmbeddingUnavailableError, match="暂不可用"):
        _ = provider.model_id


@pytest.mark.parametrize("failure", ["credential", "adapter"])
def test_gateway_embedding_provider_normalizes_gateway_configuration_errors(
    failure: str,
) -> None:
    adapter = _EmbeddingAdapter([])
    provider = GatewayEmbeddingProvider(
        _gateway(
            None if failure == "adapter" else adapter,
            credential=failure != "credential",
        )
    )

    with pytest.raises(EmbeddingUnavailableError, match="暂不可用"):
        provider.embed_query("sensitive query")


@pytest.mark.parametrize(
    "error",
    [
        ProviderRequestError("unit-secret sensitive query"),
        ProviderProtocolError("raw provider response sensitive query"),
    ],
)
def test_gateway_embedding_provider_normalizes_known_provider_errors(
    error: Exception,
) -> None:
    provider = GatewayEmbeddingProvider(_gateway(_EmbeddingAdapter([error])))

    with pytest.raises(EmbeddingUnavailableError) as captured:
        provider.embed_query("sensitive query")

    assert str(captured.value) == "Embedding 暂不可用"
    assert "unit-secret" not in str(captured.value)
    assert "sensitive query" not in str(captured.value)
    assert "raw provider response" not in str(captured.value)
