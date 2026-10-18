"""Bounded editor quotes for conversation, independent of replacement ranges."""

from __future__ import annotations

import json

from ai_novel_studio.application.novel_read_service import NovelEditorSnapshot


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeError:
        return 6_000_001


def parse_chat_selection(payload: str) -> NovelEditorSnapshot | None:
    if not isinstance(payload, str) or _utf8_size(payload) > 6_000_000:
        return None
    try:
        value = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or set(value) != {
        "chapter_id",
        "base_revision",
        "content",
        "selection",
    }:
        return None
    chapter, revision = value["chapter_id"], value["base_revision"]
    content, selection = value["content"], value["selection"]
    if (
        not isinstance(chapter, str)
        or not 0 < len(chapter) <= 200
        or type(revision) is not int
        or revision < 0
        or not isinstance(content, str)
        or _utf8_size(content) > 5_000_000
        or not isinstance(selection, str)
        or len(selection) > 20_000
        or _utf8_size(selection) > 80_000
        or "\x00" in content
        or "\x00" in selection
    ):
        return None
    return NovelEditorSnapshot(
        chapter_id=chapter, revision=revision, content=content, selection=selection
    )
