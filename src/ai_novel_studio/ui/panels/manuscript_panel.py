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
