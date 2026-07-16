from typing import Protocol

from ai_novel_studio.domain.project_guidance import ProjectGuidance


class ProjectGuidanceGateway(Protocol):
    @property
    def project_id(self) -> str: ...

    def load(self) -> ProjectGuidance: ...

    def save_manual(
        self, highest_system_prompt: str, *, expected_revision: int
    ) -> ProjectGuidance: ...


class ProjectGuidanceService:
    """Manual-write, read-only-for-model boundary for project-wide guidance."""

    def __init__(self, gateway: ProjectGuidanceGateway) -> None:
        self._gateway = gateway

    @property
    def project_id(self) -> str:
        return self._gateway.project_id

    def load(self) -> ProjectGuidance:
        return self._gateway.load()

    def save_manual(
        self, highest_system_prompt: str, *, expected_revision: int
    ) -> ProjectGuidance:
        if expected_revision < 0:
            raise ValueError("项目最高提示修订号不能为负数")
        return self._gateway.save_manual(
            highest_system_prompt, expected_revision=expected_revision
        )

    def read_highest_system_prompt(self) -> str:
        """Return project guidance without exposing a model-write operation."""

        return self._gateway.load().highest_system_prompt
