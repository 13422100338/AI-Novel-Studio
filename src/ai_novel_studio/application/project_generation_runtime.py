from __future__ import annotations

from PySide6.QtCore import QObject, Signal

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
from ai_novel_studio.application.model_task_coordinator import ModelTaskCoordinator
from ai_novel_studio.application.model_tasks import ModelTaskService, StyleAuditResult
from ai_novel_studio.application.project_audit_service import (
    ModelAuditSnapshot,
    ProjectAuditService,
)
from ai_novel_studio.application.prose_generation_coordinator import (
    ProseGenerationCoordinator,
)
from ai_novel_studio.application.prose_generation_service import ProseGenerationService
from ai_novel_studio.core.context.context_manifest import (
    ContextManifest,
    ContextManifestRepository,
)
from ai_novel_studio.domain.generation import (
    BriefStatus,
    CreationMode,
    GenerationCheckpoint,
    GenerationRun,
    GenerationStatus,
)
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


class ProjectGenerationRuntime(QObject):
    draft_chunk = Signal(str)
    reasoning_chunk = Signal(str)
    generation_usage_changed = Signal(object)
    run_changed = Signal(object)
    failed = Signal(str)
    accepted = Signal(str)
    discarded = Signal()
    recovered = Signal(object)
    usage_changed = Signal(object)
    strict_audit_changed = Signal(bool, str)

    def __init__(self, project: ProjectRepository, gateway: LLMGateway) -> None:
        super().__init__()
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
        )
        self.prose = ProseGenerationService(
            gateway,
            self.messages,
            self.runs,
            self.checkpoints,
        )
        self.coordinator = ProseGenerationCoordinator(self.prose)
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
        self.audit_coordinator = ModelTaskCoordinator(ModelTaskService(gateway), self)
        self.audit_coordinator.audit_ready.connect(self._finish_strict_model_audit)
        self.audit_coordinator.task_failed.connect(self._fail_strict_model_audit)
        self.audit_coordinator.usage_changed.connect(self.usage_changed.emit)
        self._pending_strict_model_snapshot: ModelAuditSnapshot | None = None
        self.current_chapter_id: str | None = None
        self.current_chapter_revision: int | None = None
        self.current_run_id: str | None = None
        self.accepted_chapter_revision: int | None = None

        self.coordinator.draft_chunk.connect(self.draft_chunk.emit)
        self.coordinator.reasoning_chunk.connect(self.reasoning_chunk.emit)
        self.coordinator.run_changed.connect(self._handle_run_changed)
        self.coordinator.failed.connect(self.failed.emit)
        self.coordinator.usage_changed.connect(self.generation_usage_changed.emit)
        self.coordinator.usage_changed.connect(self._emit_usage_snapshot)

    def latest_context_manifest(self, chapter_id: str) -> ContextManifest | None:
        return self.manifests.latest_for_chapter(chapter_id)

    def select_chapter(self, chapter_id: str, revision: int) -> bool:
        self.current_chapter_id = chapter_id
        self.current_chapter_revision = revision
        self.current_run_id = None
        self.accepted_chapter_revision = None
        return bool(self.briefs.list_for_chapter(chapter_id, BriefStatus.FROZEN))

    def prepare_and_start(
        self,
        mode: CreationMode,
        output_token_limit: int,
        target_words: int,
    ) -> None:
        if self.current_chapter_id is None or self.current_chapter_revision is None:
            self.failed.emit("请先选择要生成的章节")
            return
        try:
            route = self.gateway.configuration.routes.resolve(TaskPurpose.PROSE_GENERATION)
            model = self.gateway.configuration.model(route)
            frozen = self.briefs.list_for_chapter(
                self.current_chapter_id, BriefStatus.FROZEN
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
            self.coordinator.start(prepared.run.id)
        except (KeyError, LookupError, RuntimeError, ValueError) as error:
            self.failed.emit(str(error))

    def cancel_current(self) -> None:
        if self.current_run_id is not None:
            self.coordinator.cancel(self.current_run_id)

    def accept_current(self) -> None:
        if self.current_run_id is None or self.current_chapter_revision is None:
            self.failed.emit("当前没有可采用的正文草稿")
            return
        try:
            run = self.runs.get(self.current_run_id)
            accepted = self.acceptance.accept(
                run.id,
                self.current_chapter_revision,
                allow_partial=run.status == GenerationStatus.PARTIAL,
            )
            text = self.checkpoints.read(accepted.checkpoint.id)
        except (KeyError, RuntimeError, ValueError) as error:
            self.failed.emit(str(error))
            return
        self.current_chapter_revision = accepted.chapter.revision
        self.accepted_chapter_revision = accepted.chapter.revision
        self.accepted.emit(text)

    def discard_current(self) -> None:
        if self.current_run_id is None:
            return
        try:
            self.acceptance.discard(self.current_run_id)
        except (KeyError, RuntimeError, ValueError) as error:
            self.failed.emit(str(error))
            return
        self.discarded.emit()

    def recover(self) -> None:
        candidates = tuple(
            item
            for item in self.recovery.scan()
            if self.current_chapter_id is None or item.run.chapter_id == self.current_chapter_id
        )
        if not candidates:
            self.failed.emit("当前章节没有可恢复的正文草稿")
            return
        selected = candidates[-1]
        self.current_run_id = selected.run.id
        self.recovered.emit(selected)

    def _emit_usage_snapshot(self, _usage: object) -> None:
        self.usage_changed.emit(self.gateway.usage_tracker.snapshot())

    def _handle_run_changed(self, status: GenerationStatus) -> None:
        if status == GenerationStatus.COMPLETED and self.current_run_id is not None:
            try:
                run = self.runs.get(self.current_run_id)
                if run.mode == CreationMode.STRICT:
                    self.strict_audit_changed.emit(False, "严格模式正在执行采用前审校")
                    checkpoint = self.checkpoints.latest(run.id)
                    if checkpoint is None or self.current_chapter_revision is None:
                        raise RuntimeError("严格模式草稿缺少可审校的检查点或章节修订")
                    result = self.audit_workflow.run_deterministic_for_draft(
                        chapter_id=run.chapter_id,
                        generation_run_id=run.id,
                        draft_text=self.checkpoints.read(checkpoint.id),
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
                        self.strict_audit_changed.emit(
                            False,
                            f"严格模式发现 {len(blockers)} 个确定性阻断问题，请先处理",
                        )
                    else:
                        self._start_strict_model_audit(run, checkpoint)
            except (KeyError, RuntimeError, ValueError) as error:
                self.strict_audit_changed.emit(False, f"严格模式审校失败：{error}")
                self.failed.emit(str(error))
        self.run_changed.emit(status)

    def _start_strict_model_audit(
        self, run: GenerationRun, checkpoint: GenerationCheckpoint
    ) -> None:
        run_id = run.id
        chapter_id = run.chapter_id
        draft_text = self.checkpoints.read(checkpoint.id)
        route = self.gateway.configuration.routes.resolve(TaskPurpose.STYLE_AUDIT)
        revision = self.current_chapter_revision
        if revision is None:
            raise RuntimeError("严格模式缺少章节修订")
        self._pending_strict_model_snapshot = self.project_audits.generated_model_snapshot(
            chapter_id=chapter_id,
            generation_run_id=run_id,
            draft_text=draft_text,
            revision=revision,
            model_provider_id=route.provider_id,
            model_id=route.model_id,
        )
        self.strict_audit_changed.emit(False, "确定性检查通过，正在运行模型语义审校")
        self.audit_coordinator.start_audit(
            draft_text,
            self.project_audits.model_context_rules(chapter_id),
            run.output_token_limit,
        )

    def _finish_strict_model_audit(self, value: object) -> None:
        snapshot = self._pending_strict_model_snapshot
        if snapshot is None or not isinstance(value, StyleAuditResult):
            self._fail_strict_model_audit("模型审校返回了无效结果")
            return
        try:
            findings = self.project_audits.record_model_result(snapshot, value)
            blockers = tuple(
                finding
                for finding in findings
                if finding.status.value == "OPEN"
                and finding.severity.value in {"ERROR", "BLOCKER"}
            )
            self.strict_audit_changed.emit(
                not blockers,
                (
                    "严格模式确定性与模型审校均通过，可以人工采用"
                    if not blockers
                    else f"模型审校发现 {len(blockers)} 个阻断问题，请先处理"
                ),
            )
        except (KeyError, RuntimeError, ValueError) as error:
            self._fail_strict_model_audit(str(error))
        finally:
            self._pending_strict_model_snapshot = None

    def _fail_strict_model_audit(self, message: str) -> None:
        self._pending_strict_model_snapshot = None
        self.strict_audit_changed.emit(False, f"严格模式模型审校失败：{message}")


def recovered_draft_text(value: object) -> tuple[str, GenerationStatus] | None:
    if not isinstance(value, RecoverableGeneration) or value.draft_text is None:
        return None
    return value.draft_text, value.run.status
