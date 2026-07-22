from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.domain.generation import AuditPolicy, CreationMode, GenerationStatus
from ai_novel_studio.ui.demo_data import WorkspaceDemoData


class ManuscriptPanel(QFrame):
    brief_requested = Signal()
    audit_requested = Signal()
    references_requested = Signal()
    generation_requested = Signal(object, object, int, int)
    generation_cancel_requested = Signal()
    draft_accept_requested = Signal()
    draft_discard_requested = Signal()
    recovery_requested = Signal()
    save_requested = Signal()

    def __init__(self, data: WorkspaceDemoData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("manuscriptPanel")
        self.setMinimumWidth(430)
        self._requirement_locked = False
        self._phase5_generation_enabled = False
        self._frozen_brief_available = False
        self._draft_preview_active = False
        self._formal_text_before_draft = ""
        self.current_chapter_revision = 0
        self.current_requirement_revision = 0

        self.chapter_title = QLineEdit("", self)
        self.chapter_title.setPlaceholderText("打开或导入项目后显示当前章节")
        self.chapter_title.setAccessibleName("当前章节标题")

        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("快速", CreationMode.BASIC.value)
        self.mode_combo.addItem("普通", CreationMode.STANDARD.value)
        self.mode_combo.setCurrentIndex(1)
        self.mode_combo.setAccessibleName("创作档位")
        self.pre_accept_audit = QCheckBox("深度审校（采用前）", self)
        self.pre_accept_audit.setAccessibleName("普通模式深度审校（采用前）")
        self.pre_accept_audit.setToolTip(
            "开启后，草稿必须通过确定性检查和模型语义审校才能采用。"
        )

        self.target_words = self._spin_box(500, 50000, 3500, "目标字数")
        self.output_token_limit = self._spin_box(256, 200000, 8000, "输出 Token 上限")
        self.font_size = self._spin_box(12, 32, 17, "正文字体大小")
        self.font_size.setSuffix(" pt")

        title_row = QHBoxLayout()
        title_row.addWidget(self.chapter_title, 1)
        title_row.addWidget(QLabel("档位", self))
        title_row.addWidget(self.mode_combo)
        title_row.addWidget(self.pre_accept_audit)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("目标字数", self))
        settings_row.addWidget(self.target_words)
        settings_row.addWidget(QLabel("输出上限", self))
        settings_row.addWidget(self.output_token_limit)
        settings_row.addStretch(1)
        settings_row.addWidget(QLabel("字号", self))
        settings_row.addWidget(self.font_size)

        self.brief_button = QPushButton("情节点 / Brief", self)
        self.brief_button.setAccessibleName("打开章节 Brief")
        self.brief_button.clicked.connect(self.brief_requested)
        self.save_button = QPushButton("保存章节", self)
        self.save_button.setAccessibleName("保存当前章节")
        self.save_button.clicked.connect(self.save_requested)
        references_button = QPushButton("AI 参考内容", self)
        references_button.setAccessibleName("查看本次 AI 参考内容")
        references_button.clicked.connect(self.references_requested)
        audit_button = QPushButton("审校", self)
        audit_button.setAccessibleName("打开章节审校")
        audit_button.clicked.connect(self.audit_requested)
        self.recover_button = QPushButton("恢复草稿", self)
        self.recover_button.setAccessibleName("扫描并恢复未处理的生成草稿")
        self.recover_button.setEnabled(False)
        self.recover_button.clicked.connect(self.recovery_requested)
        self.cancel_generation_button = QPushButton("取消", self)
        self.cancel_generation_button.setAccessibleName("取消当前正文生成")
        self.cancel_generation_button.setEnabled(False)
        self.cancel_generation_button.clicked.connect(self.generation_cancel_requested)
        self.generate_button = QPushButton("生成正文", self)
        self.generate_button.setAccessibleName("使用当前 Brief 生成正文")
        self.generate_button.setProperty("buttonRole", "primary")
        self.generate_button.setEnabled(False)
        self.generate_button.clicked.connect(self._emit_generation_request)

        action_row = QHBoxLayout()
        action_row.addWidget(self.brief_button)
        action_row.addWidget(self.save_button)
        action_row.addWidget(references_button)
        action_row.addWidget(audit_button)
        action_row.addStretch(1)
        action_row.addWidget(self.recover_button)
        action_row.addWidget(self.cancel_generation_button)
        action_row.addWidget(self.generate_button)

        requirement_header = QHBoxLayout()
        requirement_title = QLabel("当前章要求", self)
        requirement_title.setObjectName("sectionEyebrow")
        self.requirement_status = QLabel("已折叠 · 可展开编辑", self)
        self.requirement_status.setObjectName("mutedLabel")
        self.requirement_fold_button = QPushButton("展开要求", self)
        self.requirement_fold_button.setAccessibleName("展开或折叠当前章要求")
        self.requirement_fold_button.clicked.connect(self.toggle_requirement_visibility)
        self.requirement_lock_button = QPushButton("锁定要求", self)
        self.requirement_lock_button.setAccessibleName("锁定当前章要求")
        self.requirement_lock_button.clicked.connect(self.toggle_requirement_lock)
        requirement_header.addWidget(requirement_title)
        requirement_header.addWidget(self.requirement_status)
        requirement_header.addStretch(1)
        requirement_header.addWidget(self.requirement_fold_button)
        requirement_header.addWidget(self.requirement_lock_button)

        self.chapter_requirement = QPlainTextEdit(self)
        self.chapter_requirement.setObjectName("chapterRequirement")
        self.chapter_requirement.setAccessibleName("当前章要求")
        self.chapter_requirement.setPlainText(data.chapter_requirement)
        self.chapter_requirement.setMinimumHeight(82)
        self.chapter_requirement.setMaximumHeight(120)
        self.chapter_requirement.setVisible(False)

        self.editor = QPlainTextEdit(self)
        self.editor.setObjectName("manuscriptEditor")
        self.editor.setAccessibleName("章节正文编辑器")
        self.editor.setPlainText(data.chapter_text)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setTabChangesFocus(False)
        self._set_editor_font_size(self.font_size.value())
        self._pending_draft_chunks: list[str] = []
        self._draft_flush_timer = QTimer(self)
        self._draft_flush_timer.setSingleShot(True)
        self._draft_flush_timer.setInterval(40)
        self._draft_flush_timer.timeout.connect(self._flush_draft_chunks)

        draft_header = QHBoxLayout()
        draft_title = QLabel("AI 草稿预览", self)
        draft_title.setObjectName("sectionEyebrow")
        self.draft_status_label = QLabel("生成后将在正文框内预览", self)
        self.draft_status_label.setObjectName("mutedLabel")
        self.discard_draft_button = QPushButton("放弃草稿", self)
        self.discard_draft_button.setAccessibleName("放弃当前 AI 生成草稿")
        self.discard_draft_button.setEnabled(False)
        self.discard_draft_button.clicked.connect(self.draft_discard_requested)
        self.adopt_draft_button = QPushButton("采用草稿", self)
        self.adopt_draft_button.setAccessibleName("采用当前 AI 生成草稿为正式正文")
        self.adopt_draft_button.setEnabled(False)
        self.adopt_draft_button.clicked.connect(self.draft_accept_requested)
        draft_header.addWidget(draft_title)
        draft_header.addWidget(self.draft_status_label)
        draft_header.addStretch(1)
        draft_header.addWidget(self.discard_draft_button)
        draft_header.addWidget(self.adopt_draft_button)

        self.word_count_label = QLabel(self)
        self.word_count_label.setObjectName("mutedLabel")
        self.save_status_label = QLabel("未打开章节", self)
        self.save_status_label.setObjectName("mutedLabel")
        self.pipeline_status_label = QLabel("", self)
        self.pipeline_status_label.setObjectName("mutedLabel")
        footer = QHBoxLayout()
        footer.addWidget(self.word_count_label)
        footer.addWidget(self.save_status_label)
        footer.addStretch(1)
        footer.addWidget(self.pipeline_status_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 10)
        layout.setSpacing(9)
        layout.addLayout(title_row)
        layout.addLayout(settings_row)
        layout.addLayout(action_row)
        layout.addLayout(requirement_header)
        layout.addWidget(self.chapter_requirement)
        layout.addWidget(self.editor, 1)
        layout.addLayout(draft_header)
        layout.addLayout(footer)

        self.font_size.valueChanged.connect(self._set_editor_font_size)
        self.mode_combo.currentIndexChanged.connect(self._refresh_generation_controls)
        self.pre_accept_audit.toggled.connect(self._refresh_generation_controls)
        self._word_count_timer = QTimer(self)
        self._word_count_timer.setSingleShot(True)
        self._word_count_timer.setInterval(250)
        self._word_count_timer.timeout.connect(self._update_word_count)
        self.editor.textChanged.connect(self._word_count_timer.start)
        self._update_word_count()
        self._refresh_generation_controls()

    def _spin_box(self, minimum: int, maximum: int, value: int, name: str) -> QSpinBox:
        widget = QSpinBox(self)
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        widget.setAccessibleName(name)
        return widget

    def _set_editor_font_size(self, size: int) -> None:
        font = self.editor.font()
        font.setPointSize(size)
        self.editor.setFont(font)

    def _update_word_count(self) -> None:
        count = sum(1 for character in self.editor.toPlainText() if not character.isspace())
        self.word_count_label.setText(f"{count:,} 字")

    def toggle_requirement_visibility(self) -> None:
        visible = not self.chapter_requirement.isVisible()
        self.chapter_requirement.setVisible(visible)
        self.requirement_fold_button.setText("折叠要求" if visible else "展开要求")
        self.requirement_status.setText(
            ("可编辑" if not self._requirement_locked else "已锁定")
            if visible
            else "已折叠 · 可展开编辑"
        )

    def apply_chapter_workspace(self, workspace: object) -> None:
        self._draft_preview_active = False
        self._discard_pending_draft_chunks()
        self.editor.setReadOnly(False)
        declared_number = str(getattr(workspace, "declared_number", ""))
        title = str(getattr(workspace, "title", ""))
        self.chapter_title.setText(f"{declared_number} {title}".strip())
        self.editor.setPlainText(str(getattr(workspace, "content", "")))
        self.chapter_requirement.setPlainText(str(getattr(workspace, "requirement_content", "")))
        self.current_chapter_revision = int(getattr(workspace, "revision", 0))
        self.current_requirement_revision = int(getattr(workspace, "requirement_revision", 0))
        self._set_requirement_locked(bool(getattr(workspace, "requirement_locked", False)))
        self.mark_saved(self.current_chapter_revision, self.current_requirement_revision)

    def mark_saved(self, revision: int, requirement_revision: int) -> None:
        self.current_chapter_revision = revision
        self.current_requirement_revision = requirement_revision
        self.save_status_label.setText(
            f"已保存 · 正文修订 {revision} · 要求修订 {requirement_revision}"
        )

    def mark_requirement_saved(self, requirement_revision: int) -> None:
        self.current_requirement_revision = requirement_revision
        self.save_status_label.setText(
            f"当前章要求已同步 · 要求修订 {requirement_revision}"
        )

    def _set_requirement_locked(self, locked: bool) -> None:
        self._requirement_locked = locked
        self.chapter_requirement.setReadOnly(locked)
        if locked:
            self.requirement_status.setText(
                "已锁定" if self.chapter_requirement.isVisible() else "已折叠 · 已锁定"
            )
            self.requirement_lock_button.setText("解除锁定")
            self.requirement_lock_button.setAccessibleName("解除当前章要求锁定")
        else:
            self.requirement_status.setText(
                "可编辑" if self.chapter_requirement.isVisible() else "已折叠 · 可展开编辑"
            )
            self.requirement_lock_button.setText("锁定要求")
            self.requirement_lock_button.setAccessibleName("锁定当前章要求")

    def toggle_requirement_lock(self) -> None:
        self._set_requirement_locked(not self._requirement_locked)

    def apply_requirement_draft(self, text: str) -> bool:
        if self._requirement_locked:
            return False
        self.chapter_requirement.setPlainText(text)
        if not self.chapter_requirement.isVisible():
            self.toggle_requirement_visibility()
        self.requirement_status.setText("剧情商讨生成的正式要求草稿 · 待确认")
        self.chapter_requirement.setFocus()
        return True

    def requirement_locked(self) -> bool:
        return self._requirement_locked

    def set_phase5_generation_enabled(self, enabled: bool, *, frozen_brief_available: bool) -> None:
        self._phase5_generation_enabled = enabled
        self._frozen_brief_available = frozen_brief_available
        self.recover_button.setEnabled(enabled)
        self._refresh_generation_controls()

    def set_frozen_brief_available(self, available: bool) -> None:
        self._frozen_brief_available = available
        self._refresh_generation_controls()

    def set_creation_mode(self, mode: CreationMode) -> None:
        if mode == CreationMode.STRICT:
            self.set_creation_mode(CreationMode.STANDARD)
            self.pre_accept_audit.setChecked(True)
            return
        for index in range(self.mode_combo.count()):
            if self.mode_combo.itemData(index) == mode.value:
                self.mode_combo.setCurrentIndex(index)
                if mode in {CreationMode.BASIC, CreationMode.STANDARD}:
                    self.pre_accept_audit.setChecked(False)
                return
        raise ValueError(f"unknown creation mode: {mode}")

    def current_creation_mode(self) -> CreationMode:
        data = self.mode_combo.currentData()
        if isinstance(data, CreationMode):
            mode = data
        elif isinstance(data, str):
            mode = CreationMode(data)
        else:
            mode = CreationMode.STANDARD
        return CreationMode.BASIC if mode == CreationMode.BASIC else CreationMode.STANDARD

    def current_audit_policy(self) -> AuditPolicy:
        mode = self.current_creation_mode()
        if mode == CreationMode.BASIC:
            return AuditPolicy.MINIMAL
        if self.pre_accept_audit.isChecked():
            return AuditPolicy.DEEP
        return AuditPolicy.STANDARD

    def begin_generation_draft(self) -> None:
        if not self._draft_preview_active:
            self._formal_text_before_draft = self.editor.toPlainText()
        self._draft_preview_active = True
        self._pre_accept_audit_allowed = False
        self._pre_accept_audit_message = ""
        self._discard_pending_draft_chunks()
        self.editor.clear()
        self.editor.setReadOnly(True)
        self.save_button.setEnabled(False)
        self.draft_status_label.setText("正在正文框内生成预览；尚未写入正式章节")
        self.pipeline_status_label.setText("正文生成：流式接收中")
        self.cancel_generation_button.setEnabled(True)
        self.adopt_draft_button.setText("采用草稿")
        self.adopt_draft_button.setEnabled(False)
        self.discard_draft_button.setEnabled(False)
        self.generate_button.setEnabled(False)

    def append_generation_draft(self, text: str) -> None:
        if not text:
            return
        self._pending_draft_chunks.append(text)
        self.discard_draft_button.setEnabled(True)
        if not self._draft_flush_timer.isActive():
            self._draft_flush_timer.start()

    def _flush_draft_chunks(self) -> None:
        if not self._pending_draft_chunks:
            return
        text = "".join(self._pending_draft_chunks)
        self._pending_draft_chunks.clear()
        self.editor.moveCursor(QTextCursor.MoveOperation.End)
        self.editor.insertPlainText(text)
        self.draft_status_label.setText("当前为草稿预览；可编辑、换稿、采用或放弃")
        self.discard_draft_button.setEnabled(True)

    def _discard_pending_draft_chunks(self) -> None:
        self._draft_flush_timer.stop()
        self._pending_draft_chunks.clear()

    def apply_generation_status(self, status: GenerationStatus) -> None:
        self._flush_draft_chunks()
        if status == GenerationStatus.STREAMING:
            self.pipeline_status_label.setText("正文生成：流式接收中")
        elif status == GenerationStatus.COMPLETED:
            self.pipeline_status_label.setText(
                getattr(self, "_pre_accept_audit_message", "")
                or "正文生成：完成，等待采用或放弃"
            )
            self.draft_status_label.setText("完整草稿已生成；请人工审查后采用")
            self.cancel_generation_button.setEnabled(False)
            self.adopt_draft_button.setText("采用草稿")
            self._enable_draft_decision_buttons()
            self.generate_button.setText("换一个草稿")
        elif status == GenerationStatus.PARTIAL:
            self.pipeline_status_label.setText("正文生成：部分草稿，等待人工决定")
            self.draft_status_label.setText("只收到部分草稿；需要明确采用才会写入正式正文")
            self.cancel_generation_button.setEnabled(False)
            self.adopt_draft_button.setText("采用部分草稿")
            self._enable_draft_decision_buttons()
            self.generate_button.setText("换一个草稿")
        elif status in {
            GenerationStatus.ACCEPTED,
            GenerationStatus.DISCARDED,
            GenerationStatus.FAILED,
        }:
            self.cancel_generation_button.setEnabled(False)
        self._refresh_generation_controls()

    def apply_accepted_generation(self, text: str) -> None:
        self._discard_pending_draft_chunks()
        self._draft_preview_active = False
        self._formal_text_before_draft = text
        self.editor.setPlainText(text)
        self._clear_draft_controls()
        self.pipeline_status_label.setText("正文生成：已采用")

    def discard_generation_draft(self) -> None:
        self._discard_pending_draft_chunks()
        restore = self._draft_preview_active
        self._draft_preview_active = False
        if restore:
            self.editor.setPlainText(self._formal_text_before_draft)
        self._clear_draft_controls()

    def _clear_draft_controls(self) -> None:
        self.draft_status_label.setText("生成后将在正文框内预览")
        self.adopt_draft_button.setText("采用草稿")
        self.adopt_draft_button.setEnabled(False)
        self.discard_draft_button.setEnabled(False)
        self.cancel_generation_button.setEnabled(False)
        self.save_button.setEnabled(True)
        self.editor.setReadOnly(False)
        self.generate_button.setText("生成正文")
        self.pipeline_status_label.setText("")
        self._refresh_generation_controls()

    def show_generation_error(self, message: str) -> None:
        self._flush_draft_chunks()
        self.pipeline_status_label.setText(f"正文生成失败：{message}")
        self.cancel_generation_button.setEnabled(False)
        self._refresh_generation_controls()

    def _emit_generation_request(self) -> None:
        self.begin_generation_draft()
        self.generation_requested.emit(
            self.current_creation_mode(),
            self.current_audit_policy(),
            self.output_token_limit.value(),
            self.target_words.value(),
        )

    def _enable_draft_decision_buttons(self) -> None:
        self._flush_draft_chunks()
        has_draft = bool(self.editor.toPlainText())
        audit_blocked = self.current_audit_policy() == AuditPolicy.DEEP and not getattr(
            self, "_pre_accept_audit_allowed", False
        )
        self.adopt_draft_button.setEnabled(has_draft and not audit_blocked)
        self.discard_draft_button.setEnabled(has_draft)

    def set_pre_accept_audit_result(self, allowed: bool, message: str) -> None:
        self._pre_accept_audit_allowed = allowed
        self._pre_accept_audit_message = message
        self.pipeline_status_label.setText(message)
        self._enable_draft_decision_buttons()

    def _refresh_generation_controls(self) -> None:
        mode = self.current_creation_mode()
        self.pre_accept_audit.setEnabled(mode != CreationMode.BASIC)
        if not self._phase5_generation_enabled:
            self.generate_button.setEnabled(False)
            self.generate_button.setToolTip("阶段 5：正文生成管线接入后可用")
            return
        needs_brief = mode == CreationMode.STANDARD
        if needs_brief and not self._frozen_brief_available:
            self.generate_button.setEnabled(False)
            self.generate_button.setToolTip("普通模式需要先冻结当前章 Brief")
            return
        if self.cancel_generation_button.isEnabled():
            self.generate_button.setEnabled(False)
            self.generate_button.setToolTip("正文正在生成中")
            return
        self.generate_button.setEnabled(True)
        self.generate_button.setToolTip("生成草稿；采用前不会覆盖正式正文")
