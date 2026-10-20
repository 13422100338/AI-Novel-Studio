from pathlib import Path

from ai_novel_studio.core.outline_links import chapter_markdown_link, scan_chapter_links


def test_links_resolve_only_registered_local_chapters(tmp_path: Path) -> None:
    document = tmp_path / "outlines" / "book.md"
    chapter = tmp_path / "manuscript" / "chapter.md"
    raw = (
        "[章节](../manuscript/chapter.md)\n"
        "[远程](https://example.invalid/chapter.md)\n"
        "[其他文件](../secret.md)\n"
        "`[行内代码](../manuscript/chapter.md)`\n"
        "```md\n[代码块](../manuscript/chapter.md)\n```\n"
    )
    found = scan_chapter_links(raw, document, {chapter: "chapter-id"})
    assert len(found) == 1
    assert found[0].chapter_id == "chapter-id"
    assert found[0].line == 1
    assert found[0].quote == "[章节](../manuscript/chapter.md)"


def test_markdown_link_escapes_labels_and_encodes_paths(tmp_path: Path) -> None:
    link = chapter_markdown_link("会议 [夜晚]", "manuscript/第二 章.md")
    assert link.startswith("[会议 \\[夜晚\\]](")
    chapter = tmp_path / "manuscript" / "第二 章.md"
    found = scan_chapter_links(link, tmp_path / "outlines" / "x.md", {chapter: "id"})
    assert len(found) == 1
    assert found[0].chapter_id == "id"


def test_repeated_links_keep_distinct_line_and_column_positions(tmp_path: Path) -> None:
    link = "[章](../manuscript/a.md)"
    found = scan_chapter_links(
        f"\ufeff# 事件\r\n{link} {link}\r\n{link}",
        tmp_path / "outlines" / "a.md",
        {tmp_path / "manuscript" / "a.md": "id"},
    )
    assert [(entry.line, entry.column) for entry in found] == [(2, 0), (2, len(link) + 1), (3, 0)]


def test_untrusted_links_do_not_probe_the_filesystem(tmp_path: Path, monkeypatch) -> None:
    def forbidden_resolve(*args, **kwargs):
        raise AssertionError("chapter link parsing must not resolve arbitrary filesystem paths")

    monkeypatch.setattr(Path, "resolve", forbidden_resolve)
    raw = (
        "[有效](../manuscript/a.md)\n[其他](../../outside.md)\n"
        "[编码路径](%5C%5Cserver%5Cshare%5Cx.md)"
    )
    found = scan_chapter_links(
        raw,
        tmp_path / "outlines" / "a.md",
        {tmp_path / "manuscript" / "a.md": "id"},
    )
    assert len(found) == 1
    assert found[0].chapter_id == "id"
