from __future__ import annotations

import os
from pathlib import Path

from ai_novel_studio.application.model_settings_controller import ModelSettingsController
from ai_novel_studio.application.model_task_coordinator import (
    ModelTaskCoordinator,
    ModelTaskPort,
)
from ai_novel_studio.application.model_tasks import ModelTaskService
from ai_novel_studio.infrastructure.llm import (
    CredentialStore,
    LLMGateway,
    ModelConfigRepository,
    OpenAICompatibleAdapter,
    ProviderAdapter,
    UsageTracker,
    WindowsCredentialStore,
)


class ModelRuntime:
    def __init__(
        self,
        repository: ModelConfigRepository,
        credentials: CredentialStore,
        adapters: dict[str, ProviderAdapter],
        usage_tracker: UsageTracker,
        gateway: LLMGateway,
        service: ModelTaskPort,
    ) -> None:
        self.repository = repository
        self.credentials = credentials
        self.adapters = adapters
        self.usage_tracker = usage_tracker
        self.gateway = gateway
        self.service = service
        self.coordinator = ModelTaskCoordinator(service)
        self.settings_controller = ModelSettingsController(
            repository, credentials, adapters, gateway
        )

    @classmethod
    def create_default(cls) -> ModelRuntime:
        config_root = Path(
            os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        ) / "AI Novel Studio"
        credentials = WindowsCredentialStore()
        repository = ModelConfigRepository(config_root / "model-config.json", credentials)
        configuration = repository.load()
        adapter = OpenAICompatibleAdapter()
        adapters: dict[str, ProviderAdapter] = {"openai_compatible": adapter}
        usage_tracker = UsageTracker()
        gateway = LLMGateway(configuration, credentials, adapters, usage_tracker)
        service = ModelTaskService(gateway)
        return cls(repository, credentials, adapters, usage_tracker, gateway, service)

    @classmethod
    def for_test(
        cls,
        repository: ModelConfigRepository,
        credentials: CredentialStore,
        service: ModelTaskPort,
    ) -> ModelRuntime:
        configuration = repository.load()
        adapter = OpenAICompatibleAdapter()
        adapters: dict[str, ProviderAdapter] = {"openai_compatible": adapter}
        usage_tracker = UsageTracker()
        gateway = LLMGateway(configuration, credentials, adapters, usage_tracker)
        return cls(repository, credentials, adapters, usage_tracker, gateway, service)
