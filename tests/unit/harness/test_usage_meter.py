from __future__ import annotations

import pytest

from ai_novel_studio.harness.model_roles import (
    ModelRole,
    ModelRoleBinding,
    UsageMeasurement,
)
from ai_novel_studio.harness.usage_meter import HarnessUsageMeter
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMUsage,
    ModelCapabilities,
    ModelProfile,
    ModelRoute,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.llm.usage_tracker import UsageTracker


def _profile() -> ModelProfile:
    return ModelProfile(
        provider_id="p",
        model_id="m",
        capabilities=ModelCapabilities(
            input_price_per_million=1.0, output_price_per_million=2.0
        ),
    )


def _bindings() -> tuple[ModelRoleBinding, ...]:
    return (
        ModelRoleBinding(ModelRole.AGENT, TaskPurpose.PLOT_DISCUSSION, "p", "agent"),
        ModelRoleBinding(
            ModelRole.CHAPTER_DRAFT, TaskPurpose.PROSE_GENERATION, "p", "draft"
        ),
        ModelRoleBinding(ModelRole.COMPACTION, TaskPurpose.AGENT_ASSISTANT, "p", "compact"),
    )


def test_snapshot_splits_usage_by_role_with_measurement_labels() -> None:
    tracker = UsageTracker()
    tracker.record_success(
        TaskPurpose.PLOT_DISCUSSION,
        ModelRoute("p", "agent"),
        _profile(),
        LLMUsage(input_tokens=100, output_tokens=50),
        output_token_limit=500,
        duration_ms=1,
        retry_count=0,
    )
    tracker.record_success(
        TaskPurpose.PROSE_GENERATION,
        ModelRoute("p", "draft"),
        _profile(),
        LLMUsage(estimated=True, input_tokens=200, output_tokens=80),
        output_token_limit=800,
        duration_ms=2,
        retry_count=1,
    )

    snapshot = HarnessUsageMeter(tracker, _bindings()).snapshot()

    by_role = {item.role: item for item in snapshot}
    assert set(by_role) == {ModelRole.AGENT, ModelRole.CHAPTER_DRAFT, ModelRole.COMPACTION}

    agent = by_role[ModelRole.AGENT]
    assert agent.measurement is UsageMeasurement.ACCURATE
    assert (agent.input_tokens, agent.output_tokens) == (100, 50)
    assert agent.cost is not None

    draft = by_role[ModelRole.CHAPTER_DRAFT]
    assert draft.measurement is UsageMeasurement.ESTIMATED
    assert (draft.input_tokens, draft.output_tokens) == (200, 80)

    compact = by_role[ModelRole.COMPACTION]
    assert compact.measurement is UsageMeasurement.UNKNOWN
    assert compact.call_count == 0
    assert compact.cost is None


def test_meter_rejects_duplicate_purposes() -> None:
    tracker = UsageTracker()
    bindings = (
        ModelRoleBinding(ModelRole.AGENT, TaskPurpose.AGENT_ASSISTANT, "p", "a"),
        ModelRoleBinding(ModelRole.CHAPTER_DRAFT, TaskPurpose.AGENT_ASSISTANT, "p", "b"),
    )

    with pytest.raises(ValueError):
        HarnessUsageMeter(tracker, bindings)
