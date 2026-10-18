from __future__ import annotations

import json
import re
from dataclasses import dataclass

_SKILL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _validate_schema(value: dict[str, object], field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON-serializable") from exc
    return value


@dataclass(frozen=True, slots=True)
class SkillCatalogEntry:
    """Lightweight catalog line shown to the model (design v0.3 §32)."""

    id: str
    version: int
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", self.id.strip())
        if not _SKILL_ID_PATTERN.match(self.id):
            raise ValueError("skill id must be lowercase snake_case")
        if self.version < 1:
            raise ValueError("skill version must be positive")
        object.__setattr__(self, "description", self.description.strip())
        if not self.description:
            raise ValueError("skill description cannot be empty")


@dataclass(frozen=True, slots=True)
class Skill:
    """Full skill body loaded on demand (design v0.3 §32, §33).

    Skills can only change method, checks, output structure, recommended tools
    and context recipes - never system permissions.
    """

    id: str
    version: int
    description: str
    instructions: str
    context_requirements: tuple[str, ...]
    recommended_tools: tuple[str, ...]
    output_schema: dict[str, object]

    def __post_init__(self) -> None:
        entry = SkillCatalogEntry(self.id, self.version, self.description)
        object.__setattr__(self, "id", entry.id)
        object.__setattr__(self, "description", entry.description)
        if not self.instructions.strip():
            raise ValueError("skill instructions cannot be empty")
        object.__setattr__(
            self, "output_schema", _validate_schema(self.output_schema, "output_schema")
        )

    def entry(self) -> SkillCatalogEntry:
        return SkillCatalogEntry(self.id, self.version, self.description)


class SkillCatalog:
    """Versioned skill registry (design v0.3 §32, contract §12 skeleton)."""

    def __init__(self) -> None:
        self._skills: dict[tuple[str, int], Skill] = {}

    def register(self, skill: Skill) -> None:
        key = (skill.id, skill.version)
        if key in self._skills:
            raise ValueError(f"skill {skill.id} v{skill.version} is already registered")
        self._skills[key] = skill

    def entries(self) -> tuple[SkillCatalogEntry, ...]:
        return tuple(
            skill.entry()
            for _key, skill in sorted(
                self._skills.items(), key=lambda item: (item[0][0], item[0][1])
            )
        )

    def load(self, skill_id: str, version: int | None = None) -> Skill:
        if version is not None:
            skill = self._skills.get((skill_id, version))
            if skill is None:
                raise KeyError(f"unknown skill: {skill_id} v{version}")
            return skill
        candidates = [
            skill
            for (identifier, _version), skill in self._skills.items()
            if identifier == skill_id
        ]
        if not candidates:
            raise KeyError(f"unknown skill: {skill_id}")
        return max(candidates, key=lambda skill: skill.version)
