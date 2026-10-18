from __future__ import annotations

import pytest

from ai_novel_studio.harness.proposals import (
    DeltaOp,
    PromptChangeProposal,
    PromptChangeTarget,
    PromptDelta,
    SkillChangeProposal,
    TodoCandidate,
)


def test_prompt_delta_rules() -> None:
    PromptDelta(DeltaOp.ADD, anchor="after rule 3", text="new rule")
    with pytest.raises(ValueError):
        PromptDelta(DeltaOp.ADD, anchor="after rule 3", text=" ")
    with pytest.raises(ValueError):
        PromptDelta(DeltaOp.ADD, anchor="", text="new rule")
    with pytest.raises(ValueError):
        PromptDelta(DeltaOp.REMOVE, anchor="old rule", text="unexpected")
    with pytest.raises(ValueError):
        PromptDelta(DeltaOp.REPLACE, anchor="old rule", text=" ")
    with pytest.raises(ValueError):
        PromptDelta("ADD", anchor="", text="x")


def test_prompt_change_proposal_requires_deltas_and_rationale() -> None:
    delta = PromptDelta(DeltaOp.ADD, anchor="after rule 3", text="new rule")
    with pytest.raises(ValueError):
        PromptChangeProposal(PromptChangeTarget.HARNESS_SYSTEM, 3, (), "why")
    with pytest.raises(ValueError):
        PromptChangeProposal(PromptChangeTarget.HARNESS_SYSTEM, 3, (delta,), " ")
    with pytest.raises(ValueError):
        PromptChangeProposal(PromptChangeTarget.HARNESS_SYSTEM, 0, (delta,), "why")
    proposal = PromptChangeProposal(
        PromptChangeTarget.PROJECT_CONSTITUTION,
        3,
        (delta,),
        "why",
        unresolved=("  tone.default  ", "tone.default", " "),
    )
    assert proposal.unresolved == ("tone.default",)


def test_skill_change_proposal_requires_a_change() -> None:
    with pytest.raises(ValueError):
        SkillChangeProposal("chapter_audit", 1, None, None, None, None, "why")
    with pytest.raises(ValueError):
        SkillChangeProposal("Bad-Id", 1, "new instructions", None, None, None, "why")
    with pytest.raises(ValueError):
        SkillChangeProposal("chapter_audit", 0, "new instructions", None, None, None, "why")
    with pytest.raises(ValueError):
        SkillChangeProposal(
            "chapter_audit", 1, None, None, None, {"bad": object()}, "why"
        )
    proposal = SkillChangeProposal(
        "chapter_audit",
        2,
        instructions="new instructions",
        context_requirements=None,
        recommended_tools=("manuscript.read",),
        output_schema=None,
        rationale="tighten the checks",
    )
    assert proposal.base_version == 2
    assert proposal.recommended_tools == ("manuscript.read",)


def test_todo_candidate_normalizes_text() -> None:
    candidate = TodoCandidate("  title  ", "  detail  ")
    assert candidate.title == "title"
    assert candidate.detail == "detail"
    with pytest.raises(ValueError):
        TodoCandidate("  ")
