"""QP-2A: framework-neutral model configuration service.

Security contract under test:
- snapshots expose ``has_credential: bool`` only, never secret material;
- config JSON on disk never contains API keys;
- error messages are fixed and sanitized (no keys, headers, provider bodies);
- empty/None key never clears an existing credential; clearing is explicit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_novel_studio.application.model_configuration_service import (
    ModelConfigurationService,
    ModelConfigurationServiceError,
    ProviderSpec,
)
from ai_novel_studio.infrastructure.llm import (
    LLMResponse,
    MemoryCredentialStore,
    ModelConfigRepository,
    ProviderError,
)


class FakeAdapter:
    """Deterministic offline adapter recording the keys it was given."""

    interface = "openai_compatible"

    def __init__(self, *, list_error: str | None = None) -> None:
        self.keys: list[str] = []
        self._list_error = list_error

    def list_models(self, profile, api_key: str):
        self.keys.append(api_key)
        if self._list_error is not None:
            raise ProviderError(self._list_error)
        return ("model-alpha", "model-beta")

    def complete(self, request, profile, api_key: str):
        self.keys.append(api_key)
        if self._list_error is not None:
            raise ProviderError(self._list_error)
        return LLMResponse(text="ok", model_id=request.model_id)

    def stream(self, request, profile, api_key: str):
        self.keys.append(api_key)
        if self._list_error is not None:
            raise ProviderError(self._list_error)
        return ()


def _service(tmp_path: Path, adapter: FakeAdapter | None = None) -> tuple[
    ModelConfigurationService,
    Path,
    MemoryCredentialStore,
]:
    credentials = MemoryCredentialStore()
    repository = ModelConfigRepository(tmp_path / "model-config.json", credentials)
    adapters = {"openai_compatible": adapter} if adapter is not None else {}
    service = ModelConfigurationService(
        repository=repository,
        credentials=credentials,
        adapters=adapters,
    )
    return service, tmp_path / "model-config.json", credentials


def _seed_provider(
    service: ModelConfigurationService,
    *,
    api_key: str | None = "sk-test-123",
) -> str:
    snapshot = service.upsert_provider(
        ProviderSpec(
            id=None,
            name="默认连接",
            base_url="https://api.example.com/v1",
            models_url=None,
            interface_type="openai_compatible",
            timeout_seconds=60,
        ),
        api_key=api_key,
    )
    assert snapshot.providers
    return snapshot.providers[0].id


def test_load_empty_snapshot_has_no_providers_or_credentials(tmp_path: Path) -> None:
    service, _config_path, _credentials = _service(tmp_path)

    snapshot = service.load_snapshot()

    assert snapshot.providers == ()
    assert snapshot.models == ()
    assert snapshot.plot_route is None
    assert snapshot.prose_route is None


def test_upsert_provider_reports_has_credential_without_secret(
    tmp_path: Path,
) -> None:
    service, _config_path, _credentials = _service(tmp_path)

    snapshot = service.upsert_provider(
        ProviderSpec(
            id=None,
            name="连接A",
            base_url="https://api.example.com/v1",
            models_url=None,
            interface_type="openai_compatible",
            timeout_seconds=30,
        ),
        api_key="sk-live-abc",
    )

    assert len(snapshot.providers) == 1
    provider = snapshot.providers[0]
    assert provider.has_credential is True
    dumped = json.dumps(snapshot.as_dict())
    assert "sk-live-abc" not in dumped


def test_editing_provider_with_empty_key_keeps_existing_credential(
    tmp_path: Path,
) -> None:
    service, _config_path, _credentials = _service(tmp_path)
    provider_id = _seed_provider(service)

    edited = service.upsert_provider(
        ProviderSpec(
            id=provider_id,
            name="改名后的连接",
            base_url="https://api2.example.com/v1",
            models_url=None,
            interface_type="openai_compatible",
            timeout_seconds=45,
        ),
        api_key=None,
    )
    assert edited.providers[0].has_credential is True

    cleared = service.upsert_provider(
        ProviderSpec(
            id=provider_id,
            name="改名后的连接",
            base_url="https://api2.example.com/v1",
            models_url=None,
            interface_type="openai_compatible",
            timeout_seconds=45,
        ),
        api_key="",
    )
    assert cleared.providers[0].has_credential is True


def test_clear_credential_is_explicit_and_removes_secret(tmp_path: Path) -> None:
    service, _config_path, _credentials = _service(tmp_path)
    provider_id = _seed_provider(service)

    snapshot = service.clear_credential(provider_id)

    assert snapshot.providers[0].has_credential is False


def test_config_file_on_disk_never_contains_api_key(tmp_path: Path) -> None:
    service, config_path, _credentials = _service(tmp_path)
    _seed_provider(service, api_key="sk-disk-secret-42")

    raw = config_path.read_bytes()

    assert b"sk-disk-secret-42" not in raw


def test_fetch_models_uses_given_key_then_stored_key(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service, _config_path, _credentials = _service(tmp_path, adapter=adapter)
    provider_id = _seed_provider(service, api_key=None)
    # No stored credential yet: fetching without a key fails closed.
    with pytest.raises(ModelConfigurationServiceError) as no_key:
        service.fetch_models(provider_id, api_key=None)
    assert "API Key" in str(no_key.value)

    models = service.fetch_models(provider_id, api_key="sk-fetch-once")

    assert [model.model_id for model in models] == ["model-alpha", "model-beta"]
    assert adapter.keys == ["sk-fetch-once"]

    service.set_models(provider_id, ("model-alpha",))
    service.upsert_provider(
        ProviderSpec(
            id=provider_id,
            name="默认连接",
            base_url="https://api.example.com/v1",
            models_url=None,
            interface_type="openai_compatible",
            timeout_seconds=60,
        ),
        api_key="sk-stored-key",
    )
    again = service.fetch_models(provider_id, api_key=None)
    assert [model.model_id for model in again] == ["model-alpha", "model-beta"]
    assert adapter.keys[-1] == "sk-stored-key"


def test_fetch_models_sanitizes_provider_errors(tmp_path: Path) -> None:
    adapter = FakeAdapter(list_error="HTTP 401 via Authorization: Bearer sk-leaky")
    service, _config_path, _credentials = _service(tmp_path, adapter=adapter)
    provider_id = _seed_provider(service)

    with pytest.raises(ModelConfigurationServiceError) as captured:
        service.fetch_models(provider_id, api_key="sk-whatever")

    message = str(captured.value)
    assert "模型目录获取失败" in message
    assert "sk-leaky" not in message
    assert "Authorization" not in message
    assert captured.value.__cause__ is None


def test_probe_capabilities_returns_result(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service, _config_path, _credentials = _service(tmp_path, adapter=adapter)
    provider_id = _seed_provider(service)

    result = service.probe_capabilities(provider_id, "model-alpha", api_key=None)

    assert result.basic_chat is True
    assert result.model_listing is True


def test_set_models_and_routes_validate_existence(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service, _config_path, _credentials = _service(tmp_path, adapter=adapter)
    provider_id = _seed_provider(service)
    fetched = service.fetch_models(provider_id, api_key="sk-k")
    assert fetched

    with pytest.raises(ModelConfigurationServiceError):
        service.set_routes(plot=(provider_id, "missing-model"), prose=None)

    service.set_models(provider_id, ("model-alpha", "model-beta"))
    snapshot = service.set_routes(
        plot=(provider_id, "model-alpha"),
        prose=(provider_id, "model-beta"),
    )
    assert snapshot.prose_route is not None
    assert snapshot.prose_route.model_id == "model-beta"
    assert snapshot.prose_ready is True
    assert snapshot.plot_ready is True


def test_remove_provider_drops_models_and_clears_dangling_routes(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter()
    service, _config_path, _credentials = _service(tmp_path, adapter=adapter)
    provider_id = _seed_provider(service)
    service.fetch_models(provider_id, api_key="sk-k")
    service.set_models(provider_id, ("model-alpha", "model-beta"))
    service.set_routes(prose=(provider_id, "model-alpha"), plot=None)

    snapshot = service.remove_provider(provider_id)

    assert snapshot.providers == ()
    assert snapshot.models == ()
    assert snapshot.prose_route is None
    assert snapshot.prose_ready is False


def test_invalid_connection_fields_fail_closed_before_write(tmp_path: Path) -> None:
    service, config_path, _credentials = _service(tmp_path)
    existed_before = config_path.exists()

    with pytest.raises(ModelConfigurationServiceError):
        service.upsert_provider(
            ProviderSpec(
                id=None,
                name="坏地址",
                base_url="not-a-url",
                models_url=None,
                interface_type="openai_compatible",
                timeout_seconds=30,
            ),
            api_key=None,
        )

    assert config_path.exists() is existed_before


def test_set_routes_preserves_overrides(tmp_path: Path) -> None:
    import json

    from ai_novel_studio.infrastructure.llm.schemas import TaskPurpose

    adapter = FakeAdapter()
    service, config_path, _credentials = _service(tmp_path, adapter=adapter)
    provider_id = _seed_provider(service)
    service.fetch_models(provider_id, api_key="sk-k")
    service.set_models(provider_id, ("model-alpha", "model-beta"))
    before = service.set_routes(
        plot=(provider_id, "model-alpha"),
        prose=(provider_id, "model-beta"),
    )
    assert before.plot_ready and before.prose_ready
    # Simulate an override configured by another surface (schema allows it).
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["routes"]["overrides"] = [
        {
            "purpose": TaskPurpose.MEMORY_EXTRACTION.value,
            "route": {"provider_id": provider_id, "model_id": "model-beta"},
        }
    ]
    config_path.write_text(json.dumps(raw), encoding="utf-8")

    service.set_routes(
        plot=(provider_id, "model-beta"), prose=(provider_id, "model-alpha")
    )

    reloaded = json.loads(config_path.read_text(encoding="utf-8"))
    overrides = reloaded["routes"]["overrides"]
    assert len(overrides) == 1
    assert overrides[0]["purpose"] == TaskPurpose.MEMORY_EXTRACTION.value
    assert overrides[0]["route"]["model_id"] == "model-beta"


def test_as_dict_serializes_routes_with_json(tmp_path: Path) -> None:
    import json

    adapter = FakeAdapter()
    service, _config_path, _credentials = _service(tmp_path, adapter=adapter)
    provider_id = _seed_provider(service)
    service.fetch_models(provider_id, api_key="sk-k")
    service.set_models(provider_id, ("model-alpha",))
    snapshot = service.set_routes(prose=(provider_id, "model-alpha"), plot=None)

    payload = json.dumps(snapshot.as_dict())

    assert "sk-" not in payload
    parsed = json.loads(payload)
    assert parsed["prose_route"]["model_id"] == "model-alpha"
