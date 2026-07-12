from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


class MetricChip(QFrame):
    def __init__(self, label: str, value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metricChip")
        self._label = QLabel(label, self)
        self._label.setObjectName("mutedLabel")
        self._value = QLabel(value, self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(5)
        layout.addWidget(self._label)
        layout.addWidget(self._value)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def value_text(self) -> str:
        return self._value.text()
