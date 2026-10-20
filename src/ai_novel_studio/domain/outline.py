from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime

from ai_novel_studio.domain.identifiers import validate_id

MAX_OUTLINE_BYTES = 20_000_000


def validate_outline_hash(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("大纲内容哈希无效")
    return value


def outline_content_hash(content: str) -> str:
    if not isinstance(content, str) or "\x00" in content:
        raise ValueError("大纲必须是无 NUL 字符的文本")
    payload = content.encode("utf-8")
    if len(payload) > MAX_OUTLINE_BYTES:
        raise ValueError("大纲超过 20 MB 存储上限，未保存或截断")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class OutlineDocument:
    id: str
    project_id: str
    title: str
    sort_index: int
    revision: int
    content_hash: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_id(self.project_id)
        validate_outline_hash(self.content_hash)
        if not isinstance(self.title, str) or not self.title.strip() or len(self.title) > 400:
            raise ValueError("大纲标题应为 1 至 400 字符的非空文本")
        if type(self.sort_index) is not int or self.sort_index < 0:
            raise ValueError("大纲顺序无效")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("大纲修订号无效")


@dataclass(frozen=True, slots=True)
class OutlineVersion:
    id: str
    document_id: str
    revision: int
    content_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_id(self.document_id)
        validate_outline_hash(self.content_hash)
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("大纲修订号无效")


@dataclass(frozen=True, slots=True)
class OutlineSnapshot:
    version: OutlineVersion
    content: str

    def __post_init__(self) -> None:
        if outline_content_hash(self.content) != self.version.content_hash:
            raise ValueError("大纲快照内容与版本哈希不一致")


def outline_bundle_fingerprint(project_id: str, documents: tuple[OutlineDocument, ...]) -> str:
    payload = {
        "project": project_id,
        "documents": [
            (d.id, d.revision, d.content_hash, d.sort_index, d.updated_at.isoformat())
            for d in documents
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
