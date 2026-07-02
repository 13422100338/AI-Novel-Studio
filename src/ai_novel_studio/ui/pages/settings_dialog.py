from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置 · AI Novel Studio")
        self.setMinimumSize(620, 480)
        self.resize(700, 540)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._model_tab(), "模型连接")
        self.tabs.addTab(self._appearance_tab(), "外观")
        self.tabs.addTab(self._creation_tab(), "创作默认值")

        close_button = QPushButton("关闭", self)
        close_button.setAccessibleName("关闭设置")
        close_button.clicked.connect(self.close)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(close_button)

    def _model_tab(self) -> QWidget:
        page = QWidget(self.tabs)
        form = QFormLayout(page)
        notice = QLabel(
            "阶段 2 仅展示配置界面；模型连接、拉取模型列表和 API Key 安全存储在阶段 3 接入。",
            page,
        )
        notice.setWordWrap(True)
        notice.setObjectName("mutedLabel")
        base_url = QLineEdit("https://api.example.com/v1", page)
        base_url.setAccessibleName("API Base URL 示例")
        base_url.setReadOnly(True)
        model = QComboBox(page)
        model.addItem("阶段 3 接入后选择模型")
        model.setAccessibleName("模型选择示例")
        model.setEnabled(False)
        form.addRow(notice)
        form.addRow("Base URL", base_url)
        form.addRow("模型", model)
        return page

    def _appearance_tab(self) -> QWidget:
        page = QWidget(self.tabs)
        form = QFormLayout(page)
        theme = QComboBox(page)
        theme.addItems(("浅色（当前）", "跟随系统"))
        theme.setAccessibleName("界面主题")
        density = QComboBox(page)
        density.addItems(("适中", "紧凑", "宽松"))
        density.setAccessibleName("界面密度")
        form.addRow("主题", theme)
        form.addRow("信息密度", density)
        return page

    def _creation_tab(self) -> QWidget:
        page = QWidget(self.tabs)
        form = QFormLayout(page)
        target_words = QSpinBox(page)
        target_words.setRange(500, 50000)
        target_words.setValue(3500)
        target_words.setAccessibleName("默认目标字数")
        output_tokens = QSpinBox(page)
        output_tokens.setRange(256, 200000)
        output_tokens.setValue(8000)
        output_tokens.setAccessibleName("默认输出 Token 上限")
        form.addRow("目标字数", target_words)
        form.addRow("输出 Token 上限", output_tokens)
        return page
