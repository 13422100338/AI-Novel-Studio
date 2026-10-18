from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum


class ToolScope(StrEnum):
    """Where a tool may run (design v0.3 §29)."""

    PROJECT = "PROJECT"
    RUN = "RUN"


class ToolRiskLevel(StrEnum):
    """Risk band shown in tool metadata (design v0.3 §8, §29)."""

    READ_ONLY = "READ_ONLY"
    PROPOSAL = "PROPOSAL"


class WriteEffect(StrEnum):
    """Whether a tool can change persisted state (design v0.3 §29, §31)."""

    NONE = "NONE"
    PROPOSAL_ONLY = "PROPOSAL_ONLY"
    FORMAL_WRITE = "FORMAL_WRITE"


_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def _validate_schema(value: dict[str, object], field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON-serializable") from exc
    return value


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Registry entry for one tool version (design v0.3 §29 metadata)."""

    id: str
    version: int
    scope: ToolScope
    risk_level: ToolRiskLevel
    write_effect: WriteEffect
    requires_approval: bool
    input_schema: dict[str, object]
    output_schema: dict[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", self.id.strip())
        if not _ID_PATTERN.match(self.id):
            raise ValueError("tool id must look like 'domain.action'")
        if self.version < 1:
            raise ValueError("tool version must be positive")
        if not isinstance(self.scope, ToolScope):
            raise ValueError("scope must be a ToolScope")
        if not isinstance(self.risk_level, ToolRiskLevel):
            raise ValueError("risk_level must be a ToolRiskLevel")
        if not isinstance(self.write_effect, WriteEffect):
            raise ValueError("write_effect must be a WriteEffect")
        object.__setattr__(
            self, "input_schema", _validate_schema(self.input_schema, "input_schema")
        )
        object.__setattr__(
            self, "output_schema", _validate_schema(self.output_schema, "output_schema")
        )


class ToolRegistry:
    """Versioned catalog of harness tool definitions (design v0.3 §30).

    The registry only holds definitions and version bookkeeping. Execution,
    permission checks, and provider wiring live elsewhere; tools never reach
    repositories or SQLite through the registry itself.
    """

    def __init__(self) -> None:
        self._definitions: dict[tuple[str, int], ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        key = (definition.id, definition.version)
        if key in self._definitions:
            raise ValueError(
                f"tool {definition.id} v{definition.version} is already registered"
            )
        self._definitions[key] = definition

    def resolve(self, tool_id: str, version: int | None = None) -> ToolDefinition:
        if version is not None:
            definition = self._definitions.get((tool_id, version))
            if definition is None:
                raise KeyError(f"unknown tool: {tool_id} v{version}")
            return definition
        candidates = [
            definition
            for (identifier, _version), definition in self._definitions.items()
            if identifier == tool_id
        ]
        if not candidates:
            raise KeyError(f"unknown tool: {tool_id}")
        return max(candidates, key=lambda definition: definition.version)

    def snapshot(self) -> tuple[ToolDefinition, ...]:
        """Deterministic catalog listing ordered by (id, version)."""
        return tuple(
            definition
            for _key, definition in sorted(
                self._definitions.items(), key=lambda item: (item[0][0], item[0][1])
            )
        )
