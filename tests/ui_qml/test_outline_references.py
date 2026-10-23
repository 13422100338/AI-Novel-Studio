from uuid import uuid4

from PySide6.QtGui import QTextDocument

from ai_novel_studio.core.outline_markdown import outline_headings
from ai_novel_studio.ui_qml.bridge.outline_markdown_view import OutlineMarkdownView


def test_references_follow_current_headings_and_registered_chapters_only(tmp_path):
    from ai_novel_studio.ui_qml.bridge.outline_references import build_references

    one, two, note_id = (str(uuid4()) for _ in range(3))
    chapters = [
        {"id": one, "title": "第1章 完整的章节名字", "path": "manuscript/one.md"},
        {"id": two, "title": "第2章 钟楼会面", "path": "manuscript/two.md"},
    ]
    text = (
        "# 全书\n\n## 事件一\n"
        "[二](../manuscript/two.md) [一](../manuscript/one.md)\n"
        f"[细纲](novel://note/{note_id})\n"
        "[陌生文件](../../private.txt)\n\n"
        "## 事件二\n"
        "```md\n[示例](../manuscript/one.md)\n```\n"
        f"`[代码](novel://note/{note_id})`\n"
    )
    refs = build_references(
        text,
        outline_headings(text),
        [],
        chapters,
        [{"id": note_id, "title": "会面细纲"}],
        tmp_path / "outlines/main.md",
    )
    assert len(refs) == 1
    assert refs[0]["line"] == 3
    assert [(r["kind"], r["id"]) for r in refs[0]["refs"]] == [
        ("chapter", one),
        ("chapter", two),
        ("note", note_id),
    ]
    assert refs[0]["refs"][0]["title"] == "第1章 完整的章节名字"
    shifted = "前言\n\n" + text
    moved = build_references(
        shifted,
        outline_headings(shifted),
        [],
        chapters,
        [{"id": note_id, "title": "会面细纲"}],
        tmp_path / "outlines/main.md",
    )
    assert moved[0]["line"] == 5


def test_unknown_notes_are_visible_but_cannot_be_opened(tmp_path):
    from ai_novel_studio.ui_qml.bridge.outline_references import build_references

    identity = str(uuid4())
    text = f"## 场景\n[旧笔记](novel://note/{identity})\n[恶意](javascript:alert)"
    refs = build_references(text, outline_headings(text), [], [], [], tmp_path / "outlines/a.md")
    assert len(refs[0]["refs"]) == 1
    assert refs[0]["refs"][0]["available"] is False


def test_linked_rendering_adds_heading_links_without_changing_the_source(qtbot):
    identity = str(uuid4())
    source = "# 全书😀\n\n## 相同标题\n正文。\n\n## 相同标题\n结尾。"
    references = [
        {
            "line": 3,
            "refs": [
                {
                    "id": identity,
                    "kind": "chapter",
                    "title": "第一章 很长的正式章节名称",
                    "available": True,
                }
            ],
        }
    ]
    renderer = OutlineMarkdownView()
    for inline in (False, True):
        result = renderer.renderLinked(
            source, outline_headings(source), "#ddd", references, inline, "#506050"
        )
        doc = QTextDocument()
        doc.setHtml(result["html"])
        assert f"novel://chapter/{identity}" in result["html"]
        assert doc.findBlock(result["headings"][-1]["position"]).text() == "相同标题"
        assert len(result["annotations"]) == 1
        if inline:
            assert "很长的正式章节名称" in doc.toPlainText()
    assert source.endswith("结尾。")


def test_only_reference_rows_move_to_the_margin_prose_and_code_stay_visible(qtbot, tmp_path):
    from ai_novel_studio.ui_qml.bridge.outline_references import build_references

    identity = str(uuid4())
    token = f"[场景细纲](novel://note/{identity})"
    source = f"## 事件\n{token}\n\n正文里也提到 {token}，这句话不能省略。\n\n`{token}`\n"
    refs = build_references(
        source,
        outline_headings(source),
        [],
        [],
        [{"id": identity, "title": "场景细纲"}],
        tmp_path / "outlines/a.md",
    )
    renderer = OutlineMarkdownView()
    result = renderer.renderLinked(source, outline_headings(source), "#ddd", refs, False, "#506050")
    document = QTextDocument()
    document.setHtml(result["html"])
    displayed = document.toPlainText()
    assert "这句话不能省略。" in displayed
    assert token in displayed  # inline code is literal, never relocated
    assert displayed.count("场景细纲") == 2
    assert source.splitlines()[1] == token


def test_each_heading_reference_has_its_own_utf16_connection_position(qtbot):
    source = "# 全书😀\n\n## 事件\n正文。"
    refs = [
        {
            "line": 3,
            "refs": [
                {"id": str(uuid4()), "kind": "chapter", "title": "第1章", "available": True},
                {"id": str(uuid4()), "kind": "note", "title": "细纲", "available": True},
            ],
        }
    ]
    result = OutlineMarkdownView().renderLinked(
        source, outline_headings(source), "#ddd", refs, False, "#506050"
    )
    links = result["annotations"][0]["refs"]
    assert links[0]["position"] < links[1]["position"]
    document = QTextDocument()
    document.setHtml(result["html"])
    assert document.findBlock(links[0]["position"]).text().startswith("事件")
