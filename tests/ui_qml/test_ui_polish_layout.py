import pytest
from PySide6.QtCore import QPointF, Qt

from .test_qml_shell import _find_quick_item, _load_engine


@pytest.mark.parametrize("width", [1100, 1440])
def test_chapter_actions_stay_inside_sidebar_at_supported_widths(qtbot, width):
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    window.setWidth(width)
    window.setHeight(720)
    facade.toggleAiDrawer(True)
    qtbot.wait(250)
    sidebar = _find_quick_item(window.contentItem(), "sidebarHost")
    actions = [
        _find_quick_item(window.contentItem(), name)
        for name in (
            "newVolumeButton",
            "newChapterButton",
            "importManuscriptButton",
            "deleteEmptyChaptersButton",
        )
    ]
    assert all(action is not None for action in actions)
    for action in actions:
        position = action.mapToItem(sidebar, QPointF(0, 0))
        assert position.x() >= 0
        assert position.x() + action.width() <= sidebar.width() + 1
        assert position.y() + action.height() <= sidebar.height() + 1
    assert (
        actions[2].mapToItem(sidebar, QPointF(0, 0)).y()
        > actions[0].mapToItem(sidebar, QPointF(0, 0)).y()
    )


def test_shared_button_supports_keyboard_activation(qtbot):
    engine, facade, theme = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    button = _find_quick_item(window.contentItem(), "sidebarToggle")
    button.forceActiveFocus()
    qtbot.waitUntil(lambda: bool(button.property("activeFocus")))
    assert window.property("sidebarVisible") is True
    qtbot.keyClick(window, Qt.Key_Space)
    qtbot.wait(20)
    assert window.property("sidebarVisible") is False
