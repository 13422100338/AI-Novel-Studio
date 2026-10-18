from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ai_novel_studio.harness.artifacts import ArtifactKind, ArtifactStore

DEFAULT_RETENTION_DAYS = 30

# Creative outputs are permanent; raw tool results and summaries age out
# (design v0.3 §67).
PERMANENT_KINDS = frozenset(
    {
        ArtifactKind.DRAFT_CANDIDATE,
        ArtifactKind.PARTIAL_DRAFT,
        ArtifactKind.DRAFT_CHECKPOINT,
    }
)


@dataclass(frozen=True, slots=True)
class ArtifactCleanupResult:
    """Outcome of one deterministic retention sweep (design v0.3 §67)."""

    removed: tuple[str, ...]
    kept: tuple[str, ...]


class ArtifactRetentionService:
    """Deterministic artifact retention (design v0.3 §67).

    Non-creative artifacts (tool results, summary revisions) are removed
    after the retention window; draft candidates, partials and checkpoints
    are permanent. The clock is injectable so cleanup is testable and
    reproducible.
    """

    def __init__(
        self,
        store: ArtifactStore,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        permanent_kinds: frozenset[ArtifactKind] = PERMANENT_KINDS,
    ) -> None:
        if retention_days < 1:
            raise ValueError("retention_days must be positive")
        self._store = store
        self._retention_days = retention_days
        self._permanent_kinds = permanent_kinds

    def cleanup(self, now: datetime | None = None) -> ArtifactCleanupResult:
        current = now or datetime.now(UTC)
        removed: list[str] = []
        kept: list[str] = []
        for artifact_id in self._store.list_ids():
            try:
                artifact = self._store.get(artifact_id)
            except (KeyError, ValueError):
                continue
            if artifact.kind in self._permanent_kinds:
                kept.append(artifact_id)
                continue
            age = current - artifact.created_at
            if age.days > self._retention_days:
                self._store.delete(artifact_id)
                removed.append(artifact_id)
            else:
                kept.append(artifact_id)
        return ArtifactCleanupResult(tuple(removed), tuple(kept))
