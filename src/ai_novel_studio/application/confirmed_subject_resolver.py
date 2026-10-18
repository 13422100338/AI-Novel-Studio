from __future__ import annotations

import sqlite3

from ai_novel_studio.domain.subject import SubjectType
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository


class ConfirmedSubjectResolutionError(RuntimeError):
    """Raised when the subject registry cannot be read."""


class ConfirmedSubjectResolver:
    """Resolves links against confirmed active CHARACTER subjects only.

    The registry is authoritative: canonical names and confirmed aliases
    must match exactly after ``strip()`` and comparisons stay case
    sensitive. Resolution never creates, restores, merges, or guesses
    Subjects, and model alias candidates carry no authority here.
    """

    def __init__(self, subjects: SubjectRepository) -> None:
        if not isinstance(subjects, SubjectRepository):
            raise TypeError("confirmed subject repository is invalid")
        self._subjects = subjects

    def resolve_name(self, name: str) -> tuple[str, ...]:
        """Return sorted unique IDs of matching active CHARACTER subjects.

        An empty result means unresolved; multiple entries mean ambiguous.
        """
        if not isinstance(name, str):
            raise ConfirmedSubjectResolutionError from None
        normalized = name.strip()
        try:
            accepted: list[str] = []
            for subject in self._subjects.resolve_character_name(normalized):
                if not subject.active or subject.type is not SubjectType.CHARACTER:
                    continue
                if subject.canonical_name == normalized:
                    accepted.append(subject.id)
                    continue
                if any(
                    alias.confirmed and alias.alias == normalized
                    for alias in self._subjects.list_aliases(subject.id)
                ):
                    accepted.append(subject.id)
            return tuple(sorted(set(accepted)))
        except (sqlite3.Error, TypeError, ValueError):
            raise ConfirmedSubjectResolutionError from None

    def resolve_active_character(self, subject_id: str) -> str | None:
        """Return the exact ID when it names an active CHARACTER subject."""
        if not isinstance(subject_id, str):
            raise ConfirmedSubjectResolutionError from None
        try:
            subject = self._subjects.get(subject_id)
        except KeyError:
            return None
        except (sqlite3.Error, TypeError, ValueError):
            raise ConfirmedSubjectResolutionError from None
        if not subject.active or subject.type is not SubjectType.CHARACTER:
            return None
        return subject.id


__all__ = [
    "ConfirmedSubjectResolutionError",
    "ConfirmedSubjectResolver",
]
