import json

from ai_novel_studio.infrastructure.llm import (
    MemoryCredentialStore,
    ModelCapabilities,
    ModelConfigRepository,
    ModelConfiguration,
    ModelProfile,
    ModelRoute,
    ModelSamplingParameters,
    ProviderProfile,
    TaskPurpose,
    TaskRoutes,
)


def _configuration() -> ModelConfiguration:
    provider = ProviderProfile(
        id="relay",
        name="第三方中转",
        base_url="https://relay.example/v1",
        credential_id="credential-relay",
        timeout_seconds=120,
        models_url="https://relay.example/v1/models",
    )
    model = ModelProfile(
        provider_id="relay",
        model_id="novel-pro",
        display_name="Novel Pro",
        capabilities=ModelCapabilities(
            context_window=128_000,
            max_output_tokens=32_000,
            streaming=True,
            strict_json=True,
            input_price_per_million=2.5,
            output_price_per_million=10.0,
        ),
        sampling=ModelSamplingParameters(
            temperature=0.85,
            top_p=0.92,
            frequency_penalty=0.1,
            presence_penalty=-0.2,
        ),
    )
    route = ModelRoute("relay", "novel-pro")
    return ModelConfiguration(
        providers=(provider,),
        models=(model,),
        routes=TaskRoutes(
            plot=route,
            prose=route,
            overrides=((TaskPurpose.STYLE_AUDIT, route),),
        ),
    )


def test_repository_round_trips_profiles_routes_and_capabilities(tmp_path) -> None:  # type: ignore[no-untyped-def]
    credentials = MemoryCredentialStore()
    repository = ModelConfigRepository(tmp_path / "model-config.json", credentials)
    expected = _configuration()

    repository.save(expected, {"credential-relay": "sk-private-value"})

    assert repository.load() == expected
    assert credentials.get("credential-relay") == "sk-private-value"


def test_repository_never_writes_api_key_into_json(tmp_path) -> None:  # type: ignore[no-untyped-def]
    credentials = MemoryCredentialStore()
    path = tmp_path / "model-config.json"
    repository = ModelConfigRepository(path, credentials)

    repository.save(_configuration(), {"credential-relay": "sk-private-value"})

    content = path.read_text(encoding="utf-8")
    payload = json.loads(content)
    assert "sk-private-value" not in content
    assert payload["schema_version"] == 1
    assert payload["providers"][0]["credential_id"] == "credential-relay"


def test_saving_removed_provider_deletes_retired_credential(tmp_path) -> None:  # type: ignore[no-untyped-def]
    credentials = MemoryCredentialStore()
    repository = ModelConfigRepository(tmp_path / "model-config.json", credentials)
    repository.save(_configuration(), {"credential-relay": "sk-private-value"})

    repository.save(ModelConfiguration.empty(), {})

    assert credentials.get("credential-relay") is None


def test_missing_file_loads_empty_valid_configuration(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repository = ModelConfigRepository(
        tmp_path / "not-created.json",
        MemoryCredentialStore(),
    )

    assert repository.load() == ModelConfiguration.empty()
