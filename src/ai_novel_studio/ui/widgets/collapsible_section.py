from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    def __init__(self, title: str, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._content = content
        self._toggle = QToolButton(self)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(True)
        self._toggle.setToolButtonStyle(self._toggle.toolButtonStyle())
        self._toggle.setAccessibleName(f"折叠或展开{title}")
        self._toggle.clicked.connect(self.set_expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._toggle)
        layout.addWidget(content)
        self.set_expanded(True)

    def set_expanded(self, expanded: bool) -> None:
        self._toggle.setChecked(expanded)
        self._toggle.setText(f"−  {self._title}" if expanded else f"＋  {self._title}")
        self._content.setVisible(expanded)

    def is_expanded(self) -> bool:
        return self._toggle.isChecked()
