from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.application.model_tasks import NormalizedBrief
from ai_novel_studio.ui.demo_data import DemoBrief


class BriefDialog(QDialog):
    normalize_requested = Signal(str)

    def __init__(self, brief: DemoBrief, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("章节 Brief 审查")
        self.setObjectName("briefDialog")
        self.setMinimumSize(720, 620)
        self.resize(820, 720)

        self._status = brief.status
        self.status_label = QLabel(self._status, self)
        self.status_label.setObjectName("panelTitle")
        fingerprint = QLabel(f"来源指纹  {brief.fingerprint}", self)
        fingerprint.setObjectName("mutedLabel")

        header = QHBoxLayout()
        header.addWidget(QLabel("Brief 状态", self))
        header.addWidget(self.status_label)
        header.addStretch(1)
        header.addWidget(fingerprint)

        self.source_badges: list[QLabel] = []
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("参考来源", self))
        for source in brief.sources:
            badge = QLabel(source, self)
            badge.setObjectName("metricChip")
            badge.setMargin(6)
            self.source_badges.append(badge)
            source_layout.addWidget(badge)
        source_layout.addStretch(1)

        warning_frame = QFrame(self)
        warning_frame.setObjectName("cardSurface")
        warning_layout = QVBoxLayout(warning_frame)
        warning_title = QLabel("需要确认", warning_frame)
        warning_title.setObjectName("sectionEyebrow")
        warning_layout.addWidget(warning_title)
        for warning in brief.warnings:
            warning_layout.addWidget(QLabel(f"• {warning}", warning_frame))

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        form = QWidget(scroll)
        form_layout = QVBoxLayout(form)
        self.section_editors: dict[str, QTextEdit] = {}
        for title, text in brief.sections:
            label = QLabel(title, form)
            label.setObjectName("sectionEyebrow")
            editor = QTextEdit(form)
            editor.setAcceptRichText(False)
            editor.setPlainText(text)
            editor.setMinimumHeight(76)
            editor.setAccessibleName(f"Brief {title}")
            self.section_editors[title] = editor
            form_layout.addWidget(label)
            form_layout.addWidget(editor)
        form_layout.addStretch(1)
        scroll.setWidget(form)

        self.normalize_button = QPushButton("AI 整理草稿", self)
        self.normalize_button.setAccessibleName("使用模型整理当前 Brief 草稿")
        self.normalize_button.clicked.connect(
            lambda: self.normalize_requested.emit(self.source_text())
        )
        self.clone_button = QPushButton("克隆为新草稿", self)
        self.clone_button.setAccessibleName("把当前 Brief 克隆为新草稿")
        self.clone_button.clicked.connect(self.clone_as_draft)
        self.freeze_button = QPushButton("审查并冻结", self)
        self.freeze_button.setProperty("buttonRole", "primary")
        self.freeze_button.setAccessibleName("冻结当前 Brief")
        self.freeze_button.clicked.connect(self.freeze_brief)
        close_button = QPushButton("关闭", self)
        close_button.clicked.connect(self.close)
        actions = QHBoxLayout()
        actions.addWidget(self.normalize_button)
        actions.addWidget(self.clone_button)
        actions.addStretch(1)
        actions.addWidget(close_button)
        actions.addWidget(self.freeze_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addLayout(source_layout)
        layout.addWidget(warning_frame)
        layout.addWidget(scroll, 1)
        layout.addLayout(actions)

    def brief_status(self) -> str:
        return self._status

    def freeze_brief(self) -> None:
        self._set_status("已冻结")
        for editor in self.section_editors.values():
            editor.setReadOnly(True)
        self.freeze_button.setEnabled(False)

    def mark_stale(self) -> None:
        self._set_status("已过期")
        self.freeze_button.setEnabled(False)

    def clone_as_draft(self) -> None:
        self._set_status("草稿")
        for editor in self.section_editors.values():
            editor.setReadOnly(False)
        self.freeze_button.setEnabled(True)

    def _set_status(self, status: str) -> None:
        self._status = status
        self.status_label.setText(status)

    def source_text(self) -> str:
        return "\n\n".join(
            f"{title}：\n{editor.toPlainText()}"
            for title, editor in self.section_editors.items()
        )

    def apply_normalized_brief(self, brief: NormalizedBrief) -> None:
        updates = {
            "戏剧功能": brief.dramatic_function,
            "必须事件": "\n".join(brief.hard_events),
            "自由空间": "\n".join(brief.creative_freedom),
        }
        for title, text in updates.items():
            editor = self.section_editors.get(title)
            if editor is not None:
                editor.setPlainText(text)
        self._set_status("草稿 · AI 已整理 · 待人工审查")
        self.normalize_button.setEnabled(True)
