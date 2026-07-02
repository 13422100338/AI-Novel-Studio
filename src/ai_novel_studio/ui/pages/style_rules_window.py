from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.ui.demo_data import WorkspaceDemoData


class StyleRulesWindow(QMainWindow):
    def __init__(self, data: WorkspaceDemoData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("文风规则 · AI Novel Studio")
        self.setMinimumSize(820, 640)
        self.resize(960, 740)

        surface = QWidget(self)
        surface.setObjectName("appSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel("分层文风系统", surface)
        title.setObjectName("panelTitle")
        explanation = QLabel(
            "生成时只注入与当前章节相关的规则。人工样章保持只读，AI 分析只能进入候选区。",
            surface,
        )
        explanation.setObjectName("mutedLabel")

        self.tabs = QTabWidget(surface)
        self.rules_table = QTableWidget(len(data.style_rules), 3, self.tabs)
        self.rules_table.setHorizontalHeaderLabels(("层级", "规则", "范围 / 权威"))
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        for row, values in enumerate(data.style_rules):
            for column, value in enumerate(values):
                self.rules_table.setItem(row, column, QTableWidgetItem(value))
        self.tabs.addTab(self.rules_table, "分层规则")

        self.human_sample = QPlainTextEdit(self.tabs)
        self.human_sample.setPlainText(
            "【人工样章，只读】\n雪落在旧港的铁轨上，没有声音。林默站在灯影之外，"
            "直到最后一班渡船离岸，也没有向前一步。"
        )
        self.human_sample.setReadOnly(True)
        self.human_sample.setAccessibleName("人工锁定文风样章")
        self.tabs.addTab(self.human_sample, "人工样章")

        self.candidate_editor = QPlainTextEdit(self.tabs)
        self.candidate_editor.setPlainText(
            "候选规则：动作场景减少心理解释，优先使用短句与具体空间变化。"
        )
        self.candidate_editor.setAccessibleName("AI 文风候选规则")
        self.tabs.addTab(self.candidate_editor, "AI 候选")

        layout.addWidget(title)
        layout.addWidget(explanation)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(surface)
