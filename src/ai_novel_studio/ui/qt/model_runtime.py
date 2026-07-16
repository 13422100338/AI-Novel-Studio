from __future__ import annotations

from ai_novel_studio.application.model_backend import ModelBackend
from ai_novel_studio.application.model_task_port import ModelTaskPort
from ai_novel_studio.infrastructure.llm import (
    CredentialStore,
    ModelConfigRepository,
)
from ai_novel_studio.ui.qt.model_settings_controller import ModelSettingsController
from ai_novel_studio.ui.qt.model_task_coordinator import ModelTaskCoordinator


class ModelRuntime:
    """Qt composition adapter around the framework-neutral model backend."""

    def __init__(self, backend: ModelBackend) -> None:
        self.backend = backend
        self.repository = backend.repository
        self.credentials = backend.credentials
        self.adapters = backend.adapters
        self.usage_tracker = backend.usage_tracker
        self.gateway = backend.gateway
        self.service = backend.service
        self.coordinator = ModelTaskCoordinator(backend.service)
        self.settings_controller = ModelSettingsController(
            backend.repository,
            backend.credentials,
            backend.adapters,
            backend.gateway,
        )

    @classmethod
    def create_default(cls) -> ModelRuntime:
        return cls(ModelBackend.create_default())

    @classmethod
    def for_test(
        cls,
        repository: ModelConfigRepository,
        credentials: CredentialStore,
        service: ModelTaskPort,
    ) -> ModelRuntime:
        return cls(ModelBackend.for_test(repository, credentials, service))
