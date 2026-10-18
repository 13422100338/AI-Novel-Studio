from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.domain.subject import SubjectType
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository

_MAX_SUBJECT_IDS = 100


@dataclass(frozen=True, slots=True)
class SubjectInspectionRequest:
    subject_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.subject_ids, tuple) or not self.subject_ids:
            raise ValueError("subject inspection ids cannot be empty")
        if len(self.subject_ids) > _MAX_SUBJECT_IDS:
            raise ValueError("subject inspection has too many ids")
        normalized: list[str] = []
        for value in self.subject_ids:
            if not isinstance(value, str):
                raise ValueError("subject inspection ids are invalid")
            try:
                normalized.append(validate_id(value))
            except ValueError:
                raise ValueError("subject inspection ids are invalid") from None
        if len(set(normalized)) != len(normalized):
            raise ValueError("subject inspection ids must be unique")
        object.__setattr__(self, "subject_ids", tuple(normalized))


@dataclass(frozen=True, slots=True)
class SubjectInspection:
    """Bounded subject inspection DTO owned by this capability (H0 step 4)."""

    subject_id: str
    subject_type: SubjectType
    canonical_name: str
    active: bool
    aliases: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.subject_id.strip():
            raise ValueError("subject inspection id cannot be empty")
        if not isinstance(self.subject_type, SubjectType):
            raise ValueError("subject inspection type is invalid")
        if not self.canonical_name.strip():
            raise ValueError("subject inspection name cannot be empty")
        if not isinstance(self.aliases, tuple):
            raise ValueError("subject inspection aliases are invalid")


class SubjectInspectionService:
    """inspect_subjects facade over the existing SubjectRepository."""

    def __init__(self, subjects: SubjectRepository) -> None:
        if not isinstance(subjects, SubjectRepository):
            raise TypeError("subject repository is invalid")
        self._subjects = subjects

    def inspect(self, request: SubjectInspectionRequest) -> tuple[SubjectInspection, ...]:
        if not isinstance(request, SubjectInspectionRequest):
            raise TypeError("subject inspection request is invalid")
        inspections: list[SubjectInspection] = []
        for subject_id in request.subject_ids:
            try:
                subject = self._subjects.get(subject_id)
            except KeyError:
                raise ValueError(f"unknown subject: {subject_id}") from None
            aliases = tuple(
                alias.alias for alias in self._subjects.list_aliases(subject_id)
            )
            inspections.append(
                SubjectInspection(
                    subject_id=subject.id,
                    subject_type=subject.type,
                    canonical_name=subject.canonical_name,
                    active=subject.active,
                    aliases=aliases,
                )
            )
        return tuple(inspections)
