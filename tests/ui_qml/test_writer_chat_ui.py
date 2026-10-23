from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QMetaObject

from ai_novel_studio.ui_qml.bridge.codex_session_bridge import CodexSessionController
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade

from .test_codex_session_bridge import FakeSession
from .test_qml_shell import _delete_active_engines as _delete_active_engines
from .test_qml_shell import _find_quick_item, _load_engine

_FONTS_READY = False


def make_ui(qtbot, *, demo=False):
    from PySide6.QtGui import QFontDatabase

    # Offscreen Qt may not discover Windows fonts on its own. Use the same
    # installed fonts as the desktop for geometry and image verification.
    global _FONTS_READY
    if not _FONTS_READY:
        for name in ("msyh.ttc", "segoeui.ttf", "simsun.ttc"):
            path = Path("C:/Windows/Fonts") / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
        _FONTS_READY = True
    session = FakeSession()
    messages = []
    send = session.send

    def capture(message, callback, **kwargs):
        messages.append(message)
        return send(message, callback, **kwargs)

    session.send = capture
    controller = CodexSessionController(session_factory=lambda _project: session)
    facade = MockNovelStudioFacade(codex_controller=controller, demo_mode=demo)
    controller.bind_project(str(uuid4()))
    facade.toggleAiDrawer(True)
    engine, facade, theme = _load_engine(qtbot, facade)
    return engine, facade, theme, controller, messages


def command_item(window, name):
    menu = window.findChild(object, "writingCommandMenu")
    return _find_quick_item(menu.property("contentItem"), name)


def test_writer_shortcut_sends_chat_and_never_opens_a_generation_dialog(qtbot):
    engine, facade, theme, controller, messages = make_ui(qtbot)
    window = engine.rootObjects()[0]
    assert window.findChild(object, "chapterMenuButton") is None
    assert window.findChild(object, "generationConfigDialog") is None
    QMetaObject.invokeMethod(window.findChild(object, "writingMenuButton"), "clicked")
    qtbot.waitUntil(lambda: command_item(window, "writerQuickButton") is not None)
    QMetaObject.invokeMethod(command_item(window, "writerQuickButton"), "clicked")
    qtbot.waitUntil(lambda: len(messages) == 1)
    assert "独立正文写作模型" in messages[0]
    assert messages[0].startswith("$novel-edit ")
    assert facade.property("draftStatus") == "IDLE"
    user = next(row for row in controller._model.items() if row.kind == "user_text")
    assert user.text == "/生成草稿"


def test_polish_without_a_quote_does_not_fall_back_to_whole_chapter(qtbot):
    engine, facade, theme, controller, messages = make_ui(qtbot, demo=True)
    facade.startAssistantChat("/润色")
    assert messages == []
    assert any("请先选择" in row.text for row in controller._model.items())


@pytest.mark.parametrize("width", [1100, 1440])
def test_writer_card_updates_in_place_and_expands_inside_chat(qtbot, width):
    engine, facade, theme, controller, messages = make_ui(qtbot)
    window = engine.rootObjects()[0]
    window.setWidth(width)
    event = dict(
        id="writer-layout",
        status="GENERATING",
        model="independent-writer",
        word_count=120,
        target_words=800,
        message="正在接收正文",
        draft_text="",
    )
    controller._on_writer_event(controller._epoch, event)
    qtbot.waitUntil(lambda: _find_quick_item(window.contentItem(), "writerTaskCard") is not None)
    card = _find_quick_item(window.contentItem(), "writerTaskCard")
    qtbot.waitUntil(lambda: "independent-writer" in card.property("payloadJson"))
    assert card.property("busy") is True
    controller._on_writer_event(
        controller._epoch, {**event, "status": "COMPLETED", "draft_text": "候选正文。" * 400}
    )
    qtbot.waitUntil(lambda: card.property("state") == "COMPLETED")
    assert card.property("draftText") == "候选正文。" * 400
    before = card.property("implicitHeight")
    card.setProperty("expanded", True)
    qtbot.waitUntil(lambda: card.property("implicitHeight") > before)
    timeline = window.findChild(object, "agentTimeline")
    assert card.property("width") <= timeline.property("width")
    assert not card.property("busy")


def test_model_and_session_controls_can_be_expanded_in_sidebar(qtbot):
    engine, facade, theme, controller, messages = make_ui(qtbot)
    window = engine.rootObjects()[0]
    panel = window.findChild(object, "creativeAgentPanel")
    assert not panel.property("controlsExpanded")
    QMetaObject.invokeMethod(window.findChild(object, "assistantControlsButton"), "clicked")
    assert panel.property("controlsExpanded")
    qtbot.waitUntil(lambda: bool(window.findChild(object, "codexSessionCombo").property("visible")))
    button = window.findChild(object, "assistantControlsButton")
    assert "收起" in button.property("text")
    QMetaObject.invokeMethod(button, "clicked")
    qtbot.waitUntil(lambda: not window.findChild(object, "codexSessionCombo").property("visible"))
    assert not panel.property("controlsExpanded")


