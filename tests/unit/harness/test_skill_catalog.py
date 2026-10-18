from __future__ import annotations

import pytest

from ai_novel_studio.harness.skill_catalog import Skill, SkillCatalog


def _skill(skill_id: str = "chapter_audit", version: int = 1, **overrides: object) -> Skill:
    fields: dict[str, object] = dict(
        id=skill_id,
        version=version,
        description="check facts, states and knowledge boundaries",
        instructions="audit the chapter",
        context_requirements=("current chapter",),
        recommended_tools=("manuscript.read",),
        output_schema={},
    )
    fields.update(overrides)
    return Skill(**fields)


def test_skill_id_must_be_lowercase_snake_case() -> None:
    for bad_id in ("ChapterAudit", "chapter-audit", "1audit", ""):
        with pytest.raises(ValueError):
            _skill(skill_id=bad_id)


def test_skill_requires_instructions_and_json_output_schema() -> None:
    with pytest.raises(ValueError):
        _skill(instructions="  ")
    with pytest.raises(ValueError):
        _skill(output_schema={"bad": object()})


def test_catalog_rejects_duplicates_and_resolves_highest_version() -> None:
    catalog = SkillCatalog()
    catalog.register(_skill(version=1))
    catalog.register(_skill(version=2))

    with pytest.raises(ValueError):
        catalog.register(_skill(version=2))

    assert catalog.load("chapter_audit").version == 2
    assert catalog.load("chapter_audit", version=1).version == 1
    with pytest.raises(KeyError):
        catalog.load("missing")


def test_entries_are_deterministic_and_sorted() -> None:
    catalog = SkillCatalog()
    catalog.register(_skill(skill_id="style_check", version=1))
    catalog.register(_skill(skill_id="chapter_audit", version=2))
    catalog.register(_skill(skill_id="chapter_audit", version=1))

    entries = catalog.entries()
    assert [(entry.id, entry.version) for entry in entries] == [
        ("chapter_audit", 1),
        ("chapter_audit", 2),
        ("style_check", 1),
    ]
    assert catalog.entries() == entries
