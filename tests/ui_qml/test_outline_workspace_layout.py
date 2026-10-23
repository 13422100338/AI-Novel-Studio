import hashlib

import pytest
from PySide6.QtCore import Q_ARG, QCoreApplication, QEvent, QMetaObject, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.outline_repository import OutlineRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade

from .test_outline_page import _find


@pytest.fixture
def workspace(tmp_path, qtbot):
    project = ProjectRepository.create(tmp_path / "novel", "前端工作区验证")
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(project.list_volumes()[0].id, "旧信", "1", "正式原文一。")
    second = chapters.create_chapter(project.list_volumes()[0].id, "钟声", "2", "正式原文二。")
    source = (
        "# 全书\n\n## 第一卷\n\n### 事件一\n\n**目标。 **收到旧信。\n\n"
        "| 人物 | 动机 |\n| --- | --- |\n| 林默 | 返乡 |\n\n### 事件二\n\n钟声响起。\n"
    )
    OutlineRepository(project).create("全书大纲", source)
    facade = MockNovelStudioFacade()
    assert facade.openProject(str(project.layout.root)) == ""
    outline = facade.property("outline")
    line = next(h["line"] for h in outline.state["headings"] if h["title"] == "事件一")
    assert outline.insertChapterLink(first.id, line)
    line = next(h["line"] for h in outline.state["headings"] if h["title"] == "事件二")
    assert outline.insertChapterLink(second.id, line)
    facade.setActiveNav("outline")
    facade.setReduceMotion(True)
    facade.toggleAiDrawer(True)
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda values: warnings.extend(v.toString() for v in values))
    _, theme = register_frontend_types(engine, facade)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    yield project, facade, outline, window, first, second, warnings
    facade.closeProject()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_title_bar_matches_footer_and_document_modes_are_top_level(workspace):
    _, facade, _, window, _, _, _ = workspace
    assert window.flags() & Qt.WindowType.FramelessWindowHint
    assert _find(window.contentItem(), "glassTitleBar").property("visible")
    assert _find(window.contentItem(), "windowTitleSurface").property("color") == _find(
        window.contentItem(), "windowStatusSurface"
    ).property("color")
    assert _find(window.contentItem(), "workspaceModeSwitch") is not None
    assert _find(window.contentItem(), "nav-writing") is None
    assert _find(window.contentItem(), "nav-outline") is None
    button = _find(window.contentItem(), "mode-writing")
    QMetaObject.invokeMethod(button, "clicked")
    assert facade.activeNav == "writing"
    assert _find(window.contentItem(), "chapterList").property("visible")
    QMetaObject.invokeMethod(_find(window.contentItem(), "mode-outline"), "clicked")
    assert facade.activeNav == "outline"
    assert _find(window.contentItem(), "outlineNavigator").property("visible")
    assert not _find(window.contentItem(), "chapterList").property("visible")


@pytest.mark.parametrize("sidebar_open", [False, True])
@pytest.mark.parametrize("dock_open", [False, True])
def test_document_mode_buttons_stay_fixed_when_switching_pages(
    workspace, qtbot, sidebar_open, dock_open
):
    _, facade, _, window, _, _, warnings = workspace
    window.setProperty("sidebarVisible", sidebar_open)
    facade.toggleAiDrawer(dock_open)
    facade.setActiveNav("writing")
    qtbot.wait(80)
    buttons = [
        _find(window.contentItem(), "mode-" + name) for name in ("writing", "outline", "notes")
    ]
    centers = [button.mapToScene(button.boundingRect().center()) for button in buttons]
    for name in ("outline", "notes", "writing", "outline"):
        facade.setActiveNav(name)
        qtbot.wait(60)
        for button, center in zip(buttons, centers, strict=True):
            actual = button.mapToScene(button.boundingRect().center())
            assert actual.x() == pytest.approx(center.x(), abs=1)
            assert actual.y() == pytest.approx(center.y(), abs=1)
    assert not warnings


