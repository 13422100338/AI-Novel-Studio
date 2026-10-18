from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

_SKILL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class PromptChangeTarget(StrEnum):
    """Which versioned prompt document a proposal edits (design v0.3 §38)."""

    HARNESS_SYSTEM = "HARNESS_SYSTEM"
    PROJECT_CONSTITUTION = "PROJECT_CONSTITUTION"


class DeltaOp(StrEnum):
    ADD = "ADD"
    REMOVE = "REMOVE"
    REPLACE = "REPLACE"


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


def _validate_json_object(value: dict[str, object], field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON-serializable") from exc
    return value


def _normalized_items(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
    return normalized


@dataclass(frozen=True, slots=True)
class PromptDelta:
    """One deterministic edit step in a prompt change proposal (design §38)."""

    op: DeltaOp
    anchor: str
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.op, DeltaOp):
            raise ValueError("op must be a DeltaOp")
        object.__setattr__(self, "anchor", _required(self.anchor, "anchor"))
        if self.op is DeltaOp.ADD:
            object.__setattr__(self, "text", _required(self.text, "text"))
        elif self.op is DeltaOp.REMOVE:
            if self.text.strip():
                raise ValueError("REMOVE deltas must not carry text")
        else:
            object.__setattr__(self, "text", _required(self.text, "text"))


@dataclass(frozen=True, slots=True)
class PromptChangeProposal:
    """Model-authored diff against a versioned prompt (design §38, §25).

    The agent may only propose; the author approves and a new revision is
    created by the owning system. Program permissions never change through
    prompt proposals.
    """

    target: PromptChangeTarget
    base_revision: int
    deltas: tuple[PromptDelta, ...]
    rationale: str
    unresolved: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.target, PromptChangeTarget):
            raise ValueError("target must be a PromptChangeTarget")
        if self.base_revision < 1:
            raise ValueError("base_revision must be positive")
        if not self.deltas:
            raise ValueError("deltas cannot be empty")
        object.__setattr__(self, "rationale", _required(self.rationale, "rationale"))
        object.__setattr__(self, "unresolved", _normalized_items(self.unresolved))


@dataclass(frozen=True, slots=True)
class SkillChangeProposal:
    """Model-authored change to one skill (design §33).

    Skills can only change method, checks, output structure, recommended
    tools and context recipes - never system permissions.
    """

    skill_id: str
    base_version: int
    instructions: str | None
    context_requirements: tuple[str, ...] | None
    recommended_tools: tuple[str, ...] | None
    output_schema: dict[str, object] | None
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "skill_id", _required(self.skill_id, "skill_id"))
        if not _SKILL_ID_PATTERN.match(self.skill_id):
            raise ValueError("skill id must be lowercase snake_case")
        if self.base_version < 1:
            raise ValueError("base_version must be positive")
        changed = any(
            value is not None
            for value in (
                self.instructions,
                self.context_requirements,
                self.recommended_tools,
                self.output_schema,
            )
        )
        if not changed:
            raise ValueError("skill change proposal must change something")
        object.__setattr__(self, "rationale", _required(self.rationale, "rationale"))
        if self.instructions is not None:
            object.__setattr__(self, "instructions", _required(self.instructions, "instructions"))
        if self.context_requirements is not None:
            object.__setattr__(
                self, "context_requirements", _normalized_items(self.context_requirements)
            )
        if self.recommended_tools is not None:
            object.__setattr__(
                self, "recommended_tools", _normalized_items(self.recommended_tools)
            )
        if self.output_schema is not None:
            object.__setattr__(
                self,
                "output_schema",
                _validate_json_object(self.output_schema, "output_schema"),
            )


@dataclass(frozen=True, slots=True)
class TodoCandidate:
    """Model-proposed todo awaiting author approval (design v0.3 §60)."""

    title: str
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _required(self.title, "title"))
        object.__setattr__(self, "detail", self.detail.strip())
