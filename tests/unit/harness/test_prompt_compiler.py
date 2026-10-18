from __future__ import annotations

import hashlib

import pytest

from ai_novel_studio.harness.model_roles import ModelRole
from ai_novel_studio.harness.prompt_compiler import (
    CachePlan,
    CacheStatus,
    ComponentKind,
    ComponentStability,
    ModelRequestManifest,
    PromptCompiler,
    PromptComponent,
)


def _component(
    component_id: str,
    kind: ComponentKind,
    stability: ComponentStability,
    content: str = "content",
    **overrides: object,
) -> PromptComponent:
    fields: dict[str, object] = dict(
        id=component_id,
        kind=kind,
        role="system",
        stability=stability,
        revision=1,
        content=content,
    )
    fields.update(overrides)
    return PromptComponent(**fields)


def test_content_hash_matches_content() -> None:
    component = _component(
        "c1", ComponentKind.HARNESS_SYSTEM, ComponentStability.GLOBAL, "hello"
    )
    expected = f"sha256:{hashlib.sha256(b'hello').hexdigest()}"
    assert component.content_hash == expected


def test_turn_only_kinds_cannot_enter_stable_tiers() -> None:
    for kind in (
        ComponentKind.STATE_CAPSULE,
        ComponentKind.TOOL_RESULTS,
        ComponentKind.CONTEXT_PROJECTION,
        ComponentKind.CURRENT_INPUT,
    ):
        with pytest.raises(ValueError):
            _component("x", kind, ComponentStability.RUN)
    capsule = _component("ok", ComponentKind.STATE_CAPSULE, ComponentStability.TURN)
    assert capsule.stability is ComponentStability.TURN


def test_component_rejects_unknown_role_and_negative_revision() -> None:
    with pytest.raises(ValueError):
        _component(
            "c1",
            ComponentKind.HARNESS_SYSTEM,
            ComponentStability.GLOBAL,
            role="developer",
        )
    with pytest.raises(ValueError):
        _component(
            "c1", ComponentKind.HARNESS_SYSTEM, ComponentStability.GLOBAL, revision=-1
        )


def test_assembly_orders_by_tier_priority_id_and_current_input_last() -> None:
    def c(
        component_id: str,
        kind: ComponentKind,
        stability: ComponentStability,
        **overrides: object,
    ) -> PromptComponent:
        return _component(component_id, kind, stability, content=component_id, **overrides)

    compiler = PromptCompiler(
        (
            c("turn", ComponentKind.STATE_CAPSULE, ComponentStability.TURN),
            c(
                "input",
                ComponentKind.CURRENT_INPUT,
                ComponentStability.TURN,
                ordering_priority=9999,
            ),
            c(
                "constitution",
                ComponentKind.PROJECT_CONSTITUTION,
                ComponentStability.PROJECT,
            ),
            c("system", ComponentKind.HARNESS_SYSTEM, ComponentStability.GLOBAL),
            c("task", ComponentKind.TASK_BLOCK, ComponentStability.RUN),
            c(
                "projection",
                ComponentKind.CONTEXT_PROJECTION,
                ComponentStability.TURN,
                ordering_priority=1,
            ),
        )
    )
    assembly = compiler.compile()

    assert [message.content for message in assembly.messages] == [
        "system",
        "constitution",
        "task",
        "projection",
        "turn",
        "input",
    ]


def test_assembly_is_order_independent_and_deterministic() -> None:
    components = (
        _component("a", ComponentKind.HARNESS_SYSTEM, ComponentStability.GLOBAL),
        _component("b", ComponentKind.PROJECT_POLICY, ComponentStability.PROJECT),
        _component("c", ComponentKind.TASK_BLOCK, ComponentStability.RUN),
        _component("d", ComponentKind.TOOL_RESULTS, ComponentStability.TURN),
    )
    first = PromptCompiler(components).compile()
    second = PromptCompiler(tuple(reversed(components))).compile()

    assert first.messages == second.messages
    assert first.cache_plan == second.cache_plan