def test_long_outline_has_a_visible_scrollbar_that_drags_the_document(workspace, qtbot):
    _, _, outline, window, _, _, warnings = workspace
    outline.edit(
        "# 全书\n\n" + "\n\n".join(f"## 事件 {i}\n\n" + "林默收到旧信。" * 20 for i in range(40))
    )
    assert outline.flush()
    qtbot.wait(150)
    bar = _find(window.contentItem(), "outlineReaderScrollBar")
    assert bar is not None and bar.isVisible()
    assert bar.width() >= 10 and bar.height() > 100
    thumb = bar.property("contentItem")
    reader = _find(window.contentItem(), "outlineReadView")
    original_y = reader.mapToScene(QPointF(0, 0)).y()
    assert thumb.height() >= 32
    start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
    end = start + QPoint(0, int(bar.height() * 0.6))
    QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(window, end, delay=20)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    qtbot.wait(50)
    assert bar.property("position") > 0.1
    expression = QQmlExpression(qmlContext(reader), reader, "readerScroll.contentItem.contentY")
    offset = expression.evaluate()[0]
    assert offset > 100
    assert reader.mapToScene(QPointF(0, 0)).y() <= original_y - offset + 3
    assert not outline.state["dirty"]
    assert not warnings


@pytest.mark.parametrize("source_mode", [False, True])
def test_outline_scrolls_from_wheel_events_over_the_document(workspace, qtbot, source_mode):
    project, _, outline, window, _, _, warnings = workspace
    outline.edit(
        "# 滚轮验证\n\n"
        + "\n\n".join(
            f"## 事件 {index}\n\n" + "人物收到旧信，前往钟楼核对线索。" * 25
            for index in range(30)
        )
    )
    assert outline.flush()
    if source_mode:
        QMetaObject.invokeMethod(_find(window.contentItem(), "outlineSourceToggle"), "clicked")
    reader = _find(window.contentItem(), "outlineReadView")
    scroll = "sourceScroll" if source_mode else "readerScroll"

    def evaluate(script):
        expression = QQmlExpression(qmlContext(reader), reader, script)
        value, _ = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value

    qtbot.wait(120)
    window.requestActivate()
    QTest.qWaitForWindowActive(window, 1000)
    evaluate(f"{scroll}.contentItem.contentY = 0")
    position = evaluate(f"{scroll}.mapToItem(null, {scroll}.width / 2, {scroll}.height / 2)")
    text_item = _find(window.contentItem(), "outlineEditor") if source_mode else reader
    original_y = text_item.mapToScene(QPointF(0, 0)).y()
    QTest.mouseMove(window, position.toPoint())
    for _ in range(4):
        QTest.wheelEvent(window, position, QPoint(0, -120))
        qtbot.wait(40)
    down = evaluate(f"{scroll}.contentItem.contentY")
    assert down > 50, "The document must receive normal wheel scrolling"
    assert text_item.mapToScene(QPointF(0, 0)).y() <= original_y - down + 1
    for _ in range(4):
        QTest.wheelEvent(window, position, QPoint(0, 120))
        qtbot.wait(40)
    assert evaluate(f"{scroll}.contentItem.contentY") < down
    saved = OutlineRepository(project).read(outline.state["currentId"])
    assert saved.content == outline.state["text"]
    assert not outline.state["dirty"]
    assert not warnings


def test_paragraphs_are_repainted_after_scrolling_through_long_tables(workspace, qtbot):
    project, _, outline, window, _, _, warnings = workspace
    source = "# 长大纲滚动验证\n\n" + "开篇段落必须一直可见。" * 45 + "\n\n"
    for index in range(45):
        source += f"## 事件 {index}\n\n" + "这是表格之前的剧情段落，返回时不应消失。" * 18 + "\n\n"
        source += "| 人物 | 目标 | 场景细节 |\n| --- | --- | --- |\n"
        source += "".join(
            f"| 人物 {row} | 寻找旧信 | " + "钟声传来，人物停在街口。" * 5 + " |\n"
            for row in range(10)
        )
        source += "\n表格结束后继续保留普通文字。\n\n"
    outline.edit(source)
    assert outline.flush()
    path = project.layout.root / "outlines" / (outline.state["currentId"] + ".md")
    original = path.read_bytes()
    reader = _find(window.contentItem(), "outlineReadView")

    def evaluate(script):
        expression = QQmlExpression(qmlContext(reader), reader, script)
        value, _ = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value

    def visible_ink():
        image = window.grabWindow()
        origin = evaluate("readerScroll.mapToItem(null, 0, 0)")
        ratio = image.devicePixelRatio()
        image = image.copy(
            int(origin.x() * ratio),
            int(origin.y() * ratio),
            int((evaluate("readerScroll.width") - 20) * ratio),
            int((evaluate("readerScroll.height") - 10) * ratio),
        )
        image = image.scaled(400, 300).convertToFormat(QImage.Format.Format_Grayscale8)
        return sum(value < 170 for value in bytes(image.constBits()))

    qtbot.wait(150)
    evaluate("readerScroll.contentItem.contentY = 0")
    qtbot.wait(30)
    before = visible_ink()
    assert before > 100
    original_y = reader.mapToScene(QPointF(0, 0)).y()
    maximum = evaluate("readerScroll.contentItem.contentHeight - readerScroll.contentItem.height")
    # Exercise adjacent viewports across multiple table boundaries, in both
    # directions. Text still being present in the document is not proof that
    # Qt has recreated its visible paragraph nodes.
    offsets = list(range(0, int(min(20_000, maximum)), 420))
    for offset in offsets + list(reversed(offsets)):
        evaluate(f"readerScroll.contentItem.contentY = {offset}")
        qtbot.wait(25)
        assert not window.grabWindow().isNull()
        actual = evaluate("readerScroll.contentItem.contentY")
        assert abs(actual - offset) < 2
        assert abs(reader.mapToScene(QPointF(0, 0)).y() + actual - original_y) < 2
    qtbot.wait(60)
    assert visible_ink() >= before * 0.9
    assert path.read_bytes() == original
    assert not outline.state["dirty"]
    assert not warnings


