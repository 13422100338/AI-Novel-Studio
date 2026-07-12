from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ProjectWelcome(QFrame):
    """Project entry strip.

    The widget emits requests only. Storage and import logic live outside UI.
    """

    create_project_requested = Signal(object, str)
    open_project_requested = Signal(object)
    import_project_requested = Signal(object, object)
    import_file_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("projectWelcome")
        self.setProperty("class", "panelSurface")

        self.title_label = QLabel("打开或创建一个小说项目", self)
        self.title_label.setObjectName("panelTitle")
        self.subtitle_label = QLabel(
            "可新建项目、打开已有项目，或导入 Markdown/TXT 原稿。",
            self,
        )
        self.subtitle_label.setObjectName("mutedLabel")

        self.create_button = QPushButton("新建项目", self)
        self.create_button.setAccessibleName("新建项目")
        self.create_button.clicked.connect(self.choose_create_project)
        self.open_button = QPushButton("打开项目", self)
        self.open_button.setAccessibleName("打开项目")
        self.open_button.clicked.connect(self.choose_open_project)
        self.import_button = QPushButton("导入稿件", self)
        self.import_button.setAccessibleName("导入稿件")
        self.import_button.clicked.connect(self.choose_import_file)

        action_row = QHBoxLayout()
        action_row.addWidget(self.create_button)
        action_row.addWidget(self.open_button)
        action_row.addWidget(self.import_button)
        action_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addLayout(action_row)

    def request_create_project(self, root: Path, title: str) -> None:
        self.create_project_requested.emit(root, title)

    def request_open_project(self, root: Path) -> None:
        self.open_project_requested.emit(root)

    def request_import_project(self, source: Path, destination: Path) -> None:
        self.import_project_requested.emit(source, destination)

    def request_import_file(self, source: Path) -> None:
        self.import_file_requested.emit(source)

    def choose_create_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择空文件夹作为新项目",
            str(Path.home()),
        )
        if not directory:
            return
        title, accepted = QInputDialog.getText(
            self,
            "新建项目",
            "项目名称：",
        )
        if not accepted or not title.strip():
            return
        self.request_create_project(Path(directory), title.strip())

    def choose_open_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择已有项目文件夹",
            str(Path.home()),
        )
        if not directory:
            return
        self.request_open_project(Path(directory))

    def choose_import_file(self) -> None:
        filename, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择要导入的稿件",
            str(Path.home()),
            "Manuscripts (*.md *.txt);;Markdown (*.md);;Text (*.txt)",
        )
        if not filename:
            return
        self.request_import_file(Path(filename))

    def show_import_placeholder(self) -> None:
        QMessageBox.information(self, "导入稿件", "请选择 .md 或 .txt 文件导入。")
