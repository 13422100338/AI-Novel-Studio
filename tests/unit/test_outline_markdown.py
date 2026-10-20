from ai_novel_studio.core.outline_markdown import (
    apply_editor_edit,
    editor_text,
    outline_headings,
)


def test_loading_normalized_editor_text_does_not_change_source() -> None:
    raw = "\ufeff# 总览\r\n\r\n正文  \n尾段\r\n"
    assert editor_text(raw) == "# 总览\n\n正文  \n尾段\n"
    assert apply_editor_edit(raw, editor_text(raw)) == raw


def test_edit_preserves_bom_and_untouched_mixed_line_endings() -> None:
    raw = "\ufeff# 总览\r\n旧段\n尾段\r\n"
    edited = editor_text(raw).replace("旧段", "新段\n另一段")
    assert apply_editor_edit(raw, edited) == "\ufeff# 总览\r\n新段\r\n另一段\n尾段\r\n"


def test_editor_can_replace_all_text_or_delete_last_line() -> None:
    assert apply_editor_edit("\ufeff原文\r\n", "替换\n") == "\ufeff替换\r\n"
    assert apply_editor_edit("第一行\r\n第二行", "第一行\n") == "第一行\r\n"
    assert apply_editor_edit("", "新文档\n") == "新文档\n"


def test_headings_support_markdown_and_numbered_text_without_fixed_depth() -> None:
    text = "# 全书\n\n第二部 政局\n    25. 政变\n## 场景\n正文\n```md\n# 示例不算目录\n```\n"
    headings = outline_headings(text)
    assert [h["title"] for h in headings] == ["全书", "第二部 政局", "25. 政变", "场景"]
    assert [h["line"] for h in headings] == [1, 3, 4, 5]


def test_heading_navigation_uses_utf16_editor_positions() -> None:
    headings = outline_headings("\ufeff😀\r\n\r\n## 事件 25\r\n")
    assert headings == [{"title": "事件 25", "level": 2, "line": 3, "position": 4}]
