import json
from collections.abc import Iterator
from urllib.error import HTTPError, URLError

import pytest

import ai_novel_studio.infrastructure.llm.provider_adapter as provider_adapter_module
from ai_novel_studio.infrastructure.llm import (
    EmbeddingRequest,
    LLMMessage,
    LLMRequest,
    OpenAICompatibleAdapter,
    ProviderProfile,
    ProviderProtocolError,
    ProviderRequestError,
    StreamEventKind,
    TransportResponse,
    UrllibTransport,
)


class FakeTransport:
    def __init__(self, responses: list[TransportResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.stream_lines: list[bytes] = []
        self.calls: list[tuple[str, str, dict[str, str], bytes | None, int]] = []
        self.stream_error: Exception | None = None

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: int,
    ) -> TransportResponse:
        self.calls.append((method, url, headers, body, timeout_seconds))
        return self.responses.pop(0)

    def stream(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: int,
    ) -> Iterator[bytes]:
        self.calls.append((method, url, headers, body, timeout_seconds))
        yield from self.stream_lines
        if self.stream_error is not None:
            raise self.stream_error


def _profile() -> ProviderProfile:
    return ProviderProfile(
        id="relay",
        name="第三方中转",
        base_url="https://relay.example/openai/v1",
        credential_id="credential-relay",
        timeout_seconds=123,
    )


def _request(
    *,
    stream: bool = False,
    json_mode: bool = False,
    model_id: str = "novel-pro",
) -> LLMRequest:
    return LLMRequest(
        model_id=model_id,
        messages=(LLMMessage("system", "规则"), LLMMessage("user", "请求")),
        output_token_limit=32_000,
        temperature=0.4,
        stream=stream,
        json_mode=json_mode,
    )


def test_lists_models_from_third_party_base_url_with_bearer_auth() -> None:
    transport = FakeTransport(
        [TransportResponse(200, b'{"data":[{"id":"model-b"},{"id":"model-a"}]}')]
    )
    adapter = OpenAICompatibleAdapter(transport)

    models = adapter.list_models(_profile(), "sk-private")

    assert models == ("model-a", "model-b")
    method, url, headers, body, timeout = transport.calls[0]
    assert (method, url, body, timeout) == (
        "GET",
        "https://relay.example/openai/v1/models",
        None,
        123,
    )
    assert headers["Authorization"] == "Bearer sk-private"


def test_complete_parses_text_reasoning_and_detailed_usage() -> None:
    body = b"""{
      "model":"novel-pro",
      "choices":[{"message":{"content":"answer","reasoning_content":"thinking"},"finish_reason":"stop"}],
      "usage":{"prompt_tokens":100,"completion_tokens":40,
        "prompt_tokens_details":{"cached_tokens":60},
        "completion_tokens_details":{"reasoning_tokens":15}}
    }"""
    transport = FakeTransport([TransportResponse(200, body)])

    response = OpenAICompatibleAdapter(transport).complete(
        _request(json_mode=True), _profile(), "sk-private"
    )

    assert response.text == "answer"
    assert response.reasoning == "thinking"
    assert response.finish_reason == "stop"
    assert response.usage.input_tokens == 100
    assert response.usage.output_tokens == 40
    assert response.usage.cached_input_tokens == 60
    assert response.usage.reasoning_tokens == 15
    assert response.usage.estimated is False
    request_body = transport.calls[0][3]
    assert request_body is not None
    assert b'"max_tokens": 32000' in request_body
    assert b'"response_format": {"type": "json_object"}' in request_body


def test_embeddings_post_batch_and_restore_input_order() -> None:
    body = b'''{
      "data":[
        {"index":1,"embedding":[0.3,0.4]},
        {"index":0,"embedding":[0.1,0.2]}
      ]
    }'''
    transport = FakeTransport([TransportResponse(200, body)])

    vectors = OpenAICompatibleAdapter(transport).embed(
        EmbeddingRequest("embedding-model", ("first", "second")),
        _profile(),
        "sk-private",
    )

    assert vectors == ((0.1, 0.2), (0.3, 0.4))
    method, url, headers, request_body, timeout = transport.calls[0]
    assert (method, url, timeout) == (
        "POST",
        "https://relay.example/openai/v1/embeddings",
        123,
    )
    assert headers["Authorization"] == "Bearer sk-private"
    assert request_body is not None
    assert json.loads(request_body) == {
        "model": "embedding-model",
        "input": ["first", "second"],
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"data": [{"index": 0, "embedding": [0.1, 0.2]}]},
        {
            "data": [
                {"index": True, "embedding": [0.1, 0.2]},
                {"index": 1, "embedding": [0.3, 0.4]},
            ]
        },
        {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2]},
                {"index": 0, "embedding": [0.3, 0.4]},
            ]
        },
        {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2]},
                {"index": 2, "embedding": [0.3, 0.4]},
            ]
        },
        {
            "data": [
                {"index": 0, "embedding": []},
                {"index": 1, "embedding": [0.3, 0.4]},
            ]
        },
        {
            "data": [
                {"index": 0, "embedding": [True, 0.2]},
                {"index": 1, "embedding": [0.3, 0.4]},
            ]
        },
        {
            "data": [
                {"index": 0, "embedding": [float("nan"), 0.2]},
                {"index": 1, "embedding": [0.3, 0.4]},
            ]
        },
        {
            "data": [
                {"index": 0, "embedding": [10**400, 0.2]},
                {"index": 1, "embedding": [0.3, 0.4]},
            ]
        },
        {
            "data": [
                {"index": 0, "embedding": [0.1]},
                {"index": 1, "embedding": [0.3, 0.4]},
            ]
        },
    ],
)
def test_embeddings_reject_untrusted_response_shapes(payload: object) -> None:
    transport = FakeTransport(
        [TransportResponse(200, json.dumps(payload).encode("utf-8"))]
    )

    with pytest.raises(ProviderProtocolError):
        OpenAICompatibleAdapter(transport).embed(
            EmbeddingRequest("embedding-model", ("first", "second")),
            _profile(),
            "sk-private",
        )


