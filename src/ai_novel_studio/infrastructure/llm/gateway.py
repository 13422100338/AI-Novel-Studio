from __future__ import annotations

import time
from collections.abc import Iterator, Mapping

from ai_novel_studio.infrastructure.llm.config_repository import ModelConfiguration
from ai_novel_studio.infrastructure.llm.credential_store import CredentialStore
from ai_novel_studio.infrastructure.llm.provider_adapter import (
    ProviderAdapter,
    ProviderRequestError,
)
from ai_novel_studio.infrastructure.llm.provider_profile import ProviderProfile
from ai_novel_studio.infrastructure.llm.retry_policy import RetryPolicy
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
    ModelProfile,
    ModelRoute,
    StreamEventKind,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.llm.usage_tracker import UsageTracker


class MissingCredentialError(LookupError):
    pass


class MissingProviderAdapterError(LookupError):
    pass


class LLMGateway:
    def __init__(
        self,
        configuration: ModelConfiguration,
        credentials: CredentialStore,
        adapters: Mapping[str, ProviderAdapter],
        usage_tracker: UsageTracker,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.configuration = configuration
        self.credentials = credentials
        self.adapters = dict(adapters)
        self.usage_tracker = usage_tracker
        self.retry_policy = retry_policy or RetryPolicy()

    def complete(
        self,
        purpose: TaskPurpose,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        *,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> LLMResponse:
        route, model, profile, adapter, api_key = self._resolve(purpose)
        request = LLMRequest(
            model_id=route.model_id,
            messages=messages,
            output_token_limit=output_token_limit,
            temperature=temperature,
            json_mode=json_mode,
        )
        started = time.perf_counter()
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                response = adapter.complete(request, profile, api_key)
                self.usage_tracker.record_success(
                    purpose,
                    route,
                    model,
                    response.usage,
                    output_token_limit=output_token_limit,
                    duration_ms=self._elapsed_ms(started),
                    retry_count=attempt - 1,
                )
                return response
            except ProviderRequestError:
                if attempt >= self.retry_policy.max_attempts:
                    self.usage_tracker.record_failure(
                        purpose,
                        route,
                        model,
                        output_token_limit=output_token_limit,
                        duration_ms=self._elapsed_ms(started),
                        retry_count=attempt - 1,
                    )
                    raise
                self._wait(attempt + 1)
        raise AssertionError("unreachable")

    def stream(
        self,
        purpose: TaskPurpose,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        *,
        temperature: float = 0.7,
    ) -> Iterator[LLMStreamEvent]:
        route, model, profile, adapter, api_key = self._resolve(purpose)
        request = LLMRequest(
            model_id=route.model_id,
            messages=messages,
            output_token_limit=output_token_limit,
            temperature=temperature,
            stream=True,
        )
        started = time.perf_counter()
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            emitted_content = False
            usage: LLMUsage | None = None
            try:
                for event in adapter.stream(request, profile, api_key):
                    if event.kind in {StreamEventKind.TEXT, StreamEventKind.REASONING}:
                        emitted_content = True
                    if event.usage is not None:
                        usage = event.usage
                    yield event
                    if event.kind == StreamEventKind.PARTIAL_FAILURE:
                        self.usage_tracker.record_failure(
                            purpose,
                            route,
                            model,
                            output_token_limit=output_token_limit,
                            duration_ms=self._elapsed_ms(started),
                            retry_count=attempt - 1,
                            partial_usage=usage,
                        )
                        return
                self.usage_tracker.record_success(
                    purpose,
                    route,
                    model,
                    usage or LLMUsage(estimated=True),
                    output_token_limit=output_token_limit,
                    duration_ms=self._elapsed_ms(started),
                    retry_count=attempt - 1,
                )
                return
            except ProviderRequestError:
                if emitted_content or attempt >= self.retry_policy.max_attempts:
                    self.usage_tracker.record_failure(
                        purpose,
                        route,
                        model,
                        output_token_limit=output_token_limit,
                        duration_ms=self._elapsed_ms(started),
                        retry_count=attempt - 1,
                        partial_usage=usage,
                    )
                    raise
                self._wait(attempt + 1)

    def _resolve(
        self, purpose: TaskPurpose
    ) -> tuple[ModelRoute, ModelProfile, ProviderProfile, ProviderAdapter, str]:
        route = self.configuration.routes.resolve(purpose)
        model = self.configuration.model(route)
        profile = self.configuration.provider(route.provider_id)
        adapter = self.adapters.get(profile.interface_type)
        if adapter is None:
            raise MissingProviderAdapterError(
                f"没有可用的接口适配器：{profile.interface_type}"
            )
        api_key = self.credentials.get(profile.credential_id)
        if not api_key:
            raise MissingCredentialError("当前模型连接尚未保存 API Key")
        return route, model, profile, adapter, api_key

    def _wait(self, next_attempt: int) -> None:
        delay = self.retry_policy.delay_before(next_attempt)
        if delay:
            time.sleep(delay)

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, round((time.perf_counter() - started) * 1000))