def test_slash_palette_filters_and_inserts_command_without_sending(qtbot):
    engine, facade, theme, controller, messages = make_ui(qtbot)
    window = engine.rootObjects()[0]
    composer = window.findChild(object, "agentComposer")
    input_item = window.findChild(object, "agentComposerInput")
    menu = window.findChild(object, "writingCommandMenu")
    input_item.setProperty("text", "/pol")
    qtbot.waitUntil(lambda: menu.property("visible"))
    choices = composer.property("filteredCommands").toVariant()
    assert [item["name"] for item in choices] == ["润色"]
    button = command_item(window, "writingCommandpolish")
    QMetaObject.invokeMethod(button, "clicked")
    assert input_item.property("text") == "/润色 "
    assert messages == []
    assert not menu.property("visible")
    input_item.setProperty("text", "/model")
    QMetaObject.invokeMethod(composer, "submit")
    qtbot.waitUntil(
        lambda: window.findChild(object, "composerCodexModelComboPopup").property("visible")
    )
    assert not window.findChild(object, "creativeAgentPanel").property("controlsExpanded")


def test_slash_palette_supports_keyboard_selection(qtbot):
    from PySide6.QtCore import Qt

    engine, facade, theme, controller, messages = make_ui(qtbot)
    window = engine.rootObjects()[0]
    window.requestActivate()
    qtbot.waitUntil(window.isActive)
    input_item = window.findChild(object, "agentComposerInput")
    input_item.forceActiveFocus()
    input_item.setProperty("text", "/")
    qtbot.waitUntil(lambda: window.findChild(object, "writingCommandMenu").property("opened"))
    qtbot.waitUntil(lambda: input_item.property("activeFocus"))
    qtbot.keyClick(window, Qt.Key_Down)
    assert window.findChild(object, "agentComposer").property("commandIndex") == 1
    qtbot.keyClick(window, Qt.Key_Return)
    assert input_item.property("text") == "/润色 "
    assert messages == []
    input_item.setProperty("text", "第一行\n第二行")
    input_item.setProperty("cursorPosition", 6)
    qtbot.keyClick(window, Qt.Key_Up)
    assert input_item.property("cursorPosition") == 2
    qtbot.keyClick(window, Qt.Key_Down)
    assert input_item.property("cursorPosition") == 6
    input_item.setProperty("text", "/")
    input_item.setProperty("cursorPosition", 1)
    qtbot.waitUntil(lambda: window.findChild(object, "writingCommandMenu").property("opened"))
    qtbot.keyClick(window, Qt.Key_Return, Qt.ShiftModifier)
    assert input_item.property("text") == "/\n"


@pytest.mark.parametrize("width", [1100, 1440])
def test_sidebar_keeps_chat_space_and_collapse_hit_target(qtbot, tmp_path, width):
    import json

    from PySide6.QtCore import QPointF, Qt

    engine, facade, theme, controller, messages = make_ui(qtbot, demo=True)
    window = engine.rootObjects()[0]
    window.setWidth(width)
    window.setHeight(840)
    panel = window.findChild(object, "creativeAgentPanel")
    timeline = window.findChild(object, "agentTimeline")
    qtbot.waitUntil(lambda: timeline.property("height") > 0.6 * panel.property("height"))
    button = window.findChild(object, "assistantControlsButton")

    def click_control():
        point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        qtbot.mouseClick(window, Qt.LeftButton, pos=point)

    click_control()
    qtbot.waitUntil(lambda: panel.property("controlsExpanded"))
    click_control()
    qtbot.waitUntil(lambda: not panel.property("controlsExpanded"))
    facade.setChatSelectionJson(
        json.dumps(
            dict(
                chapter_id=facade.currentChapterId,
                base_revision=facade.currentRevision,
                content=facade.currentChapterBody,
                selection="清晨的雾港还浸在灰蓝色的光线里。",
            )
        )
    )
    facade.startAssistantChat("测试侧栏消息")
    qtbot.waitUntil(lambda: not controller.is_busy)
    assert window.grabWindow().save(str(tmp_path / f"sidebar-{width}.png"))
    QMetaObject.invokeMethod(window.findChild(object, "writingMenuButton"), "clicked")
    qtbot.waitUntil(lambda: window.findChild(object, "writingCommandMenu").property("opened"))
    assert window.grabWindow().save(str(tmp_path / f"writing-menu-{width}.png"))
