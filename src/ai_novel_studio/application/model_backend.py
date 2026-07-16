from __future__ import annotations

import os
from pathlib import Path

from ai_novel_studio.application.model_task_port import ModelTaskPort
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


class ModelBackend:
    """Framework-neutral composition root for model access."""

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

    @classmethod
    def create_default(cls) -> ModelBackend:
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
    ) -> ModelBackend:
        configuration = repository.load()
        adapter = OpenAICompatibleAdapter()
        adapters: dict[str, ProviderAdapter] = {"openai_compatible": adapter}
        usage_tracker = UsageTracker()
        gateway = LLMGateway(configuration, credentials, adapters, usage_tracker)
        return cls(repository, credentials, adapters, usage_tracker, gateway, service)
