from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from ai_novel_studio.infrastructure.logging_config import configure_logging
from ai_novel_studio.ui.i18n import language_manager
from ai_novel_studio.ui.main_window import MainWindow
from ai_novel_studio.ui.pages.language_dialog import LanguageSelectionDialog


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("AI Novel Studio")
    app.setOrganizationName("AI Novel Studio")
    return app


def configure_application_logging() -> None:
    data_dir = Path(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    )
    configure_logging(data_dir / "logs" / "app.log")


def main(argv: Sequence[str] | None = None) -> int:
    app = create_application(argv)
    manager = language_manager()
    if not manager.has_saved_language:
        dialog = LanguageSelectionDialog(manager)
        if dialog.exec() != LanguageSelectionDialog.DialogCode.Accepted:
            return 0
    manager.install(app)
    configure_application_logging()
    window = MainWindow()
    window.show()
    return app.exec()
