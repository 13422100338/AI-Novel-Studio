"""Display references from author Markdown and project-owned catalogs; no file reads."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from ai_novel_studio.core.outline_links import (
    _LINK,
    _lines,
    registered_chapter_path,
    scan_chapter_links,
)


def reference_url(kind: str, identity: str) -> str:
    if kind not in {"chapter", "note"} or str(UUID(identity)) != identity:
        raise ValueError("Invalid outline reference")
    return f"novel://{kind}/{identity}"


def build_references(
    raw: str,
    headings: list[dict[str, Any]],
    chapter_links: list[dict[str, Any]],
    chapters: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    document_path: Path,
    *,
    dirty: bool = False,
) -> list[dict[str, Any]]:
    root = document_path.parent.parent
    catalog = {c["id"]: c for c in chapters}
    note_catalog = {n["id"]: n for n in notes}
    registered = {
        path: c["id"]
        for c in chapters
        if (path := registered_chapter_path(root, c.get("path", ""))) is not None
    }
    statuses = {
        (link["chapterId"], link["line"]): link["statusText"]
        for link in chapter_links
        if link["active"] and link["status"] != "MISSING_SOURCE"
    }
    grouped: dict[int, dict[str, Any]] = {}

    def add(
        line: int, kind: str, identity: str, title: str, available: bool, status: str, quote: str
    ) -> None:
        heading = next((h for h in reversed(headings) if h["line"] <= line), None)
        if heading is None:
            return
        try:
            url = reference_url(kind, identity)
        except (ValueError, TypeError, AttributeError):
            return
        group = grouped.setdefault(
            heading["line"],
            {
                "line": heading["line"],
                "position": heading["position"],
                "heading": heading["title"],
                "refs": [],
            },
        )
        existing = next((r for r in group["refs"] if r["url"] == url), None)
        source = {"line": line, "quote": quote}
        if existing:
            existing["sources"].append(source)
        else:
            group["refs"].append(
                {
                    "kind": kind,
                    "id": identity,
                    "url": url,
                    "title": title,
                    "available": available,
                    "status": status,
                    "sources": [source],
                }
            )

    for link in scan_chapter_links(raw, document_path, registered):
        chapter = catalog[link.chapter_id]
        add(
            link.line,
            "chapter",
            link.chapter_id,
            chapter["title"],
            True,
            "待确认" if dirty else statuses.get((link.chapter_id, link.line), "待确认"),
            link.quote,
        )
    for line, text, blocked in _lines(raw):
        if blocked:
            continue
        code = [(m.start(), m.end()) for m in re.finditer(r"(`+).*?\1", text)]
        for match in _LINK.finditer(text):
            if any(start <= match.start() < end for start, end in code):
                continue
            try:
                target = urlsplit(match.group(2) or match.group(3))
            except ValueError:
                continue
            if (
                (target.scheme, target.netloc) != ("novel", "note")
                or target.query
                or target.fragment
            ):
                continue
            identity = target.path.removeprefix("/")
            note = note_catalog.get(identity)
            title = note["title"] if note else re.sub(r"\\(.)", r"\1", match.group(1))
            add(
                line,
                "note",
                identity,
                title or "笔记不可用",
                note is not None,
                "创作笔记" if note else "当前项目中未找到笔记",
                match.group(),
            )
    order = {c["id"]: i for i, c in enumerate(chapters)}
    for group in grouped.values():
        group["refs"].sort(key=lambda r: order.get(r["id"], len(order)))
    return [grouped[line] for line in sorted(grouped)]
