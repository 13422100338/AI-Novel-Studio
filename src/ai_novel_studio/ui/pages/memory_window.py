from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.application.chapter_context_pin_service import (
    ChapterContextPinService,
)
from ai_novel_studio.application.character_identity_service import (
    CharacterIdentityService,
)
from ai_novel_studio.application.memory_workspace_service import (
    MemoryBulkPromotionResult,
    MemoryWorkspaceRecord,
    MemoryWorkspaceService,
)
from ai_novel_studio.application.project_guidance_service import ProjectGuidanceService
from ai_novel_studio.application.view_assertion_service import (
    LegacyReaderViewCandidate,
    ViewAssertionReviewError,
)
from ai_novel_studio.domain.memory import Authority, MemoryStatus, ReviewStatus
from ai_novel_studio.domain.view import ViewAssertion
from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.i18n import language_manager
from ai_novel_studio.ui.pages.character_identity_conflict_dialog import (
    CharacterIdentityConflictDialog,
)
from ai_novel_studio.ui.qt.memory_promotion_coordinator import (
    MemoryPromotionCoordinator,
)

CANON_GROUPS = (
    ("WORLD", "世界观"),
    ("CHARACTER_IDENTITY", "人物身份背景"),
    ("ITEM_ABILITY", "重要物品、能力与兵器"),
    ("ORGANIZATION", "组织、团队与成员"),
)


class ReaderViewOperationService(Protocol):
    def list_legacy_reader_view_candidates(
        self,
    ) -> tuple[LegacyReaderViewCandidate, ...]: ...

    def replace_legacy_reader_event(
        self,
        *,
        legacy_event_id: str,
        subject_id: str,
        content: str,
        confirmed_by_user: bool,
    ) -> object: ...


class ViewAssertionReviewService(Protocol):
    def list_review_candidates(self, *, limit: int = 100) -> tuple[ViewAssertion, ...]: ...

    def approve_candidate(
        self, assertion_id: str, *, confirmed_by_user: bool
    ) -> ViewAssertion: ...

    def reject_candidate(
        self, assertion_id: str, *, confirmed_by_user: bool
    ) -> ViewAssertion: ...


