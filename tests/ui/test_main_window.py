from pytestqt.qtbot import QtBot

from ai_novel_studio.ui.main_window import MainWindow


def test_main_window_has_public_product_identity(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.windowTitle() == "AI Novel Studio"
    assert window.minimumWidth() >= 960
    assert window.minimumHeight() >= 640
