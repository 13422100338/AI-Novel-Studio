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
from ai_novel_studio.domain.generation import BriefStatus, ChapterBrief
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import BriefDraftData
from ai_novel_studio.ui.demo_data import DemoBrief


class BriefDialog(QDialog):
    normalize_requested = Signal(str)
    save_requested = Signal()
    freeze_requested = Signal()
    clone_requested = Signal()
    recompile_requested = Signal()

    def __init__(self, brief: DemoBrief, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("章节 Brief 审查")
        self.setObjectName("briefDialog")
        self.setMinimumSize(720, 620)
        self.resize(820, 720)
        self._status = brief.status
        self._project_brief: ChapterBrief | None = None

        self.status_label = QLabel(self._status, self)
        self.status_label.setObjectName("panelTitle")
        self.fingerprint_label = QLabel(f"来源指纹  {brief.fingerprint}", self)
        self.fingerprint_label.setObjectName("mutedLabel")
        header = QHBoxLayout()
        header.addWidget(QLabel("Brief 状态", self))
        header.addWidget(self.status_label)
        header.addStretch(1)
        header.addWidget(self.fingerprint_label)

        self.source_badges: list[QLabel] = []
        self.source_layout = QHBoxLayout()
        self.source_layout.addWidget(QLabel("参考来源", self))
        for source in brief.sources:
            badge = QLabel(source, self)
            badge.setObjectName("metricChip")
            badge.setMargin(6)
            self.source_badges.append(badge)
            self.source_layout.addWidget(badge)
        self.source_layout.addStretch(1)

        warning_frame = QFrame(self)
        warning_frame.setObjectName("cardSurface")
        warning_layout = QVBoxLayout(warning_frame)
        warning_title = QLabel("需要确认", warning_frame)
        warning_title.setObjectName("sectionEyebrow")
        warning_layout.addWidget(warning_title)
        self.warning_label = QLabel("\n".join(f"• {item}" for item in brief.warnings))
        warning_layout.addWidget(self.warning_label)

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
        self.normalize_button.clicked.connect(
            lambda: self.normalize_requested.emit(self.source_text())
        )
        self.clone_button = QPushButton("克隆为新草稿", self)
        self.clone_button.clicked.connect(self.clone_as_draft)
        self.save_button = QPushButton("保存草稿", self)
        self.save_button.clicked.connect(self.save_requested.emit)
        self.recompile_button = QPushButton("重新编译", self)
        self.recompile_button.clicked.connect(self.recompile_requested.emit)
        self.freeze_button = QPushButton("审查并冻结", self)
        self.freeze_button.setProperty("buttonRole", "primary")
        self.freeze_button.clicked.connect(self.freeze_brief)
        close_button = QPushButton("关闭", self)
        close_button.clicked.connect(self.close)
        actions = QHBoxLayout()
        actions.addWidget(self.normalize_button)
        actions.addWidget(self.clone_button)
        actions.addWidget(self.save_button)
        actions.addWidget(self.recompile_button)
        actions.addStretch(1)
        actions.addWidget(close_button)
        actions.addWidget(self.freeze_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addLayout(self.source_layout)
        layout.addWidget(warning_frame)
        layout.addWidget(scroll, 1)
        layout.addLayout(actions)

    def brief_status(self) -> str:
        return self._status

    def freeze_brief(self) -> None:
        if self._project_brief is not None:
            self.freeze_requested.emit()
            return
        self._set_status("已冻结")
        for editor in self.section_editors.values():
            editor.setReadOnly(True)
        self.freeze_button.setEnabled(False)

    def mark_stale(self) -> None:
        self._set_status("已过期")
        self.freeze_button.setEnabled(False)

    def clone_as_draft(self) -> None:
        if self._project_brief is not None:
            self.clone_requested.emit()
            return
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

    def bind_project_brief(self, brief: ChapterBrief) -> None:
        self._project_brief = brief
        labels = {
            BriefStatus.DRAFT: "草稿",
            BriefStatus.FROZEN: "已冻结",
            BriefStatus.STALE: "已过期",
            BriefStatus.ARCHIVED: "已归档",
        }
        self._set_status(labels[brief.status])
        self.fingerprint_label.setText(f"来源指纹  {brief.source_fingerprint[:12]}")
        self.warning_label.setText("\n".join(f"• {item}" for item in brief.warnings))
        values = {
            "戏剧功能": brief.dramatic_purpose,
            "必须事件": "\n".join(brief.hard_events),
            "知识边界": "\n".join(brief.knowledge),
            "叙事线索": "\n".join(brief.clue_actions),
            "文风": "\n".join(brief.style_rules),
            "自由空间": "\n".join(brief.creative_freedom),
        }
        for title, value in values.items():
            editor = self.section_editors.get(title)
            if editor is not None:
                editor.setPlainText(value)
        editable = brief.status == BriefStatus.DRAFT
        for editor in self.section_editors.values():
            editor.setReadOnly(not editable)
        self.save_button.setEnabled(editable)
        self.freeze_button.setEnabled(editable)
        self.clone_button.setEnabled(brief.status in {BriefStatus.FROZEN, BriefStatus.STALE})
        self.recompile_button.setEnabled(True)

    def show_error(self, message: str) -> None:
        self.warning_label.setText(f"操作未完成：{message}")

    def project_draft_data(self) -> BriefDraftData:
        current = self._require_project_brief()

        def lines(title: str) -> tuple[str, ...]:
            editor = self.section_editors.get(title)
            return () if editor is None else tuple(
                line.strip() for line in editor.toPlainText().splitlines() if line.strip()
            )

        dramatic = self.section_editors["戏剧功能"].toPlainText().strip()
        return BriefDraftData(
            current.chapter_id,
            current.mode,
            dramatic,
            current.target_length,
            current.story_date,
            current.pov_character_id,
            lines("必须事件"),
            current.soft_goals,
            current.prohibited_changes,
            lines("自由空间"),
            current.participants,
            lines("知识边界"),
            lines("叙事线索"),
            lines("文风"),
            current.warnings,
        )

    def project_brief_identity(self) -> tuple[str, int]:
        brief = self._require_project_brief()
        return brief.id, brief.revision

    def _require_project_brief(self) -> ChapterBrief:
        if self._project_brief is None:
            raise RuntimeError("Brief 尚未绑定真实项目")
        return self._project_brief