class MemoryWindow(QMainWindow):
    setting_save_requested = Signal(str, str, str, object)
    setting_analyze_requested = Signal(str, str, str, object)
    identity_changed = Signal()
    reader_view_changed = Signal()
    view_assertion_review_changed = Signal()

    def __init__(self, data: WorkspaceDemoData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service: MemoryWorkspaceService | None = None
        self._records: dict[str, MemoryWorkspaceRecord] = {}
        self.selectors: dict[str, QComboBox] = {}
        self.group_selectors: dict[str, QComboBox] = {}
        self._category_records: dict[str, list[MemoryWorkspaceRecord]] = {}
        self.editors: dict[str, QPlainTextEdit] = {}
        self.field_widgets: dict[str, dict[str, QWidget]] = {}
        self.setting_source_id: str | None = None
        self._promotion_coordinator: MemoryPromotionCoordinator | None = None
        self._pin_service: ChapterContextPinService | None = None
        self._pin_chapter_id: str | None = None
        self._guidance_service: ProjectGuidanceService | None = None
        self._guidance_project_id: str | None = None
        self._guidance_revision = 0
        self._identity_service: CharacterIdentityService | None = None
        self.identity_dialog: CharacterIdentityConflictDialog | None = None
        self._reader_view_service: ReaderViewOperationService | None = None
        self._reader_view_candidates: dict[str, LegacyReaderViewCandidate] = {}
        self._view_assertion_review_service: ViewAssertionReviewService | None = None
        self._view_assertion_review_candidates: dict[str, ViewAssertion] = {}
        self._view_assertion_subject_names: dict[str, str] = {}

        self.setWindowTitle("记忆库 · AI Novel Studio")
        self.setMinimumSize(820, 640)
        self.resize(980, 760)

        surface = QWidget(self)
        surface.setObjectName("appSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("长篇记忆库", surface)
        title.setObjectName("panelTitle")
        self.explanation_label = QLabel(
            "AI 生成前，压缩前文只记录已发生剧情、人物成长、连续性与原文细节摘录；"
            "伏笔和未决问题独立存放在叙事线索。"
            "模型提取内容只会成为待审查候选；只有用户明确晋升后才可成为当前记忆。",
            surface,
        )
        self.explanation_label.setWordWrap(True)
        self.explanation_label.setObjectName("mutedLabel")

        self.tabs = QTabWidget(surface)
        self.tabs.setObjectName("memoryTabs")
        self._add_guidance_tab()
        for tab_name, text in data.memory_tabs:
            self._add_demo_tab(tab_name, text)
        self._add_setting_tab()
        self.tabs.currentChanged.connect(self._refresh_current_record)

        note = QFrame(surface)
        note.setObjectName("cardSurface")
        note_layout = QVBoxLayout(note)
        self.metadata_label = QLabel("离线演示数据：尚未绑定项目记忆服务。", note)
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setObjectName("mutedLabel")
        note_layout.addWidget(self.metadata_label)
        actions = QHBoxLayout()
        self.save_button = QPushButton("保存人工修改", note)
        self.save_button.setAccessibleName("保存当前记忆记录")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save_current)
        self.promote_button = QPushButton("晋升为已审查", note)
        self.promote_button.setAccessibleName("晋升当前候选记忆")
        self.promote_button.setEnabled(False)
        self.promote_button.clicked.connect(self._promote_current)
        self.promote_all_button = QPushButton("一键晋升全部候选", note)
        self.promote_all_button.setAccessibleName("晋升记忆库中的全部待审查候选")
        self.promote_all_button.setEnabled(False)
        self.promote_all_button.clicked.connect(self._promote_all)
        self.retry_button = QPushButton("撤销晋升并重整本章", note)
        self.retry_button.setAccessibleName("撤销当前模型摘要晋升并标记重新整理")
        self.retry_button.setToolTip(
            "仅适用于已晋升的模型章节摘要；不会删除记录。标记后请点击主界面的“整理记忆”。"
        )
        self.retry_button.setEnabled(False)
        self.retry_button.clicked.connect(self._request_model_retry)
        self.pin_button = QPushButton("＋ 强制加入当前章", note)
        self.pin_button.setAccessibleName("将当前记忆强制加入当前章 AI 参考")
        self.pin_button.setEnabled(False)
        self.pin_button.clicked.connect(self._toggle_current_pin)
        self.pin_summaries_button = QPushButton("一键加入压缩前文", note)
        self.pin_summaries_button.setAccessibleName("将可用压缩前文加入当前章 AI 参考")
        self.pin_summaries_button.setEnabled(False)
        self.pin_summaries_button.clicked.connect(self._pin_compressed_history)
        self.identity_review_button = QPushButton("人物身份冲突", note)
        self.identity_review_button.setAccessibleName("审查疑似重复人物卡")
        self.identity_review_button.setToolTip(
            "按名称和别名列出疑似重复卡；只有人工确认后才会归并。"
        )
        self.identity_review_button.setEnabled(False)
        self.identity_review_button.clicked.connect(self.open_identity_review)
        actions.addWidget(self.save_button)
        actions.addWidget(self.promote_button)
        actions.addWidget(self.promote_all_button)
        actions.addWidget(self.retry_button)
        actions.addWidget(self.identity_review_button)
        actions.addStretch(1)
        note_layout.addLayout(actions)
        pin_actions = QHBoxLayout()
        pin_label = QLabel("当前章人工必选参考", note)
        pin_label.setObjectName("sectionEyebrow")
        pin_actions.addWidget(pin_label)
        pin_actions.addWidget(self.pin_button)
        pin_actions.addWidget(self.pin_summaries_button)
        pin_actions.addStretch(1)
        note_layout.addLayout(pin_actions)

        layout.addWidget(title)
        layout.addWidget(self.explanation_label)
        layout.addWidget(self.tabs, 1)
        self.reader_view_panel = self._reader_view_operation_panel(surface)
        layout.addWidget(self.reader_view_panel)
        self.view_assertion_review_panel = self._view_assertion_review_panel(surface)
        layout.addWidget(self.view_assertion_review_panel)
        layout.addWidget(note)
        self.setCentralWidget(surface)

    def bind(
        self,
        service: MemoryWorkspaceService,
        before_chapter_id: str,
        *,
        pin_service: ChapterContextPinService | None = None,
        target_chapter_id: str | None = None,
        guidance_service: ProjectGuidanceService | None = None,
        identity_service: CharacterIdentityService | None = None,
        reader_view_service: ReaderViewOperationService | None = None,
        reader_view_subjects: tuple[tuple[str, str], ...] = (),
        view_assertion_review_service: ViewAssertionReviewService | None = None,
    ) -> None:
        if (
            self._promotion_coordinator is not None
            and self._promotion_coordinator.is_running
        ):
            self.metadata_label.setText(
                self._tr("批量晋升仍在后台运行，请等待完成。")
            )
            return
        setting_draft = (
            self._setting_values()
            if hasattr(self, "setting_title_edit")
            else ("", "混合设定", "")
        )
        guidance_draft = self.guidance_editor.toPlainText()
        guidance_modified = self.guidance_editor.document().isModified()
        guidance_project_id = self._guidance_project_id
        guidance_revision = self._guidance_revision
        snapshot = service.load(before_chapter_id)
        grouped: dict[str, list[MemoryWorkspaceRecord]] = defaultdict(list)
        for record in snapshot.records:
            grouped[record.category].append(record)
        self._service = service
        self._pin_service = pin_service
        self._pin_chapter_id = target_chapter_id
        self._identity_service = identity_service
        self.identity_review_button.setEnabled(identity_service is not None)
        self._reader_view_service = reader_view_service
        self._view_assertion_review_service = view_assertion_review_service
        self._promotion_coordinator = MemoryPromotionCoordinator(service, self)
        self._promotion_coordinator.progress_changed.connect(
            self._bulk_promotion_progress
        )
        self._promotion_coordinator.completed.connect(self._bulk_promotion_completed)
        self._promotion_coordinator.failed.connect(self._bulk_promotion_failed)
        self._records = {record.id: record for record in snapshot.records}
        self.tabs.clear()
        self.selectors.clear()
        self.group_selectors.clear()
        self._category_records.clear()
        self.editors.clear()
        self.field_widgets.clear()
        self._add_guidance_tab()
        self._bind_guidance(
            guidance_service,
            preserved_draft=(
                guidance_draft
                if guidance_modified
                and guidance_service is not None
                and guidance_service.project_id == guidance_project_id
                else None
            ),
            preserved_revision=guidance_revision,
        )
        for category, records in grouped.items():
            self._add_record_tab(category, records)
        self._add_setting_tab()
        self.setting_title_edit.setText(setting_draft[0])
        self.setting_type_combo.setCurrentText(setting_draft[1])
        self.setting_editor.setPlainText(setting_draft[2])
        self._bind_reader_view_operation(reader_view_subjects)
        self._bind_view_assertion_review_operation(reader_view_subjects)
        if not grouped:
            self.metadata_label.setText("该章节边界之前没有可显示的记忆记录。")
            self.save_button.setEnabled(False)
            self.promote_button.setEnabled(False)
            self.promote_all_button.setEnabled(False)
            self.retry_button.setEnabled(False)
            self.pin_button.setEnabled(False)
            self.pin_summaries_button.setEnabled(False)
            return
        # Keep the first actual memory category selected so existing review actions
        # remain immediately usable; the project guidance tab stays available at index 0.
        self.tabs.setCurrentIndex(1)
        self._refresh_current_record()

    def _reader_view_operation_panel(self, parent: QWidget) -> QFrame:
        panel = QFrame(parent)
        panel.setObjectName("cardSurface")
        layout = QVBoxLayout(panel)
        title = QLabel("Reader View 接管", panel)
        title.setObjectName("sectionEyebrow")
        explanation = QLabel(
            "仅将一条已确认的旧读者知识接管为 Reader View；不会删除原记录，也不会批量处理。",
            panel,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("mutedLabel")
        self.reader_view_candidate_selector = QComboBox(panel)
        self.reader_view_candidate_selector.setAccessibleName("选择待接管的旧读者知识")
        self.reader_view_candidate_selector.currentIndexChanged.connect(
            self._render_reader_view_candidate
        )
        self.reader_view_source_label = QLabel(panel)
        self.reader_view_source_label.setWordWrap(True)
        self.reader_view_source_label.setObjectName("mutedLabel")
        self.reader_view_subject_selector = QComboBox(panel)
        self.reader_view_subject_selector.setAccessibleName("选择 Reader View 目标人物")
        self.reader_view_subject_selector.currentIndexChanged.connect(
            self._refresh_reader_view_button
        )
        self.reader_view_content_editor = QPlainTextEdit(panel)
        self.reader_view_content_editor.setAccessibleName("编辑 Reader View 内容")
        self.reader_view_content_editor.setMaximumHeight(90)
        self.reader_view_content_editor.textChanged.connect(
            self._refresh_reader_view_button
        )
        self.reader_view_convert_button = QPushButton("确认接管为 Reader View", panel)
        self.reader_view_convert_button.setAccessibleName("确认单条 Reader View 接管")
        self.reader_view_convert_button.clicked.connect(self._replace_reader_view_candidate)
        self.reader_view_status_label = QLabel("当前未绑定项目。", panel)
        self.reader_view_status_label.setWordWrap(True)
        self.reader_view_status_label.setObjectName("mutedLabel")
        form = QFormLayout()
        form.addRow("旧读者知识", self.reader_view_candidate_selector)
        form.addRow("来源", self.reader_view_source_label)
        form.addRow("目标人物", self.reader_view_subject_selector)
        form.addRow("Reader View 内容", self.reader_view_content_editor)
        layout.addWidget(title)
        layout.addWidget(explanation)
        layout.addLayout(form)
        layout.addWidget(self.reader_view_convert_button)
        layout.addWidget(self.reader_view_status_label)
        self._set_reader_view_operation_enabled(False)
        return panel

    def _bind_reader_view_operation(
        self, reader_view_subjects: tuple[tuple[str, str], ...]
    ) -> None:
        self.reader_view_subject_selector.blockSignals(True)
        self.reader_view_subject_selector.clear()
        for subject_id, subject_name in reader_view_subjects:
            self.reader_view_subject_selector.addItem(subject_name, subject_id)
        self.reader_view_subject_selector.blockSignals(False)
        service = self._reader_view_service
        if service is None:
            self._reader_view_candidates = {}
            self.reader_view_status_label.setText("当前未绑定项目，无法接管 Reader View。")
            self._set_reader_view_operation_enabled(False)
            return
        candidates = service.list_legacy_reader_view_candidates()
        self._reader_view_candidates = {candidate.event_id: candidate for candidate in candidates}
        self.reader_view_candidate_selector.blockSignals(True)
        self.reader_view_candidate_selector.clear()
        for candidate in candidates:
            self.reader_view_candidate_selector.addItem(
                f"{candidate.title} · {candidate.source_chapter_title}", candidate.event_id
            )
        self.reader_view_candidate_selector.blockSignals(False)
        if not candidates:
            self.reader_view_source_label.clear()
            self.reader_view_content_editor.clear()
            self.reader_view_status_label.setText("没有可接管的旧读者知识。")
            self._set_reader_view_operation_enabled(False)
            return
        if not reader_view_subjects:
            self.reader_view_source_label.clear()
            self.reader_view_content_editor.clear()
            self.reader_view_status_label.setText("没有可用的人物 Subject，无法创建 Reader View。")
            self._set_reader_view_operation_enabled(False)
            return
        self._set_reader_view_operation_enabled(True)
        self._render_reader_view_candidate()

    def _render_reader_view_candidate(self, _index: int = -1) -> None:
        candidate = self._current_reader_view_candidate()
        if candidate is None:
            return
        self.reader_view_source_label.setText(
            f"{candidate.source_chapter_title} · {candidate.source_chapter_id} · "
            f"{candidate.state.value}"
        )
        self.reader_view_content_editor.setPlainText(candidate.detail)
        self.reader_view_status_label.setText("请选择目标人物并确认单条接管。")
        self._refresh_reader_view_button()

    def _current_reader_view_candidate(self) -> LegacyReaderViewCandidate | None:
        event_id = str(self.reader_view_candidate_selector.currentData() or "")
        return self._reader_view_candidates.get(event_id)

    def _set_reader_view_operation_enabled(self, enabled: bool) -> None:
        self.reader_view_candidate_selector.setEnabled(enabled)
        self.reader_view_subject_selector.setEnabled(enabled)
        self.reader_view_content_editor.setReadOnly(not enabled)
        self.reader_view_convert_button.setEnabled(False)

    def _refresh_reader_view_button(self, _index: int = -1) -> None:
        ready = (
            self._reader_view_service is not None
            and self._current_reader_view_candidate() is not None
            and bool(self.reader_view_subject_selector.currentData())
            and bool(self.reader_view_content_editor.toPlainText().strip())
        )
        self.reader_view_convert_button.setEnabled(ready)

    def _replace_reader_view_candidate(self) -> None:
        service = self._reader_view_service
        candidate = self._current_reader_view_candidate()
        subject_id = str(self.reader_view_subject_selector.currentData() or "")
        content = self.reader_view_content_editor.toPlainText().strip()
        if service is None or candidate is None or not subject_id or not content:
            self.reader_view_status_label.setText("请选择候选、目标人物，并填写 Reader View 内容。")
            self._refresh_reader_view_button()
            return
        answer = QMessageBox.question(
            self,
            "确认 Reader View 接管",
            "这会仅接管当前一条旧读者知识为 Reader View，不会删除原记录。是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            service.replace_legacy_reader_event(
                legacy_event_id=candidate.event_id,
                subject_id=subject_id,
                content=content,
                confirmed_by_user=True,
            )
        except (PermissionError, ValueError) as error:
            self.reader_view_status_label.setText(f"Reader View 接管失败：{error}")
            return
        self._bind_reader_view_operation(
            tuple(
                (
                    str(self.reader_view_subject_selector.itemData(index)),
                    self.reader_view_subject_selector.itemText(index),
                )
                for index in range(self.reader_view_subject_selector.count())
            )
        )
        self.reader_view_status_label.setText("已接管当前旧读者知识为 Reader View。")
        self.reader_view_changed.emit()

    def _view_assertion_review_panel(self, parent: QWidget) -> QFrame:
        panel = QFrame(parent)
        panel.setObjectName("cardSurface")
        layout = QVBoxLayout(panel)
        title = QLabel("View Assertion 审查", panel)
        title.setObjectName("sectionEyebrow")
        explanation = QLabel(
            "仅审查一条模型候选。批准或拒绝都需要明确确认，候选内容不可在此编辑。",
            panel,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("mutedLabel")
        self.view_assertion_review_selector = QComboBox(panel)
        self.view_assertion_review_selector.setAccessibleName("选择待审查 View Assertion 候选")
        self.view_assertion_review_selector.currentIndexChanged.connect(
            self._render_view_assertion_review_candidate
        )
        self.view_assertion_review_details = QPlainTextEdit(panel)
        self.view_assertion_review_details.setAccessibleName("查看 View Assertion 候选详情")
        self.view_assertion_review_details.setReadOnly(True)
        self.view_assertion_review_details.setMaximumHeight(120)
        actions = QHBoxLayout()
        self.view_assertion_approve_button = QPushButton("批准候选", panel)
        self.view_assertion_approve_button.setAccessibleName("批准当前 View Assertion 候选")
        self.view_assertion_approve_button.clicked.connect(
            lambda: self._review_view_assertion_candidate(ReviewStatus.APPROVED)
        )
        self.view_assertion_reject_button = QPushButton("拒绝候选", panel)
        self.view_assertion_reject_button.setAccessibleName("拒绝当前 View Assertion 候选")
        self.view_assertion_reject_button.clicked.connect(
            lambda: self._review_view_assertion_candidate(ReviewStatus.REJECTED)
        )
        actions.addWidget(self.view_assertion_approve_button)
        actions.addWidget(self.view_assertion_reject_button)
        actions.addStretch(1)
        self.view_assertion_review_status_label = QLabel("当前未绑定项目。", panel)
        self.view_assertion_review_status_label.setWordWrap(True)
        self.view_assertion_review_status_label.setObjectName("mutedLabel")
        layout.addWidget(title)
        layout.addWidget(explanation)
        layout.addWidget(self.view_assertion_review_selector)
        layout.addWidget(self.view_assertion_review_details)
        layout.addLayout(actions)
        layout.addWidget(self.view_assertion_review_status_label)
        self._set_view_assertion_review_enabled(False)
        return panel

    def _bind_view_assertion_review_operation(
        self, reader_view_subjects: tuple[tuple[str, str], ...]
    ) -> None:
        self._view_assertion_subject_names = dict(reader_view_subjects)
        service = self._view_assertion_review_service
        if service is None:
            self._view_assertion_review_candidates = {}
            self.view_assertion_review_selector.clear()
            self.view_assertion_review_details.clear()
            self.view_assertion_review_status_label.setText(
                "当前未绑定项目，无法审查 View Assertion 候选。"
            )
            self._set_view_assertion_review_enabled(False)
            return
        candidates = service.list_review_candidates(limit=100)
        self._view_assertion_review_candidates = {
            candidate.id: candidate for candidate in candidates
        }
        self.view_assertion_review_selector.blockSignals(True)
        self.view_assertion_review_selector.clear()
        for candidate in candidates:
            subject_name = self._view_assertion_subject_name(candidate.subject_id)
            self.view_assertion_review_selector.addItem(
                f"{candidate.view_type.value} · {subject_name}",
                candidate.id,
            )
        self.view_assertion_review_selector.blockSignals(False)
        if not candidates:
            self.view_assertion_review_details.clear()
            self.view_assertion_review_status_label.setText("没有待审查的 View Assertion 候选。")
            self._set_view_assertion_review_enabled(False)
            return
        self._set_view_assertion_review_enabled(True)
        self._render_view_assertion_review_candidate()

    def _render_view_assertion_review_candidate(self, _index: int = -1) -> None:
        candidate = self._current_view_assertion_review_candidate()
        if candidate is None:
            return
        viewer = (
            self._view_assertion_subject_name(candidate.viewer_subject_id)
            if candidate.viewer_subject_id is not None
            else "—"
        )
        valid_from = candidate.valid_from_sequence
        valid_to = candidate.valid_to_sequence
        visible_from = candidate.narrative_visible_from_sequence
        visible_to = candidate.narrative_visible_to_sequence
        self.view_assertion_review_details.setPlainText(
            "\n".join(
                (
                    f"视图类型：{candidate.view_type.value}",
                    f"Subject：{self._view_assertion_subject_name(candidate.subject_id)}",
                    f"Viewer：{viewer}",
                    f"内容：{candidate.content}",
                    f"来源：{candidate.source_type.value} / {candidate.source_id} / "
                    f"修订 {candidate.source_revision}",
                    f"有效时间：{valid_from if valid_from is not None else '—'} 至 "
                    f"{valid_to if valid_to is not None else '—'}",
                    f"叙事可见：{visible_from if visible_from is not None else '—'} 至 "
                    f"{visible_to if visible_to is not None else '—'}",
                )
            )
        )
        self.view_assertion_review_status_label.setText("请选择批准或拒绝；候选内容保持只读。")

    def _current_view_assertion_review_candidate(self) -> ViewAssertion | None:
        assertion_id = str(self.view_assertion_review_selector.currentData() or "")
        return self._view_assertion_review_candidates.get(assertion_id)

    def _view_assertion_subject_name(self, subject_id: str | None) -> str:
        if subject_id is None:
            return "—"
        return self._view_assertion_subject_names.get(subject_id, subject_id)

    def _set_view_assertion_review_enabled(self, enabled: bool) -> None:
        self.view_assertion_review_selector.setEnabled(enabled)
        self.view_assertion_approve_button.setEnabled(enabled)
        self.view_assertion_reject_button.setEnabled(enabled)

    def _review_view_assertion_candidate(self, decision: ReviewStatus) -> None:
        service = self._view_assertion_review_service
        candidate = self._current_view_assertion_review_candidate()
        if service is None or candidate is None:
            self.view_assertion_review_status_label.setText("没有可审查的 View Assertion 候选。")
            self._set_view_assertion_review_enabled(False)
            return
        action = "批准" if decision == ReviewStatus.APPROVED else "拒绝"
        answer = QMessageBox.question(
            self,
            f"确认{action} View Assertion",
            f"将{action}当前模型候选“{candidate.view_type.value}”。是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if decision == ReviewStatus.APPROVED:
                service.approve_candidate(candidate.id, confirmed_by_user=True)
            else:
                service.reject_candidate(candidate.id, confirmed_by_user=True)
        except (PermissionError, ValueError, ViewAssertionReviewError) as error:
            self.view_assertion_review_status_label.setText(
                f"View Assertion {action}失败：{error}"
            )
            return
        self._bind_view_assertion_review_operation(
            tuple(self._view_assertion_subject_names.items())
        )
        self.view_assertion_review_status_label.setText(f"已{action}当前 View Assertion 候选。")
        self.view_assertion_review_changed.emit()

    def open_identity_review(self) -> None:
        if self._identity_service is None:
            return
        if self.identity_dialog is not None and self.identity_dialog.isVisible():
            self.identity_dialog.raise_()
            self.identity_dialog.activateWindow()
            return
        self.identity_dialog = CharacterIdentityConflictDialog(self._identity_service, self)
        self.identity_dialog.changed.connect(self.identity_changed.emit)
        self.identity_dialog.show()

    def _add_setting_tab(self) -> None:
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 10, 8, 8)
        explanation = QLabel(
            "用于粘贴世界观、人物小传、剧情计划或文风资料。原文会完整保存；"
            "AI 整理结果只会进入待审查候选，不会直接覆盖正式记忆。",
            page,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("mutedLabel")
        form = QFormLayout()
        self.setting_title_edit = QLineEdit(page)
        self.setting_title_edit.setPlaceholderText("例如：世界观与主要人物设定")
        self.setting_type_combo = QComboBox(page)
        self.setting_type_combo.addItems(("混合设定", "世界观", "人物设定", "剧情大纲", "文风资料"))
        form.addRow("资料标题", self.setting_title_edit)
        form.addRow("资料类型", self.setting_type_combo)
        self.setting_editor = QPlainTextEdit(page)
        self.setting_editor.setPlaceholderText("在此粘贴设定文档。建议一次处理一份主题明确的短文档。")
        buttons = QHBoxLayout()
        self.setting_save_button = QPushButton("保存原始资料", page)
        self.setting_analyze_button = QPushButton("AI 整理为待审查候选", page)
        self.setting_status_label = QLabel("尚未保存", page)
        self.setting_status_label.setObjectName("mutedLabel")
        self.setting_save_button.clicked.connect(self._request_setting_save)
        self.setting_analyze_button.clicked.connect(self._request_setting_analyze)
        buttons.addWidget(self.setting_save_button)
        buttons.addWidget(self.setting_analyze_button)
        buttons.addWidget(self.setting_status_label, 1)
        layout.addWidget(explanation)
        layout.addLayout(form)
        layout.addWidget(self.setting_editor, 1)
        layout.addLayout(buttons)
        self.tabs.addTab(page, "设定资料整理")

    def _add_guidance_tab(self) -> None:
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 10, 8, 8)
        explanation = QLabel(
            "这里保存整部小说不可被模型自动覆盖的最高创作指令，例如基本目的、主题、"
            "写作视角和不可违背的总原则。它只能由用户人工编辑；本页不会调用 AI。",
            page,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("mutedLabel")
        self.guidance_editor = QPlainTextEdit(page)
        self.guidance_editor.setAccessibleName("编辑小说最高系统提示")
        self.guidance_editor.setReadOnly(True)
        self.guidance_editor.setPlaceholderText(
            "例如：本书讲述人在失去中学习承担；使用第三人称限知视角……"
        )
        actions = QHBoxLayout()
        self.guidance_save_button = QPushButton("保存最高提示", page)
        self.guidance_save_button.setAccessibleName("人工保存小说最高系统提示")
        self.guidance_save_button.setEnabled(False)
        self.guidance_status_label = QLabel("当前未绑定项目", page)
        self.guidance_status_label.setObjectName("mutedLabel")
        self.guidance_save_button.clicked.connect(self._save_guidance)
        self.guidance_editor.textChanged.connect(self._guidance_text_changed)
        actions.addWidget(self.guidance_save_button)
        actions.addWidget(self.guidance_status_label, 1)
        layout.addWidget(explanation)
        layout.addWidget(self.guidance_editor, 1)
        layout.addLayout(actions)
        self.tabs.addTab(page, "小说最高提示")

    def _bind_guidance(
        self,
        service: ProjectGuidanceService | None,
        *,
        preserved_draft: str | None,
        preserved_revision: int,
    ) -> None:
        self._guidance_service = service
        if service is None:
            self._guidance_project_id = None
            self._guidance_revision = 0
            self.guidance_editor.clear()
            self.guidance_editor.setReadOnly(True)
            self.guidance_editor.document().setModified(False)
            self.guidance_save_button.setEnabled(False)
            self.guidance_status_label.setText("当前未绑定项目")
            return
        self._guidance_project_id = service.project_id
        self.guidance_editor.setReadOnly(False)
        if preserved_draft is not None:
            self._guidance_revision = preserved_revision
            self.guidance_editor.setPlainText(preserved_draft)
            self.guidance_editor.document().setModified(True)
            self.guidance_save_button.setEnabled(True)
            self.guidance_status_label.setText("保留了尚未保存的人工修改")
            return
        guidance = service.load()
        self._guidance_revision = guidance.revision
        self.guidance_editor.setPlainText(guidance.highest_system_prompt)
        self.guidance_editor.document().setModified(False)
        self.guidance_save_button.setEnabled(False)
        self.guidance_status_label.setText(
            f"已加载人工修订 {guidance.revision}"
            if guidance.highest_system_prompt
            else "尚未填写；仅在人工保存后生效"
        )

    def _guidance_text_changed(self) -> None:
        if self._guidance_service is None:
            self.guidance_save_button.setEnabled(False)
            return
        modified = self.guidance_editor.document().isModified()
        self.guidance_save_button.setEnabled(modified)
        if modified:
            self.guidance_status_label.setText("有尚未保存的人工修改")

    def _save_guidance(self) -> None:
        service = self._guidance_service
        if service is None:
            return
        try:
            saved = service.save_manual(
                self.guidance_editor.toPlainText(),
                expected_revision=self._guidance_revision,
            )
        except (RuntimeError, ValueError) as error:
            self.guidance_status_label.setText(f"保存失败：{error}")
            return
        self._guidance_revision = saved.revision
        self.guidance_editor.setPlainText(saved.highest_system_prompt)
        self.guidance_editor.document().setModified(False)
        self.guidance_save_button.setEnabled(False)
        self.guidance_status_label.setText(f"已人工保存 · 修订 {saved.revision}")

    def _setting_values(self) -> tuple[str, str, str]:
        return (
            self.setting_title_edit.text().strip(),
            self.setting_type_combo.currentText(),
            self.setting_editor.toPlainText().strip(),
        )

    def _request_setting_save(self) -> None:
        title, document_type, text = self._setting_values()
        self.setting_save_requested.emit(title, document_type, text, self.setting_source_id)

    def _request_setting_analyze(self) -> None:
        title, document_type, text = self._setting_values()
        self.setting_analyze_requested.emit(title, document_type, text, self.setting_source_id)

    def set_setting_busy(self, busy: bool, message: str) -> None:
        self.setting_save_button.setEnabled(not busy)
        self.setting_analyze_button.setEnabled(not busy)
        self.setting_status_label.setText(message)

    def setting_saved(self, source_id: str, message: str) -> None:
        self.setting_source_id = source_id
        self.set_setting_busy(False, message)

    def _add_demo_tab(self, tab_name: str, text: str) -> None:
        editor = QPlainTextEdit(self.tabs)
        editor.setPlainText(text)
        editor.setAccessibleName(f"编辑{tab_name}")
        self.editors[tab_name] = editor
        self.tabs.addTab(editor, tab_name)

    def _add_record_tab(self, category: str, records: list[MemoryWorkspaceRecord]) -> None:
        page = QWidget(self.tabs)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 8, 0, 0)
        selector = QComboBox(page)
        selector.setAccessibleName(f"选择{category}记录")
        editor = QPlainTextEdit(page)
        editor.setAccessibleName(f"编辑{category}")
        field_widgets: dict[str, QWidget] = {}
        fields = records[0].fields
        self._category_records[category] = records
        if category == "正典事实" and any(record.group_key for record in records):
            group_selector = QComboBox(page)
            group_selector.setAccessibleName("选择正典卡片")
            for group_key, group_title in CANON_GROUPS:
                group_selector.addItem(group_title, group_key)
            available_groups = {record.group_key for record in records}
            first_available = next(
                (
                    index
                    for index in range(group_selector.count())
                    if group_selector.itemData(index) in available_groups
                ),
                0,
            )
            group_selector.setCurrentIndex(first_available)
            selector.setAccessibleName("选择正典卡片内事实")
            selectors_form = QFormLayout()
            selectors_form.addRow("正典卡片", group_selector)
            selectors_form.addRow("卡内事实", selector)
            page_layout.addLayout(selectors_form)
            self.group_selectors[category] = group_selector
        else:
            for record in records:
                selector.addItem(record.title, record.id)
            page_layout.addWidget(selector)
        if fields:
            form = QFormLayout()
            for field in fields:
                widget: QWidget
                if field.choices:
                    widget = QComboBox(page)
                    widget.addItems(field.choices)
                elif field.multiline:
                    widget = QPlainTextEdit(page)
                    widget.setMaximumHeight(90)
                else:
                    widget = QLineEdit(page)
                widget.setAccessibleName(f"{category}：{field.label}")
                field_widgets[field.key] = widget
                form.addRow(field.label, widget)
            page_layout.addLayout(form)
            editor.hide()
        page_layout.addWidget(editor, 1)
        self.selectors[category] = selector
        self.editors[category] = editor
        self.field_widgets[category] = field_widgets
        selector.currentIndexChanged.connect(self._refresh_current_record)
        bound_group_selector = self.group_selectors.get(category)
        if bound_group_selector is not None:
            bound_group_selector.currentIndexChanged.connect(
                lambda _index, selected_category=category: self._filter_group_records(
                    selected_category
                )
            )
            self._filter_group_records(category)
        self.tabs.addTab(page, category)

    def _filter_group_records(self, category: str) -> None:
        group_selector = self.group_selectors.get(category)
        selector = self.selectors.get(category)
        if group_selector is None or selector is None:
            return
        selected_group = str(group_selector.currentData() or "")
        selector.blockSignals(True)
        selector.clear()
        for record in self._category_records.get(category, []):
            if record.group_key == selected_group:
                selector.addItem(record.title, record.id)
        selector.blockSignals(False)
        self._refresh_current_record()

    def _current_record(self) -> MemoryWorkspaceRecord | None:
        category = self.tabs.tabText(self.tabs.currentIndex())
        selector = self.selectors.get(category)
        if selector is None:
            return None
        record_id = selector.currentData()
        return self._records.get(str(record_id))

    def _refresh_current_record(self, _index: int = -1) -> None:
        record = self._current_record()
        if record is None:
            category = self.tabs.tabText(self.tabs.currentIndex())
            selector = self.selectors.get(category)
            if selector is not None and selector.count() == 0:
                editor = self.editors.get(category)
                if editor is not None:
                    editor.clear()
                    editor.setReadOnly(True)
                for widget in self.field_widgets.get(category, {}).values():
                    if isinstance(widget, QComboBox):
                        widget.setCurrentIndex(-1)
                        widget.setEnabled(False)
                    elif isinstance(widget, QPlainTextEdit):
                        widget.clear()
                        widget.setReadOnly(True)
                    elif isinstance(widget, QLineEdit):
                        widget.clear()
                        widget.setReadOnly(True)
                self.metadata_label.setText("当前正典卡片暂无事实记录。")
            if self._service is not None:
                self.save_button.setEnabled(False)
                self.promote_button.setEnabled(False)
                self._refresh_bulk_promotion_button()
                self._refresh_pin_buttons()
            return
        category = self.tabs.tabText(self.tabs.currentIndex())
        editor = self.editors[category]
        editor.setPlainText(record.content)
        locked = record.review_status == ReviewStatus.LOCKED
        editor.setReadOnly(locked or not record.editable)
        widgets = self.field_widgets.get(category, {})
        for field in record.fields:
            field_widget = widgets.get(field.key)
            if isinstance(field_widget, QComboBox):
                field_widget.setCurrentText(field.value)
                field_widget.setEnabled(not locked and field.editable)
            elif isinstance(field_widget, QPlainTextEdit):
                field_widget.setPlainText(field.value)
                field_widget.setReadOnly(locked or not field.editable)
            elif isinstance(field_widget, QLineEdit):
                field_widget.setText(field.value)
                field_widget.setReadOnly(locked or not field.editable)
        source = record.source_chapter_id or "无章节来源"
        source_revision = (
            str(record.source_revision) if record.source_revision is not None else "未知"
        )
        self.metadata_label.setText(
            f"来源：{record.source_type} / {source} / 修订 {source_revision}　"
            f"权限：{record.authority.value}　审查：{record.review_status.value}　"
            f"状态：{record.status.value}"
        )
        if record.source_type == "SUMMARY_FALLBACK":
            self.metadata_label.setText(
                "⚠ 当前内容只是模型提取失败后的原文定位预览，并非有效压缩摘要。"
                "请返回主界面点击“整理记忆”重试。\n" + self.metadata_label.text()
            )
        busy = self._bulk_promotion_running()
        self.save_button.setEnabled(record.editable and not locked and not busy)
        self.promote_button.setEnabled(record.promotable and not locked and not busy)
        self.retry_button.setEnabled(
            record.source_type == "SUMMARY"
            and record.authority == Authority.MODEL_EXTRACTED
            and record.review_status == ReviewStatus.APPROVED
            and record.source_chapter_id is not None
            and not busy
        )
        if record.source_type == "SUMMARY_FALLBACK":
            self.retry_button.setText("本章已等待重新整理")
        else:
            self.retry_button.setText("撤销晋升并重整本章")
        self._refresh_bulk_promotion_button()
        self._refresh_pin_buttons()

    def _refresh_pin_buttons(self) -> None:
        record = self._current_record()
        service = self._pin_service
        chapter_id = self._pin_chapter_id
        if record is None or service is None or not chapter_id:
            self.pin_button.setEnabled(False)
            self.pin_summaries_button.setEnabled(False)
            return
        pinned = service.is_pinned(chapter_id, record)
        self.pin_button.setText(
            "✓ 已强制加入（点击移除）" if pinned else "＋ 强制加入当前章"
        )
        self.pin_button.setToolTip(
            "强制参考不会被 Token 预算静默省略；若总量超出模型输入能力，生成会明确失败。"
        )
        eligible = (
            record.review_status in {ReviewStatus.APPROVED, ReviewStatus.LOCKED}
            and record.status == MemoryStatus.CURRENT
        )
        self.pin_button.setEnabled(pinned or eligible)
        summaries = tuple(
            item
            for item in self._records.values()
            if item.source_type == "SUMMARY"
            and item.review_status in {ReviewStatus.APPROVED, ReviewStatus.LOCKED}
            and item.status == MemoryStatus.CURRENT
        )
        self.pin_summaries_button.setEnabled(bool(summaries))
        self.pin_summaries_button.setToolTip(
            f"当前有 {len(summaries)} 条已审查压缩前文可加入"
        )

    def _toggle_current_pin(self) -> None:
        record = self._current_record()
        service = self._pin_service
        chapter_id = self._pin_chapter_id
        if record is None or service is None or not chapter_id:
            return
        try:
            if service.is_pinned(chapter_id, record):
                service.unpin(chapter_id, record)
                self.metadata_label.setText(f"已从当前章 AI 参考移除：{record.title}")
            else:
                service.pin(chapter_id, record)
                self.metadata_label.setText(f"已加入当前章 AI 参考：{record.title}")
        except (KeyError, PermissionError, RuntimeError, ValueError) as error:
            self.metadata_label.setText(f"加入当前章失败：{error}")
        self._refresh_pin_buttons()

    def _pin_compressed_history(self) -> None:
        service = self._pin_service
        chapter_id = self._pin_chapter_id
        if service is None or not chapter_id:
            return
        pinned = service.pin_compressed_history(
            chapter_id,
            tuple(self._records.values()),
        )
        self.metadata_label.setText(
            f"已将 {len(pinned)} 条可用压缩前文强制加入当前章 AI 参考。"
            "这些内容不会被静默省略；若超过模型输入能力，生成会明确报错。"
        )
        self._refresh_pin_buttons()

    def _save_current(self) -> None:
        record = self._current_record()
        service = self._service
        if record is None or service is None:
            return
        category = self.tabs.tabText(self.tabs.currentIndex())
        try:
            if record.fields:
                values: dict[str, str] = {}
                for field in record.fields:
                    widget = self.field_widgets[category][field.key]
                    if isinstance(widget, QComboBox):
                        values[field.key] = widget.currentText()
                    elif isinstance(widget, QPlainTextEdit):
                        values[field.key] = widget.toPlainText()
                    elif isinstance(widget, QLineEdit):
                        values[field.key] = widget.text()
                updated = service.edit_fields(record.id, values, expected_revision=record.revision)
            else:
                updated = service.edit(
                    record.id,
                    self.editors[category].toPlainText(),
                    expected_revision=record.revision,
                )
        except (KeyError, PermissionError, RuntimeError, ValueError) as error:
            self.metadata_label.setText(f"保存失败：{error}")
            return
        self._records[updated.id] = updated
        category_records = self._category_records.get(category)
        if category_records is not None:
            self._category_records[category] = [
                updated if item.id == updated.id else item for item in category_records
            ]
        group_selector = self.group_selectors.get(category)
        if group_selector is not None and updated.group_key:
            group_index = group_selector.findData(updated.group_key)
            if group_index >= 0 and group_index != group_selector.currentIndex():
                group_selector.setCurrentIndex(group_index)
            else:
                self._filter_group_records(category)
            selector = self.selectors[category]
            record_index = selector.findData(updated.id)
            if record_index >= 0:
                selector.setCurrentIndex(record_index)
        else:
            self._refresh_current_record()

    def _promote_current(self) -> None:
        record = self._current_record()
        service = self._service
        if record is None or service is None:
            return
        try:
            promoted = service.promote(record.id, expected_revision=record.revision)
        except (KeyError, PermissionError, RuntimeError, ValueError) as error:
            self.metadata_label.setText(f"晋升失败：{error}")
            return
        self._records[promoted.id] = promoted
        self._refresh_current_record()

    def _request_model_retry(self) -> None:
        record = self._current_record()
        service = self._service
        if record is None or service is None:
            return
        answer = QMessageBox.question(
            self,
            "确认撤销晋升",
            "这会把当前模型章节摘要退回待审查，并标记为下次“整理记忆”时重新提取。\n"
            "旧摘要及该章已经晋升的其他记忆不会删除；重新提取的结果会作为待审查候选。\n"
            "人工确认或锁定摘要不会受影响。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            retried = service.request_model_retry(
                record.id, expected_revision=record.revision
            )
        except (KeyError, PermissionError, RuntimeError, ValueError) as error:
            self.metadata_label.setText(f"撤销晋升失败：{error}")
            return
        self._records[retried.id] = retried
        self._refresh_current_record()
        self.metadata_label.setText(
            "已撤销晋升并标记本章重整。请关闭记忆库后点击左侧“整理记忆”；"
            "正常章节不会重新调用模型。"
        )

    def _refresh_bulk_promotion_button(self) -> None:
        count = (
            self._service.pending_promotion_count()
            if self._service is not None
            else 0
        )
        self.promote_all_button.setEnabled(count > 0 and not self._bulk_promotion_running())
        self.promote_all_button.setToolTip(
            self._tr("当前共有 {count} 条可晋升候选").format(count=count)
        )

    def _promote_all(self) -> None:
        service = self._service
        if service is None:
            return
        count = service.pending_promotion_count()
        if count <= 0:
            self.metadata_label.setText(self._tr("当前没有可晋升的待审查候选。"))
            self._refresh_bulk_promotion_button()
            return
        answer = QMessageBox.question(
            self,
            self._tr("确认批量晋升"),
            self._tr(
                "将把当前项目中的 {count} 条待审查候选晋升为已审查记忆。\n"
                "编辑框中尚未保存的修改不会自动保存。是否继续？"
            ).format(count=count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        coordinator = self._promotion_coordinator
        if coordinator is None:
            self.metadata_label.setText(self._tr("批量晋升服务尚未连接。"))
            return
        self._set_bulk_promotion_busy(True)
        self.metadata_label.setText(
            self._tr("正在后台晋升 0 / {count} 条候选……").format(count=count)
        )
        try:
            coordinator.start()
        except RuntimeError as error:
            self._set_bulk_promotion_busy(False)
            self.metadata_label.setText(
                self._tr("批量晋升失败：{message}").format(message=error)
            )

    def _bulk_promotion_progress(self, current: int, total: int, title: str) -> None:
        self.metadata_label.setText(
            self._tr("正在后台晋升 {current} / {total} 条候选……当前：{title}").format(
                current=current,
                total=total,
                title=title,
            )
        )

    def _bulk_promotion_completed(self, value: object) -> None:
        if not isinstance(value, MemoryBulkPromotionResult):
            self._bulk_promotion_failed(self._tr("批量晋升返回了无效结果"))
            return
        result = value
        for promoted in result.promoted:
            self._records[promoted.id] = promoted
        self._set_bulk_promotion_busy(False)
        self._refresh_current_record()
        if result.failures:
            self.metadata_label.setText(
                self._tr(
                    "批量晋升完成：成功 {promoted} 条，失败 {failed} 条。"
                    "失败记录仍保留为待审查候选，可逐条处理。"
                ).format(
                    promoted=len(result.promoted), failed=len(result.failures)
                )
            )
        else:
            self.metadata_label.setText(
                self._tr("批量晋升完成：已成功晋升 {count} 条候选。").format(
                    count=len(result.promoted)
                )
            )
        self._refresh_bulk_promotion_button()

    def _bulk_promotion_failed(self, message: str) -> None:
        self._set_bulk_promotion_busy(False)
        self.metadata_label.setText(
            self._tr("批量晋升失败：{message}").format(message=message)
        )
        self._refresh_bulk_promotion_button()

    def _set_bulk_promotion_busy(self, busy: bool) -> None:
        self.tabs.setEnabled(not busy)
        if busy:
            self.save_button.setEnabled(False)
            self.promote_button.setEnabled(False)
            self.promote_all_button.setEnabled(False)
            self.retry_button.setEnabled(False)

    def _bulk_promotion_running(self) -> bool:
        return bool(
            self._promotion_coordinator is not None
            and self._promotion_coordinator.is_running
        )

    @staticmethod
    def _tr(text: str) -> str:
        return language_manager().translate(text)
