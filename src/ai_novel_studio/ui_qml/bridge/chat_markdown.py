"""Native Markdown formatting for chat without HTML or image resource access."""

from __future__ import annotations

from functools import lru_cache
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QFont, QTextDocument


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
def _render(source: str, markdown: bool) -> str:
    document = _ChatDocument()
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(14)
    document.setDefaultFont(font)
    if markdown:
        document.setMarkdown(
            source,
            QTextDocument.MarkdownFeature.MarkdownDialectGitHub
            | QTextDocument.MarkdownFeature.MarkdownNoHTML,
        )
    else:
        document.setPlainText(source)
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
