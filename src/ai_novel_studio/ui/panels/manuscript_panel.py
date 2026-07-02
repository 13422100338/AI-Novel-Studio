from PySide6.QtCore import Signal
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

from ai_novel_studio.ui.demo_data import WorkspaceDemoData


class ManuscriptPanel(QFrame):
    brief_requested = Signal()
    audit_requested = Signal()
    references_requested = Signal()
    generation_requested = Signal()

    def __init__(self, data: WorkspaceDemoData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("manuscriptPanel")
        self.setMinimumWidth(430)

        self.chapter_title = QLineEdit("第 2 章 · 没有寄出的信", self)
        self.chapter_title.setAccessibleName("当前章节标题")
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItems(("快速", "标准", "严格"))
        self.mode_combo.setCurrentText("标准")
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
        self.generate_button = QPushButton("生成正文", self)
        self.generate_button.setAccessibleName("使用当前 Brief 生成正文")
        self.generate_button.setProperty("buttonRole", "primary")
        self.generate_button.setEnabled(False)
        self.generate_button.setToolTip("阶段 3 接入模型后可用")
        self.generate_button.clicked.connect(self.generation_requested)
        action_row = QHBoxLayout()
        action_row.addWidget(self.brief_button)
        action_row.addWidget(references_button)
        action_row.addWidget(audit_button)
        action_row.addStretch(1)
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

        self._requirement_locked = False
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
        layout.addLayout(footer)

        self.font_size.valueChanged.connect(self._set_editor_font_size)
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
