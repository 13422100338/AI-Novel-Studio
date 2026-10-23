"""Read-only outline typesetting and source-heading navigation, with no file access."""

import re
from collections import defaultdict, deque
from functools import lru_cache
from typing import Any

from PySide6.QtCore import QObject, Slot
from PySide6.QtGui import QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtQuick import QQuickItem

from ai_novel_studio.ui_qml.bridge.chat_markdown import _ChatDocument, _render
from ai_novel_studio.ui_qml.bridge.outline_references import reference_url


@lru_cache(maxsize=256)
def _heading_text(title: str, heading: bool = False) -> tuple[str, bool]:
    doc = _ChatDocument()
    # Inside an ATX heading, "1. Title" is inline text, not an ordered list.
    # Preserve that context when matching the rendered document's blocks.
    doc.setHtml(_render(("# " if heading else "") + title, True))
    return doc.toPlainText().strip(), doc.begin().textList() is not None


def _typeset(document: _ChatDocument) -> None:
    """Apply reading spacing to the display copy, preserving source and inline styles."""
    block = document.begin()
    while block.isValid():
        cursor = QTextCursor(block)
        style = block.blockFormat()
        level = style.headingLevel()
        in_table = cursor.currentTable() is not None
        style.setLineHeight(145, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        style.setTopMargin(20 if level else 0)
        style.setBottomMargin(10 if level else 0 if in_table else 6 if block.textList() else 12)
        cursor.setBlockFormat(style)
        if level:
            font = QTextCharFormat()
            font.setProperty(
                QTextFormat.Property.FontPixelSize, (28, 23, 20, 18, 17, 16)[level - 1]
            )
            font.setFontWeight(QFont.Weight.DemiBold)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.mergeCharFormat(font)
        block = block.next()


class OutlineMarkdownView(QObject):
    @Slot(QObject)
    def prepareTableReader(self, reader: QObject) -> None:
        # Qt's rich-text viewport pruning can lose paragraph nodes when a
        # long table is scrolled backwards. Keep normal ancestor clipping,
        # but build the complete table document's scene nodes.
        if not isinstance(reader, QQuickItem):
            return
        text = reader.property("text")
        if isinstance(text, str) and "<table" in text:
            reader.setFlag(QQuickItem.Flag.ItemObservesViewport, False)
            reader.update()

    @Slot(str, list, str, list, bool, str, result="QVariantMap")
    def renderLinked(
        self,
        source: str,
        headings: list[dict[str, Any]],
        border: str,
        references: list[dict[str, Any]],
        inline: bool,
        accent: str,
    ) -> dict[str, Any]:
        # Reference-only rows are displayed beside the heading (or as inline
        # links on narrow screens). Preserve prose, code, line numbers and the
        # author file; only these already indexed labels move in the view copy.
        lines = source.splitlines(keepends=True)
        labels: dict[int, list[str]] = defaultdict(list)
        for group in references:
            for ref in group["refs"]:
                for origin in ref.get("sources", []):
                    labels[origin["line"]].append(origin["quote"])
        for line, quotes in labels.items():
            if not 1 <= line <= len(lines):
                continue
            remaining = lines[line - 1]
            for quote in quotes:
                remaining = remaining.replace(quote, "")
            if not remaining.strip():
                lines[line - 1] = "\n" if lines[line - 1].endswith("\n") else ""
        rendered = self.render("".join(lines), headings, border)
        document = _ChatDocument()
        document.setHtml(rendered["html"])
        markers = []
        for heading in rendered["headings"]:
            cursor = QTextCursor(document)
            cursor.setPosition(heading["position"])
            cursor.setKeepPositionOnInsert(True)
            markers.append((heading["line"], cursor))
        by_line = {r["line"]: r["refs"] for r in references}
        annotations = []
        for line, marker in reversed(markers):
            refs = by_line.get(line, [])
            if not refs:
                continue
            cursor = QTextCursor(marker)
            cursor.setKeepPositionOnInsert(False)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            safe: list[tuple[dict[str, Any], QTextCursor]] = []
            for ref in refs:
                try:
                    url = reference_url(ref["kind"], ref["id"])
                except (KeyError, ValueError, TypeError, AttributeError):
                    continue
                title = str(ref.get("title", "引用")).replace("\n", " ").replace("\r", " ")
                label = "  [" + title + "]" if inline else "  ↗" + str(len(safe) + 1)
                style = QTextCharFormat()
                style.setProperty(QTextFormat.Property.FontPixelSize, 12)
                style.setFontWeight(QFont.Weight.Normal)
                style.setForeground(QColor(accent))
                if ref.get("available", False):
                    style.setAnchor(True)
                    style.setAnchorHref(url)
                    style.setFontUnderline(True)
                cursor.insertText(label, style)
                link_marker = QTextCursor(cursor)
                link_marker.setKeepPositionOnInsert(True)
                safe.append(({**ref, "url": url}, link_marker))
            anchor = QTextCursor(cursor)
            anchor.setKeepPositionOnInsert(True)
            annotations.append((line, anchor, safe))
        return {
            "html": document.toHtml(),
            "headings": [{"line": line, "position": cursor.position()} for line, cursor in markers],
            "annotations": [
                {
                    "line": line,
                    "position": cursor.position(),
                    "refs": [{**ref, "position": marker.position()} for ref, marker in refs],
                }
                for line, cursor, refs in reversed(annotations)
                if refs
            ],
        }

    @Slot(str, result=str)
    def title(self, source: str) -> str:
        return _heading_text(source, True)[0]

    @Slot(str, list, str, result="QVariantMap")
    def render(self, source: str, headings: list[dict[str, Any]], border: str) -> dict[str, Any]:
        # The outline reader has no chat-display cap. Large documents bypass the
        # small-message cache rather than omitting their tail.
        renderer = _render if len(source) <= 200_000 else _render.__wrapped__
        html = renderer(source, True, "SimSun", 18, border)
        document = _ChatDocument()
        document.setHtml(html)
        _typeset(document)
        blocks: dict[tuple[str, int, bool], deque[int]] = defaultdict(deque)
        block = document.begin()
        while block.isValid():
            blocks[
                (
                    block.text().strip(),
                    block.blockFormat().headingLevel(),
                    block.textList() is not None,
                )
            ].append(block.position())
            block = block.next()
        lines = source.splitlines()
        mapped, previous = [], -1
        for heading in headings:
            line, level, title = heading.get("line"), heading.get("level"), heading.get("title")
            if (
                type(line) is not int
                or not 1 <= line <= len(lines)
                or type(level) is not int
                or not isinstance(title, str)
            ):
                continue
            atx = re.match(r"^#{1,6}\s", lines[line - 1]) is not None
            visible, is_list = _heading_text(title, atx)
            candidates = blocks.get(
                (visible, level if atx else 0, False if atx else is_list), deque()
            )
            while candidates and candidates[0] <= previous:
                candidates.popleft()
            if candidates:
                previous = candidates.popleft()
                mapped.append({"line": line, "position": previous})
        return {"html": document.toHtml(), "headings": mapped}
