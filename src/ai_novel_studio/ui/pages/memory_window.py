from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.ui.demo_data import WorkspaceDemoData


class MemoryWindow(QMainWindow):
    def __init__(self, data: WorkspaceDemoData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("记忆库 · AI Novel Studio")
        self.setMinimumSize(820, 640)
        self.resize(980, 760)

        surface = QWidget(self)
        surface.setObjectName("appSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("长篇记忆库", surface)
        title.setObjectName("panelTitle")
        self.explanation_label = QLabel(
            "这里保存 AI 生成前会检索的压缩前文、人物时间线、知识边界、正典和叙事线索。"
            "用户可以直接审查和修改；后续模型生成只会读取经过时间边界过滤的有效记录。",
            surface,
        )
        self.explanation_label.setWordWrap(True)
        self.explanation_label.setObjectName("mutedLabel")

        self.tabs = QTabWidget(surface)
        self.tabs.setObjectName("memoryTabs")
        self.editors: dict[str, QPlainTextEdit] = {}
        for tab_name, text in data.memory_tabs:
            editor = QPlainTextEdit(self.tabs)
            editor.setPlainText(text)
            editor.setAccessibleName(f"编辑{tab_name}")
            self.editors[tab_name] = editor
            self.tabs.addTab(editor, tab_name)

        note = QFrame(surface)
        note.setObjectName("cardSurface")
        note_layout = QVBoxLayout(note)
        note_layout.addWidget(QLabel("阶段 2 使用模拟数据；保存操作不会写入项目数据库。", note))
        save_button = QPushButton("保存本页修改（模拟）", note)
        save_button.setAccessibleName("保存当前记忆页模拟修改")
        note_layout.addWidget(save_button)

        layout.addWidget(title)
        layout.addWidget(self.explanation_label)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(note)
        self.setCentralWidget(surface)
