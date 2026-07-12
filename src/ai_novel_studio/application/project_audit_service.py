from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ai_novel_studio.application.audit_workflow_service import AuditWorkflowService
from ai_novel_studio.application.model_audit_service import (
    ModelAuditFindingInput,
    ModelAuditService,
)
from ai_novel_studio.application.model_tasks import StyleAuditResult
from ai_novel_studio.application.repair_application_service import (
    AppliedRepair,
    RepairApplicationError,
    RepairApplicationService,
)
from ai_novel_studio.domain.audit import (
    AuditFinding,
    AuditFindingCategory,
    AuditFindingSource,
    AuditFindingStatus,
    AuditSeverity,
    AuditTargetKind,
    RepairProposal,
    RepairProposalStatus,
    RepairStrategy,
)
from ai_novel_studio.domain.generation import BriefStatus, CreationMode
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    ChapterBriefRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


@dataclass(frozen=True, slots=True)
class ModelAuditSnapshot:
    chapter_id: str
    target_kind: AuditTargetKind
    target_id: str
    target_revision: int
    target_hash: str
    mode: CreationMode
    model_provider_id: str
    model_id: str


class ProjectAuditService:
    """Runs project-aware audits and persists their evidence snapshot."""

    def __init__(self, project: ProjectRepository) -> None:
        self.repository = AuditRepository(project)
        self.chapters = ChapterRepository(project)
        self.workflow = AuditWorkflowService(
            self.chapters,
            ChapterRequirementRepository(project),
            self.repository,
        )
        self.model_audits = ModelAuditService(self.repository)
        self.repairs = RepairApplicationService(self.chapters, self.repository)
        self.briefs = ChapterBriefRepository(project)
        self.characters = CharacterMemoryRepository(project)
        self.summaries = SummaryRepository(project)

    def run_deterministic(
        self,
        *,
        chapter_id: str,
        text: str,
        revision: int,
        requirement: str,
        mode: CreationMode,
    ) -> tuple[AuditFinding, ...]:
        del requirement
        chapter = self.chapters.get_chapter(chapter_id, include_deleted=False)
        saved_text = self.chapters.read_content(chapter_id)
        if text == saved_text and revision == chapter.revision:
            return self.workflow.run_deterministic_for_formal_chapter(
                chapter_id, mode=mode
            ).findings
        return self.workflow.run_deterministic_for_draft(
            chapter_id=chapter_id,
            generation_run_id=f"editor-preview-{chapter_id}",
            draft_text=text,
            base_chapter_revision=revision,
            mode=mode,
        ).findings

    def model_context_rules(self, chapter_id: str) -> tuple[str, ...]:
        rules: list[str] = ["逐项核对当前章要求，并只引用正文中的原句作为证据。"]
        frozen = self.briefs.list_for_chapter(chapter_id, BriefStatus.FROZEN)
        if frozen:
            brief = frozen[-1]
            rules.append(f"冻结 Brief 戏剧功能：{brief.dramatic_purpose}")
            rules.extend(f"冻结 Brief 必须事件：{item}" for item in brief.hard_events)
            rules.extend(f"冻结 Brief 禁止改动：{item}" for item in brief.prohibited_changes)
            rules.extend(f"冻结 Brief 伏笔动作：{item}" for item in brief.clue_actions)
        for character in self.characters.list_characters():
            state = self.characters.state_before(character.id, chapter_id, inclusive=True)
            if state is not None:
                rules.append(
                    f"人物状态 {character.canonical_name}：动机={state.motivation}；"
                    f"心理={state.psychology}；目标={state.current_goal}；"
                    f"最近活动={state.recent_activity}"
                )
        current_summaries = [
            item for item in self.summaries.list_all() if chapter_id in item.source_chapter_ids
        ]
        rules.extend(f"记忆摘要：{item.content}" for item in current_summaries[-3:])
        return tuple(rules)

    def update_finding_status(
        self, finding_id: str, status: AuditFindingStatus
    ) -> AuditFinding:
        return self.repository.update_finding_status(finding_id, status)

    def model_snapshot(
        self,
        *,
        chapter_id: str,
        text: str,
        revision: int,
        mode: CreationMode,
        model_provider_id: str,
        model_id: str,
    ) -> ModelAuditSnapshot:
        chapter = self.chapters.get_chapter(chapter_id, include_deleted=False)
        formal = text == self.chapters.read_content(chapter_id) and revision == chapter.revision
        return ModelAuditSnapshot(
            chapter_id=chapter_id,
            target_kind=(
                AuditTargetKind.FORMAL_CHAPTER
                if formal
                else AuditTargetKind.GENERATED_DRAFT
            ),
            target_id=chapter_id if formal else f"editor-preview-{chapter_id}",
            target_revision=revision,
            target_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            mode=mode,
            model_provider_id=model_provider_id,
            model_id=model_id,
        )

    def generated_model_snapshot(
        self,
        *,
        chapter_id: str,
        generation_run_id: str,
        draft_text: str,
        revision: int,
        model_provider_id: str,
        model_id: str,
    ) -> ModelAuditSnapshot:
        return ModelAuditSnapshot(
            chapter_id=chapter_id,
            target_kind=AuditTargetKind.GENERATED_DRAFT,
            target_id=generation_run_id,
            target_revision=revision,
            target_hash=hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
            mode=CreationMode.STRICT,
            model_provider_id=model_provider_id,
            model_id=model_id,
        )

    def record_model_result(
        self, snapshot: ModelAuditSnapshot, result: StyleAuditResult
    ) -> tuple[AuditFinding, ...]:
        inputs = tuple(
            ModelAuditFindingInput(
                category=_model_category(item.category),
                severity=_model_severity(item.severity),
                quote=item.evidence,
                evidence=item.evidence,
                explanation=item.issue,
                confidence=0.7,
            )
            for item in result.findings
        )
        return self.model_audits.record_findings(
            chapter_id=snapshot.chapter_id,
            target_kind=snapshot.target_kind,
            target_id=snapshot.target_id,
            target_revision=snapshot.target_revision,
            target_hash=snapshot.target_hash,
            mode=snapshot.mode,
            model_provider_id=snapshot.model_provider_id,
            model_id=snapshot.model_id,
            prompt_version="model-audit-ui-v1",
            findings=inputs,
        ).findings

    def latest_model_findings(self, chapter_id: str) -> tuple[AuditFinding, ...]:
        runs = self.repository.list_runs_for_target(
            target_kind=AuditTargetKind.FORMAL_CHAPTER,
            target_id=chapter_id,
        )
        for run in runs:
            findings = tuple(
                item
                for item in self.repository.list_findings(run.id)
                if item.source == AuditFindingSource.MODEL
            )
            if findings:
                return findings
        return ()

    def create_replacement_proposal(
        self,
        *,
        finding_id: str,
        chapter_id: str,
        target_text: str,
        replacement_text: str,
    ) -> RepairProposal:
        return self.repairs.create_validated_text_repair(
            finding_id=finding_id,
            chapter_id=chapter_id,
            strategy=RepairStrategy.REPLACE_TEXT,
            target_text=target_text,
            replacement_text=replacement_text,
            explanation="用户审查后的局部替换建议",
            risk_note="仅替换第一次出现的目标原文；采用前需再次核对上下文。",
        )

    def apply_repair_proposal(
        self,
        proposal_id: str,
        *,
        chapter_id: str,
        expected_revision: int,
        visible_text: str,
    ) -> AppliedRepair:
        if visible_text != self.chapters.read_content(chapter_id):
            raise RepairApplicationError("编辑器存在未保存修改，请先保存或撤销后再采用修复")
        return self.repairs.apply(
            proposal_id,
            chapter_id=chapter_id,
            expected_revision=expected_revision,
        )

    def reject_repair_proposal(self, proposal_id: str) -> RepairProposal:
        proposal = self.repository.get_repair_proposal(proposal_id)
        if proposal.status not in {
            RepairProposalStatus.DRAFT,
            RepairProposalStatus.VALIDATED,
        }:
            raise RepairApplicationError(
                f"当前修复建议不能拒绝：{proposal.status.value}"
            )
        return self.repository.update_repair_status(
            proposal_id, RepairProposalStatus.REJECTED
        )


_CATEGORY_ALIASES = {
    "声音": "STYLE",
    "文风": "STYLE",
    "风格": "STYLE",
    "人物": "CHARACTER",
    "知识": "KNOWLEDGE",
    "伏笔": "CLUE",
    "正典": "CANON",
    "时间线": "TIMELINE",
    "格式": "FORMAT",
    "要求": "REQUIREMENT",
}
_SEVERITY_ALIASES = {
    "低": "INFO",
    "中": "WARNING",
    "高": "ERROR",
    "严重": "BLOCKER",
}


def _model_category(value: str) -> str:
    normalized = value.strip().upper()
    candidate = _CATEGORY_ALIASES.get(value.strip(), normalized)
    try:
        return AuditFindingCategory(candidate).value
    except ValueError as error:
        raise ValueError(f"未知的审校问题分类：{value}") from error


def _model_severity(value: str) -> str:
    normalized = value.strip().upper()
    candidate = _SEVERITY_ALIASES.get(value.strip(), normalized)
    try:
        return AuditSeverity(candidate).value
    except ValueError as error:
        raise ValueError(f"未知的审校严重程度：{value}") from error
