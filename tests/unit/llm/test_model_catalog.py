from collections.abc import Iterator

from ai_novel_studio.infrastructure.llm import (
    CapabilityProbe,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
    ModelCatalog,
    ProviderProfile,
    StreamEventKind,
)


class ProbeAdapter:
    def __init__(self) -> None:
        self.requests = []

    def list_models(self, profile: ProviderProfile, api_key: str) -> tuple[str, ...]:
        return ("novel-pro",)

    def complete(self, request, profile, api_key):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        if request.json_mode:
            return LLMResponse('{"ok":true}', request.model_id, LLMUsage(5, 2))
        return LLMResponse("ok", request.model_id, LLMUsage(5, 2), reasoning="trace")

    def stream(self, request, profile, api_key) -> Iterator[LLMStreamEvent]:  # type: ignore[no-untyped-def]
        yield LLMStreamEvent(StreamEventKind.TEXT, text="ok")
        yield LLMStreamEvent(StreamEventKind.COMPLETED)

    def probe_tools(self, profile, api_key, model_id):  # type: ignore[no-untyped-def]
        return True


def _profile() -> ProviderProfile:
    return ProviderProfile(
        id="relay",
        name="中转",
        base_url="https://relay.example/v1",
        credential_id="credential-relay",
    )


def test_catalog_returns_unknown_capabilities_instead_of_guessing_from_name() -> None:
    models = ModelCatalog().refresh(ProbeAdapter(), _profile(), "secret")

    assert len(models) == 1
    assert models[0].model_id == "novel-pro"
    assert models[0].capabilities.streaming is None
    assert models[0].capabilities.tools is None


def test_capability_probe_records_only_observed_support() -> None:
    adapter = ProbeAdapter()
    result = CapabilityProbe().probe(adapter, _profile(), "secret", "novel-pro")

    assert result.basic_chat is True
    assert result.model_listing is True
    assert result.streaming is True
    assert result.strict_json is True
    assert result.reasoning is True
    assert result.usage_reporting is True
    assert result.tools is True
    json_request = next(request for request in adapter.requests if request.json_mode)
    assert "JSON" in json_request.messages[0].content
    assert json_request.output_token_limit >= 128