def test_outline_opens_as_rendered_markdown_and_source_editing_preserves_original(workspace, qtbot):
    project, _, outline, window, _, _, warnings = workspace
    path = project.layout.root / "outlines" / (outline.state["currentId"] + ".md")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    reader = _find(window.contentItem(), "outlineReadView")
    assert reader is not None and reader.property("visible")
    assert "<table" in reader.property("text")
    qtbot.wait(1050)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not outline.state["dirty"]
    QMetaObject.invokeMethod(_find(window.contentItem(), "outlineSourceToggle"), "clicked")
    editor = _find(window.contentItem(), "outlineEditor")
    assert editor.property("visible")
    editor.setProperty("text", editor.property("text").replace("收到旧信", "读完旧信"))
    assert outline.state["dirty"]
    QMetaObject.invokeMethod(_find(window.contentItem(), "outlineSaveButton"), "clicked")
    assert "读完旧信" in OutlineRepository(project).read(outline.state["currentId"]).content
    assert not [w for w in warnings if "Outline" in w or "Workspace" in w]


@pytest.mark.parametrize("long_outline", [False, True])
def test_outline_remains_readable_after_visiting_notes(workspace, qtbot, long_outline):
    project, facade, outline, window, _, _, warnings = workspace
    assert facade.notes.createNote("场景细纲", "OUTLINE")
    facade.notes.edit(
        "# 钟楼会面\n\n**视角**：林默。\n\n| 节拍 | 行动 |\n| --- | --- |\n| 转折 | 钟声响起 |"
    )
    assert facade.notes.flush()
    if long_outline:
        outline.edit(
            "# 全书\n\n"
            + "\n\n".join(
                f"## 事件 {index}\n\n" + "林默收到旧信，决定查明真相。" * 30 for index in range(50)
            )
        )
        assert outline.flush()
    reader = _find(window.contentItem(), "outlineReadView")
    qtbot.wait(150)
    if long_outline:
        outline.selectHeading(outline.state["headings"][-1]["line"])
        qtbot.wait(150)
    path = project.layout.root / "outlines" / (outline.state["currentId"] + ".md")
    original = path.read_bytes()
    rendered = reader.property("text")

    def evaluate(source):
        expression = QQmlExpression(qmlContext(reader), reader, source)
        value, _ = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value

    if long_outline:
        evaluate("readerScroll.contentItem.contentY -= 110")
    before_y = evaluate("readerScroll.contentItem.contentY")
    for _ in range(3):
        QMetaObject.invokeMethod(_find(window.contentItem(), "mode-notes"), "clicked")
        qtbot.wait(100)
        QMetaObject.invokeMethod(_find(window.contentItem(), "mode-outline"), "clicked")
        qtbot.wait(150)
        assert reader.isVisible()
        assert reader.width() > 100
        assert reader.height() > 0
        assert reader.property("text") == rendered
        assert evaluate("readerScroll.contentItem.contentY") == pytest.approx(before_y, abs=2)
    # A page hidden while the window is resized must restore a valid reading
    # viewport once it becomes visible again.
    for width in (1100, 1920, 1440):
        facade.setActiveNav("notes")
        window.setWidth(width)
        qtbot.wait(100)
        facade.setActiveNav("outline")
        qtbot.wait(150)
        assert evaluate(
            "readerScroll.contentItem.contentY <= "
            "Math.max(0, readerScroll.contentItem.contentHeight "
            "- readerScroll.contentItem.height) + 2"
        )
    assert path.read_bytes() == original
    assert not warnings


