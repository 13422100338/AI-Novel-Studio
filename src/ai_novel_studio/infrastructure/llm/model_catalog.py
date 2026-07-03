from __future__ import annotations

import json
from dataclasses import dataclass

from ai_novel_studio.infrastructure.llm.provider_adapter import ProviderAdapter, ProviderError
from ai_novel_studio.infrastructure.llm.provider_profile import ProviderProfile
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMMessage,
    LLMRequest,
    ModelCapabilities,
    ModelProfile,
    StreamEventKind,
)


class ModelCatalog:
    def refresh(
        self,
        adapter: ProviderAdapter,
        profile: ProviderProfile,
        api_key: str,
    ) -> tuple[ModelProfile, ...]:
        return tuple(
            ModelProfile(provider_id=profile.id, model_id=model_id)
            for model_id in adapter.list_models(profile, api_key)
        )


@dataclass(frozen=True, slots=True)
class CapabilityProbeResult:
    basic_chat: bool | None = None
    model_listing: bool | None = None
    streaming: bool | None = None
    strict_json: bool | None = None
    reasoning: bool | None = None
    tools: bool | None = None
    usage_reporting: bool | None = None

    def to_model_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            streaming=self.streaming,
            reasoning=self.reasoning,
            tools=self.tools,
            strict_json=self.strict_json,
        )


class CapabilityProbe:
    def probe(
        self,
        adapter: ProviderAdapter,
        profile: ProviderProfile,
        api_key: str,
        model_id: str,
    ) -> CapabilityProbeResult:
        model_listing = self._probe_listing(adapter, profile, api_key)
        basic_chat: bool | None = None
        reasoning: bool | None = None
        usage_reporting: bool | None = None
        streaming: bool | None = None
        strict_json: bool | None = None
        try:
            response = adapter.complete(self._request(model_id, "只回复 ok"), profile, api_key)
            basic_chat = bool(response.text.strip())
            reasoning = True if response.reasoning.strip() else None
            usage_reporting = (
                response.usage.input_tokens is not None
                or response.usage.output_tokens is not None
            )
        except (ProviderError, ValueError):
            basic_chat = False
        try:
            events = tuple(
                adapter.stream(
                    self._request(model_id, "只回复 ok", stream=True), profile, api_key
                )
            )
            streaming = any(event.kind == StreamEventKind.COMPLETED for event in events)
        except (ProviderError, ValueError):
            streaming = False
        try:
            response = adapter.complete(
                self._request(model_id, '只回复 {"ok": true}', json_mode=True),
                profile,
                api_key,
            )
            strict_json = isinstance(json.loads(response.text), dict)
        except (ProviderError, ValueError, json.JSONDecodeError):
            strict_json = False
        return CapabilityProbeResult(
            basic_chat=basic_chat,
            model_listing=model_listing,
            streaming=streaming,
            strict_json=strict_json,
            reasoning=reasoning,
            tools=None,
            usage_reporting=usage_reporting,
        )

    @staticmethod
    def _probe_listing(
        adapter: ProviderAdapter,
        profile: ProviderProfile,
        api_key: str,
    ) -> bool:
        try:
            adapter.list_models(profile, api_key)
            return True
        except ProviderError:
            return False

    @staticmethod
    def _request(
        model_id: str,
        instruction: str,
        *,
        stream: bool = False,
        json_mode: bool = False,
    ) -> LLMRequest:
        return LLMRequest(
            model_id=model_id,
            messages=(LLMMessage("user", instruction),),
            output_token_limit=32,
            temperature=0,
            stream=stream,
            json_mode=json_mode,
        )