@pytest.mark.parametrize("body", [b"not-json", b'{}', b'{"data":{}}'])
def test_embeddings_normalize_damaged_json_and_fields(body: bytes) -> None:
    transport = FakeTransport([TransportResponse(200, body)])

    with pytest.raises(ProviderProtocolError):
        OpenAICompatibleAdapter(transport).embed(
            EmbeddingRequest("embedding-model", ("text",)),
            _profile(),
            "sk-private",
        )


@pytest.mark.parametrize(
    "body",
    [
        b'{"data":[{"index":0,"embedding":[' + (b"9" * 5_000) + b"]}]}",
        (b"[" * 10_000) + b"0" + (b"]" * 10_000),
    ],
    ids=["oversized-integer", "recursive-json"],
)
def test_embeddings_normalize_extreme_json_parser_failures(body: bytes) -> None:
    transport = FakeTransport([TransportResponse(200, body)])

    with pytest.raises(ProviderProtocolError):
        OpenAICompatibleAdapter(transport).embed(
            EmbeddingRequest("embedding-model", ("text",)),
            _profile(),
            "sk-private",
        )


def test_embeddings_reject_vectors_over_dimension_limit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(provider_adapter_module, "_MAX_EMBEDDING_DIMENSIONS", 2)
    transport = FakeTransport(
        [TransportResponse(200, b'{"data":[{"index":0,"embedding":[1,2,3]}]}')]
    )

    with pytest.raises(ProviderProtocolError, match="维度"):
        OpenAICompatibleAdapter(transport).embed(
            EmbeddingRequest("embedding-model", ("text",)),
            _profile(),
            "sk-private",
        )


def test_embedding_request_rejects_empty_input_before_transport() -> None:
    transport = FakeTransport()

    with pytest.raises(ValueError, match="input"):
        OpenAICompatibleAdapter(transport).embed(
            EmbeddingRequest("embedding-model", ()),
            _profile(),
            "sk-private",
        )

    assert transport.calls == []


@pytest.mark.parametrize("text", ["", "   ", "\t\r\n"])
def test_embedding_request_rejects_blank_text_before_transport(text: str) -> None:
    transport = FakeTransport()

    with pytest.raises(ValueError, match="空白"):
        OpenAICompatibleAdapter(transport).embed(
            EmbeddingRequest("embedding-model", (text,)),
            _profile(),
            "sk-private",
        )

    assert transport.calls == []


@pytest.mark.parametrize("status", [429, 503])
def test_embedding_http_error_never_echoes_secret_or_response_body(status: int) -> None:
    transport = FakeTransport(
        [TransportResponse(status, b'{"error":"Bearer sk-private request first"}')]
    )

    with pytest.raises(ProviderRequestError) as captured:
        OpenAICompatibleAdapter(transport).embed(
            EmbeddingRequest("embedding-model", ("first",)),
            _profile(),
            "sk-private",
        )

    message = str(captured.value)
    assert str(status) in message
    assert "sk-private" not in message
    assert "Bearer" not in message
    assert "first" not in message


