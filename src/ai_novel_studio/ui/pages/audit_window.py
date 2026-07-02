from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.ui.demo_data import WorkspaceDemoData


class AuditWindow(QMainWindow):
    def __init__(self, data: WorkspaceDemoData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("审校工作台 · AI Novel Studio")
        self.setMinimumSize(860, 640)
        self.resize(1040, 760)

        surface = QWidget(self)
        surface.setObjectName("appSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel("独立审校工作台", surface)
        title.setObjectName("panelTitle")
        explanation = QLabel(
            "确定性检查负责频率和格式；模型审校负责知识边界、动机、节奏和声音。"
            "任何修复都必须先显示差异。",
            surface,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("mutedLabel")

        deterministic = [row for row in data.audit_findings if row[0] == "确定性"]
        model = [row for row in data.audit_findings if row[0] == "模型"]
        self.tabs = QTabWidget(surface)
        self.deterministic_table = self._finding_table(deterministic, self.tabs)
        self.model_table = self._finding_table(model, self.tabs)
        self.tabs.addTab(self.deterministic_table, "确定性检查")
        self.tabs.addTab(self.model_table, "模型审校")

        accept_button = QPushButton("接受标记", surface)
        accept_button.setAccessibleName("接受当前审校标记")
        reject_button = QPushButton("忽略标记", surface)
        reject_button.setAccessibleName("忽略当前审校标记")
        self.repair_button = QPushButton("生成局部修复建议", surface)
        self.repair_button.setEnabled(False)
        self.repair_button.setToolTip("阶段 3 接入模型后可用")
        actions = QHBoxLayout()
        actions.addWidget(accept_button)
        actions.addWidget(reject_button)
        actions.addStretch(1)
        actions.addWidget(self.repair_button)

        layout.addWidget(title)
        layout.addWidget(explanation)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(actions)
        self.setCentralWidget(surface)

    @staticmethod
    def _finding_table(findings: list[tuple[str, str, str]], parent: QWidget) -> QTableWidget:
        table = QTableWidget(len(findings), 3, parent)
        table.setHorizontalHeaderLabels(("来源", "问题", "证据"))
        table.horizontalHeader().setStretchLastSection(True)
        for row, values in enumerate(findings):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        return table
