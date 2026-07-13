from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ai_novel_studio.ui.i18n import Language, LocalizationManager


class LanguageSelectionDialog(QDialog):
    """First-run language gate shown before the main workspace is created."""

    def __init__(
        self,
        manager: LocalizationManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self.setWindowTitle("选择语言 / Choose Language")
        self.setModal(True)
        self.setFixedSize(460, 220)

        title = QLabel("请选择界面语言\nChoose your interface language", self)
        title.setObjectName("panelTitle")
        title.setAlignment(title.alignment())
        note = QLabel(
            "之后可以在“设置 → 外观 → 语言”中修改。\n"
            "You can change this later in Settings → Appearance → Language.",
            self,
        )
        note.setWordWrap(True)
        note.setObjectName("mutedLabel")

        self.chinese_button = QPushButton("简体中文", self)
        self.chinese_button.setMinimumHeight(44)
        self.chinese_button.clicked.connect(
            lambda: self._select_language(Language.CHINESE)
        )
        self.english_button = QPushButton("English", self)
        self.english_button.setMinimumHeight(44)
        self.english_button.clicked.connect(
            lambda: self._select_language(Language.ENGLISH)
        )

        buttons = QHBoxLayout()
        buttons.addWidget(self.chinese_button)
        buttons.addWidget(self.english_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(note)
        layout.addStretch(1)
        layout.addLayout(buttons)

    def _select_language(self, language: Language) -> None:
        self._manager.set_language(language)
        self.accept()