def test_prefix_hashes_cover_only_cache_eligible_stable_content() -> None:
    base = (
        _component(
            "global", ComponentKind.HARNESS_SYSTEM, ComponentStability.GLOBAL, "g"
        ),
        _component(
            "project", ComponentKind.PROJECT_POLICY, ComponentStability.PROJECT, "p"
        ),
        _component("run", ComponentKind.TASK_BLOCK, ComponentStability.RUN, "r"),
    )
    original = PromptCompiler(base).compile().cache_plan

    changed_turn = PromptCompiler(
        base
        + (
            _component(
                "capsule", ComponentKind.STATE_CAPSULE, ComponentStability.TURN, "x"
            ),
        )
    ).compile().cache_plan
    assert changed_turn == original

    changed_run = PromptCompiler(
        (
            base[0],
            base[1],
            _component("run", ComponentKind.TASK_BLOCK, ComponentStability.RUN, "r2"),
        )
    ).compile().cache_plan
    assert changed_run.run_prefix_hash != original.run_prefix_hash
    assert changed_run.global_prefix_hash == original.global_prefix_hash
    assert changed_run.project_prefix_hash == original.project_prefix_hash

    ineligible = PromptCompiler(
        (
            _component(
                "global2",
                ComponentKind.HARNESS_SYSTEM,
                ComponentStability.GLOBAL,
                "x",
                cache_eligible=False,
            ),
            base[0],
            base[1],
            base[2],
        )
    ).compile().cache_plan
    assert ineligible.global_prefix_hash == original.global_prefix_hash


def test_compiler_rejects_duplicate_component_ids() -> None:
    component = _component("dup", ComponentKind.HARNESS_SYSTEM, ComponentStability.GLOBAL)
    with pytest.raises(ValueError):
        PromptCompiler((component, component))


def test_cache_plan_validates_hashes_and_provider() -> None:
    with pytest.raises(ValueError):
        CachePlan(
            provider=" ",
            global_prefix_hash="a" * 64,
            project_prefix_hash="b" * 64,
            run_prefix_hash="c" * 64,
            explicit_breakpoints=(),
            cache_key=None,
            cache_retention="provider_default",
        )
    with pytest.raises(ValueError):
        CachePlan(
            provider="generic",
            global_prefix_hash="not-a-hash",
            project_prefix_hash="b" * 64,
            run_prefix_hash="c" * 64,
            explicit_breakpoints=(),
            cache_key=None,
            cache_retention="provider_default",
        )


def test_manifest_validates_fields() -> None:
    with pytest.raises(ValueError):
        _manifest(run_prefix_hash="bad")
    with pytest.raises(ValueError):
        _manifest(role="AGENT")
    with pytest.raises(ValueError):
        _manifest(cache_status="ACCURATE")
    with pytest.raises(ValueError):
        _manifest(editor_snapshot_revision=-1)
    manifest = _manifest()
    assert manifest.role is ModelRole.AGENT
    assert manifest.cache_status is CacheStatus.ACCURATE


def _manifest(**overrides: object) -> ModelRequestManifest:
    fields: dict[str, object] = dict(
        request_id="req-1",
        run_id="run-1",
        step_id="step-1",
        role=ModelRole.AGENT,
        provider_id="provider-a",
        model_id="model-x",
        prompt_revision="harness-v1",
        project_constitution_revision=3,
        project_policy_revision=None,
        writing_profile_revision=None,
        toolset_revision=1,
        skill_revisions=(),
        editor_snapshot_revision=7,
        context_manifest_id="ctx-manifest-1",
        conversation_summary_revision=12,
        global_prefix_hash="a" * 64,
        project_prefix_hash="b" * 64,
        run_prefix_hash="c" * 64,
        source_artifacts=(),
        input_token_estimate=None,
        cached_input_tokens=None,
        cache_status=CacheStatus.ACCURATE,
    )
    fields.update(overrides)
    return ModelRequestManifest(**fields)
