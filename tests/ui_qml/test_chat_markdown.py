from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject
from PySide6.QtGui import QTextDocument

from ai_novel_studio.ui_qml.bridge.chat_markdown import ChatMarkdown
from ai_novel_studio.ui_qml.bridge.dtos import AgentTimelineItemDto
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade

from .test_agent_timeline_geometry import _find_all, _load_panel


def displayed_text(body):
    return QMetaObject.invokeMethod(
        body, "getText", Q_RETURN_ARG(str), Q_ARG(int, 0), Q_ARG(int, body.property("length"))
    )


def test_markdown_formats_headings_bold_lists_tables_and_code(qtbot):
    markup = ChatMarkdown()
    html = markup.render(
        "# 章节分析\n\n**重点**与`代码`\n\n- 第一项\n- 第二项\n\n"
        '| 人物 | 目标 |\n| --- | --- |\n| 主角 | 寻人 |\n\n```python\nprint("test")\n```'
    )
    doc = QTextDocument()
    doc.setHtml(html)
    plain = doc.toPlainText()
    assert "章节分析" in plain and "重点" in plain and 'print("test")' in plain
    assert "**" not in plain and "```" not in plain
    assert "<h1 " in html and "font-weight:700" in html and "<table " in html


def test_markdown_does_not_load_images_html_or_unsafe_links(qtbot):
    html = ChatMarkdown().render(
        '![秘密](file:///secret.png)\n\n<img src="https://external.test/a.png">\n\n'
        "[打开](file:///secret.txt) [脚本](javascript:alert(1))"
    )
    assert "<img " not in html
    assert 'href="file:' not in html and 'href="javascript:' not in html
    assert "&lt;img" in html


def test_assistant_markdown_and_literal_user_text_have_different_display(qtbot):
    facade = MockNovelStudioFacade()
    facade.property("agentTimeline").set_items(
        [
            AgentTimelineItemDto(id="a", kind="assistant_text", text="**重点**\n\n- 第一项"),
            AgentTimelineItemDto(id="u", kind="user_text", text="请保留 ** 这两个符号"),
        ]
    )
    engine, content, timeline, window = _load_panel(qtbot, facade)
    qtbot.waitUntil(lambda: len(_find_all(content, "agentMessageBody")) == 2)
    bodies = _find_all(content, "agentMessageBody")
    plain = [displayed_text(body) for body in bodies]
    assert any("重点" in text and "**" not in text for text in plain)
    assert any("请保留 ** 这两个符号" == text for text in plain), plain
    facade.property("agentTimeline").update_item("a", text="**重点**\n\n## 新标题\n\n第二段")
    qtbot.waitUntil(lambda: any("新标题" in displayed_text(body) for body in bodies))
