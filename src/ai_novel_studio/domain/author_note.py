"""Author-owned writing guidance, separate from outlines and formal prose."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

NOTE_KINDS = ("OUTLINE", "CHARACTER", "STYLE", "CAUTION", "OTHER")
NOTE_MODES = ("NONE", "FULL", "SUMMARY")


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def note_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def note_id(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("笔记 ID 无效")
    return value


def validate_note_text(value: str, *, title: bool = False) -> None:
    if not isinstance(value, str) or len(value) > (200 if title else 200_000):
        raise ValueError("笔记标题最多200字，正文最多200000字，未截断")
    if title and not value.strip():
        raise ValueError("请输入笔记标题")
    if any(
        (ord(c) < 32 and (title or c not in "\n\r\t")) or 0xD800 <= ord(c) <= 0xDFFF for c in value
    ):
        raise ValueError("笔记包含无效控制字符或代理码点")


@dataclass(frozen=True, slots=True)
class AuthorNote:
    id: str
    title: str
    kind: str
    revision: int
    content: str
    source_hash: str
    created_at: str

    def summary(self) -> dict[str, Any]:
        return {
            "note_id": self.id,
            "title": self.title,
            "kind": self.kind,
            "revision": self.revision,
            "source_hash": self.source_hash,
            "chars": len(self.content),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class NoteSelection:
    mode: str = "NONE"
    ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.ids, tuple)
            or not all(isinstance(i, str) for i in self.ids)
            or self.mode not in NOTE_MODES
            or len(self.ids) > 32
            or len(set(self.ids)) != len(self.ids)
        ):
            raise ValueError("本次最多选择32篇不同笔记")
        for identity in self.ids:
            note_id(identity)
        if (self.mode == "NONE") != (not self.ids):
            raise ValueError("请先选择笔记，或使用不附笔记模式")

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical({"mode": self.mode, "note_ids": self.ids})).hexdigest()


@dataclass(frozen=True, slots=True)
class NoteRef:
    note_id: str
    revision: int
    source_hash: str

    def __post_init__(self) -> None:
        note_id(self.note_id)
        if (
            type(self.revision) is not int
            or not 1 <= self.revision <= 2000
            or not isinstance(self.source_hash, str)
            or not re.fullmatch("[0-9a-f]{64}", self.source_hash)
        ):
            raise ValueError("笔记引用身份无效")
