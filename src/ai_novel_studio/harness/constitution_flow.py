from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.project_constitution_service import (
    ProjectConstitutionService,
)
from ai_novel_studio.domain.project_constitution import (
    ConstitutionRule,
    ProjectConstitution,
    ProjectConstitutionProposal,
)
from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approval_service import ApprovalService
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalRequest
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.prompt_compiler import (
    ComponentKind,
    ComponentStability,
    PromptComponent,
)
from ai_novel_studio.infrastructure.storage.project_constitution_repository import (
    ProjectConstitutionRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_LAYER_KEYS = (
    "shared_creative_rules",
    "agent_only_rules",
    "writer_only_rules",
    "overridable_rules",
    "non_overridable_rules",
)


@dataclass(frozen=True, slots=True)
class ConstitutionResolution:
    approval: ApprovalRequest
    constitution: ProjectConstitution | None


def _proposal_to_payload(proposal: ProjectConstitutionProposal) -> dict[str, object]:
    payload: dict[str, object] = {
        "base_revision": proposal.base_revision,
        "source_decisions": list(proposal.source_decisions),
        "excluded_provisional": list(proposal.excluded_provisional),
        "unresolved": list(proposal.unresolved),
        "behavior_note": proposal.behavior_note,
    }
    for layer in _LAYER_KEYS:
        payload[layer] = [
            {"rule_id": rule.rule_id, "text": rule.text}
            for rule in getattr(proposal, layer)
        ]
    return payload


def _payload_to_proposal(payload: dict[str, object]) -> ProjectConstitutionProposal:
    def rules(key: str) -> tuple[ConstitutionRule, ...]:
        raw = payload.get(key, [])
        if not isinstance(raw, list):
            raise ValueError(f"constitution payload {key} is invalid")
        return tuple(
            ConstitutionRule(str(item["rule_id"]), str(item["text"]))
            for item in raw
        )

    def items(key: str) -> tuple[str, ...]:
        raw = payload.get(key, [])
        if not isinstance(raw, list) or any(not isinstance(v, str) for v in raw):
            raise ValueError(f"constitution payload {key} is invalid")
        return tuple(raw)

    base_raw = payload.get("base_revision")
    if isinstance(base_raw, bool) or not isinstance(base_raw, int):
        raise ValueError("constitution payload base_revision is invalid")
    return ProjectConstitutionProposal(
        base_revision=base_raw,
        shared_creative_rules=rules("shared_creative_rules"),
        agent_only_rules=rules("agent_only_rules"),
        writer_only_rules=rules("writer_only_rules"),
        overridable_rules=rules("overridable_rules"),
        non_overridable_rules=rules("non_overridable_rules"),
        source_decisions=items("source_decisions"),
        excluded_provisional=items("excluded_provisional"),
        unresolved=items("unresolved"),
        behavior_note=str(payload.get("behavior_note", "")),
    )


class ConstitutionFlowService:
    """A11 Agent-side flow: propose -> approval -> backend commit (design §37.1).

    The agent proposes through the harness approval lifecycle; only an
    approved resolution touches the backend constitution repository. The
    committed revision is rendered back into a PromptComponent for the
    PromptCompiler's Project Stable Prefix.
    """

    def __init__(
        self,
        approval_service: ApprovalService,
        backend: ProjectConstitutionService,
    ) -> None:
        self._approvals = approval_service
        self._backend = backend

    @classmethod
    def for_project(cls, project: ProjectRepository) -> ConstitutionFlowService:
        store = HarnessEventStore(HarnessEventRepository(project))
        approval_service = ApprovalService(store, ApprovalRepository(project))
        backend = ProjectConstitutionService(
            ProjectConstitutionRepository(project)
        )
        return cls(approval_service, backend)

    def propose(
        self,
        run_id: str,
        proposal: ProjectConstitutionProposal,
        *,
        idempotency_key: str,
    ) -> ApprovalRequest:
        if not isinstance(proposal, ProjectConstitutionProposal):
            raise TypeError("constitution proposal is invalid")
        return self._approvals.request_approval(
            run_id=run_id,
            kind=ApprovalKind.PROJECT_CONSTITUTION,
            summary=_proposal_summary(proposal),
            payload=_proposal_to_payload(proposal),
            idempotency_key=idempotency_key,
        )

    def resolve(
        self,
        request_id: str,
        *,
        approved: bool,
        resolution_note: str | None = None,
    ) -> ConstitutionResolution:
        approval = self._approvals.resolve_approval(
            request_id=request_id,
            approved=approved,
            resolution_note=resolution_note,
        )
        if not approved:
            return ConstitutionResolution(approval=approval, constitution=None)
        proposal = _payload_to_proposal(approval.payload)
        constitution = self._backend.commit(
            proposal,
            approved_by_author=True,
            expected_revision=proposal.base_revision,
        )
        return ConstitutionResolution(approval=approval, constitution=constitution)

    @staticmethod
    def to_prompt_component(constitution: ProjectConstitution) -> PromptComponent:
        return PromptComponent(
            id=f"project-constitution-{constitution.project_id}",
            kind=ComponentKind.PROJECT_CONSTITUTION,
            role="system",
            stability=ComponentStability.PROJECT,
            revision=constitution.revision,
            content=_render_constitution(constitution),
            ordering_priority=200,
        )

    @staticmethod
    def to_writer_prompt_component(
        constitution: ProjectConstitution,
    ) -> PromptComponent:
        """Writer-only constitution projection (design §37.1).

        The chapter draft model only receives shared_creative_rules and
        writer_only_rules; agent, overridable and non-overridable layers
        never enter the draft request.
        """
        return PromptComponent(
            id=f"project-constitution-writer-{constitution.project_id}",
            kind=ComponentKind.PROJECT_CONSTITUTION,
            role="system",
            stability=ComponentStability.PROJECT,
            revision=constitution.revision,
            content=_render_writer_constitution(constitution),
            ordering_priority=200,
        )


def _proposal_summary(proposal: ProjectConstitutionProposal) -> str:
    total = sum(len(getattr(proposal, layer)) for layer in _LAYER_KEYS)
    return f"小说最高提示词提案 v{proposal.base_revision + 1}({total} 条规则)"


def _render_constitution(constitution: ProjectConstitution) -> str:
    labels = {
        "shared_creative_rules": "共享创作规则",
        "agent_only_rules": "Agent 专用规则",
        "writer_only_rules": "正文模型专用规则",
        "overridable_rules": "可覆盖规则",
        "non_overridable_rules": "不可覆盖规则",
    }
    lines = [f"【小说最高提示词 v{constitution.revision}】"]
    for layer in _LAYER_KEYS:
        rules = sorted(getattr(constitution, layer), key=lambda rule: rule.rule_id)
        if not rules:
            continue
        lines.append(labels[layer] + ":")
        lines.extend(f"- {rule.rule_id}: {rule.text}" for rule in rules)
    if constitution.unresolved_exclusions:
        lines.append("未决排除:")
        lines.extend(f"- {item}" for item in constitution.unresolved_exclusions)
    return "\n".join(lines)


_WRITER_LAYER_KEYS = ("shared_creative_rules", "writer_only_rules")


def _render_writer_constitution(constitution: ProjectConstitution) -> str:
    labels = {
        "shared_creative_rules": "共享创作规则",
        "writer_only_rules": "正文模型专用规则",
    }
    lines = [f"【小说最高提示词(正文模型) v{constitution.revision}】"]
    for layer in _WRITER_LAYER_KEYS:
        rules = sorted(getattr(constitution, layer), key=lambda rule: rule.rule_id)
        if not rules:
            continue
        lines.append(labels[layer] + ":")
        lines.extend(f"- {rule.rule_id}: {rule.text}" for rule in rules)
    return "\n".join(lines)
