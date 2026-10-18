from __future__ import annotations

import pytest

from ai_novel_studio.harness.tool_registry import (
    ToolDefinition,
    ToolRegistry,
    ToolRiskLevel,
    ToolScope,
    WriteEffect,
)


def _definition(
    tool_id: str = "manuscript.read",
    version: int = 1,
    **overrides: object,
) -> ToolDefinition:
    fields: dict[str, object] = dict(
        id=tool_id,
        version=version,
        scope=ToolScope.PROJECT,
        risk_level=ToolRiskLevel.READ_ONLY,
        write_effect=WriteEffect.NONE,
        requires_approval=False,
        input_schema={},
        output_schema={},
    )
    fields.update(overrides)
    return ToolDefinition(**fields)


def test_tool_id_is_normalized() -> None:
    definition = _definition(tool_id="  manuscript.read  ")
    assert definition.id == "manuscript.read"


def test_tool_id_must_look_like_domain_action() -> None:
    for bad_id in ("read", "Manuscript.read", "manuscript..read", "1manuscript.read"):
        with pytest.raises(ValueError):
            _definition(tool_id=bad_id)


def test_tool_version_must_be_positive() -> None:
    with pytest.raises(ValueError):
        _definition(version=0)


def test_tool_schemas_must_be_json_objects() -> None:
    with pytest.raises(ValueError):
        _definition(input_schema="not-a-dict")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        _definition(output_schema={"bad": object()})


def test_registry_rejects_duplicate_same_version() -> None:
    registry = ToolRegistry()
    registry.register(_definition())
    with pytest.raises(ValueError):
        registry.register(_definition())


def test_resolve_prefers_highest_version() -> None:
    registry = ToolRegistry()
    registry.register(_definition(version=1))
    registry.register(_definition(version=2))

    assert registry.resolve("manuscript.read").version == 2
    assert registry.resolve("manuscript.read", version=1).version == 1


def test_resolve_unknown_tool_raises() -> None:
    registry = ToolRegistry()
    with pytest.raises(KeyError):
        registry.resolve("subject.query")
    with pytest.raises(KeyError):
        registry.resolve("manuscript.read", version=9)


def test_snapshot_is_deterministic_and_sorted() -> None:
    registry = ToolRegistry()
    registry.register(_definition(tool_id="subject.query", version=1))
    registry.register(_definition(tool_id="manuscript.read", version=2))
    registry.register(_definition(tool_id="manuscript.read", version=1))

    snapshot = registry.snapshot()
    assert [(item.id, item.version) for item in snapshot] == [
        ("manuscript.read", 1),
        ("manuscript.read", 2),
        ("subject.query", 1),
    ]
    assert registry.snapshot() == snapshot
