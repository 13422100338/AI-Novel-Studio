from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime


def _normalized_items(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    """Structured rolling summary of the project conversation (design §17).

    Incremental compaction only: an old summary plus events since then produce
    the next summary; re-summarizing all history is forbidden (design §17).
    A summary is never a source of novel domain truth (design §18).
    """

    confirmed_decisions: tuple[str, ...] = ()
    rejected_options: tuple[str, ...] = ()
    provisional_ideas: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    author_preferences: tuple[str, ...] = ()
    important_rationale: tuple[str, ...] = ()
    active_entities: tuple[str, ...] = ()
    source_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in (
            "confirmed_decisions",
            "rejected_options",
            "provisional_ideas",
            "unresolved_questions",
            "author_preferences",
            "important_rationale",
            "active_entities",
            "source_references",
        ):
            object.__setattr__(self, field, _normalized_items(getattr(self, field)))

    def to_json(self) -> str:
        return json.dumps(
            {field: list(getattr(self, field)) for field in self._fields()},
            ensure_ascii=False,
        )

    @staticmethod
    def _fields() -> tuple[str, ...]:
        return (
            "confirmed_decisions",
            "rejected_options",
            "provisional_ideas",
            "unresolved_questions",
            "author_preferences",
            "important_rationale",
            "active_entities",
            "source_references",
        )


@dataclass(frozen=True, slots=True)
class SummaryRevision:
    """One immutable summary version with its sequence number (design §18)."""

    revision: int
    summary: ConversationSummary
    created_at: datetime

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("revision must be positive")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
