import pytest
from PySide6.QtCore import QMetaObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem

from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade


def _find(root: QQuickItem, name: str) -> QQuickItem | None:
    if root.objectName() == name:
        return root
    for child in root.childItems():
        found = _find(child, name)
        if found is not None:
            return found
    return None


@pytest.fixture
def panel(tmp_path, qtbot):
    project = ProjectRepository.create(tmp_path / "novel", "章节关联测试")
    repository = ChapterRepository(project)
    first = repository.create_chapter(
        project.list_volumes()[0].id, "铺垫一", "1", "第一章正式正文。"
    )
    second = repository.create_chapter(
        project.list_volumes()[0].id, "铺垫二", "2", "第二章正式正文。"
    )
    facade = MockNovelStudioFacade()
    assert facade.openProject(str(project.layout.root)) == ""
    bridge = facade.property("outline")
    assert bridge.newDocument("完整大纲")
    bridge.edit("# 全书\n\n25. 政变\n")
    assert bridge.flush()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
    _, _theme = register_frontend_types(engine, facade)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    assert engine.rootObjects()
    window = engine.rootObjects()[0]
    facade.setActiveNav("outline")
    editor = _find(window.contentItem(), "outlineEditor")
    editor.setProperty("cursorPosition", bridge.state["text"].index("25."))
    QMetaObject.invokeMethod(_find(window.contentItem(), "outlineLinksButton"), "clicked")
    qtbot.waitUntil(lambda: _find(window.contentItem(), "outlineLinkInsertButton") is not None)
    yield project, first, second, facade, bridge, window, warnings
    facade.closeProject()
    engine.deleteLater()
    qtbot.wait(30)


def test_actual_panel_inserts_and_confirms_selected_chapter(panel, qtbot):
    project, first, second, facade, bridge, window, warnings = panel
    choice = _find(window.contentItem(), "outlineLinkChapterChoice")
    choice.setProperty("currentIndex", 1)
    QMetaObject.invokeMethod(_find(window.contentItem(), "outlineLinkInsertButton"), "clicked")
    qtbot.waitUntil(lambda: len(bridge.state["links"]) == 1)
    link = bridge.state["links"][0]
    assert link["chapterId"] == second.id
    check = _find(window.contentItem(), "outline-link-select-" + link["id"])
    assert check is not None
    check.setProperty("checked", True)
    QMetaObject.invokeMethod(check, "clicked")
    confirm = _find(window.contentItem(), "outlineLinksConfirmButton")
    assert confirm.property("enabled")
    QMetaObject.invokeMethod(confirm, "clicked")
    qtbot.waitUntil(lambda: bridge.state["links"][0]["status"] == "CONFIRMED")
    assert bridge.state["pendingLinkCount"] == 0
    bridge.edit(bridge.state["text"] + "新前提\n")
    assert not confirm.property("enabled")
    assert bridge.flush()
    assert bridge.state["links"][0]["status"] == "PENDING"
    assert ChapterRepository(project).read_content_exact(second.id) == "第二章正式正文。"
    assert not [w for w in warnings if "OutlineLinksPanel.qml" in w or "OutlinePage.qml" in w]


def test_open_link_uses_tree_row_mapping_and_closes_panel(panel, qtbot):
    project, first, second, facade, bridge, window, warnings = panel
    assert facade.property("currentChapterId") == first.id
    assert bridge.insertChapterLink(second.id, 3)
    link_id = bridge.state["links"][0]["id"]
    qtbot.waitUntil(lambda: _find(window.contentItem(), "outline-link-open-" + link_id) is not None)
    QMetaObject.invokeMethod(_find(window.contentItem(), "outline-link-open-" + link_id), "clicked")
    assert facade.property("currentChapterId") == second.id
    assert facade.property("activeNav") == "writing"
    assert not window.findChild(object, "outlineLinksPanel").property("visible")


def test_failed_prose_save_blocks_opening_linked_chapter(panel, monkeypatch):
    project, first, second, facade, bridge, window, warnings = panel
    facade.editorTextChanged("未保存的正文编辑")
    monkeypatch.setattr(facade, "requestSave", lambda: None)
    assert not bridge.openLinkedChapter(second.id)
    assert facade.property("currentChapterId") == first.id
    assert facade.property("currentChapterBody") == "未保存的正文编辑"
    assert ChapterRepository(project).read_content_exact(first.id) == "第一章正式正文。"
