from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.audit_workflow_service import AuditWorkflowService
from ai_novel_studio.application.generation_acceptance_service import (
    GenerationAcceptanceService,
)
from ai_novel_studio.application.generation_context_service import (
    GenerationContextService,
    GenerationPreparationRequest,
)
from ai_novel_studio.application.generation_recovery_service import (
    GenerationRecoveryService,
    RecoverableGeneration,
)
from ai_novel_studio.application.model_tasks import StyleAuditResult
from ai_novel_studio.application.project_audit_service import (
    ModelAuditSnapshot,
    ProjectAuditService,
)
from ai_novel_studio.application.prose_generation_service import ProseGenerationService
from ai_novel_studio.core.context.context_manifest import (
    ContextManifest,
    ContextManifestRepository,
)
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.domain.generation import BriefStatus, CreationMode, GenerationStatus
from ai_novel_studio.infrastructure.llm import LLMGateway, LLMMessage, TaskPurpose
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    ChapterBriefRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.checkpoint_repository import CheckpointRepository
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class PreparedMessageStore:
    def __init__(self) -> None:
        self._messages: dict[str, tuple[LLMMessage, ...]] = {}

    def put(self, run_id: str, messages: tuple[LLMMessage, ...]) -> None:
        if not run_id.strip() or not messages:
            raise ValueError("生成任务和提示消息不能为空")
        self._messages[run_id] = messages

    def messages_for(self, run_id: str) -> tuple[LLMMessage, ...]:
        try:
            return self._messages[run_id]
        except KeyError as error:
            raise KeyError("当前会话没有该生成任务的提示消息") from error


@dataclass(frozen=True, slots=True)
class AcceptedGeneration:
    text: str
    chapter_revision: int


@dataclass(frozen=True, slots=True)
class PreAcceptModelAuditRequest:
    snapshot: ModelAuditSnapshot
    draft_text: str
    rules: tuple[str, ...]
    output_token_limit: int


@dataclass(frozen=True, slots=True)
class PreAcceptAuditPlan:
    deterministic_blocker_count: int
    model_request: PreAcceptModelAuditRequest | None