def test_returning_to_outline_restores_a_discarded_display_document(workspace, qtbot):
    project, facade, outline, window, _, _, warnings = workspace
    reader = _find(window.contentItem(), "outlineReadView")
    qtbot.wait(100)
    rendered = reader.property("text")
    path = project.layout.root / "outlines" / (outline.state["currentId"] + ".md")
    original = path.read_bytes()
    facade.setActiveNav("notes")
    qtbot.wait(50)
    # Discard only the cached read-only display, never the author source. This
    # reproduces a hidden reader returning with an empty document.
    assert QMetaObject.invokeMethod(reader, "clear")
    assert reader.property("text") != rendered
    facade.setActiveNav("outline")
    qtbot.waitUntil(lambda: reader.property("text") == rendered)
    assert reader.isVisible()
    assert not outline.state["dirty"]
    assert path.read_bytes() == original
    # Re-entering must retain the live source binding for later edits, too.
    outline.edit(outline.state["text"] + "\n\n后续事件：归航。")
    qtbot.waitUntil(lambda: "后续事件" in reader.property("text"))
    assert not warnings


def test_event_chapter_references_are_inside_the_outline_page(workspace, qtbot):
    _, facade, outline, window, first, second, _ = workspace
    one = next(h for h in outline.state["headings"] if h["title"] == "事件一")
    outline.selectHeading(one["line"])
    qtbot.waitUntil(lambda: _find(window.contentItem(), "outline-linked-" + first.id) is not None)
    assert [c["chapterId"] for c in outline.navigation["chapters"]] == [first.id]
    two = next(h for h in outline.state["headings"] if h["title"] == "事件二")
    outline.selectHeading(two["line"])
    qtbot.waitUntil(lambda: _find(window.contentItem(), "outline-linked-" + second.id) is not None)
    assert [c["chapterId"] for c in outline.navigation["chapters"]] == [second.id]
    QMetaObject.invokeMethod(_find(window.contentItem(), "outline-linked-" + second.id), "clicked")
    assert facade.activeNav == "writing"
    assert facade.currentChapterId == second.id


def test_clicking_numbered_outline_titles_reveals_their_actual_text(workspace, qtbot):
    project, _, outline, window, _, _, warnings = workspace
    outline.edit(
        "# 总览😀\n\n" + "开篇介绍。" * 160 + "\n\n"
        "### 1. 一句话故事\n\n" + "第一处事件的正文。" * 100 + "\n\n"
        "| 人物 | 目标 |\n| --- | --- |\n| 主角 | 返回 |\n\n"
        "### 2. **完整故事**\n\n" + "第二处事件的正文。" * 100 + "\n\n"
        "### 3. 转折\n\n" + "保留足够的结尾。" * 120
    )
    assert outline.flush()
    path = project.layout.root / "outlines" / (outline.state["currentId"] + ".md")
    original = path.read_bytes()
    qtbot.wait(180)
    reader = _find(window.contentItem(), "outlineReadView")
    document = QTextDocument()
    document.setHtml(reader.property("text"))
    window.requestActivate()
    QTest.qWaitForWindowActive(window, 1000)
    for title in ("2. 完整故事", "1. 一句话故事", "3. 转折"):
        heading = next(
            h for h in outline.state["headings"] if h["title"].replace("**", "") == title
        )
        button = _find(window.contentItem(), "outline-nav-heading-" + str(heading["line"]))
        assert button is not None and button.isVisible()
        QTest.mouseClick(
            window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            button.mapToScene(button.boundingRect().center()).toPoint(),
        )
        qtbot.waitUntil(
            lambda expected=heading["line"]: outline.navigation["headingLine"] == expected
        )
        qtbot.wait(80)
        cursor = document.find(title)
        assert not cursor.isNull()
        expression = QQmlExpression(
            qmlContext(reader), reader,
            f"reader.positionToRectangle({cursor.selectionStart()}).y"
            " + reader.mapToItem(null, 0, 0).y"
            " - readerScroll.mapToItem(null, 0, 0).y",
        )
        actual_y, _ = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        assert 0 <= actual_y <= 60, f"Clicked {title}, but the target is {actual_y}px offscreen"
    assert path.read_bytes() == original
    assert not warnings


