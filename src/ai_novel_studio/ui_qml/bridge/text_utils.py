"""Deterministic text metrics for the presentation layer."""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z0-9]+")


def count_words(text: str) -> int:
    """Count CJK characters plus latin/numeric word tokens."""
    return len(_CJK_RE.findall(text)) + len(_LATIN_RE.findall(text))


def format_word_count(count: int) -> str:
    """Format a word count for the status bar (e.g. ``约 18.6K``)."""
    if count >= 1000:
        return f"约 {count / 1000:.1f}K"
    return str(count)

