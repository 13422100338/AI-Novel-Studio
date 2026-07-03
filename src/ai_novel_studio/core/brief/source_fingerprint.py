from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ai_novel_studio.domain.generation import BriefSource


@dataclass(frozen=True, slots=True)
class BriefSourceSnapshot:
    source_type: str
    source_id: str
    source_revision: int
    source_hash: str
    required: bool

    def __post_init__(self) -> None:
        if (
            not self.source_type.strip()
            or not self.source_id.strip()
            or not self.source_hash.strip()
        ):
            raise ValueError("Brief 来源类型、ID 和哈希不能为空")
        if self.source_revision < 0:
            raise ValueError("Brief 来源修订号不能为负数")


SourceValue = BriefSourceSnapshot | BriefSource


def source_key(source: SourceValue) -> tuple[str, str]:
    return source.source_type, source.source_id


def compute_source_fingerprint(sources: tuple[SourceValue, ...]) -> str:
    ordered = sorted(
        sources,
        key=lambda source: (
            source.source_type,
            source.source_id,
            source.source_revision,
            source.source_hash,
            source.required,
        ),
    )
    payload = [
        {
            "source_type": source.source_type,
            "source_id": source.source_id,
            "source_revision": source.source_revision,
            "source_hash": source.source_hash,
            "required": source.required,
        }
        for source in ordered
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
