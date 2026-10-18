from __future__ import annotations

import pytest

from ai_novel_studio.domain.project_constitution import (
    ConstitutionRule,
    ProjectConstitutionProposal,
)


def _rule(rule_id: str, text: str = "规则文本") -> ConstitutionRule:
    return ConstitutionRule(rule_id, text)


def _proposal(**overrides: object) -> ProjectConstitutionProposal:
    fields: dict[str, object] = dict(
        base_revision=0,
        shared_creative_rules=(_rule("tone.default", "压抑克制"),),
        agent_only_rules=(),
        writer_only_rules=(_rule("pov.consistency", "视角一致"),),
        overridable_rules=(_rule("tone.default", "压抑克制"),),
        non_overridable_rules=(),
        source_decisions=("已确认:基调压抑",),
        behavior_note="可能影响正文基调",
    )
    fields.update(overrides)
    return ProjectConstitutionProposal(**fields)


def test_proposal_requires_rules_and_source_decisions() -> None:
    with pytest.raises(ValueError):
        _proposal(shared_creative_rules=(), writer_only_rules=(), overridable_rules=())
    with pytest.raises(ValueError):
        _proposal(source_decisions=())
    with pytest.raises(ValueError):
        _proposal(base_revision=-1)


def test_proposal_rejects_duplicate_rule_ids_in_one_set() -> None:
    with pytest.raises(ValueError):
        _proposal(
            shared_creative_rules=(_rule("x"), _rule("x", "别的文本")),
        )


def test_rule_normalizes_and_bounds_text() -> None:
    rule = ConstitutionRule("  x  ", "  内容  ")
    assert rule.rule_id == "x"
    assert rule.text == "内容"
    with pytest.raises(ValueError):
        ConstitutionRule("", "文本")
    with pytest.raises(ValueError):
        ConstitutionRule("x", "  ")
