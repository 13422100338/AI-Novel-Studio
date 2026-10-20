"""Ordinary local Markdown chapter links, without a story or event graph."""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

_LINK = re.compile(r'(?<!!)\[((?:\\.|[^\]\\])*)\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+"[^"]*")?\s*\)')


@dataclass(frozen=True, slots=True)
class MarkdownChapterLink:
    line: int
    column: int
    quote: str
    chapter_id: str


def _lines(raw: str) -> Iterator[tuple[int, str, bool]]:
    fence = ""
    for number, line in enumerate(raw.splitlines(), start=1):
        marker = re.match(r"\s*(`{3,}|~{3,})", line.removeprefix("\ufeff"))
        blocked = bool(fence) or marker is not None
        if marker:
            run = marker.group(1)
            if not fence:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = ""
        yield number, line, blocked


def chapter_markdown_link(title: str, content_path: str) -> str:
    if any(c in title for c in "\r\n\x00"):
        raise ValueError("章节标题不能包含换行或 NUL")
    label = title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    target = quote(posixpath.relpath(content_path, "outlines"), safe="/-._~")
    return f"[{label}]({target})"


def registered_chapter_path(root: Path, content_path: str) -> Path | None:
    relative = Path(content_path.replace("\\", "/"))
    if relative.is_absolute() or relative.drive:
        return None
    path = Path(os.path.abspath(root / relative))
    return path if path.is_relative_to(root / "manuscript") else None


def scan_chapter_links(
    raw: str, document_path: Path, registered: Mapping[Path, str]
) -> tuple[MarkdownChapterLink, ...]:
    result: list[MarkdownChapterLink] = []
    for number, line, blocked in _lines(raw):
        if blocked:
            continue
        code = tuple((m.start(), m.end()) for m in re.finditer(r"(`+).*?\1", line))
        for match in _LINK.finditer(line):
            if any(start <= match.start() < end for start, end in code):
                continue
            try:
                target = urlsplit(match.group(2) or match.group(3))
            except ValueError:
                continue
            decoded = unquote(target.path)
            if target.scheme or target.netloc or target.query or "\\" in decoded:
                continue
            if Path(decoded).is_absolute() or Path(decoded).drive:
                continue
            # Lexical normalization only: unknown links must not probe files or network shares.
            path = Path(os.path.abspath(document_path.parent / decoded))
            chapter_id = registered.get(path)
            if chapter_id is not None:
                result.append(MarkdownChapterLink(number, match.start(), match.group(), chapter_id))
    return tuple(result)


def insert_chapter_link(raw: str, line: int, token: str) -> str:
    lines = raw.splitlines(keepends=True)
    final_blank = bool(raw) and raw.endswith(("\r", "\n", "\u2028", "\u2029"))
    if type(line) is not int or line < 1 or line > max(1, len(lines) + int(final_blank)):
        raise ValueError("请选择有效的大纲行")
    if any(number == line and blocked for number, _, blocked in _lines(raw)):
        raise ValueError("不能在代码块内插入章节关联")
    separator = re.search(r"\r\n|\r|\n", raw)
    newline = separator.group() if separator else "\n"
    prefix, suffix = "".join(lines[:line]), "".join(lines[line:])
    if lines and line > len(lines):
        prefix += newline
    if prefix and not prefix.endswith(("\r", "\n", "\u2028", "\u2029")):
        prefix += newline
    return prefix + token + newline + suffix
