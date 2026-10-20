"""Navigation and minimal edits for a plain-text outline editor, without Markdown rewriting."""

from __future__ import annotations

import re

_BREAKS = re.compile(r"\r\n|[\r\u2028\u2029]")
_ATX = re.compile(r"^(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_NUMBERED = re.compile(r"^([ \t]*)(\d+(?:\.\d+)*[.)、）]?(?:[ \t]+|(?=[^\d.\s]))\S.*)$")
_CHINESE = re.compile(
    r"^第[零〇一二三四五六七八九十百千万两\d]+"
    r"(?:部|卷|章|幕|节|事件|阶段|场景).*$"
)


def editor_text(raw: str) -> str:
    return _BREAKS.sub("\n", raw.removeprefix("\ufeff"))


def _raw_position(raw: str, position: int) -> int:
    result = position + int(raw.startswith("\ufeff"))
    for match in re.finditer(r"\r\n", raw):
        if match.start() >= result:
            break
        result += 1
    return result


def apply_editor_edit(raw: str, edited: str) -> str:
    """Replace only the changed range; retain untouched BOM, whitespace and line endings."""
    before = editor_text(raw)
    after = _BREAKS.sub("\n", edited)
    if before == after:
        return raw
    prefix = 0
    while prefix < min(len(before), len(after)) and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < min(len(before), len(after)) - prefix and before[-suffix - 1] == after[-suffix - 1]
    ):
        suffix += 1
    separator = re.search(r"\r\n|\r|\n", raw)
    newline = separator.group() if separator else "\n"
    inserted = after[prefix : len(after) - suffix].replace("\n", newline)
    return (
        raw[: _raw_position(raw, prefix)]
        + inserted
        + raw[_raw_position(raw, len(before) - suffix) :]
    )


def outline_headings(raw: str) -> list[dict[str, str | int]]:
    headings: list[dict[str, str | int]] = []
    position = 0
    fence = ""
    for number, line in enumerate(editor_text(raw).splitlines(keepends=True), start=1):
        text = line.rstrip("\n")
        stripped = text.lstrip()
        marker = re.match(r"(`{3,}|~{3,})", stripped)
        if marker:
            run = marker.group()
            if not fence:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = ""
        elif not fence:
            atx, numbered = _ATX.match(text), _NUMBERED.match(text)
            title, level = "", 1
            if atx:
                title, level = atx.group(2), len(atx.group(1))
            elif numbered:
                title = numbered.group(2).strip()
                level += len(numbered.group(1).expandtabs(4)) // 2
                level += title.split()[0].rstrip(".、)）").count(".")
            elif _CHINESE.match(stripped):
                title = stripped
            if title:
                headings.append(
                    {"title": title, "level": level, "line": number, "position": position}
                )
        position += len(line.encode("utf-16-le")) // 2
    return headings
