from ai_novel_studio.application.model_backend import ModelBackend
from ai_novel_studio.infrastructure.llm import (
    MemoryCredentialStore,
    ModelConfigRepository,
)


class FakeTaskService:
    pass


def test_model_backend_composes_framework_neutral_model_dependencies(tmp_path) -> None:
    credentials = MemoryCredentialStore()
    repository = ModelConfigRepository(tmp_path / "models.json", credentials)
    service = FakeTaskService()

    backend = ModelBackend.for_test(repository, credentials, service)  # type: ignore[arg-type]

    assert backend.repository is repository
    assert backend.credentials is credentials
    assert backend.service is service
    assert backend.gateway.configuration == repository.load()
    assert "openai_compatible" in backend.adapters
