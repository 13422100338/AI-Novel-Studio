from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ai_novel_studio.core.context.context_ranking import RankedContextBlock

MAX_NORMALIZED_DUPLICATE_LENGTH = 50_000


@dataclass(frozen=True, slots=True)
class DuplicateContextBlock:
    dropped: RankedContextBlock
    kept_block_id: str


@dataclass(frozen=True, slots=True)
class ContextDeduplicationResult:
    kept: tuple[RankedContextBlock, ...]
    duplicates: tuple[DuplicateContextBlock, ...]


class ContextDeduplicator:
    """Keeps the highest-ranked optional block for identical prompt content."""

    def deduplicate(
        self,
        ranked: tuple[RankedContextBlock, ...],
    ) -> ContextDeduplicationResult:
        kept: list[RankedContextBlock] = []
        duplicates: list[DuplicateContextBlock] = []
        seen: dict[str, str] = {}
        for item in ranked:
            fingerprint = _fingerprint(
                item.block.content,
                item.block.fallback_content,
            )
            kept_block_id = seen.get(fingerprint)
            if kept_block_id is not None:
                duplicates.append(DuplicateContextBlock(item, kept_block_id))
                continue
            seen[fingerprint] = item.block.id
            kept.append(item)
        return ContextDeduplicationResult(tuple(kept), tuple(duplicates))


def _fingerprint(content: str, fallback_content: str | None) -> str:
    digest = hashlib.sha256()
    content_bytes = _normalized(content).encode("utf-8")
    digest.update(len(content_bytes).to_bytes(8, "big"))
    digest.update(content_bytes)
    if fallback_content is None:
        digest.update(b"\0")
    else:
        fallback_bytes = _normalized(fallback_content).encode("utf-8")
        digest.update(b"\1")
        digest.update(len(fallback_bytes).to_bytes(8, "big"))
        digest.update(fallback_bytes)
    return digest.hexdigest()


def _normalized(content: str) -> str:
    if len(content) <= MAX_NORMALIZED_DUPLICATE_LENGTH:
        return " ".join(content.casefold().split())
    return content