class ProjectGenerationSession:
    """Framework-neutral project generation state and synchronous use cases."""

    def __init__(
        self,
        project: ProjectRepository,
        gateway: LLMGateway,
        history: HistoryRetriever,
    ) -> None:
        self.project = project
        self.gateway = gateway
        self.chapters = ChapterRepository(project)
        self.requirements = ChapterRequirementRepository(project)
        self.briefs = ChapterBriefRepository(project)
        self.runs = GenerationRepository(project)
        self.checkpoints = CheckpointRepository(project, self.runs)
        self.messages = PreparedMessageStore()
        self.manifests = ContextManifestRepository(project)
        self.context = GenerationContextService(
            project,
            self.chapters,
            self.requirements,
            self.briefs,
            self.runs,
            self.manifests,
            history=history,
        )
        self.prose = ProseGenerationService(
            gateway,
            self.messages,
            self.runs,
            self.checkpoints,
        )
        self.acceptance = GenerationAcceptanceService(
            project,
            self.runs,
            self.checkpoints,
            self.chapters,
        )
        self.recovery = GenerationRecoveryService(self.runs, self.checkpoints)
        self.audit_workflow = AuditWorkflowService(
            self.chapters,
            self.requirements,
            AuditRepository(project),
        )
        self.project_audits = ProjectAuditService(project)
        self.current_chapter_id: str | None = None
        self.current_chapter_revision: int | None = None
        self.current_run_id: str | None = None
        self.accepted_chapter_revision: int | None = None

    def latest_context_manifest(self, chapter_id: str) -> ContextManifest | None:
        return self.manifests.latest_for_chapter(chapter_id)

    def select_chapter(self, chapter_id: str, revision: int) -> bool:
        self.current_chapter_id = chapter_id
        self.current_chapter_revision = revision
        self.current_run_id = None
        self.accepted_chapter_revision = None
        return bool(self.briefs.list_for_chapter(chapter_id, BriefStatus.FROZEN))

    def synchronize_requirement(
        self,
        content: str,
        *,
        expected_revision: int,
        locked: bool,
    ) -> int:
        if self.current_chapter_id is None:
            raise RuntimeError("请先选择要生成的章节")
        requirement = self.requirements.get_or_create(self.current_chapter_id)
        if requirement.content != content or requirement.is_locked != locked:
            requirement = self.requirements.update(
                self.current_chapter_id,
                content,
                is_locked=locked,
                expected_revision=expected_revision,
            )
        return requirement.revision

    def prepare_generation(
        self,
        mode: CreationMode,
        output_token_limit: int,
        target_words: int,
    ) -> str:
        if self.current_chapter_id is None or self.current_chapter_revision is None:
            raise RuntimeError("请先选择要生成的章节")
        route = self.gateway.configuration.routes.resolve(TaskPurpose.PROSE_GENERATION)
        model = self.gateway.configuration.model(route)
        frozen = self.briefs.list_for_chapter(
            self.current_chapter_id,
            BriefStatus.FROZEN,
        )
        brief_id = frozen[-1].id if mode != CreationMode.BASIC and frozen else None
        prepared = self.context.prepare(
            GenerationPreparationRequest(
                chapter_id=self.current_chapter_id,
                mode=mode,
                brief_id=brief_id,
                output_token_limit=output_token_limit,
                model_capabilities=model.capabilities,
                target_words=target_words,
                model_provider_id=route.provider_id,
                model_id=route.model_id,
            )
        )
        self.messages.put(prepared.run.id, prepared.messages)
        self.current_run_id = prepared.run.id
        return prepared.run.id

    def accept_current(self) -> AcceptedGeneration:
        if self.current_run_id is None or self.current_chapter_revision is None:
            raise RuntimeError("当前没有可采用的正文草稿")
        run = self.runs.get(self.current_run_id)
        accepted = self.acceptance.accept(
            run.id,
            self.current_chapter_revision,
            allow_partial=run.status == GenerationStatus.PARTIAL,
        )
        text = self.checkpoints.read(accepted.checkpoint.id)
        self.current_chapter_revision = accepted.chapter.revision
        self.accepted_chapter_revision = accepted.chapter.revision
        return AcceptedGeneration(text, accepted.chapter.revision)

    def discard_current(self) -> bool:
        if self.current_run_id is None:
            return False
        self.acceptance.discard(self.current_run_id)
        return True

    def recover_current(self) -> RecoverableGeneration | None:
        candidates = tuple(
            item
            for item in self.recovery.scan()
            if self.current_chapter_id is None
            or item.run.chapter_id == self.current_chapter_id
        )
        if not candidates:
            return None
        selected = candidates[-1]
        self.current_run_id = selected.run.id
        return selected

    def prepare_pre_accept_audit(self) -> PreAcceptAuditPlan | None:
        if self.current_run_id is None:
            raise RuntimeError("采用前审校缺少生成任务")
        run = self.runs.get(self.current_run_id)
        # STRICT is retained only as the persisted encoding for pre-accept audit.
        if run.mode != CreationMode.STRICT:
            return None
        checkpoint = self.checkpoints.latest(run.id)
        if checkpoint is None or self.current_chapter_revision is None:
            raise RuntimeError("草稿缺少可审校的检查点或章节修订")
        draft_text = self.checkpoints.read(checkpoint.id)
        result = self.audit_workflow.run_deterministic_for_draft(
            chapter_id=run.chapter_id,
            generation_run_id=run.id,
            draft_text=draft_text,
            base_chapter_revision=self.current_chapter_revision,
            mode=CreationMode.STRICT,
        )
        blockers = tuple(
            finding
            for finding in result.findings
            if finding.status.value == "OPEN"
            and finding.severity.value in {"ERROR", "BLOCKER"}
        )
        if blockers:
            return PreAcceptAuditPlan(len(blockers), None)

        route = self.gateway.configuration.routes.resolve(TaskPurpose.STYLE_AUDIT)
        snapshot = self.project_audits.generated_model_snapshot(
            chapter_id=run.chapter_id,
            generation_run_id=run.id,
            draft_text=draft_text,
            revision=self.current_chapter_revision,
            model_provider_id=route.provider_id,
            model_id=route.model_id,
        )
        return PreAcceptAuditPlan(
            0,
            PreAcceptModelAuditRequest(
                snapshot=snapshot,
                draft_text=draft_text,
                rules=self.project_audits.model_context_rules(run.chapter_id),
                output_token_limit=run.output_token_limit,
            ),
        )

    def record_pre_accept_model_audit(
        self,
        snapshot: ModelAuditSnapshot,
        value: object,
    ) -> int:
        if not isinstance(value, StyleAuditResult):
            raise ValueError("模型审校返回了无效结果")
        findings = self.project_audits.record_model_result(snapshot, value)
        return sum(
            1
            for finding in findings
            if finding.status.value == "OPEN"
            and finding.severity.value in {"ERROR", "BLOCKER"}
        )
