from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.memory import CanonEntry
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)


@dataclass(frozen=True, slots=True)
class CanonResolution:
    entry: CanonEntry | None
    conflicts: tuple[CanonEntry, ...]


class CanonLedger:
    def __init__(self, repository: NarrativeMemoryRepository) -> None:
        self.repository = repository

    def resolve(self, title: str, before_chapter_id: str) -> CanonResolution:
        entries = self.repository.canon_before(title, before_chapter_id)
        if not entries:
            return CanonResolution(None, ())
        highest = max(entry.authority.rank for entry in entries)
        candidates = tuple(entry for entry in entries if entry.authority.rank == highest)
        details = {entry.detail for entry in candidates}
        if len(details) > 1:
            return CanonResolution(None, candidates)
        return CanonResolution(candidates[-1], ())

