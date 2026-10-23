"""Native Markdown formatting for chat without HTML or image resource access."""

from __future__ import annotations

import re
from functools import lru_cache
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QColor, QFont, QTextDocument, QTextFrameFormat, QTextLength, QTextTable


def _display_markdown(source: str) -> str:
    """Tolerate a closing bold marker after spaces, only in displayed prose."""

    def prose(part: str) -> str:
        markers = list(re.finditer(r"(?<![\\*])\*\*(?!\*)", part))
        edits = []
        for first, last in zip(markers[::2], markers[1::2], strict=False):
            inside = part[first.end() : last.start()]
            if inside and not inside[0].isspace() and inside[-1] in " \t":
                trimmed = inside.rstrip(" \t")
                edits.append(
                    (first.start(), last.end(), "**" + trimmed + "**" + inside[len(trimmed) :])
                )
        for start, end, value in reversed(edits):
            part = part[:start] + value + part[end:]
        return part

    result, fence = [], ""
    for line in source.splitlines(keepends=True):
        marker = re.match(r"\s*(`{3,}|~{3,})", line)
        if marker:
            run = marker.group(1)
            if not fence:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = ""
            result.append(line)
        elif fence:
            result.append(line)
        else:
            start = 0
            parts: list[str] = []
            for code in re.finditer(r"(?P<ticks>`+).*?(?P=ticks)", line):
                parts.extend((prose(line[start : code.start()]), code.group()))
                start = code.end()
            result.append("".join(parts) + prose(line[start:]))
    return "".join(result)


class _ChatDocument(QTextDocument):
    def loadResource(self, resource_type: int, url: QUrl | str) -> None:  # noqa: N802
        # Markdown must not cause either local file reads or remote image requests.
        return None


class _DisplayHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            self.parts.append("[图片]")
            return
        safe = []
        for name, value in attrs:
            if (
                name == "href"
                and value
                and not (
                    value.startswith("#") or urlsplit(value).scheme.lower() in {"http", "https"}
                )
            ):
                continue
            safe.append(f' {name}="{escape(value or "", quote=True)}"')
        self.parts.append("<" + tag + "".join(safe) + ">")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag != "img":
            self.parts.append("</" + tag + ">")

    def handle_data(self, data: str) -> None:
        self.parts.append(escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        self.parts.append("&" + name + ";")

    def handle_charref(self, name: str) -> None:
        self.parts.append("&#" + name + ";")


@lru_cache(maxsize=16)
def _render(
    source: str,
    markdown: bool,
    family: str = "Microsoft YaHei UI",
    size: int = 14,
    table_border: str = "",
) -> str:
    document = _ChatDocument()
    font = QFont(family)
    font.setPixelSize(size)
    document.setDefaultFont(font)
    if markdown:
        document.setMarkdown(
            _display_markdown(source),
            QTextDocument.MarkdownFeature.MarkdownDialectGitHub
            | QTextDocument.MarkdownFeature.MarkdownNoHTML,
        )
    else:
        document.setPlainText(source)
    if table_border:
        color = QColor(table_border)
        if not color.isValid():
            color = QColor("#d8c9b7")
        for frame in document.rootFrame().childFrames():
            if isinstance(frame, QTextTable):
                style = frame.format()
                style.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
                style.setBorder(1)
                style.setBorderBrush(color)
                style.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
                style.setCellPadding(7)
                style.setCellSpacing(0)
                frame.setFormat(style)
    display = _DisplayHtml()
    display.feed(document.toHtml())
    return "".join(display.parts)


class ChatMarkdown(QObject):
    @Slot(str, result=str)
    def render(self, source: str) -> str:
        return _render(source[:200_000], True)

    @Slot(str, result=str)
    def literal(self, source: str) -> str:
        return _render(source[:200_000], False)
