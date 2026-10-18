from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.application.project_constitution_service import (
    ProjectConstitutionService,
)
from ai_novel_studio.domain.project_constitution import (
    ConstitutionRule,
    ProjectConstitutionProposal,
)
from ai_novel_studio.infrastructure.storage.project_constitution_repository import (
    ProjectConstitutionRepository,
    StaleConstitutionRevisionError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _rule(rule_id: str, text: str = "规则文本") -> ConstitutionRule:
    return ConstitutionRule(rule_id, text)


def _proposal(base_revision: int = 0, **overrides: object) -> ProjectConstitutionProposal:
    fields: dict[str, object] = dict(
        base_revision=base_revision,
        shared_creative_rules=(_rule("tone.default", "压抑克制"),),
        agent_only_rules=(_rule("agent.planning", "先提问再计划"),),
        writer_only_rules=(),
        overridable_rules=(_rule("tone.default", "压抑克制"),),
        non_overridable_rules=(_rule("canon.locked", "禁止改写已确认设定"),),
        source_decisions=("已确认:基调压抑",),
        unresolved=("结尾悬念未定",),
        behavior_note="影响正文与剧情模型",
    )
    fields.update(overrides)
    return ProjectConstitutionProposal(**fields)


def _service(tmp_path: Path) -> tuple[ProjectConstitutionService, ProjectConstitutionRepository]:
    project = ProjectRepository.create(tmp_path / "novel", "Constitution")
    repository = ProjectConstitutionRepository(project)
    return ProjectConstitutionService(repository), repository


def test_get_returns_none_before_first_commit(tmp_path: Path) -> None:
    service, _repository = _service(tmp_path)
    assert service.get_project_constitution() is None


def test_commit_creates_revision_and_history(tmp_path: Path) -> None:
    service, repository = _service(tmp_path)

    first = service.commit(
        _proposal(0),
        approved_by_author=True,
        expected_revision=0,
    )
    assert first.revision == 1
    assert first.approved_by_author is True
    assert any(rule.rule_id == "tone.default" for rule in first.shared_creative_rules)

    second = service.commit(
        _proposal(1, shared_creative_rules=(_rule("tone.default", "更克制"),)),
        approved_by_author=True,
        expected_revision=1,
    )
    assert second.revision == 2

    history = repository.history()
    assert [item.revision for item in history] == [1, 2]
    assert service.get_project_constitution() == second


def test_commit_requires_approval_and_fresh_revision(tmp_path: Path) -> None:
    service, _repository = _service(tmp_path)

    with pytest.raises(ValueError):
        service.commit(_proposal(0), approved_by_author=False, expected_revision=0)
    with pytest.raises(StaleConstitutionRevisionError):
        service.commit(_proposal(0), approved_by_author=True, expected_revision=3)

    service.commit(_proposal(0), approved_by_author=True, expected_revision=0)
    with pytest.raises(StaleConstitutionRevisionError):
        service.commit(_proposal(0), approved_by_author=True, expected_revision=0)


def test_build_preview_reports_layer_diffs(tmp_path: Path) -> None:
    service, _repository = _service(tmp_path)
    service.commit(_proposal(0), approved_by_author=True, expected_revision=0)

    preview = service.build_proposal(
        _proposal(
            1,
            shared_creative_rules=(
                _rule("tone.default", "更克制"),
                _rule("tone.new", "新规则"),
            ),
        )
    )

    assert preview.current_matches_base is True
    shared = next(layer for layer in preview.layers if layer.layer == "shared_creative_rules")
    assert shared.added_ids == ("tone.new",)
    assert shared.changed_ids == ("tone.default",)
    assert shared.removed_ids == ()
