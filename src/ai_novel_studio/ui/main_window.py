from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.application.brief_lifecycle_service import BriefValidationError
from ai_novel_studio.application.chapter_context_pin_service import (
    ChapterContextPinService,
)
from ai_novel_studio.application.character_identity_service import (
    CharacterIdentityService,
)
from ai_novel_studio.application.character_status_service import CharacterStatusService
from ai_novel_studio.application.chat_context_service import ChatContextService
from ai_novel_studio.application.deterministic_audit_service import (
    DeterministicAuditRequest,
    DeterministicAuditService,
)
from ai_novel_studio.application.manuscript_import_service import ManuscriptImportService
from ai_novel_studio.application.manuscript_memory_build_service import (
    ManuscriptMemoryBuildFailure,
    ManuscriptMemoryBuildReport,
    ManuscriptMemoryBuildService,
    MemoryBuildProgress,
    MemoryBuildProgressPhase,
)
from ai_novel_studio.application.memory_analysis_service import MemoryAnalysisService
from ai_novel_studio.application.memory_workspace_service import MemoryWorkspaceService
from ai_novel_studio.application.model_tasks import (
    ChatSummaryResult,
    NormalizedBrief,
    StyleAuditResult,
)
from ai_novel_studio.application.plot_memory_context_service import (
    PlotMemoryContextService,
)
from ai_novel_studio.application.project_guidance_service import ProjectGuidanceService
from ai_novel_studio.application.project_memory_workspace_gateway import (
    ProjectMemoryWorkspaceGateway,
)
from ai_novel_studio.application.project_runtime import ProjectRuntime
from ai_novel_studio.application.repair_application_service import RepairApplicationError
from ai_novel_studio.application.setting_document_service import (
    SettingDocumentAnalysisService,
    SettingDocumentMemoryService,
    SettingImportReport,
)
from ai_novel_studio.application.style_workspace_service import StyleWorkspaceService
from ai_novel_studio.domain.agent import AgentToolCallStatus, AgentToolName
from ai_novel_studio.domain.audit import AuditFindingStatus
from ai_novel_studio.infrastructure.llm import LLMMessage, TaskPurpose, UsageSnapshot
from ai_novel_studio.infrastructure.llm.contract_runner import LLMContractRunner
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    ImmutableBriefError,
    StaleBriefError,
)
from ai_novel_studio.infrastructure.storage.chapter_context_pin_repository import (
    ChapterContextPinRepository,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
    ProjectGuidanceRepository,
)
from ai_novel_studio.ui.appearance import appearance_manager
from ai_novel_studio.ui.demo_data import DemoMessage, WorkspaceDemoData
from ai_novel_studio.ui.pages.agent_trace_window import AgentTraceWindow
from ai_novel_studio.ui.pages.audit_window import AuditWindow
from ai_novel_studio.ui.pages.brief_dialog import BriefDialog
from ai_novel_studio.ui.pages.detached_chat_window import DetachedChatWindow
from ai_novel_studio.ui.pages.generation_process_dialog import GenerationProcessDialog
from ai_novel_studio.ui.pages.memory_window import MemoryWindow
from ai_novel_studio.ui.pages.project_welcome import ProjectWelcome
from ai_novel_studio.ui.pages.reference_window import ReferenceWindow
from ai_novel_studio.ui.pages.settings_dialog import SettingsDialog
from ai_novel_studio.ui.pages.style_rules_window import StyleRulesWindow
from ai_novel_studio.ui.panels.chapter_sidebar import ChapterSidebar
from ai_novel_studio.ui.panels.manuscript_panel import ManuscriptPanel
from ai_novel_studio.ui.panels.plot_chat_panel import PlotChatPanel
from ai_novel_studio.ui.panels.top_bar import TopBar
from ai_novel_studio.ui.qt.memory_build_coordinator import MemoryBuildCoordinator
from ai_novel_studio.ui.qt.model_runtime import ModelRuntime
from ai_novel_studio.ui.qt.model_task_coordinator import ModelTaskCoordinator
from ai_novel_studio.ui.qt.project_generation_runtime import (
    QtProjectGenerationRuntime,
    recovered_draft_text,
)
from ai_novel_studio.ui.qt.setting_document_coordinator import (
    SettingDocumentCoordinator,
)


def _memory_build_failure_text(
    failures: tuple[ManuscriptMemoryBuildFailure, ...],
) -> str:
    if not failures:
        return ""
    previews = "；".join(
        f"{failure.chapter_title[:60]}（{failure.message[:120]}）"
        for failure in failures[:3]
    )
    remainder = len(failures) - 3
    remainder_text = f"；另有 {remainder} 章" if remainder > 0 else ""
    return (
        f"，模型失败 {len(failures)} 章（已保留可重试记录）："
        f"{previews}{remainder_text}"
    )


