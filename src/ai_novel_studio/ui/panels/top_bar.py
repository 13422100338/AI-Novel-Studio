from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ai_novel_studio.infrastructure.llm import UsageSnapshot
from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.widgets.metric_chip import MetricChip


class TopBar(QFrame):
    settings_requested = Signal()

    def __init__(self, data: WorkspaceDemoData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")

        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 12, 0)
        title_layout.setSpacing(1)
        self.project_label = QLabel(data.project_title, self)
        self.project_label.setObjectName("panelTitle")
        self.volume_label = QLabel(data.current_volume, self)
        self.volume_label.setObjectName("mutedLabel")
        title_layout.addWidget(self.project_label)
        title_layout.addWidget(self.volume_label)

        self.metrics = {
            "input": MetricChip("输入", "约 18.6K", self),
            "output": MetricChip("输出上限", "8K", self),
            "cost": MetricChip("预计费用", "¥0.18", self),
            "memory": MetricChip("记忆", "有效", self),
        }
        self.settings_button = QPushButton("设置", self)
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setAccessibleName("打开应用设置")
        self.settings_button.setToolTip("模型、外观与项目设置")
        self.settings_button.clicked.connect(self.settings_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(8)
        layout.addLayout(title_layout)
        layout.addStretch(1)
        for metric in self.metrics.values():
            layout.addWidget(metric)
        layout.addWidget(self.settings_button)

    def update_usage(self, snapshot: UsageSnapshot) -> None:
        self.metrics["input"].set_value(self._token_text(snapshot.input_tokens))
        self.metrics["output"].set_value(self._token_text(snapshot.output_tokens))
        cost = "未知" if snapshot.cost is None else f"¥{snapshot.cost:.3f}"
        self.metrics["cost"].set_value(cost)
        cache = (
            self._token_text(snapshot.cached_input_tokens)
            if snapshot.cache_known
            else "未知"
        )
        self.metrics["memory"].set_value(f"缓存 {cache}")

    @staticmethod
    def _token_text(value: int) -> str:
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return str(value)
