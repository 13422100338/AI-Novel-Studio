from __future__ import annotations

import pytest

from ai_novel_studio.harness.run_state import RunStage
from ai_novel_studio.harness.state_capsule import (
    AgentStateCapsule,
    ContextHealth,
    OptimizationStatus,
)


def _capsule(**overrides: object) -> AgentStateCapsule:
    fields: dict[str, object] = dict(
        run_id="run-1",
        goal="draft chapter three",
        stage=RunStage.CONTEXT_COMPILED,
        active_chapter_id=None,
        editor_snapshot_revision=None,
        formal_revision=None,
        context_manifest_id=None,
        conversation_summary_revision=None,
        last_model_request_manifest_id=None,
        context_health=ContextHealth.HEALTHY,
        optimization_status=OptimizationStatus.OPTIMIZED,
    )
    fields.update(overrides)
    return AgentStateCapsule(**fields)


def test_capsule_builds_with_defaults() -> None:
    capsule = _capsule()
    assert capsule.plan == ()
    assert capsule.loaded_tools == ()
    assert capsule.context_budget is None


def test_capsule_requires_run_id_and_goal() -> None:
    with pytest.raises(ValueError):
        _capsule(run_id=" ")
    with pytest.raises(ValueError):
        _capsule(goal=" ")


def test_capsule_rejects_non_enum_fields() -> None:
    with pytest.raises(ValueError):
        _capsule(stage="CONTEXT_COMPILED")
    with pytest.raises(ValueError):
        _capsule(context_health="HEALTHY")
    with pytest.raises(ValueError):
        _capsule(optimization_status="OPTIMIZED")


def test_capsule_rejects_negative_revisions_and_budget() -> None:
    with pytest.raises(ValueError):
        _capsule(editor_snapshot_revision=-1)
    with pytest.raises(ValueError):
        _capsule(formal_revision=-2)
    with pytest.raises(ValueError):
        _capsule(context_budget=-1)


def test_capsule_normalizes_lists_and_rejects_duplicates() -> None:
    capsule = _capsule(plan=("  beat one  ", "beat two", " "), loaded_tools=("subject.query",))
    assert capsule.plan == ("beat one", "beat two")
    assert capsule.loaded_tools == ("subject.query",)
    with pytest.raises(ValueError):
        _capsule(assumptions=("same", "same"))
