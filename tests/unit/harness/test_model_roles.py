from __future__ import annotations

import pytest

from ai_novel_studio.harness.model_roles import (
    ModelRole,
    ModelRoleBinding,
    UsageMeasurement,
)
from ai_novel_studio.infrastructure.llm.schemas import TaskPurpose


def test_model_role_vocabulary_matches_design() -> None:
    assert {role.value for role in ModelRole} == {
        "AGENT",
        "CHAPTER_DRAFT",
        "COMPACTION",
    }


def test_usage_measurement_vocabulary_matches_design() -> None:
    assert {measurement.value for measurement in UsageMeasurement} == {
        "ACCURATE",
        "ESTIMATED",
        "UNKNOWN",
    }


def test_binding_normalizes_and_validates_fields() -> None:
    binding = ModelRoleBinding(
        role=ModelRole.AGENT,
        purpose=TaskPurpose.AGENT_ASSISTANT,
        provider_id="  provider-a  ",
        model_id="  model-x  ",
    )
    assert binding.provider_id == "provider-a"
    assert binding.model_id == "model-x"


def test_binding_rejects_empty_provider_or_model() -> None:
    with pytest.raises(ValueError):
        ModelRoleBinding(ModelRole.AGENT, TaskPurpose.AGENT_ASSISTANT, " ", "model-x")
    with pytest.raises(ValueError):
        ModelRoleBinding(ModelRole.AGENT, TaskPurpose.AGENT_ASSISTANT, "p", " ")


def test_binding_rejects_non_enum_values() -> None:
    with pytest.raises(ValueError):
        ModelRoleBinding("AGENT", TaskPurpose.AGENT_ASSISTANT, "p", "m")
    with pytest.raises(ValueError):
        ModelRoleBinding(ModelRole.AGENT, "agent_assistant", "p", "m")
