from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ai_novel_studio.infrastructure.llm.provider_profile import ProviderProfile
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
    StreamEventKind,
)


class ProviderError(RuntimeError):
    pass


class ProviderRequestError(ProviderError):
    pass


class ProviderProtocolError(ProviderError):
    pass


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: int,
    ) -> TransportResponse: ...

    def stream(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: int,
    ) -> Iterator[bytes]: ...


class ProviderAdapter(Protocol):
    def list_models(self, profile: ProviderProfile, api_key: str) -> tuple[str, ...]: ...

    def complete(
        self,
        request: LLMRequest,
        profile: ProviderProfile,
        api_key: str,
    ) -> LLMResponse: ...

    def stream(
        self,
        request: LLMRequest,
        profile: ProviderProfile,
        api_key: str,
    ) -> Iterator[LLMStreamEvent]: ...


class UrllibTransport:
    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: int,
    ) -> TransportResponse:
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return TransportResponse(response.status, response.read())
        except HTTPError as error:
            return TransportResponse(error.code, error.read())
        except URLError as error:
            raise ProviderRequestError("无法连接模型服务") from error

    def stream(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: int,
    ) -> Iterator[bytes]:
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                yield from response
        except HTTPError as error:
            raise ProviderRequestError(f"模型服务请求失败（HTTP {error.code}）") from error
        except URLError as error:
            raise ProviderRequestError("模型流式连接中断") from error


class OpenAICompatibleAdapter:
    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._transport = transport or UrllibTransport()

    def list_models(self, profile: ProviderProfile, api_key: str) -> tuple[str, ...]:
        url = profile.models_url or f"{profile.base_url}/models"
        response = self._transport.request(
            "GET", url, self._headers(api_key), None, profile.timeout_seconds
        )
        self._require_success(response)
        payload = self._json_object(response.body)
        values = self._list(payload.get("data"), "模型列表 data")
        model_ids: list[str] = []
        for value in values:
            item = self._mapping(value, "模型列表条目")
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip():
                model_ids.append(model_id)
        return tuple(sorted(set(model_ids), key=str.casefold))

    def complete(
        self,
        request: LLMRequest,
        profile: ProviderProfile,
        api_key: str,
    ) -> LLMResponse:
        response = self._transport.request(
            "POST",
            f"{profile.base_url}/chat/completions",
            self._headers(api_key),
            self._request_body(request, stream=False),
            profile.timeout_seconds,
        )
        self._require_success(response)
        return self._response(self._json_object(response.body), request.model_id)

    def stream(
        self,
        request: LLMRequest,
        profile: ProviderProfile,
        api_key: str,
    ) -> Iterator[LLMStreamEvent]:
        received_content = False
        try:
            lines = self._transport.stream(
                "POST",
                f"{profile.base_url}/chat/completions",
                self._headers(api_key),
                self._request_body(request, stream=True),
                profile.timeout_seconds,
            )
            for raw_line in lines:
                line = raw_line.decode("utf-8").strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    yield LLMStreamEvent(StreamEventKind.COMPLETED)
                    return
                payload = self._json_object(data.encode("utf-8"))
                usage = self._usage(payload.get("usage"))
                if usage is not None:
                    yield LLMStreamEvent(StreamEventKind.USAGE, usage=usage)
                for event in self._delta_events(payload):
                    received_content = True
                    yield event
            yield LLMStreamEvent(StreamEventKind.COMPLETED)
        except (OSError, UnicodeError, ValueError, ProviderError, json.JSONDecodeError) as error:
            if received_content:
                yield LLMStreamEvent(
                    StreamEventKind.PARTIAL_FAILURE,
                    error="流式连接中断，已保留收到的部分内容",
                )
                return
            raise ProviderRequestError("流式请求失败，尚未收到内容") from error

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        if not api_key:
            raise ProviderRequestError("模型连接缺少 API Key")
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _request_body(request: LLMRequest, *, stream: bool) -> bytes:
        payload: dict[str, object] = {
            "model": request.model_id,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "max_tokens": request.output_token_limit,
            "temperature": request.temperature,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    @classmethod
    def _response(cls, payload: dict[str, object], fallback_model: str) -> LLMResponse:
        choices = cls._list(payload.get("choices"), "choices")
        if not choices:
            raise ProviderProtocolError("模型响应不包含 choices")
        choice = cls._mapping(choices[0], "choice")
        message = cls._mapping(choice.get("message"), "message")
        content = message.get("content")
        if not isinstance(content, str):
            raise ProviderProtocolError("模型响应正文不是文本")
        reasoning_value = message.get("reasoning_content", "")
        reasoning = reasoning_value if isinstance(reasoning_value, str) else ""
        model_value = payload.get("model")
        model_id = model_value if isinstance(model_value, str) else fallback_model
        finish_value = choice.get("finish_reason")
        finish_reason = finish_value if isinstance(finish_value, str) else None
        return LLMResponse(
            text=content,
            model_id=model_id,
            usage=cls._usage(payload.get("usage")) or LLMUsage(estimated=True),
            reasoning=reasoning,
            finish_reason=finish_reason,
        )

    @classmethod
    def _delta_events(cls, payload: dict[str, object]) -> Iterator[LLMStreamEvent]:
        choices_value = payload.get("choices")
        if choices_value is None:
            return
        choices = cls._list(choices_value, "choices")
        for value in choices:
            choice = cls._mapping(value, "choice")
            delta = cls._mapping(choice.get("delta"), "delta")
            content = delta.get("content")
            if isinstance(content, str) and content:
                yield LLMStreamEvent(StreamEventKind.TEXT, text=content)
            reasoning = delta.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                yield LLMStreamEvent(StreamEventKind.REASONING, text=reasoning)

    @classmethod
    def _usage(cls, value: object) -> LLMUsage | None:
        if value is None:
            return None
        data = cls._mapping(value, "usage")
        prompt_details = cls._optional_mapping(data.get("prompt_tokens_details"))
        completion_details = cls._optional_mapping(data.get("completion_tokens_details"))
        return LLMUsage(
            input_tokens=cls._optional_int(data.get("prompt_tokens")),
            output_tokens=cls._optional_int(data.get("completion_tokens")),
            cached_input_tokens=cls._optional_int(prompt_details.get("cached_tokens")),
            reasoning_tokens=cls._optional_int(completion_details.get("reasoning_tokens")),
            estimated=False,
        )

    @staticmethod
    def _require_success(response: TransportResponse) -> None:
        if not 200 <= response.status < 300:
            raise ProviderRequestError(f"模型服务请求失败（HTTP {response.status}）")

    @staticmethod
    def _json_object(raw: bytes) -> dict[str, object]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ProviderProtocolError("模型服务返回了无效 JSON") from error
        return OpenAICompatibleAdapter._mapping(value, "响应")

    @staticmethod
    def _mapping(value: object, field: str) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ProviderProtocolError(f"模型响应字段 {field} 不是对象")
        return cast(dict[str, object], value)

    @staticmethod
    def _optional_mapping(value: object) -> dict[str, object]:
        if value is None:
            return {}
        return OpenAICompatibleAdapter._mapping(value, "usage details")

    @staticmethod
    def _list(value: object, field: str) -> list[object]:
        if not isinstance(value, list):
            raise ProviderProtocolError(f"模型响应字段 {field} 不是数组")
        return cast(list[object], value)

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return None