def test_transport_connection_error_never_echoes_request_details(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_connection(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise URLError("Bearer sk-private request first")

    monkeypatch.setattr(
        "ai_novel_studio.infrastructure.llm.provider_adapter.urlopen",
        fail_connection,
    )

    with pytest.raises(ProviderRequestError) as captured:
        UrllibTransport().request(
            "POST",
            "https://relay.example/openai/v1/embeddings",
            {"Authorization": "Bearer sk-private"},
            b'{"input":["first"]}',
            90,
        )

    message = str(captured.value)
    assert "sk-private" not in message
    assert "Bearer" not in message
    assert "first" not in message


def test_transport_rejects_oversized_non_streaming_response(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class OversizedResponse:
        status = 200
        requested_size: int | None = None

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args):  # type: ignore[no-untyped-def]
            return False

        def read(self, size: int = -1) -> bytes:
            self.requested_size = size
            return b"x" * size

    response = OversizedResponse()
    monkeypatch.setattr(provider_adapter_module, "_MAX_PROVIDER_RESPONSE_BYTES", 4)
    monkeypatch.setattr(provider_adapter_module, "urlopen", lambda *_args, **_kwargs: response)

    with pytest.raises(ProviderProtocolError, match="大小"):
        UrllibTransport().request("GET", "https://relay.example/v1/models", {}, None, 5)

    assert response.requested_size == 5


def test_transport_closes_http_error_without_reading_body(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class ErrorBody:
        closed = False

        def read(self, _size: int = -1) -> bytes:
            raise AssertionError("HTTP error body must not be read")

        def close(self) -> None:
            self.closed = True

    error_body = ErrorBody()
    http_error = HTTPError(
        "https://relay.example/v1/models",
        503,
        "temporary",
        None,
        error_body,
    )

    def fail_request(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise http_error

    monkeypatch.setattr(provider_adapter_module, "urlopen", fail_request)

    response = UrllibTransport().request(
        "GET", "https://relay.example/v1/models", {}, None, 5
    )

    assert response == TransportResponse(503, b"")
    assert error_body.closed is True


def test_complete_sends_optional_sampling_parameters_when_configured() -> None:
    transport = FakeTransport(
        [TransportResponse(200, b'{"choices":[{"message":{"content":"ok"}}]}')]
    )
    request = LLMRequest(
        model_id="novel-pro",
        messages=(LLMMessage("user", "请求"),),
        output_token_limit=100,
        top_p=0.9,
        frequency_penalty=0.2,
        presence_penalty=-0.1,
    )

    OpenAICompatibleAdapter(transport).complete(request, _profile(), "secret")

    request_body = transport.calls[0][3]
    assert request_body is not None
    assert b'"top_p": 0.9' in request_body
    assert b'"frequency_penalty": 0.2' in request_body
    assert b'"presence_penalty": -0.1' in request_body


def test_deepseek_json_request_disables_thinking_to_preserve_final_content() -> None:
    body = b'''{
      "model":"deepseek-v4-pro",
      "choices":[{"message":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]
    }'''
    transport = FakeTransport([TransportResponse(200, body)])

    OpenAICompatibleAdapter(transport).complete(
        _request(json_mode=True, model_id="deepseek-v4-pro"),
        _profile(),
        "sk-private",
    )

    request_body = transport.calls[0][3]
    assert request_body is not None
    assert b'"thinking": {"type": "disabled"}' in request_body


def test_stream_preserves_text_order_and_emits_usage_then_completion() -> None:
    transport = FakeTransport()
    transport.stream_lines = [
        b'data: {"choices":[{"delta":{"content":"first"}}]}\n',
        b'data: {"choices":[{"delta":{"reasoning_content":"why"}}]}\n',
        b'data: {"choices":[],"usage":{"prompt_tokens":8,"completion_tokens":3}}\n',
        b"data: [DONE]\n",
    ]

    events = list(
        OpenAICompatibleAdapter(transport).stream(
            _request(stream=True), _profile(), "sk-private"
        )
    )

    assert [event.kind for event in events] == [
        StreamEventKind.TEXT,
        StreamEventKind.REASONING,
        StreamEventKind.USAGE,
        StreamEventKind.COMPLETED,
    ]
    assert events[0].text == "first"
    assert events[1].text == "why"
    assert events[2].usage is not None
    assert events[2].usage.input_tokens == 8


def test_stream_failure_after_text_becomes_partial_failure_event() -> None:
    transport = FakeTransport()
    transport.stream_lines = [b'data: {"choices":[{"delta":{"content":"partial"}}]}\n']
    transport.stream_error = OSError("socket closed")

    events = list(
        OpenAICompatibleAdapter(transport).stream(
            _request(stream=True), _profile(), "sk-private"
        )
    )

    assert [event.kind for event in events] == [
        StreamEventKind.TEXT,
        StreamEventKind.PARTIAL_FAILURE,
    ]
    assert "socket closed" not in events[-1].error


def test_http_error_never_echoes_api_key_or_response_body() -> None:
    transport = FakeTransport(
        [TransportResponse(401, b'{"error":"bad key sk-private"}')]
    )

    with pytest.raises(ProviderRequestError) as captured:
        OpenAICompatibleAdapter(transport).complete(
            _request(), _profile(), "sk-private"
        )

    message = str(captured.value)
    assert "401" in message
    assert "sk-private" not in message
    assert "bad key" not in message


def test_tool_probe_sends_function_schema_and_observes_tool_call() -> None:
    body = b'''{
      "model":"novel-pro",
      "choices":[{"message":{"content":null,"tool_calls":[{
        "id":"call_1","type":"function",
        "function":{"name":"capability_probe","arguments":"{\\"value\\":\\"ok\\"}"}
      }]},"finish_reason":"tool_calls"}]
    }'''
    transport = FakeTransport([TransportResponse(200, body)])
    adapter = OpenAICompatibleAdapter(transport)

    supported = adapter.probe_tools(_profile(), "sk-private", "novel-pro")

    assert supported is True
    request_body = transport.calls[0][3]
    assert request_body is not None
    assert b'"tools"' in request_body
    assert b'"tool_choice"' not in request_body
    assert b'"capability_probe"' in request_body
