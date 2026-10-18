from __future__ import annotations

from pathlib import Path

from ai_novel_studio.application.project_constitution_service import (
    ProjectConstitutionService,
)
from ai_novel_studio.domain.project_constitution import (
    ConstitutionRule,
    ProjectConstitutionProposal,
)
from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approval_service import ApprovalService
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalStatus
from ai_novel_studio.harness.constitution_flow import (
    ConstitutionFlowService,
    ConstitutionResolution,
)
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.prompt_compiler import (
    ComponentKind,
    ComponentStability,
)
from ai_novel_studio.infrastructure.storage.project_constitution_repository import (
    ProjectConstitutionRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _proposal(**overrides: object) -> ProjectConstitutionProposal:
    fields: dict[str, object] = dict(
        base_revision=0,
        shared_creative_rules=(ConstitutionRule("tone.default", "压抑克制"),),
        agent_only_rules=(ConstitutionRule("agent.planning", "先提问再计划"),),
        writer_only_rules=(),
        overridable_rules=(ConstitutionRule("tone.default", "压抑克制"),),
        non_overridable_rules=(ConstitutionRule("canon.locked", "禁止改写已确认设定"),),
        source_decisions=("已确认:基调压抑",),
        behavior_note="影响正文与剧情模型",
    )
    fields.update(overrides)
    return ProjectConstitutionProposal(**fields)


def _service(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Constitution flow")
    store = HarnessEventStore(HarnessEventRepository(project))
    approval_service = ApprovalService(store, ApprovalRepository(project))
    backend = ProjectConstitutionService(ProjectConstitutionRepository(project))
    flow = ConstitutionFlowService(approval_service, backend)
    run, _ = store.start_run(goal="确认小说最高提示词")
    return flow, store, run


def test_propose_then_approve_commits_constitution(tmp_path: Path) -> None:
    flow, store, run = _service(tmp_path)

    request = flow.propose(run.id, _proposal(), idempotency_key="key-1")

    assert request.kind is ApprovalKind.PROJECT_CONSTITUTION
    assert request.status is ApprovalStatus.PENDING
    resolution = flow.resolve(request.request_id, approved=True, resolution_note="作者认可")

    assert isinstance(resolution, ConstitutionResolution)
    assert resolution.constitution is not None
    assert resolution.constitution.revision == 1
    assert store.get_run(run.id).stage.value == "WAITING_APPROVAL"


def test_rejected_proposal_never_commits(tmp_path: Path) -> None:
    flow, _store, run = _service(tmp_path)

    request = flow.propose(run.id, _proposal(), idempotency_key="key-1")
    resolution = flow.resolve(request.request_id, approved=False)

    assert resolution.constitution is None
    assert resolution.approval.status is ApprovalStatus.REJECTED


def test_stale_proposal_fails_closed_on_commit(tmp_path: Path) -> None:
    flow, _store, run = _service(tmp_path)

    flow.propose(run.id, _proposal(), idempotency_key="key-1")
    first = flow.propose(run.id, _proposal(), idempotency_key="key-1")
    assert first.request_id == flow.propose(run.id, _proposal(), idempotency_key="key-1").request_id

    resolved = flow.resolve(first.request_id, approved=True)
    assert resolved.constitution is not None

    # 同一 base_revision 再次提交应失败(后端并发控制)
    from ai_novel_studio.infrastructure.storage.project_constitution_repository import (
        StaleConstitutionRevisionError,
    )

    second_request = flow.propose(run.id, _proposal(), idempotency_key="key-2")
    try:
        flow.resolve(second_request.request_id, approved=True)
    except StaleConstitutionRevisionError:
        return
    raise AssertionError("stale constitution commit must fail")


def test_prompt_component_enters_project_prefix(tmp_path: Path) -> None:
    flow, _store, run = _service(tmp_path)

    request = flow.propose(run.id, _proposal(), idempotency_key="key-1")
    resolution = flow.resolve(request.request_id, approved=True)
    component = flow.to_prompt_component(resolution.constitution)

    assert component.kind is ComponentKind.PROJECT_CONSTITUTION
    assert component.stability is ComponentStability.PROJECT
    assert component.revision == 1
    assert "tone.default" in component.content
    assert "压抑克制" in component.content
