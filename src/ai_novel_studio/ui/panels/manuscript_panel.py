from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
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

from ai_novel_studio.domain.generation import CreationMode, GenerationStatus
from ai_novel_studio.ui.demo_data import WorkspaceDemoData


class ManuscriptPanel(QFrame):
    brief_requested = Signal()
    audit_requested = Signal()
    references_requested = Signal()
    generation_requested = Signal(object, int, int)
    generation_cancel_requested = Signal()
    draft_accept_requested = Signal()
    draft_discard_requested = Signal()
    recovery_requested = Signal()

    def __init__(self, data: WorkspaceDemoData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("manuscriptPanel")
        self.setMinimumWidth(430)
        self._requirement_locked = False
        self._phase5_generation_enabled = False
        self._frozen_brief_available = False

        self.chapter_title = QLineEdit("第 2 章 · 没有寄出的信", self)
        self.chapter_title.setAccessibleName("当前章节标题")
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("快速", CreationMode.BASIC.value)
        self.mode_combo.addItem("标准", CreationMode.STANDARD.value)
        self.mode_combo.addItem("严格", CreationMode.STRICT.value)
        self.mode_combo.setCurrentIndex(1)
        self.mode_combo.setAccessibleName("创作档位")
        self.target_words = self._spin_box(500, 50000, 3500, "目标字数")
        self.output_token_limit = self._spin_box(256, 200000, 8000, "输出 Token 上限")
        self.font_size = self._spin_box(12, 32, 17, "正文字体大小")
        self.font_size.setSuffix(" pt")

        title_row = QHBoxLayout()
        title_row.addWidget(self.chapter_title, 1)
        title_row.addWidget(QLabel("档位", self))
        title_row.addWidget(self.mode_combo)

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
        self.generate_button.setToolTip("阶段 5 接入章节生成管线后可用")
        self.generate_button.clicked.connect(self._emit_generation_request)
        action_row = QHBoxLayout()
        action_row.addWidget(self.brief_button)
        action_row.addWidget(references_button)
        action_row.addWidget(audit_button)
        action_row.addStretch(1)
        action_row.addWidget(self.recover_button)
        action_row.addWidget(self.cancel_generation_button)
        action_row.addWidget(self.generate_button)

        requirement_header = QHBoxLayout()
        requirement_title = QLabel("当前章要求", self)
        requirement_title.setObjectName("sectionEyebrow")
        self.requirement_status = QLabel("人工指令 · 可编辑 · 最高优先级", self)
        self.requirement_status.setObjectName("mutedLabel")
        self.requirement_lock_button = QPushButton("锁定要求", self)
        self.requirement_lock_button.setAccessibleName("锁定当前章要求")
        self.requirement_lock_button.clicked.connect(self.toggle_requirement_lock)
        requirement_header.addWidget(requirement_title)
        requirement_header.addWidget(self.requirement_status)
        requirement_header.addStretch(1)
        requirement_header.addWidget(self.requirement_lock_button)

        self.chapter_requirement = QPlainTextEdit(self)
        self.chapter_requirement.setObjectName("chapterRequirement")
        self.chapter_requirement.setAccessibleName("当前章要求")
        self.chapter_requirement.setPlainText(data.chapter_requirement)
        self.chapter_requirement.setMinimumHeight(82)
        self.chapter_requirement.setMaximumHeight(120)

        self.editor = QPlainTextEdit(self)
        self.editor.setObjectName("manuscriptEditor")
        self.editor.setAccessibleName("章节正文编辑器")
        self.editor.setPlainText(data.chapter_text)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setTabChangesFocus(False)
        self._set_editor_font_size(self.font_size.value())

        draft_header = QHBoxLayout()
        draft_title = QLabel("AI 生成草稿", self)
        draft_title.setObjectName("sectionEyebrow")
        self.draft_status_label = QLabel(
            "尚无草稿；生成内容会先停在这里，采用后才写入正式正文", self
        )
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

        self.generated_draft_editor = QPlainTextEdit(self)
        self.generated_draft_editor.setObjectName("generatedDraftEditor")
        self.generated_draft_editor.setAccessibleName("AI 生成草稿预览")
        self.generated_draft_editor.setReadOnly(True)
        self.generated_draft_editor.setMinimumHeight(90)
        self.generated_draft_editor.setMaximumHeight(150)
        self.generated_draft_editor.setPlaceholderText("生成中的正文草稿会显示在这里。")

        self.word_count_label = QLabel(self)
        self.word_count_label.setObjectName("mutedLabel")
        self.save_status_label = QLabel("本地修改已保存 · 修订 12", self)
        self.save_status_label.setObjectName("mutedLabel")
        self.pipeline_status_label = QLabel("Brief：草稿 · 管线：等待确认", self)
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
        layout.addWidget(self.generated_draft_editor)
        layout.addLayout(footer)

        self.font_size.valueChanged.connect(self._set_editor_font_size)
        self.mode_combo.currentIndexChanged.connect(self._refresh_generation_controls)
        self.editor.textChanged.connect(self._update_word_count)
        self._update_word_count()

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

    def toggle_requirement_lock(self) -> None:
        self._requirement_locked = not self._requirement_locked
        self.chapter_requirement.setReadOnly(self._requirement_locked)
        if self._requirement_locked:
            self.requirement_status.setText("人工指令 · 已锁定 · 最高优先级")
            self.requirement_lock_button.setText("解除锁定")
            self.requirement_lock_button.setAccessibleName("解除当前章要求锁定")
        else:
            self.requirement_status.setText("人工指令 · 可编辑 · 最高优先级")
            self.requirement_lock_button.setText("锁定要求")
            self.requirement_lock_button.setAccessibleName("锁定当前章要求")

    def apply_requirement_draft(self, text: str) -> bool:
        if self._requirement_locked:
            return False
        self.chapter_requirement.setPlainText(text)
        self.requirement_status.setText("剧情商讨生成的正式要求草稿 · 待确认")
        self.chapter_requirement.setFocus()
        return True

    def requirement_locked(self) -> bool:
        return self._requirement_locked

    def set_phase5_generation_enabled(
        self, enabled: bool, *, frozen_brief_available: bool
    ) -> None:
        self._phase5_generation_enabled = enabled
        self._frozen_brief_available = frozen_brief_available
        self.recover_button.setEnabled(enabled)
        self._refresh_generation_controls()

    def set_frozen_brief_available(self, available: bool) -> None:
        self._frozen_brief_available = available
        self._refresh_generation_controls()

    def set_creation_mode(self, mode: CreationMode) -> None:
        for index in range(self.mode_combo.count()):
            if self.mode_combo.itemData(index) == mode.value:
                self.mode_combo.setCurrentIndex(index)
                return
        raise ValueError(f"unknown creation mode: {mode}")

    def current_creation_mode(self) -> CreationMode:
        data = self.mode_combo.currentData()
        if isinstance(data, CreationMode):
            return data
        if isinstance(data, str):
            return CreationMode(data)
        return CreationMode.STANDARD

    def begin_generation_draft(self) -> None:
        self.generated_draft_editor.clear()
        self.draft_status_label.setText("正在生成；正式正文尚未改变")
        self.pipeline_status_label.setText("正文生成：流式接收中")
        self.cancel_generation_button.setEnabled(True)
        self.adopt_draft_button.setText("采用草稿")
        self.adopt_draft_button.setEnabled(False)
        self.discard_draft_button.setEnabled(False)
        self.generate_button.setEnabled(False)

    def append_generation_draft(self, text: str) -> None:
        if not text:
            return
        self.generated_draft_editor.moveCursor(QTextCursor.MoveOperation.End)
        self.generated_draft_editor.insertPlainText(text)
        self.draft_status_label.setText("草稿已保存到检查点；采用前不会覆盖正式正文")
        self.discard_draft_button.setEnabled(True)

    def apply_generation_status(self, status: GenerationStatus) -> None:
        if status == GenerationStatus.STREAMING:
            self.pipeline_status_label.setText("正文生成：流式接收中")
        elif status == GenerationStatus.COMPLETED:
            self.pipeline_status_label.setText("正文生成：完成，等待采用或放弃")
            self.draft_status_label.setText("完整草稿已就绪；请人工审查后采用")
            self.cancel_generation_button.setEnabled(False)
            self.adopt_draft_button.setText("采用草稿")
            self._enable_draft_decision_buttons()
        elif status == GenerationStatus.PARTIAL:
            self.pipeline_status_label.setText("正文生成：部分草稿，等待人工决定")
            self.draft_status_label.setText("只收到部分草稿；需要明确采用才会写入正式正文")
            self.cancel_generation_button.setEnabled(False)
            self.adopt_draft_button.setText("采用部分草稿")
            self._enable_draft_decision_buttons()
        elif status in {
            GenerationStatus.ACCEPTED,
            GenerationStatus.DISCARDED,
            GenerationStatus.FAILED,
        }:
            self.cancel_generation_button.setEnabled(False)
        self._refresh_generation_controls()

    def apply_accepted_generation(self, text: str) -> None:
        self.editor.setPlainText(text)
        self.discard_generation_draft()
        self.pipeline_status_label.setText("正文生成：已采用")

    def discard_generation_draft(self) -> None:
        self.generated_draft_editor.clear()
        self.draft_status_label.setText("尚无草稿；生成内容会先停在这里，采用后才写入正式正文")
        self.adopt_draft_button.setText("采用草稿")
        self.adopt_draft_button.setEnabled(False)
        self.discard_draft_button.setEnabled(False)
        self.cancel_generation_button.setEnabled(False)
        self.pipeline_status_label.setText("正文生成：未开始")
        self._refresh_generation_controls()

    def show_generation_error(self, message: str) -> None:
        self.pipeline_status_label.setText(f"正文生成失败：{message}")
        self.cancel_generation_button.setEnabled(False)
        self._refresh_generation_controls()

    def _emit_generation_request(self) -> None:
        self.begin_generation_draft()
        self.generation_requested.emit(
            self.current_creation_mode(),
            self.output_token_limit.value(),
            self.target_words.value(),
        )

    def _enable_draft_decision_buttons(self) -> None:
        has_draft = bool(self.generated_draft_editor.toPlainText())
        self.adopt_draft_button.setEnabled(has_draft)
        self.discard_draft_button.setEnabled(has_draft)

    def _refresh_generation_controls(self) -> None:
        if not self._phase5_generation_enabled:
            self.generate_button.setEnabled(False)
            self.generate_button.setToolTip("阶段 5 接入章节生成管线后可用")
            return
        mode = self.current_creation_mode()
        if mode == CreationMode.STRICT:
            self.generate_button.setEnabled(False)
            self.generate_button.setToolTip("严格模式将在阶段 6 审校与修复管线开放")
            return
        if mode == CreationMode.STANDARD and not self._frozen_brief_available:
            self.generate_button.setEnabled(False)
            self.generate_button.setToolTip("标准模式需要先冻结当前章 Brief")
            return
        if self.cancel_generation_button.isEnabled():
            self.generate_button.setEnabled(False)
            self.generate_button.setToolTip("正文正在生成中")
            return
        self.generate_button.setEnabled(True)
        self.generate_button.setToolTip("生成草稿；采用前不会覆盖正式正文")