class MainWindow(QMainWindow):
    def __init__(
        self,
        model_runtime: ModelRuntime | None = None,
        generation_runtime: Any | None = None,
        agent_runtime: Any | None = None,
        project_runtime: ProjectRuntime | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("AI Novel Studio")
        self.setMinimumSize(1100, 680)
        self.resize(1440, 900)
        self.setStyleSheet(appearance_manager().stylesheet())
        appearance_manager().appearance_changed.connect(self._apply_appearance)
        self.model_runtime = model_runtime or ModelRuntime.create_default()
        self.generation_runtime = generation_runtime
        self.agent_runtime = agent_runtime
        self.project_runtime = project_runtime
        self.current_chapter_id: str | None = None
        self.chat_session_id: str | None = None
        self._pending_chat_summary: tuple[int, int] | None = None
        model_service = getattr(self.model_runtime, "service", None)
        self.chat_summary_coordinator = (
            ModelTaskCoordinator(model_service, self) if model_service is not None else None
        )
        if self.chat_summary_coordinator is not None:
            self.chat_summary_coordinator.chat_summary_ready.connect(self.apply_chat_summary)
            self.chat_summary_coordinator.usage_changed.connect(self.update_usage)
            self.chat_summary_coordinator.task_failed.connect(self.chat_summary_failed)
        self.deterministic_audit_service = DeterministicAuditService()
        self.manuscript_import_service = ManuscriptImportService()
        gateway = getattr(self.model_runtime, "gateway", None)
        analyzer = (
            MemoryAnalysisService(LLMContractRunner(gateway)) if gateway is not None else None
        )
        setting_analyzer = (
            SettingDocumentAnalysisService(LLMContractRunner(gateway))
            if gateway is not None
            else None
        )
        self.setting_document_service = SettingDocumentMemoryService(setting_analyzer)
        self.setting_document_coordinator = SettingDocumentCoordinator(self)
        self.setting_document_coordinator.completed.connect(self.finish_setting_document)
        self.setting_document_coordinator.failed.connect(self.fail_setting_document)
        self.manuscript_memory_build_service = ManuscriptMemoryBuildService(analyzer)
        self.memory_build_coordinator = MemoryBuildCoordinator(
            self.manuscript_memory_build_service, self
        )
        self.memory_build_coordinator.progress_changed.connect(self.update_memory_build_progress)
        self.memory_build_coordinator.completed.connect(self.finish_project_memory)
        self.memory_build_coordinator.failed.connect(self.fail_project_memory)

        self.data = (
            WorkspaceDemoData.sample()
            if self.project_runtime is not None
            else WorkspaceDemoData.empty()
        )
        self.brief_dialog: BriefDialog | None = None
        self.detached_chat_window: DetachedChatWindow | None = None
        self.memory_window: MemoryWindow | None = None
        self.style_rules_window: StyleRulesWindow | None = None
        self.audit_window: AuditWindow | None = None
        self.agent_trace_window: AgentTraceWindow | None = None
        self.reference_window: ReferenceWindow | None = None
        self.generation_process_dialog: GenerationProcessDialog | None = None
        self.last_agent_result: Any | None = None
        self._pending_model_audit: Any | None = None
        self._model_audit_pending = False
        self._brief_normalization_pending = False
        self.settings_dialog: SettingsDialog | None = None
        self._bound_generation_runtime: Any | None = None
        surface = QWidget(self)
        surface.setObjectName("appSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.top_bar = TopBar(self.data, surface)
        layout.addWidget(self.top_bar)
        self.project_welcome = ProjectWelcome(surface)
        self.project_welcome.setVisible(project_runtime is None)
        layout.addWidget(self.project_welcome)

        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, surface)
        self.workspace_splitter.setObjectName("workspaceSplitter")
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(5)

        self.chapter_sidebar = ChapterSidebar(self.data, self.workspace_splitter)
        self.manuscript_panel = ManuscriptPanel(self.data, self.workspace_splitter)
        self.plot_chat_panel = PlotChatPanel(self.data.messages, self.workspace_splitter)
        self.workspace_splitter.addWidget(self.chapter_sidebar)
        self.workspace_splitter.addWidget(self.manuscript_panel)
        self.workspace_splitter.addWidget(self.plot_chat_panel)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setStretchFactor(2, 0)
        self.workspace_splitter.setSizes([280, 760, 360])
        layout.addWidget(self.workspace_splitter, 1)
        self.setCentralWidget(surface)
        self.manuscript_panel.brief_requested.connect(self.open_brief_dialog)
        self.manuscript_panel.references_requested.connect(self.open_reference_window)
        self.plot_chat_panel.message_sent.connect(
            lambda message: self.request_plot_reply(message, self.plot_chat_panel)
        )
        self.plot_chat_panel.chapter_requirement_requested.connect(self.request_requirement)
        self.plot_chat_panel.detach_requested.connect(self.open_detached_chat)
        self.plot_chat_panel.agent_trace_requested.connect(self.open_agent_trace_window)
        self.plot_chat_panel.summary_requested.connect(self.open_chat_summary_editor)
        self.chapter_sidebar.memory_requested.connect(self.open_memory_window)
        self.chapter_sidebar.memory_build_requested.connect(self.build_project_memory)
        self.chapter_sidebar.style_requested.connect(self.open_style_rules_window)
        self.chapter_sidebar.audit_requested.connect(self.open_audit_window)
        self.chapter_sidebar.chapter_selected.connect(self.load_project_chapter)
        self.chapter_sidebar.chapter_create_requested.connect(self.create_project_chapter)
        self.chapter_sidebar.volume_create_requested.connect(self.create_project_volume)
        self.chapter_sidebar.rename_requested.connect(self.rename_project_tree_item)
        self.chapter_sidebar.delete_requested.connect(self.delete_project_tree_item)
        self.chapter_sidebar.character_edit_applied.connect(self.save_sidebar_character_state)
        self.manuscript_panel.audit_requested.connect(self.open_audit_window)
        self.manuscript_panel.save_requested.connect(self.save_current_chapter)
        self.manuscript_panel.generation_requested.connect(self.request_prose_generation)
        self.manuscript_panel.generation_cancel_requested.connect(self.cancel_prose_generation)
        self.manuscript_panel.draft_accept_requested.connect(self.accept_prose_generation)
        self.manuscript_panel.draft_discard_requested.connect(self.discard_prose_generation)
        self.manuscript_panel.recovery_requested.connect(self.recover_prose_generation)
        self.top_bar.settings_requested.connect(self.open_settings_dialog)
        self.project_welcome.create_project_requested.connect(self.create_project_path)
        self.project_welcome.open_project_requested.connect(self.open_project_path)
        self.project_welcome.import_file_requested.connect(self.import_manuscript_file)
        coordinator = self.model_runtime.coordinator
        coordinator.chat_chunk.connect(self.append_plot_chat_chunk)
        coordinator.chat_finished.connect(self.finish_plot_chat_response)
        coordinator.requirement_ready.connect(self.apply_model_requirement)
        coordinator.brief_ready.connect(self.apply_normalized_brief)
        coordinator.audit_ready.connect(self.apply_model_audit)
        coordinator.task_failed.connect(self.show_model_error)
        coordinator.usage_changed.connect(self.update_usage)
        self._bind_generation_runtime()
        if self.project_runtime is not None:
            self.apply_project_runtime(self.project_runtime)

    def create_project_path(self, root: str | Path, title: str) -> None:
        runtime = ProjectRuntime.create(Path(root), title, self.model_runtime)
        self.apply_project_runtime(runtime)

    def open_project_path(self, root: str | Path) -> None:
        runtime = ProjectRuntime.open(Path(root), self.model_runtime)
        self.apply_project_runtime(runtime)

    def import_manuscript_file(self, source: str | Path) -> None:
        source_path = Path(source)
        try:
            if self.project_runtime is None:
                destination = QFileDialog.getExistingDirectory(
                    self,
                    "选择导入后项目保存位置",
                    str(source_path.parent),
                )
                if not destination:
                    return
                title, accepted = QInputDialog.getText(
                    self,
                    "导入为新项目",
                    "项目名称：",
                    text=source_path.stem,
                )
                if not accepted or not title.strip():
                    return
                self.apply_project_runtime(
                    ProjectRuntime.create(Path(destination), title.strip(), self.model_runtime)
                )
            if self.project_runtime is None:
                return
            report = self.manuscript_import_service.import_file(
                self.project_runtime.project,
                source_path,
            )
            self.refresh_project_tree()
            if report.first_chapter_id is not None:
                self.load_project_chapter(report.first_chapter_id)
            QMessageBox.information(
                self,
                "导入完成",
                f"已导入 {report.imported_chapters} 章。下一步请点击左侧「整理记忆」。",
            )
        except Exception as exc:  # pragma: no cover - UI safety net
            QMessageBox.critical(self, "导入失败", str(exc))

    def apply_project_runtime(self, runtime: ProjectRuntime) -> None:
        if self.style_rules_window is not None:
            self.style_rules_window.close()
            self.style_rules_window = None
        self.project_runtime = runtime
        self.agent_runtime = runtime.agent_runtime
        self.generation_runtime = QtProjectGenerationRuntime(runtime.generation_session)
        self._bind_generation_runtime()
        summary = runtime.workspace.summary()
        self.top_bar.update_project(summary.title, str(summary.root))
        self.project_welcome.setVisible(False)
        self.refresh_project_tree()
        self.refresh_character_sidebar()
        self.restore_project_chat_history()
        volumes = runtime.workspace.volume_tree()
        for volume in volumes:
            if volume.chapters:
                self.load_project_chapter(volume.chapters[0].id)
                return

    def refresh_project_tree(self) -> None:
        if self.project_runtime is None:
            return
        self.chapter_sidebar.apply_volume_tree(self.project_runtime.workspace.volume_tree())

    def create_project_volume(self) -> None:
        if self.project_runtime is None:
            return
        title, accepted = QInputDialog.getText(self, "新增卷", "卷名称：")
        if not accepted or not title.strip():
            return
        try:
            self.project_runtime.workspace.create_volume(title)
        except (LookupError, RuntimeError, ValueError) as error:
            self.manuscript_panel.pipeline_status_label.setText(f"新增卷失败：{error}")
            return
        self.refresh_project_tree()
        self.manuscript_panel.pipeline_status_label.setText("新卷已创建")

    def create_project_chapter(self, volume_id: str) -> None:
        if self.project_runtime is None:
            return
        title, accepted = QInputDialog.getText(self, "新增章节", "章节标题：")
        if not accepted or not title.strip():
            return
        tree = self.project_runtime.workspace.volume_tree()
        volume = next((item for item in tree if item.id == volume_id), None)
        declared_number = f"第 {len(volume.chapters) + 1} 章" if volume is not None else ""
        try:
            chapter = self.project_runtime.workspace.create_chapter(
                volume_id,
                title,
                declared_number,
            )
        except (LookupError, RuntimeError, ValueError) as error:
            self.manuscript_panel.pipeline_status_label.setText(f"新增章节失败：{error}")
            return
        self.refresh_project_tree()
        self.chapter_sidebar.select_chapter(chapter.id)
        self.load_project_chapter(chapter.id)
        self.manuscript_panel.pipeline_status_label.setText("新章节已创建")

    def rename_project_tree_item(self, kind: str, item_id: str) -> None:
        if self.project_runtime is None:
            return
        current_title = self._project_tree_item_title(kind, item_id)
        title, accepted = QInputDialog.getText(
            self,
            "重命名",
            "新名称：",
            text=current_title,
        )
        if not accepted or not title.strip() or title.strip() == current_title:
            return
        try:
            if kind == "chapter":
                self.project_runtime.workspace.rename_chapter(item_id, title)
            elif kind == "volume":
                self.project_runtime.workspace.rename_volume(item_id, title)
            else:
                raise ValueError("未知的章节树项目")
        except (KeyError, RuntimeError, ValueError) as error:
            self.manuscript_panel.pipeline_status_label.setText(f"重命名失败：{error}")
            return
        self.refresh_project_tree()
        if kind == "chapter":
            self.chapter_sidebar.select_chapter(item_id)
            if item_id == self.current_chapter_id:
                self.load_project_chapter(item_id)
        self.manuscript_panel.pipeline_status_label.setText("名称已更新")

    def delete_project_tree_item(self, kind: str, item_id: str) -> None:
        if self.project_runtime is None:
            return
        title = self._project_tree_item_title(kind, item_id)
        detail = (
            "章节正文会移入项目回收区，可由底层恢复。"
            if kind == "chapter"
            else "卷内章节会自动移动到相邻卷，不会删除正文。"
        )
        answer = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除“{title}”吗？\n{detail}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if kind == "chapter":
                self.project_runtime.workspace.delete_chapter(item_id)
                if self.current_chapter_id == item_id:
                    self.current_chapter_id = None
            elif kind == "volume":
                self.project_runtime.workspace.delete_volume(item_id)
            else:
                raise ValueError("未知的章节树项目")
        except (KeyError, RuntimeError, ValueError) as error:
            self.manuscript_panel.pipeline_status_label.setText(f"删除失败：{error}")
            return
        self.refresh_project_tree()
        if self.current_chapter_id is not None:
            self.chapter_sidebar.select_chapter(self.current_chapter_id)
        else:
            self._load_first_project_chapter()
        self.manuscript_panel.pipeline_status_label.setText("删除完成；正文未被静默销毁")

    def _project_tree_item_title(self, kind: str, item_id: str) -> str:
        if self.project_runtime is None:
            return ""
        for volume in self.project_runtime.workspace.volume_tree():
            if kind == "volume" and volume.id == item_id:
                return volume.title
            for chapter in volume.chapters:
                if kind == "chapter" and chapter.id == item_id:
                    return chapter.title
        return ""

    def _load_first_project_chapter(self) -> None:
        if self.project_runtime is None:
            return
        for volume in self.project_runtime.workspace.volume_tree():
            if volume.chapters:
                self.chapter_sidebar.select_chapter(volume.chapters[0].id)
                self.load_project_chapter(volume.chapters[0].id)
                return

    def load_project_chapter(self, chapter_id: str) -> None:
        if self.project_runtime is None:
            return
        workspace = self.project_runtime.workspace.load_chapter(chapter_id)
        self.current_chapter_id = workspace.id
        self.manuscript_panel.apply_chapter_workspace(workspace)
        frozen_brief = (
            self.generation_runtime.select_chapter(workspace.id, workspace.revision)
            if self.generation_runtime is not None
            else False
        )
        self.manuscript_panel.set_phase5_generation_enabled(
            True, frozen_brief_available=frozen_brief
        )
        self.refresh_character_sidebar()

    def refresh_character_sidebar(self) -> None:
        if self.project_runtime is None or self.current_chapter_id is None:
            return
        records = CharacterStatusService(
            CharacterMemoryRepository(self.project_runtime.project)
        ).list_cards_for_chapter(self.current_chapter_id, inclusive=True)
        self.chapter_sidebar.apply_character_records(records)

    def save_sidebar_character_state(self, payload: object) -> None:
        if self.project_runtime is None or self.current_chapter_id is None:
            return
        if not isinstance(payload, dict):
            return
        try:
            CharacterStatusService(CharacterMemoryRepository(self.project_runtime.project)).save(
                self.current_chapter_id,
                character_id=str(payload.get("id") or ""),
                name=str(payload.get("name") or ""),
                profile=str(payload.get("profile") or ""),
                motivation=str(payload.get("motivation") or ""),
                psychology=str(payload.get("psychology") or ""),
                goal=str(payload.get("goal") or ""),
                relationships=str(payload.get("relationships") or ""),
                recent=str(payload.get("recent") or ""),
            )
        except Exception as exc:  # pragma: no cover - UI safety net
            self.manuscript_panel.pipeline_status_label.setText(f"人物状态保存失败：{exc}")
            self.chapter_sidebar.set_character_feedback(f"保存失败：{exc}")
            return
        self.refresh_character_sidebar()
        self.manuscript_panel.pipeline_status_label.setText("人物状态已保存到记忆库")
        self.chapter_sidebar.set_character_feedback("人物状态已保存到当前章节节点。")

    def save_current_chapter(self) -> None:
        if self.project_runtime is None or self.current_chapter_id is None:
            self.manuscript_panel.save_status_label.setText("未打开项目，无法保存")
            return
        result = self.project_runtime.workspace.save_chapter(
            self.current_chapter_id,
            self.manuscript_panel.editor.toPlainText(),
            expected_revision=self.manuscript_panel.current_chapter_revision,
            requirement_content=self.manuscript_panel.chapter_requirement.toPlainText(),
            expected_requirement_revision=(self.manuscript_panel.current_requirement_revision),
            requirement_locked=self.manuscript_panel.requirement_locked(),
        )
        self.manuscript_panel.mark_saved(
            result.revision,
            result.requirement_revision,
        )
        if self.generation_runtime is not None:
            frozen_brief = self.generation_runtime.select_chapter(
                self.current_chapter_id, result.revision
            )
            self.manuscript_panel.set_frozen_brief_available(frozen_brief)
        self._update_current_chapter_tree(result.revision)

    def open_brief_dialog(self) -> None:
        if self.brief_dialog is None:
            self.brief_dialog = BriefDialog(self.data.brief, self)
            self.brief_dialog.normalize_requested.connect(self.request_brief_normalization)
            self.brief_dialog.save_requested.connect(self.save_project_brief)
            self.brief_dialog.freeze_requested.connect(self.freeze_project_brief)
            self.brief_dialog.clone_requested.connect(self.clone_project_brief)
            self.brief_dialog.recompile_requested.connect(self.recompile_project_brief)
        if self.project_runtime is not None and self.current_chapter_id is not None:
            try:
                brief = self.project_runtime.brief_service.load_or_compile(
                    self.current_chapter_id,
                    self.manuscript_panel.target_words.value(),
                )
                self.brief_dialog.bind_project_brief(brief)
            except (KeyError, OSError, RuntimeError, ValueError) as exc:
                self.brief_dialog.show_load_error(str(exc))
        self.brief_dialog.show()
        self.brief_dialog.raise_()
        self.brief_dialog.activateWindow()

    def open_reference_window(self) -> None:
        if self.reference_window is None:
            self.reference_window = ReferenceWindow(self)
        manifest = None
        if self.generation_runtime is not None and self.current_chapter_id is not None:
            try:
                manifest = self.generation_runtime.latest_context_manifest(
                    self.current_chapter_id
                )
            except (KeyError, OSError, TypeError, ValueError) as exc:
                self.reference_window.show_error(str(exc))
            else:
                self.reference_window.bind_manifest(manifest)
        else:
            self.reference_window.bind_manifest(manifest)
        self._show_workspace_window(self.reference_window)

    def save_project_brief(self) -> bool:
        if self.project_runtime is None or self.brief_dialog is None:
            return False
        try:
            brief_id, revision = self.brief_dialog.project_brief_identity()
            brief = self.project_runtime.brief_service.save(
                brief_id,
                self.brief_dialog.project_draft_data(),
                revision,
            )
            self.brief_dialog.bind_project_brief(brief)
            return True
        except (BriefValidationError, ImmutableBriefError, StaleBriefError, ValueError) as exc:
            self.brief_dialog.show_error(str(exc))
            return False

    def freeze_project_brief(self) -> None:
        if self.project_runtime is None or self.brief_dialog is None:
            return
        if not self.save_project_brief():
            return
        try:
            brief_id, revision = self.brief_dialog.project_brief_identity()
            brief = self.project_runtime.brief_service.freeze(brief_id, revision)
            self.brief_dialog.bind_project_brief(brief)
        except (BriefValidationError, ImmutableBriefError, StaleBriefError, ValueError) as exc:
            self.brief_dialog.show_error(str(exc))
            return
        if self.generation_runtime is not None and self.current_chapter_id is not None:
            available = self.generation_runtime.select_chapter(
                self.current_chapter_id,
                self.manuscript_panel.current_chapter_revision,
            )
            self.manuscript_panel.set_frozen_brief_available(available)

    def clone_project_brief(self) -> None:
        if self.project_runtime is None or self.brief_dialog is None:
            return
        brief_id, _revision = self.brief_dialog.project_brief_identity()
        try:
            result = self.project_runtime.brief_service.clone(brief_id)
            self.brief_dialog.bind_project_brief(result.brief)
        except (BriefValidationError, ImmutableBriefError, StaleBriefError, ValueError) as exc:
            self.brief_dialog.show_error(str(exc))

    def recompile_project_brief(self) -> None:
        if (
            self.project_runtime is None
            or self.brief_dialog is None
            or self.current_chapter_id is None
        ):
            return
        try:
            brief = self.project_runtime.brief_service.recompile(
                self.current_chapter_id,
                self.manuscript_panel.target_words.value(),
            )
            self.brief_dialog.bind_project_brief(brief)
        except (BriefValidationError, ImmutableBriefError, StaleBriefError, ValueError) as exc:
            self.brief_dialog.show_error(str(exc))

    def request_plot_reply(
        self,
        message: str,
        source_panel: PlotChatPanel | None = None,
    ) -> None:
        source_panel = source_panel or self.plot_chat_panel
        self._mirror_user_message(message, source_panel)
        self.persist_chat_message("user", message)
        if source_panel.agent_mode_enabled():
            self.request_agent_plot_reply(message)
            return
        self.begin_plot_chat_response()
        self.model_runtime.coordinator.start_chat(
            self._conversation_messages(),
            self.manuscript_panel.editor.toPlainText(),
            self.manuscript_panel.output_token_limit.value(),
        )

    def request_requirement(self) -> None:
        if self.manuscript_panel.requirement_locked():
            self.manuscript_panel.requirement_status.setText("人工指令 · 已锁定，模型草稿未请求")
            return
        self.plot_chat_panel.set_requirement_busy(True)
        self.model_runtime.coordinator.start_requirement(
            self._conversation_messages(),
            self.manuscript_panel.editor.toPlainText(),
            self.manuscript_panel.output_token_limit.value(),
        )

    def apply_model_requirement(self, text: str) -> None:
        self.manuscript_panel.apply_requirement_draft(text)
        self.plot_chat_panel.set_requirement_busy(False)

    def request_brief_normalization(self, source: str) -> None:
        if self.brief_dialog is not None:
            self.brief_dialog.set_normalization_busy(True)
        self._brief_normalization_pending = True
        self.model_runtime.coordinator.start_brief(
            source,
            self.manuscript_panel.output_token_limit.value(),
        )

    def apply_normalized_brief(self, value: object) -> None:
        self._brief_normalization_pending = False
        if self.brief_dialog is not None and isinstance(value, NormalizedBrief):
            self.brief_dialog.apply_normalized_brief(value)

    def request_model_audit(self) -> None:
        if self.audit_window is not None:
            self.audit_window.error_label.clear()
            self.audit_window.run_model_audit_button.setEnabled(False)
            self.audit_window.run_model_audit_button.setText("审校中…")
        self._model_audit_pending = True
        try:
            rules: tuple[str, ...] = (
                "保持人物声音和叙述视角一致",
                "避免直接解释人物情绪",
            )
            if self.project_runtime is not None and self.current_chapter_id is not None:
                rules = self.project_runtime.audit_service.model_context_rules(
                    self.current_chapter_id
                )
                gateway = getattr(self.model_runtime, "gateway", None)
                if gateway is not None:
                    route = gateway.configuration.routes.resolve(TaskPurpose.STYLE_AUDIT)
                    self._pending_model_audit = (
                        self.project_runtime.audit_service.model_snapshot(
                            chapter_id=self.current_chapter_id,
                            text=self.manuscript_panel.editor.toPlainText(),
                            revision=self.manuscript_panel.current_chapter_revision,
                            mode=self.manuscript_panel.current_creation_mode(),
                            model_provider_id=route.provider_id,
                            model_id=route.model_id,
                        )
                    )
            self.model_runtime.coordinator.start_audit(
                self.manuscript_panel.editor.toPlainText(),
                rules,
                self.manuscript_panel.output_token_limit.value(),
            )
        except (KeyError, RuntimeError, ValueError) as error:
            self._pending_model_audit = None
            self._model_audit_pending = False
            if self.audit_window is not None:
                self.audit_window.show_error(str(error))

    def request_deterministic_audit(self) -> None:
        if self.audit_window is not None:
            self.audit_window.error_label.clear()
            self.audit_window.run_deterministic_audit_button.setEnabled(False)
            self.audit_window.run_deterministic_audit_button.setText("检查中…")
        try:
            findings: tuple[Any, ...]
            if self.project_runtime is not None and self.current_chapter_id is not None:
                findings = self.project_runtime.audit_service.run_deterministic(
                    chapter_id=self.current_chapter_id,
                    text=self.manuscript_panel.editor.toPlainText(),
                    revision=self.manuscript_panel.current_chapter_revision,
                    requirement=self.manuscript_panel.chapter_requirement.toPlainText(),
                    mode=self.manuscript_panel.current_creation_mode(),
                )
            else:
                findings = self.deterministic_audit_service.run(
                    DeterministicAuditRequest(
                        chapter_id="ui-current-chapter",
                        target_text=self.manuscript_panel.editor.toPlainText(),
                        target_revision=0,
                        target_hash="ui-preview",
                        requirement_content=(
                            self.manuscript_panel.chapter_requirement.toPlainText()
                        ),
                    )
                )
            if self.audit_window is not None:
                self.audit_window.apply_deterministic_findings(findings)
        except (KeyError, RuntimeError, ValueError) as error:
            if self.audit_window is not None:
                self.audit_window.show_deterministic_error(str(error))

    def request_prose_generation(
        self,
        mode: object,
        output_token_limit: int,
        target_words: int,
    ) -> None:
        if self.generation_runtime is None:
            self.manuscript_panel.show_generation_error("正文生成运行时尚未连接")
            return
        self.open_generation_process_dialog()
        self.manuscript_panel.begin_generation_draft()
        self.generation_runtime.prepare_and_start(
            mode,
            output_token_limit,
            target_words,
            requirement_content=self.manuscript_panel.chapter_requirement.toPlainText(),
            expected_requirement_revision=(
                self.manuscript_panel.current_requirement_revision
            ),
            requirement_locked=self.manuscript_panel.requirement_locked(),
        )

    def open_generation_process_dialog(self) -> None:
        if self.generation_process_dialog is None:
            self.generation_process_dialog = GenerationProcessDialog(self)
        self.generation_process_dialog.begin()
        self.generation_process_dialog.show()
        self.generation_process_dialog.raise_()
        self.generation_process_dialog.activateWindow()

    def append_generation_reasoning(self, text: str) -> None:
        if self.generation_process_dialog is not None:
            self.generation_process_dialog.append_reasoning(text)

    def append_generation_draft(self, text: str) -> None:
        self.manuscript_panel.append_generation_draft(text)
        if self.generation_process_dialog is not None:
            self.generation_process_dialog.note_draft_chunk()

    def apply_generation_status(self, status: Any) -> None:
        self.manuscript_panel.apply_generation_status(status)
        if self.generation_process_dialog is not None:
            self.generation_process_dialog.apply_status(status)

    def show_generation_error(self, message: str) -> None:
        self.manuscript_panel.show_generation_error(message)
        if self.generation_process_dialog is not None:
            self.generation_process_dialog.show_error(message)

    def update_generation_usage(self, usage: object) -> None:
        if self.generation_process_dialog is not None:
            self.generation_process_dialog.apply_usage(usage)

    def cancel_prose_generation(self) -> None:
        if self.generation_runtime is not None:
            self.generation_runtime.cancel_current()

    def accept_prose_generation(self) -> None:
        if self.generation_runtime is not None:
            self.generation_runtime.accept_current()

    def discard_prose_generation(self) -> None:
        if self.generation_runtime is not None:
            self.generation_runtime.discard_current()

    def recover_prose_generation(self) -> None:
        if self.generation_runtime is not None:
            self.generation_runtime.recover()

    def apply_model_audit(self, value: object) -> None:
        self._model_audit_pending = False
        if self.audit_window is not None and isinstance(value, StyleAuditResult):
            self.audit_window.error_label.clear()
            if self.project_runtime is not None and self._pending_model_audit is not None:
                try:
                    findings = self.project_runtime.audit_service.record_model_result(
                        self._pending_model_audit, value
                    )
                    self.audit_window.apply_saved_model_findings(findings)
                except ValueError as exc:
                    self.audit_window.show_error(str(exc))
                finally:
                    self._pending_model_audit = None
            else:
                self.audit_window.apply_model_audit(value)

    def update_usage(self, value: object) -> None:
        if isinstance(value, UsageSnapshot):
            self.top_bar.update_usage(value)

    def _bind_generation_runtime(self) -> None:
        if self.generation_runtime is None:
            return
        if self._bound_generation_runtime is self.generation_runtime:
            return
        self._bound_generation_runtime = self.generation_runtime
        self.manuscript_panel.set_phase5_generation_enabled(True, frozen_brief_available=False)
        self.generation_runtime.draft_chunk.connect(self.append_generation_draft)
        self.generation_runtime.run_changed.connect(self.apply_generation_status)
        self.generation_runtime.failed.connect(self.show_generation_error)
        self.generation_runtime.accepted.connect(self.apply_accepted_generation)
        self.generation_runtime.discarded.connect(self.manuscript_panel.discard_generation_draft)
        recovered = getattr(self.generation_runtime, "recovered", None)
        if recovered is not None:
            recovered.connect(self.apply_recovered_generation)
        usage_changed = getattr(self.generation_runtime, "usage_changed", None)
        if usage_changed is not None:
            usage_changed.connect(self.update_usage)
        reasoning_chunk = getattr(self.generation_runtime, "reasoning_chunk", None)
        if reasoning_chunk is not None:
            reasoning_chunk.connect(self.append_generation_reasoning)
        requirement_saved = getattr(self.generation_runtime, "requirement_saved", None)
        if requirement_saved is not None:
            requirement_saved.connect(self.manuscript_panel.mark_requirement_saved)
        generation_usage = getattr(
            self.generation_runtime, "generation_usage_changed", None
        )
        if generation_usage is not None:
            generation_usage.connect(self.update_generation_usage)
        pre_accept_audit_changed = getattr(
            self.generation_runtime,
            "pre_accept_audit_changed",
            None,
        )
        if pre_accept_audit_changed is not None:
            pre_accept_audit_changed.connect(
                self.manuscript_panel.set_pre_accept_audit_result
            )

    def apply_accepted_generation(self, text: str) -> None:
        self.manuscript_panel.apply_accepted_generation(text)
        revision = getattr(self.generation_runtime, "accepted_chapter_revision", None)
        if isinstance(revision, int):
            self.manuscript_panel.mark_saved(
                revision,
                self.manuscript_panel.current_requirement_revision,
            )
            self._update_current_chapter_tree(revision)

    def _update_current_chapter_tree(self, revision: int) -> None:
        if self.current_chapter_id is None:
            return
        word_count = sum(
            1
            for character in self.manuscript_panel.editor.toPlainText()
            if not character.isspace()
        )
        self.chapter_sidebar.update_chapter_status(
            self.current_chapter_id,
            word_count=word_count,
            revision=revision,
        )

    def apply_recovered_generation(self, value: object) -> None:
        recovered = recovered_draft_text(value)
        if recovered is None:
            self.manuscript_panel.show_generation_error("恢复记录没有可用草稿")
            return
        text, status = recovered
        self.manuscript_panel.begin_generation_draft()
        self.manuscript_panel.append_generation_draft(text)
        self.manuscript_panel.apply_generation_status(status)

    def _conversation_messages(self) -> tuple[LLMMessage, ...]:
        if self.project_runtime is not None and self.chat_session_id is not None:
            session = self.project_runtime.chat_repository.get_or_create_default()
            messages = self.project_runtime.chat_repository.list_messages(session.id)
            context_window = 128_000
            try:
                route = self.model_runtime.gateway.configuration.routes.resolve(
                    TaskPurpose.PLOT_DISCUSSION
                )
                configured = self.model_runtime.gateway.configuration.model(route)
                context_window = configured.capabilities.context_window or context_window
            except (AttributeError, LookupError, ValueError):
                pass
            output_limit = self.manuscript_panel.output_token_limit.value()
            history_budget = max(1_000, min(32_000, context_window - output_limit - 10_000))
            history = (
                ChatContextService().select(session, messages, token_budget=history_budget).messages
            )
            memory_message = None
            if self.current_chapter_id is not None:
                memory_message = (
                    PlotMemoryContextService(self.project_runtime.project)
                    .select(self.current_chapter_id, token_budget=6_000)
                    .message
                )
            return ((memory_message,) if memory_message is not None else ()) + history
        return tuple(
            LLMMessage(message.role, message.text)
            for message in self.plot_chat_panel.message_snapshot()
        )

    def _chat_panels(self) -> tuple[PlotChatPanel, ...]:
        panels = [self.plot_chat_panel]
        if self.detached_chat_window is not None:
            panels.append(self.detached_chat_window.chat_panel)
        return tuple(panels)

    def _mirror_user_message(self, message: str, source_panel: PlotChatPanel) -> None:
        for panel in self._chat_panels():
            if panel is not source_panel:
                panel.append_external_message("user", message)

    def restore_project_chat_history(self) -> None:
        if self.project_runtime is None:
            return
        session = self.project_runtime.chat_repository.get_or_create_default()
        self.chat_session_id = session.id
        messages = tuple(
            DemoMessage(item.role, item.content)
            for item in self.project_runtime.chat_repository.list_messages(session.id)
        )
        self.plot_chat_panel.replace_messages(messages)
        if self.detached_chat_window is not None:
            self.detached_chat_window.chat_panel.replace_messages(messages)

    def persist_chat_message(self, role: str, text: str) -> None:
        if self.project_runtime is None or self.chat_session_id is None or not text.strip():
            return
        self.project_runtime.chat_repository.append(
            self.chat_session_id,
            role,
            text,
            chapter_id=self.current_chapter_id,
        )

    def schedule_chat_compression(self) -> None:
        if (
            self.project_runtime is None
            or self.chat_session_id is None
            or self.chat_summary_coordinator is None
            or self._pending_chat_summary is not None
        ):
            return
        session = self.project_runtime.chat_repository.get_or_create_default()
        messages = self.project_runtime.chat_repository.list_messages(session.id)
        candidate = ChatContextService().compression_candidate(
            session, messages, retain_recent_tokens=8_000
        )
        if candidate is None:
            return
        self._pending_chat_summary = (
            candidate.through_sequence,
            session.summary_revision,
        )
        self.chat_summary_coordinator.start_chat_summary(
            session.summary,
            candidate.transcript,
            self.manuscript_panel.output_token_limit.value(),
        )

    def apply_chat_summary(self, value: object) -> None:
        pending = self._pending_chat_summary
        self._pending_chat_summary = None
        if (
            not isinstance(value, ChatSummaryResult)
            or pending is None
            or self.project_runtime is None
            or self.chat_session_id is None
        ):
            return
        through_sequence, expected_revision = pending
        self.project_runtime.chat_repository.update_summary(
            self.chat_session_id,
            value.summary,
            through_sequence=through_sequence,
            expected_revision=expected_revision,
        )

    def chat_summary_failed(self, _message: str) -> None:
        self._pending_chat_summary = None

    def begin_plot_chat_response(self) -> None:
        for panel in self._chat_panels():
            panel.begin_assistant_response()

    def append_plot_chat_chunk(self, text: str) -> None:
        for panel in self._chat_panels():
            panel.append_assistant_chunk(text)

    def finish_plot_chat_response(self) -> None:
        for panel in self._chat_panels():
            panel.finish_assistant_response()
        messages = self.plot_chat_panel.message_snapshot()
        if messages and messages[-1].role == "assistant":
            self.persist_chat_message("assistant", messages[-1].text)
            self.schedule_chat_compression()

    def show_plot_chat_error(self, message: str) -> None:
        for panel in self._chat_panels():
            panel.show_model_error(message)

    def request_agent_plot_reply(self, message: str) -> None:
        self.begin_plot_chat_response()
        if self.agent_runtime is None:
            self.show_plot_chat_error("Agent 运行时尚未连接")
            return
        try:
            route = self.model_runtime.gateway.configuration.routes.resolve(
                TaskPurpose.AGENT_ASSISTANT
            )
            result = self.agent_runtime.discuss_plot_with_tools(
                user_message=message,
                current_manuscript=self.manuscript_panel.editor.toPlainText(),
                chapter_requirement=self.manuscript_panel.chapter_requirement.toPlainText(),
                conversation_context=self._agent_conversation_context(message),
                chapter_id=self.current_chapter_id or "ui-current-chapter",
                model_provider_id=route.provider_id,
                model_id=route.model_id,
                output_token_limit=self.manuscript_panel.output_token_limit.value(),
            )
        except Exception as exc:  # pragma: no cover - UI safety net
            self.show_plot_chat_error(str(exc))
            return
        self.last_agent_result = result
        status = getattr(result, "status", None)
        status_value = getattr(status, "value", str(status))
        if status_value == "COMPLETED":
            self.append_plot_chat_chunk(result.final_answer)
            self.finish_plot_chat_response()
            self._open_agent_character_identity_proposal(result.run_id)
        else:
            self.show_plot_chat_error(getattr(result, "failure_message", None) or "Agent 调用失败")

    def _open_agent_character_identity_proposal(self, run_id: str) -> None:
        if self.project_runtime is None:
            return
        calls = self.project_runtime.agent_repository.list_tool_calls(run_id)
        has_proposal = any(
            call.tool_name == AgentToolName.PROPOSE_CHARACTER_IDENTITY_MERGE
            and call.status == AgentToolCallStatus.EXECUTED
            for call in calls
        )
        if not has_proposal:
            return
        self.open_memory_window()
        if self.memory_window is not None:
            self.memory_window.open_identity_review()

    def _agent_conversation_context(
        self, current_user_message: str
    ) -> tuple[LLMMessage, ...]:
        messages = list(self._conversation_messages())
        if (
            messages
            and messages[-1].role == "user"
            and messages[-1].content.strip() == current_user_message.strip()
        ):
            messages.pop()
        return tuple(messages)

    def show_model_error(self, message: str) -> None:
        self.show_plot_chat_error(message)
        for panel in self._chat_panels():
            panel.set_requirement_busy(False)
        self.manuscript_panel.pipeline_status_label.setText(f"模型调用失败：{message}")
        if self.brief_dialog is not None:
            self.brief_dialog.set_normalization_busy(False)
            if self._brief_normalization_pending:
                self.brief_dialog.show_error(message)
        self._brief_normalization_pending = False
        if self.audit_window is not None:
            self.audit_window.run_model_audit_button.setEnabled(True)
            self.audit_window.run_model_audit_button.setText("运行模型审校")
            if self._model_audit_pending:
                self.audit_window.show_error(message)
        if self._model_audit_pending:
            self._pending_model_audit = None
        self._model_audit_pending = False

    def open_detached_chat(self) -> None:
        if self.detached_chat_window is None:
            self.detached_chat_window = DetachedChatWindow(
                self.plot_chat_panel.message_snapshot(), self
            )
            self.detached_chat_window.chat_panel.message_sent.connect(
                lambda message: self.request_plot_reply(
                    message,
                    self.detached_chat_window.chat_panel
                    if self.detached_chat_window is not None
                    else self.plot_chat_panel,
                )
            )
            self.detached_chat_window.chat_panel.chapter_requirement_requested.connect(
                self.request_requirement
            )
            self.detached_chat_window.chat_panel.agent_trace_requested.connect(
                self.open_agent_trace_window
            )
            self.detached_chat_window.chat_panel.summary_requested.connect(
                self.open_chat_summary_editor
            )
        self.detached_chat_window.show()
        self.detached_chat_window.raise_()
        self.detached_chat_window.activateWindow()

    def open_chat_summary_editor(self) -> None:
        if self.project_runtime is None or self.chat_session_id is None:
            return
        session = self.project_runtime.chat_repository.get_or_create_default()
        summary, accepted = QInputDialog.getMultiLineText(
            self,
            "剧情商讨长期摘要",
            "摘要用于压缩较早对话；原始聊天记录不会被删除：",
            session.summary,
        )
        if not accepted or not summary.strip():
            return
        through_sequence = session.summarized_through_sequence
        if through_sequence < 0:
            messages = self.project_runtime.chat_repository.list_messages(session.id)
            if not messages:
                return
            through_sequence = messages[-1].sequence
        self.project_runtime.chat_repository.update_summary(
            session.id,
            summary,
            through_sequence=through_sequence,
            expected_revision=session.summary_revision,
        )

    def open_memory_window(self) -> None:
        if self.memory_window is None:
            self.memory_window = MemoryWindow(self.data, self)
            self.memory_window.setting_save_requested.connect(self.save_setting_document)
            self.memory_window.setting_analyze_requested.connect(self.analyze_setting_document)
            self.memory_window.identity_changed.connect(self._character_identity_changed)
        self._bind_memory_window()
        self._show_workspace_window(self.memory_window)

    def _bind_memory_window(self) -> None:
        if self.memory_window is None or self.project_runtime is None:
            return
        project = self.project_runtime.project
        chapter_id = self.current_chapter_id
        self.memory_window.bind(
            MemoryWorkspaceService(ProjectMemoryWorkspaceGateway(project)),
            "__all__",
            pin_service=(
                ChapterContextPinService(ChapterContextPinRepository(project))
                if chapter_id
                else None
            ),
            target_chapter_id=chapter_id,
            guidance_service=ProjectGuidanceService(ProjectGuidanceRepository(project)),
            identity_service=CharacterIdentityService(project),
        )

    def _character_identity_changed(self) -> None:
        self.refresh_character_sidebar()
        self._bind_memory_window()

    def save_setting_document(
        self, title: str, document_type: str, text: str, source_id: object
    ) -> None:
        if self.project_runtime is None:
            QMessageBox.warning(self, "无法保存", "请先打开一个小说项目。")
            return
        try:
            saved_id = self.setting_document_service.save_source(
                self.project_runtime.project,
                title,
                document_type,
                text,
                source_id=str(source_id) if source_id else None,
            )
        except (KeyError, RuntimeError, ValueError) as error:
            if self.memory_window is not None:
                self.memory_window.set_setting_busy(False, f"保存失败：{error}")
            return
        if self.memory_window is not None:
            self.memory_window.setting_saved(saved_id, "原始资料已完整保存")

    def analyze_setting_document(
        self, title: str, document_type: str, text: str, source_id: object
    ) -> None:
        runtime = self.project_runtime
        if runtime is None:
            QMessageBox.warning(self, "无法整理", "请先打开一个小说项目。")
            return
        if self.setting_document_coordinator.is_running:
            return
        if self.memory_window is not None:
            self.memory_window.set_setting_busy(True, "正在后台整理；窗口仍可正常使用……")
        self.setting_document_coordinator.start(
            lambda: self.setting_document_service.analyze_and_store(
                runtime.project,
                title,
                document_type,
                text,
                source_id=str(source_id) if source_id else None,
            )
        )

    def finish_setting_document(self, result: object) -> None:
        if not isinstance(result, SettingImportReport):
            self.fail_setting_document("整理服务返回了无法识别的结果")
            return
        if self.memory_window is not None:
            self.memory_window.setting_saved(
                result.source_id,
                f"整理完成：正典/人物/伏笔候选 {result.created_canon} 条",
            )
            self._bind_memory_window()

    def fail_setting_document(self, message: str) -> None:
        if self.memory_window is not None:
            self.memory_window.set_setting_busy(False, f"整理失败：{message}")

    def build_project_memory(self) -> None:
        if self.project_runtime is None:
            self.manuscript_panel.pipeline_status_label.setText("请先打开或导入项目。")
            return
        if self.memory_build_coordinator.is_running:
            self.memory_build_coordinator.cancel()
            self.manuscript_panel.pipeline_status_label.setText(
                "正在等待当前章节分析结束，随后取消记忆整理……"
            )
            return
        self.chapter_sidebar.set_memory_build_running(True)
        self.manuscript_panel.pipeline_status_label.setText("正在准备记忆整理……")
        self.memory_build_coordinator.start(self.project_runtime.project)

    def update_memory_build_progress(self, progress: MemoryBuildProgress) -> None:
        if progress.phase == MemoryBuildProgressPhase.MODEL_CALL:
            text = (
                f"正在调用模型 {progress.current}/{progress.total}："
                f"{progress.chapter_title}"
            )
        else:
            text = (
                f"正在扫描章节 {progress.current}/{progress.total}："
                f"{progress.chapter_title}（检查是否需要模型整理）"
            )
        self.manuscript_panel.pipeline_status_label.setText(text)

    def finish_project_memory(self, report: ManuscriptMemoryBuildReport) -> None:
        self.chapter_sidebar.set_memory_build_running(False)
        prefix = "记忆整理已取消：" if report.cancelled else "记忆整理完成："
        failure_text = _memory_build_failure_text(report.failures)
        self.manuscript_panel.pipeline_status_label.setText(
            prefix + f"处理 {report.processed_chapters} 章，"
            f"新增摘要 {report.created_summaries} 条，"
            f"新增人物状态 {report.created_character_states} 条，"
            f"正典 {report.created_canon} 条，"
            f"线索 {report.created_clues} 条，"
            f"知识 {report.created_knowledge} 条，"
            f"跳过未变化摘要 {report.skipped_current_summaries} 条，"
            f"本轮新增保底摘要 {report.fallback_summaries} 条，"
            f"待模型升级 {report.pending_upgrade_summaries} 条，"
            f"索引 {report.indexed_documents} 章{failure_text}。"
        )
        self.refresh_character_sidebar()
        self._bind_memory_window()
        snapshot_method = getattr(
            getattr(self.model_runtime, "service", None), "usage_snapshot", None
        )
        if callable(snapshot_method):
            self.update_usage(snapshot_method())

    def fail_project_memory(self, message: str) -> None:
        self.chapter_sidebar.set_memory_build_running(False)
        self.manuscript_panel.pipeline_status_label.setText(f"记忆整理失败：{message}")

    def open_style_rules_window(self) -> None:
        if self.style_rules_window is None:
            service = (
                StyleWorkspaceService(self.project_runtime.project)
                if self.project_runtime is not None
                else None
            )
            default_scope_id = (
                self.project_runtime.project.project.id if self.project_runtime is not None else ""
            )
            self.style_rules_window = StyleRulesWindow(
                self.data,
                self,
                service=service,
                default_scope_id=default_scope_id,
            )
        else:
            self.style_rules_window.reload()
        self._show_workspace_window(self.style_rules_window)

    def open_audit_window(self) -> None:
        if self.audit_window is None:
            self.audit_window = AuditWindow(self.data, self)
            self.audit_window.deterministic_audit_requested.connect(
                self.request_deterministic_audit
            )
            self.audit_window.model_audit_requested.connect(self.request_model_audit)
            self.audit_window.evidence_activated.connect(self.focus_audit_evidence)
            self.audit_window.finding_status_requested.connect(self.update_audit_finding_status)
            self.audit_window.repair_proposal_requested.connect(self.create_audit_repair_proposal)
            self.audit_window.repair_apply_requested.connect(self.apply_audit_repair_proposal)
            self.audit_window.repair_reject_requested.connect(self.reject_audit_repair_proposal)
        if self.project_runtime is not None and self.current_chapter_id is not None:
            self.audit_window.apply_saved_model_findings(
                self.project_runtime.audit_service.latest_model_findings(self.current_chapter_id)
            )
        self._show_workspace_window(self.audit_window)

    def focus_audit_evidence(self, evidence: str) -> None:
        if not evidence.strip():
            return
        editor = self.manuscript_panel.editor
        editor.moveCursor(QTextCursor.MoveOperation.Start)
        if editor.find(evidence):
            editor.setFocus()

    def update_audit_finding_status(self, finding_id: str, status: str) -> None:
        if self.project_runtime is None:
            return
        finding = self.project_runtime.audit_service.update_finding_status(
            finding_id, AuditFindingStatus(status)
        )
        if self.audit_window is not None:
            self.audit_window.mark_finding_status(finding.id, finding.status.value)

    def create_audit_repair_proposal(
        self, finding_id: str, target_text: str, replacement_text: str
    ) -> None:
        if (
            self.project_runtime is None
            or self.current_chapter_id is None
            or self.audit_window is None
        ):
            return
        try:
            proposal = self.project_runtime.audit_service.create_replacement_proposal(
                finding_id=finding_id,
                chapter_id=self.current_chapter_id,
                target_text=target_text,
                replacement_text=replacement_text,
            )
            self.audit_window.show_repair_proposal(proposal)
        except RepairApplicationError as exc:
            self.audit_window.show_repair_error(str(exc))

    def apply_audit_repair_proposal(self, proposal_id: str) -> None:
        if (
            self.project_runtime is None
            or self.current_chapter_id is None
            or self.audit_window is None
            or not proposal_id
        ):
            return
        try:
            self.project_runtime.audit_service.apply_repair_proposal(
                proposal_id,
                chapter_id=self.current_chapter_id,
                expected_revision=self.manuscript_panel.current_chapter_revision,
                visible_text=self.manuscript_panel.editor.toPlainText(),
            )
            chapter_id = self.current_chapter_id
            self.load_project_chapter(chapter_id)
            self.audit_window.mark_repair_applied()
        except RepairApplicationError as exc:
            self.audit_window.show_repair_error(str(exc))

    def reject_audit_repair_proposal(self, proposal_id: str) -> None:
        if self.project_runtime is None or self.audit_window is None or not proposal_id:
            return
        try:
            self.project_runtime.audit_service.reject_repair_proposal(proposal_id)
            self.audit_window.mark_repair_rejected()
        except RepairApplicationError as exc:
            self.audit_window.show_repair_error(str(exc))

    def open_agent_trace_window(self) -> None:
        result = self.last_agent_result
        if result is None and self.project_runtime is not None:
            result = self.project_runtime.agent_repository.latest_run()
        if result is None:
            result = type(
                "EmptyAgentTrace",
                (),
                {
                    "run_id": "暂无",
                    "status": type("Status", (), {"value": "NO_RUN"})(),
                    "final_answer": "",
                    "failure_code": None,
                    "failure_message": None,
                },
            )()
        turns: tuple[LLMMessage, ...] = ()
        tool_calls: tuple[dict[str, object], ...] = ()
        run_id = str(getattr(result, "run_id", getattr(result, "id", "")))
        if self.project_runtime is not None and run_id and run_id != "暂无":
            turns = tuple(
                LLMMessage(turn.role, turn.content)
                for turn in self.project_runtime.agent_repository.list_turns(run_id)
            )
            tool_calls = tuple(
                {
                    "tool_name": getattr(call.tool_name, "value", str(call.tool_name)),
                    "status": getattr(call.status, "value", str(call.status)),
                    "result_chars": call.result_chars,
                    "omitted": " · ".join(
                        part
                        for part in (
                            f"来源 {call.source_refs_json}" if call.source_refs_json else "",
                            call.failure_message or "",
                        )
                        if part
                    ),
                }
                for call in self.project_runtime.agent_repository.list_tool_calls(run_id)
            )
        self.agent_trace_window = AgentTraceWindow(result, turns, tool_calls, self)
        self._show_workspace_window(self.agent_trace_window)

    def open_settings_dialog(self) -> None:
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(
                self, controller=self.model_runtime.settings_controller
            )
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _apply_appearance(self, _theme: str, _density: str) -> None:
        self.setStyleSheet(appearance_manager().stylesheet())

    @staticmethod
    def _show_workspace_window(window: QMainWindow) -> None:
        window.show()
        window.raise_()
        window.activateWindow()

    @staticmethod
    def _placeholder(object_name: str, title: str, minimum_width: int) -> QFrame:
        frame = QFrame()
        frame.setObjectName(object_name)
        frame.setProperty("class", "panelSurface")
        frame.setMinimumWidth(minimum_width)
        label = QLabel(title, frame)
        label.setObjectName("panelTitle")
        layout = QVBoxLayout(frame)
        layout.addWidget(label)
        layout.addStretch(1)
        return frame
