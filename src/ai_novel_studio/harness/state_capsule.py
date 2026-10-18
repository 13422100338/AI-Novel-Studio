from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ai_novel_studio.harness.run_state import RunStage


class ContextHealth(StrEnum):
    """Engineering health of the run context (design v0.3 §64.1)."""

    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    RECOMPILING = "RECOMPILING"
    UNKNOWN = "UNKNOWN"


class OptimizationStatus(StrEnum):
    """Whether the context needs optimization work (design v0.3 §14)."""

    OPTIMIZED = "OPTIMIZED"
    NEEDS_COMPACTION = "NEEDS_COMPACTION"
    NEEDS_RECOMPILE = "NEEDS_RECOMPILE"
    UNKNOWN = "UNKNOWN"


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _optional_non_negative(value: int | None, field: str) -> int | None:
    if value is not None and value < 0:
        raise ValueError(f"{field} cannot be negative")
    return value


def _normalized_items(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values if value.strip())
    if len(set(normalized)) != len(normalized):
        raise ValueError("list items must be unique")
    return normalized


@dataclass(frozen=True, slots=True)
class AgentStateCapsule:
    """Run-fact snapshot for UI, recovery and compaction (design v0.3 §14).

    The capsule is a derived snapshot of run facts - never a display model by
    itself and never a second source of domain truth.
    """

    run_id: str
    goal: str
    stage: RunStage
    active_chapter_id: str | None
    editor_snapshot_revision: int | None
    formal_revision: int | None
    context_manifest_id: str | None
    conversation_summary_revision: int | None
    last_model_request_manifest_id: str | None
    context_health: ContextHealth
    optimization_status: OptimizationStatus
    plan: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    pending_approvals: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    loaded_skills: tuple[str, ...] = ()
    loaded_tools: tuple[str, ...] = ()
    context_budget: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _required(self.run_id, "run_id"))
        object.__setattr__(self, "goal", _required(self.goal, "goal"))
        if not isinstance(self.stage, RunStage):
            raise ValueError("stage must be a RunStage")
        if not isinstance(self.context_health, ContextHealth):
            raise ValueError("context_health must be a ContextHealth")
        if not isinstance(self.optimization_status, OptimizationStatus):
            raise ValueError("optimization_status must be an OptimizationStatus")
        object.__setattr__(
            self, "active_chapter_id", _optional_text(self.active_chapter_id)
        )
        for field in (
            "editor_snapshot_revision",
            "formal_revision",
            "conversation_summary_revision",
        ):
            object.__setattr__(
                self, field, _optional_non_negative(getattr(self, field), field)
            )
        object.__setattr__(
            self, "context_manifest_id", _optional_text(self.context_manifest_id)
        )
        object.__setattr__(
            self,
            "last_model_request_manifest_id",
            _optional_text(self.last_model_request_manifest_id),
        )
        object.__setattr__(
            self, "context_budget", _optional_non_negative(self.context_budget, "context_budget")
        )
        for field in (
            "plan",
            "assumptions",
            "pending_approvals",
            "unresolved_questions",
            "loaded_skills",
            "loaded_tools",
        ):
            object.__setattr__(self, field, _normalized_items(getattr(self, field)))
