from PySide6.QtGui import QTextDocument

from ai_novel_studio.core.outline_markdown import outline_headings
from ai_novel_studio.ui_qml.bridge.chat_markdown import ChatMarkdown


def render(source):
    from ai_novel_studio.ui_qml.bridge.outline_markdown_view import OutlineMarkdownView

    return OutlineMarkdownView().render(source, outline_headings(source), "#d8c9b7")


def plain(html):
    document = QTextDocument()
    document.setHtml(html)
    return document.toPlainText()


def test_outline_displays_headings_bold_lists_and_tables_without_source_markers(qtbot):
    source = (
        "# 全书\n\n## 事件 **旧信**\n\n- **目标**：寻找线索\n\n"
        "| 人物 | 动机 |\n| --- | --- |\n| 林默 | 返乡 |\n"
    )
    result = render(source)
    displayed = plain(result["html"])
    assert "<table" in result["html"]
    assert all(text in displayed for text in ("全书", "旧信", "目标", "林默", "返乡"))
    assert "##" not in displayed and "**" not in displayed and "| ---" not in displayed


def test_reader_does_not_truncate_long_outline(qtbot):
    source = "# 全书\n\n" + "甲" * 200_100 + "\n\nOUTLINE-LAST-MARKER"
    assert plain(render(source)["html"]).endswith("OUTLINE-LAST-MARKER")


def test_cjk_bold_with_space_before_closing_marker_is_displayed_cleanly(qtbot):
    source = "- **人物的相处。 **这里是说明。"
    assert "**" not in plain(render(source)["html"])
    assert "人物的相处。" in plain(ChatMarkdown().render(source))
    assert "**" not in plain(ChatMarkdown().render(source))
    assert "**" in plain(ChatMarkdown().literal(source))


def test_literal_code_and_escaped_markers_are_not_repaired(qtbot):
    source = "`**代码 **`\n\n```md\n**示例 **\n```\n\n\\*\\*原样\\*\\*"
    displayed = plain(render(source)["html"])
    assert "**代码 **" in displayed
    assert "**示例 **" in displayed
    assert "**原样**" in displayed


def test_rendering_cannot_load_local_or_remote_images_or_execute_html(qtbot):
    source = (
        "# 安全\n\n![x](file:///private.txt) ![y](https://example.com/a.png)\n\n"
        "[坏链接](javascript:alert) <script>window.bad=1</script>"
    )
    html = render(source)["html"]
    assert "<img" not in html
    assert 'href="file:' not in html and 'href="javascript:' not in html
    assert "<script>" not in html


def test_heading_positions_survive_tables_emoji_and_repeated_titles(qtbot):
    source = "# 全书😀\n\n## 同名\n\n| A | B |\n| --- | --- |\n| 甲 | 乙 |\n\n## 同名\n\n结尾。"
    result = render(source)
    positions = result["headings"]
    assert [item["line"] for item in positions] == [h["line"] for h in outline_headings(source)]
    assert [item["position"] for item in positions] == sorted(
        set(item["position"] for item in positions)
    )
    doc = QTextDocument()
    doc.setHtml(result["html"])
    assert doc.findBlock(positions[-1]["position"]).text() == "同名"


def test_numbered_events_and_natural_volume_titles_have_reading_positions(qtbot):
    source = "# 总览\n\n第二部 政局\n\n25. 政变\n\n必须发生的事情。\n\n26. 逃离\n\n结尾。"
    assert [h["line"] for h in render(source)["headings"]] == [
        h["line"] for h in outline_headings(source)
    ]


def test_numbered_markdown_titles_are_not_interpreted_as_list_items(qtbot):
    source = (
        "# 总览😀\n\n### 1. 一句话故事\n\n开篇。\n\n"
        "| 人物 | 目标 |\n| --- | --- |\n| 主角 | 返回 |\n\n"
        "### 2. **完整故事**\n\n正文。\n\n3. 真正的列表事件\n\n后续。\n\n"
        "### 1. 一句话故事\n\n再次出现。"
    )
    result = render(source)
    headings = outline_headings(source)
    assert [item["line"] for item in result["headings"]] == [
        item["line"] for item in headings
    ]
    document = QTextDocument()
    document.setHtml(result["html"])
    titles = [document.findBlock(item["position"]).text() for item in result["headings"]]
    assert titles == ["总览😀", "1. 一句话故事", "2. 完整故事", "真正的列表事件", "1. 一句话故事"]
