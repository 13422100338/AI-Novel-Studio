from pathlib import Path

from ai_novel_studio.infrastructure.llm import (
    CredentialStoreError,
    ModelConfigRepository,
    ModelConfiguration,
    ProviderProfile,
    TaskRoutes,
)
from ai_novel_studio.ui.qt.model_settings_controller import ModelSettingsController


class FailingCredentialStore:
    def get(self, credential_id: str) -> str | None:
        raise CredentialStoreError("credential backend failed")

    def set(self, credential_id: str, secret: str) -> None:
        raise CredentialStoreError("credential backend failed")

    def delete(self, credential_id: str) -> None:
        raise CredentialStoreError("credential backend failed")


def test_settings_controller_turns_credential_failure_into_ui_error(tmp_path: Path) -> None:
    credentials = FailingCredentialStore()
    repository = ModelConfigRepository(tmp_path / "models.json", credentials)
    controller = ModelSettingsController(repository, credentials, {}, None)
    messages: list[str] = []
    controller.failed.connect(messages.append)
    profile = ProviderProfile(
        id="relay",
        name="中转",
        base_url="https://relay.example/v1",
        credential_id="credential-relay",
    )
    configuration = ModelConfiguration(
        providers=(profile,),
        models=(),
        routes=TaskRoutes(None, None),
    )

    controller.save(configuration, {"credential-relay": "secret"})

    assert messages
    assert "credential backend failed" not in messages[0]
    assert "系统凭据" in messages[0]
