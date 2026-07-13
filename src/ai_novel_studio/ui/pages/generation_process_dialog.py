from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.infrastructure.llm import LLMUsage
from ai_novel_studio.ui.i18n import language_manager


class GenerationProcessDialog(QDialog):
    """Modeless view of observable prose-generation events.

    This surface only renders events returned by the provider or emitted by the
    deterministic application pipeline. It never invents hidden chain-of-thought.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("正文生成过程")
        self.setMinimumSize(620, 460)
        self.resize(760, 600)
        self.setModal(False)
        self._draft_started = False
        self._has_tool_events = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QFrame(self)
        header.setProperty("class", "panelSurface")
        header_layout = QHBoxLayout(header)
        heading = QVBoxLayout()
        title = QLabel("AI 正文生成过程", header)
        title.setObjectName("panelTitle")
        description = QLabel(
            "展示程序实际执行阶段、模型 API 明确返回的推理内容和工具记录；不显示或伪造隐藏思维链。",
            header,
        )
        description.setObjectName("mutedLabel")
        description.setWordWrap(True)
        heading.addWidget(title)
        heading.addWidget(description)
        header_layout.addLayout(heading, 1)
        self.status_badge = QLabel("等待开始", header)
        self.status_badge.setObjectName("traceStatusBadge")
        header_layout.addWidget(self.status_badge)
        layout.addWidget(header)

        self.tabs = QTabWidget(self)
        self.activity_log = self._read_only_text("生成阶段")
        self.reasoning_output = self._read_only_text("模型返回的推理内容")
        self.reasoning_output.setPlaceholderText(
            "当前模型尚未返回可展示的推理内容。部分模型或中转站只返回最终正文。"
        )
        self.tool_output = self._read_only_text("工具调用记录")
        self.tabs.addTab(self.activity_log, "过程概览")
        self.tabs.addTab(self.reasoning_output, "模型推理")
        self.tabs.addTab(self.tool_output, "工具调用")
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.usage_label = QLabel("本次 Token：等待模型返回", self)
        self.usage_label.setObjectName("mutedLabel")
        footer.addWidget(self.usage_label)
        footer.addStretch(1)
        close_button = QPushButton("关闭", self)
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self.begin()

    def _read_only_text(self, accessible_name: str) -> QPlainTextEdit:
        editor = QPlainTextEdit(self)
        editor.setReadOnly(True)
        editor.setAccessibleName(accessible_name)
        return editor

    def begin(self) -> None:
        self._draft_started = False
        self._has_tool_events = False
        self.status_badge.setText(self._tr("准备中"))
        self.activity_log.setPlainText(
            self._tr("1. 程序：准备当前章要求、冻结 Brief、记忆与相关上下文。")
            + "\n"
            + self._tr("2. 程序：上下文准备完成后，将向正文模型发起流式请求。")
        )
        self.reasoning_output.clear()
        self.tool_output.setPlainText(
            self._tr(
                "当前正文生成不是模型驱动的 Agent 工具循环。"
                "记忆检索和上下文组装由程序在调用模型前完成，"
                "可在“AI 参考内容”中审查实际采用的来源。"
            )
        )
        self.usage_label.setText(self._tr("本次 Token：等待模型返回"))
        self.tabs.setCurrentIndex(0)

    def append_reasoning(self, text: str) -> None:
        if not text:
            return
        self.reasoning_output.moveCursor(QTextCursor.MoveOperation.End)
        self.reasoning_output.insertPlainText(text)

    def note_draft_chunk(self) -> None:
        if self._draft_started:
            return
        self._draft_started = True
        self.status_badge.setText(self._tr("生成中"))
        self.activity_log.appendPlainText(
            self._tr("3. 模型：开始流式返回正文草稿。")
        )

    def apply_status(self, status: object) -> None:
        value = str(getattr(status, "value", status))
        labels = {
            "PREPARING": ("准备中", "正在建立生成任务。"),
            "READY": ("等待模型", "上下文已冻结，等待模型请求开始。"),
            "STREAMING": ("生成中", "模型连接已建立，正在接收流式响应。"),
            "PARTIAL": ("部分完成", "生成中断，已保留收到的部分草稿。"),
            "COMPLETED": ("已完成", "完整草稿已生成，等待人工审查。"),
            "FAILED": ("失败", "本次生成失败。"),
            "ACCEPTED": ("已采用", "草稿已由用户采用。"),
            "DISCARDED": ("已放弃", "草稿已由用户放弃。"),
        }
        label, message = labels.get(value, (value, f"生成状态变更为 {value}。"))
        self.status_badge.setText(self._tr(label))
        self.activity_log.appendPlainText(
            f"{self._tr('状态')}：{self._tr(message)}"
        )

    def apply_usage(self, usage: object) -> None:
        if not isinstance(usage, LLMUsage):
            return
        input_tokens = usage.input_tokens if usage.input_tokens is not None else "未知"
        output_tokens = usage.output_tokens if usage.output_tokens is not None else "未知"
        reasoning_tokens = (
            usage.reasoning_tokens if usage.reasoning_tokens is not None else "未知"
        )
        self.usage_label.setText(
            f"{self._tr('本次 Token')}：{self._tr('输入')} {input_tokens} · "
            f"{self._tr('输出')} {output_tokens} · {self._tr('推理')} {reasoning_tokens}"
        )

    def record_tool_call(self, name: str, status: str, summary: str = "") -> None:
        """Future-compatible entry point for a prose Agent tool loop."""
        if not self._has_tool_events:
            self.tool_output.clear()
            self._has_tool_events = True
        safe_name = name.strip() or "未知工具"
        safe_status = status.strip() or "未知状态"
        detail = summary.strip()
        line = f"{safe_name} · {safe_status}"
        if detail:
            line += f"\n{detail}"
        self.tool_output.appendPlainText(line)

    def show_error(self, message: str) -> None:
        self.status_badge.setText(self._tr("失败"))
        self.activity_log.appendPlainText(f"{self._tr('错误')}：{message}")

    @staticmethod
    def _tr(text: str) -> str:
        return language_manager().translate(text)
