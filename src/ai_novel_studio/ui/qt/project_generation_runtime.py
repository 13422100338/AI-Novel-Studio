from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ai_novel_studio.application.generation_recovery_service import (
    RecoverableGeneration,
)
from ai_novel_studio.application.model_tasks import ModelTaskService
from ai_novel_studio.application.project_audit_service import ModelAuditSnapshot
from ai_novel_studio.application.project_generation_session import (
    PreAcceptModelAuditRequest,
    ProjectGenerationSession,
)
from ai_novel_studio.core.context.context_manifest import ContextManifest
from ai_novel_studio.domain.generation import (
    AuditPolicy,
    CreationMode,
    GenerationStatus,
)
from ai_novel_studio.ui.qt.model_task_coordinator import ModelTaskCoordinator
from ai_novel_studio.ui.qt.prose_generation_coordinator import (
    ProseGenerationCoordinator,
)


class QtProjectGenerationRuntime(QObject):
    """Translate a framework-neutral generation session into Qt signals and jobs."""

    draft_chunk = Signal(str)
    reasoning_chunk = Signal(str)
    requirement_saved = Signal(int)
    generation_usage_changed = Signal(object)
    run_changed = Signal(object)
    failed = Signal(str)
    accepted = Signal(str)
    discarded = Signal()
    recovered = Signal(object)
    usage_changed = Signal(object)
    pre_accept_audit_changed = Signal(bool, str)

    def __init__(
        self,
        session: ProjectGenerationSession,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.gateway = session.gateway
        self.coordinator = ProseGenerationCoordinator(session.prose)
        self.audit_coordinator = ModelTaskCoordinator(
            ModelTaskService(session.gateway),
            self,
        )
        self.audit_coordinator.audit_ready.connect(self._finish_pre_accept_model_audit)
        self.audit_coordinator.task_failed.connect(self._fail_pre_accept_model_audit)
        self.audit_coordinator.usage_changed.connect(self.usage_changed.emit)
        self._pending_pre_accept_snapshot: ModelAuditSnapshot | None = None

        self.coordinator.draft_chunk.connect(self.draft_chunk.emit)
        self.coordinator.reasoning_chunk.connect(self.reasoning_chunk.emit)
        self.coordinator.run_changed.connect(self._handle_run_changed)
        self.coordinator.failed.connect(self.failed.emit)
        self.coordinator.usage_changed.connect(self.generation_usage_changed.emit)
        self.coordinator.usage_changed.connect(self._emit_usage_snapshot)

    def latest_context_manifest(self, chapter_id: str) -> ContextManifest | None:
        return self.session.latest_context_manifest(chapter_id)

    def select_chapter(self, chapter_id: str, revision: int) -> bool:
        return self.session.select_chapter(chapter_id, revision)

    @property
    def current_chapter_id(self) -> str | None:
        return self.session.current_chapter_id

    @property
    def current_chapter_revision(self) -> int | None:
        return self.session.current_chapter_revision

    @property
    def current_run_id(self) -> str | None:
        return self.session.current_run_id

    @property
    def accepted_chapter_revision(self) -> int | None:
        return self.session.accepted_chapter_revision

    def prepare_and_start(
        self,
        mode: CreationMode,
        audit_policy: AuditPolicy,
        output_token_limit: int,
        target_words: int,
        *,
        requirement_content: str,
        expected_requirement_revision: int,
        requirement_locked: bool,
    ) -> None:
        try:
            requirement_revision = self.session.synchronize_requirement(
                requirement_content,
                expected_revision=expected_requirement_revision,
                locked=requirement_locked,
            )
            self.requirement_saved.emit(requirement_revision)
            run_id = self.session.prepare_generation(
                mode,
                output_token_limit,
                target_words,
                audit_policy,
            )
            self.coordinator.start(run_id)
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
            accepted = self.session.accept_current()
        except (KeyError, RuntimeError, ValueError) as error:
            self.failed.emit(str(error))
            return
        self.accepted.emit(accepted.text)

    def discard_current(self) -> None:
        try:
            discarded = self.session.discard_current()
        except (KeyError, RuntimeError, ValueError) as error:
            self.failed.emit(str(error))
            return
        if discarded:
            self.discarded.emit()

    def recover(self) -> None:
        selected = self.session.recover_current()
        if selected is None:
            self.failed.emit("当前章节没有可恢复的正文草稿")
            return
        self.recovered.emit(selected)

    def _emit_usage_snapshot(self, _usage: object) -> None:
        self.usage_changed.emit(self.gateway.usage_tracker.snapshot())

    def _handle_run_changed(self, status: GenerationStatus) -> None:
        if status == GenerationStatus.COMPLETED and self.current_run_id is not None:
            try:
                plan = self.session.prepare_pre_accept_audit()
                if plan is not None:
                    self.pre_accept_audit_changed.emit(False, "正在执行采用前审校")
                    if plan.deterministic_blocker_count:
                        self.pre_accept_audit_changed.emit(
                            False,
                            "采用前审校发现 "
                            f"{plan.deterministic_blocker_count} 个确定性阻断问题，请先处理",
                        )
                    elif plan.model_request is not None:
                        self._start_pre_accept_model_audit(plan.model_request)
            except (KeyError, RuntimeError, ValueError) as error:
                self.pre_accept_audit_changed.emit(False, f"采用前审校失败：{error}")
                self.failed.emit(str(error))
        self.run_changed.emit(status)

    def _start_pre_accept_model_audit(
        self,
        request: PreAcceptModelAuditRequest,
    ) -> None:
        self._pending_pre_accept_snapshot = request.snapshot
        self.pre_accept_audit_changed.emit(False, "确定性检查通过，正在运行模型语义审校")
        self.audit_coordinator.start_audit(
            request.draft_text,
            request.rules,
            request.output_token_limit,
        )

    def _finish_pre_accept_model_audit(self, value: object) -> None:
        snapshot = self._pending_pre_accept_snapshot
        if snapshot is None:
            self._fail_pre_accept_model_audit("模型审校返回了无效结果")
            return
        try:
            blocker_count = self.session.record_pre_accept_model_audit(
                snapshot,
                value,
            )
            self.pre_accept_audit_changed.emit(
                blocker_count == 0,
                (
                    "采用前确定性检查与模型审校均通过，可以人工采用"
                    if blocker_count == 0
                    else f"模型审校发现 {blocker_count} 个阻断问题，请先处理"
                ),
            )
        except (KeyError, RuntimeError, ValueError) as error:
            self._fail_pre_accept_model_audit(str(error))
        finally:
            self._pending_pre_accept_snapshot = None

    def _fail_pre_accept_model_audit(self, message: str) -> None:
        self._pending_pre_accept_snapshot = None
        self.pre_accept_audit_changed.emit(False, f"采用前模型审校失败：{message}")


def recovered_draft_text(value: object) -> tuple[str, GenerationStatus] | None:
    if not isinstance(value, RecoverableGeneration) or value.draft_text is None:
        return None
    return value.draft_text, value.run.status