def test_heading_note_link_can_be_inserted_and_opened_without_attaching_it_to_writing(
    workspace, qtbot
):
    _, facade, outline, window, _, _, warnings = workspace
    assert facade.notes.createNote("事件一细纲", "OUTLINE")
    identity = facade.notes.state["currentId"]
    heading = next(h for h in outline.state["headings"] if h["title"] == "事件一")
    outline.selectHeading(heading["line"])
    page = _find(window.contentItem(), "outlinePage")
    assert QMetaObject.invokeMethod(page, "addReference", Q_ARG(str, "note"))
    qtbot.waitUntil(lambda: _find(window.contentItem(), "outlineReferenceConfirm") is not None)
    QMetaObject.invokeMethod(_find(window.contentItem(), "outlineReferenceConfirm"), "clicked")
    reader = _find(window.contentItem(), "outlineReadView")
    qtbot.waitUntil(lambda: f"novel://note/{identity}" in reader.property("text"))
    assert _find(window.contentItem(), "outlineChapterRail") is None
    overlay = _find(window.contentItem(), "outlineReferenceOverlay")
    assert overlay.isVisible()
    assert QMetaObject.invokeMethod(reader, "linkActivated", Q_ARG(str, f"novel://note/{identity}"))
    assert facade.activeNav == "notes"
    assert facade.notes.current_selection.mode == "NONE"
    assert not warnings


def test_tall_margin_references_keep_their_scroll_position_when_visiting_notes(workspace, qtbot):
    project, facade, outline, window, _, _, warnings = workspace
    outline.edit("## 当前事件\n短正文。\n")
    assert outline.flush()
    chapters = ChapterRepository(project)
    for index in range(8):
        chapter = chapters.create_chapter(
            project.list_volumes()[0].id, "很长的章节名称" * 8, str(index), ""
        )
        assert outline.insertChapterLink(chapter.id, 1)
    qtbot.wait(180)
    reader = _find(window.contentItem(), "outlineReadView")
    expression = QQmlExpression(
        qmlContext(reader),
        reader,
        "readerScroll.contentItem.contentY = "
        "readerScroll.contentItem.contentHeight - readerScroll.contentItem.height",
    )
    before, _ = expression.evaluate()
    assert before > 100
    facade.setActiveNav("notes")
    qtbot.wait(50)
    facade.setActiveNav("outline")
    qtbot.wait(150)
    actual = QQmlExpression(
        qmlContext(reader), reader, "readerScroll.contentItem.contentY"
    ).evaluate()[0]
    assert actual == pytest.approx(before, abs=2)
    assert not warnings


def test_event_chapters_follow_manuscript_order_after_adding_another_link(workspace, qtbot):
    _, _, outline, _, first, second, _ = workspace
    one = next(h for h in outline.state["headings"] if h["title"] == "事件一")
    outline.selectHeading(one["line"])
    assert outline.insertChapterLink(second.id, one["line"])
    # Registry insertion/UUID order is independent of formal chapter ordering.
    outline._state["links"].sort(key=lambda link: link["chapterId"] == first.id)
    outline.changed.emit()
    qtbot.wait(50)
    assert outline.navigation["headingTitle"] == "事件一"
    assert [c["chapterId"] for c in outline.navigation["chapters"]] == [first.id, second.id]


def test_empty_outline_workspace_still_exposes_create_and_import(workspace, tmp_path):
    _, facade, _, window, _, _, _ = workspace
    facade.closeProject()
    project = ProjectRepository.create(tmp_path / "empty", "空白项目")
    assert facade.openProject(str(project.layout.root)) == ""
    facade.setActiveNav("outline")
    window.setWidth(1100)
    assert _find(window.contentItem(), "outlineNewButton").property("visible")
    assert _find(window.contentItem(), "outlineImportButton").property("visible")


@pytest.mark.parametrize("width", [1100, 1440, 1920])
def test_outline_columns_fit_with_readable_center_at_supported_widths(workspace, qtbot, width):
    _, _, _, window, _, _, _ = workspace
    window.setWidth(width)
    qtbot.wait(60)
    center = _find(window.contentItem(), "workspaceHost")
    rail = _find(window.contentItem(), "outlineChapterRail")
    dock = _find(window.contentItem(), "agentDock")
    assert center.width() >= 280
    assert rail is None
    assert center.x() + center.width() <= dock.x()
    assert dock.x() + dock.width() <= dock.parentItem().width()
    dock.setProperty("currentWidth", 9999)
    qtbot.wait(40)
    assert center.width() >= 280
    assert dock.x() + dock.width() <= dock.parentItem().width()
