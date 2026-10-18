from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ai_novel_studio.domain.identifiers import validate_id

_MAX_RULES_PER_SET = 200
_MAX_RULE_ID_CHARS = 100
_MAX_RULE_TEXT_CHARS = 2000


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"constitution {field} cannot be empty")
    return normalized


def _normalized_items(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _validated_rules(
    values: tuple[ConstitutionRule, ...], field: str
) -> tuple[ConstitutionRule, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(rule, ConstitutionRule) for rule in values
    ):
        raise ValueError(f"constitution {field} is invalid")
    if len(values) > _MAX_RULES_PER_SET:
        raise ValueError(f"constitution {field} has too many rules")
    identifiers = [rule.rule_id for rule in values]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"constitution {field} rule ids must be unique")
    return values


@dataclass(frozen=True, slots=True)
class ConstitutionRule:
    rule_id: str
    text: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "rule_id", _required(self.rule_id, "rule id")[:_MAX_RULE_ID_CHARS]
        )
        object.__setattr__(
            self, "text", _required(self.text, "rule text")[:_MAX_RULE_TEXT_CHARS]
        )


@dataclass(frozen=True, slots=True)
class ProjectConstitution:
    """One immutable constitution revision (DCP step 5, option A)."""

    id: str
    project_id: str
    revision: int
    shared_creative_rules: tuple[ConstitutionRule, ...]
    agent_only_rules: tuple[ConstitutionRule, ...]
    writer_only_rules: tuple[ConstitutionRule, ...]
    overridable_rules: tuple[ConstitutionRule, ...]
    non_overridable_rules: tuple[ConstitutionRule, ...]
    source_decisions: tuple[str, ...]
    unresolved_exclusions: tuple[str, ...]
    approved_by_author: bool
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", validate_id(self.id))
        object.__setattr__(self, "project_id", validate_id(self.project_id))
        if self.revision < 1:
            raise ValueError("constitution revision must be positive")
        for field in (
            "shared_creative_rules",
            "agent_only_rules",
            "writer_only_rules",
            "overridable_rules",
            "non_overridable_rules",
        ):
            object.__setattr__(self, field, _validated_rules(getattr(self, field), field))
        object.__setattr__(self, "source_decisions", _normalized_items(self.source_decisions))
        object.__setattr__(
            self, "unresolved_exclusions", _normalized_items(self.unresolved_exclusions)
        )


@dataclass(frozen=True, slots=True)
class ProjectConstitutionProposal:
    """Model-authored constitution change awaiting author approval."""

    base_revision: int
    shared_creative_rules: tuple[ConstitutionRule, ...]
    agent_only_rules: tuple[ConstitutionRule, ...]
    writer_only_rules: tuple[ConstitutionRule, ...]
    overridable_rules: tuple[ConstitutionRule, ...]
    non_overridable_rules: tuple[ConstitutionRule, ...]
    source_decisions: tuple[str, ...]
    excluded_provisional: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    behavior_note: str = ""

    def __post_init__(self) -> None:
        if self.base_revision < 0:
            raise ValueError("constitution base revision cannot be negative")
        for field in (
            "shared_creative_rules",
            "agent_only_rules",
            "writer_only_rules",
            "overridable_rules",
            "non_overridable_rules",
        ):
            object.__setattr__(self, field, _validated_rules(getattr(self, field), field))
        if not any(
            getattr(self, field)
            for field in (
                "shared_creative_rules",
                "agent_only_rules",
                "writer_only_rules",
                "overridable_rules",
                "non_overridable_rules",
            )
        ):
            raise ValueError("constitution proposal must contain at least one rule")
        object.__setattr__(self, "source_decisions", _normalized_items(self.source_decisions))
        if not self.source_decisions:
            raise ValueError("constitution proposal must cite source decisions")
        object.__setattr__(
            self, "excluded_provisional", _normalized_items(self.excluded_provisional)
        )
        object.__setattr__(self, "unresolved", _normalized_items(self.unresolved))
        object.__setattr__(self, "behavior_note", self.behavior_note.strip())
