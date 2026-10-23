import pytest
from PySide6.QtCore import QMetaObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem

from ai_novel_studio.infrastructure.storage.outline_repository import OutlineRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade


def _find(root: QQuickItem, name: str) -> QQuickItem | None:
    if root.objectName() == name:
        return root
    for child in root.childItems():
        result = _find(child, name)
        if result is not None:
            return result
    return None


@pytest.fixture
def shell(tmp_path, qtbot):
    project = ProjectRepository.create(tmp_path / "novel", "雪花式创作测试")
    facade = MockNovelStudioFacade()
    assert facade.openProject(str(project.layout.root)) == ""
    bridge = facade.property("outline")
    assert bridge is not None
    assert bridge.newDocument("全书大纲")
    bridge.edit("# 全书概览\n\n第二部 政局\n\n25. 政变\n艾瑞克视角。\n")
    assert bridge.flush()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
    # Keep context QObjects alive through teardown.
    _, _theme = register_frontend_types(engine, facade)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    assert engine.rootObjects()
    facade.setActiveNav("outline")
    qtbot.waitUntil(lambda: facade.property("activeNav") == "outline")
    yield project, facade, bridge, engine.rootObjects()[0], warnings
    facade.closeProject()
    engine.deleteLater()
    qtbot.wait(30)


def test_outline_page_edits_and_saves_through_real_qml(shell, qtbot):
    project, facade, bridge, window, warnings = shell
    editor = _find(window.contentItem(), "outlineEditor")
    save = _find(window.contentItem(), "outlineSaveButton")
    assert editor is not None and save is not None
    QMetaObject.invokeMethod(_find(window.contentItem(), "outlineSourceToggle"), "clicked")
    assert editor.property("visible")
    editor.setProperty("text", editor.property("text").replace("艾瑞克视角", "艾瑞克的限知视角"))
    qtbot.waitUntil(lambda: bridge.state["dirty"])
    status = _find(window.contentItem(), "autoSaveStatusChip")
    assert status.property("value") == "等待保存"
    assert _find(window.contentItem(), "wordCountStatusChip").property("label") == "大纲"
    QMetaObject.invokeMethod(save, "clicked")
    qtbot.waitUntil(lambda: bridge.state["dirty"] is False)
    assert status.property("value") == "已保存"
    assert "艾瑞克的限知视角" in OutlineRepository(project).read(bridge.state["currentId"]).content
    assert not [w for w in warnings if "OutlinePage.qml" in w]


def test_loading_original_md_does_not_schedule_an_unrequested_save(shell, tmp_path, qtbot):
    project, facade, bridge, window, warnings = shell
    source = tmp_path / "original.md"
    raw = "\ufeff# 原文\r\n\r\n**原样保留**  \r\n[章节](../manuscript/x.md)\r\n"
    source.write_bytes(raw.encode())
    assert bridge.importFile(QUrl.fromLocalFile(str(source)))
    qtbot.wait(1100)
    snapshot = OutlineRepository(project).read(bridge.state["currentId"])
    assert snapshot.content == raw
    assert snapshot.version.revision == 1
    assert not bridge.state["dirty"]


def test_outline_conflict_blocks_project_close_and_navigation(shell, qtbot):
    project, facade, bridge, window, warnings = shell
    current = bridge.state["currentId"]
    bridge.edit("仍需保留的本地编辑")
    (project.layout.root / "outlines" / f"{current}.md").write_bytes("外部修改".encode())
    facade.setActiveNav("settings")
    assert facade.property("activeNav") == "outline"
    facade.closeProject()
    assert facade.property("projectSource") == "project"
    window.close()
    qtbot.wait(30)
    assert window.isVisible()
    assert bridge.state["text"] == "仍需保留的本地编辑"
    # Explicit fixture cleanup; the normal owner correctly refused the destructive switch.
    assert bridge.previewDisk()
    assert bridge.applyPreview()


def test_outline_navigation_is_a_visible_shell_entry(shell):
    project, facade, bridge, window, warnings = shell
    button = _find(window.contentItem(), "mode-outline")
    assert button is not None
    assert button.property("text") == "大纲"
    facade.setActiveNav("writing")
    QMetaObject.invokeMethod(button, "clicked")
    assert facade.property("activeNav") == "outline"


def test_outline_directory_can_navigate_to_a_numbered_event(shell, qtbot):
    project, facade, bridge, window, warnings = shell
    button = _find(window.contentItem(), "outlineContentsButton")
    assert button is not None
    QMetaObject.invokeMethod(button, "clicked")
    qtbot.waitUntil(lambda: _find(window.contentItem(), "outline-heading-5") is not None)
    event = _find(window.contentItem(), "outline-heading-5")
    QMetaObject.invokeMethod(event, "clicked")
    editor = _find(window.contentItem(), "outlineEditor")
    expected = next(item["position"] for item in bridge.state["headings"] if item["line"] == 5)
    assert editor.property("cursorPosition") == expected
    assert not [w for w in warnings if "OutlinePage.qml" in w]


def test_new_document_confirmation_works_in_the_actual_dialog(shell, qtbot):
    project, facade, bridge, window, warnings = shell
    before = len(bridge.state["documents"])
    button = _find(window.contentItem(), "outlineNewButton")
    QMetaObject.invokeMethod(button, "clicked")
    qtbot.waitUntil(lambda: _find(window.contentItem(), "outlineNewTitle") is not None)
    name = _find(window.contentItem(), "outlineNewTitle")
    name.setProperty("text", "第三部事件大纲")
    accept = _find(window.contentItem(), "outlineNewDialog-accept")
    assert accept is not None
    QMetaObject.invokeMethod(accept, "clicked")
    qtbot.waitUntil(lambda: bridge.state["title"] == "第三部事件大纲")
    assert len(bridge.state["documents"]) == before + 1
    assert not [w for w in warnings if "OutlinePage.qml" in w]
