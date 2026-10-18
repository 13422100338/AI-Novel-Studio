from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ai_novel_studio.infrastructure.llm.schemas import TaskPurpose


class ModelRole(StrEnum):
    """Logical model roles in a Harness run (design v0.3 §35, §15.2)."""

    AGENT = "AGENT"
    CHAPTER_DRAFT = "CHAPTER_DRAFT"
    COMPACTION = "COMPACTION"


class UsageMeasurement(StrEnum):
    """Provider-side accuracy of a usage figure (design v0.3 §66)."""

    ACCURATE = "ACCURATE"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class ModelRoleBinding:
    """Frozen mapping from one logical model role to a concrete model route.

    Bindings are frozen when a run starts (design v0.3 §35): switching models
    only affects new runs, and historical runs keep their recorded bindings.
    """

    role: ModelRole
    purpose: TaskPurpose
    provider_id: str
    model_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, ModelRole):
            raise ValueError("role must be a ModelRole")
        if not isinstance(self.purpose, TaskPurpose):
            raise ValueError("purpose must be a TaskPurpose")
        object.__setattr__(self, "provider_id", _required(self.provider_id, "provider_id"))
        object.__setattr__(self, "model_id", _required(self.model_id, "model_id"))
