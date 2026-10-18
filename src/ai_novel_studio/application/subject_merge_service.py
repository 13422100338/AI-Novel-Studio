from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.character_identity_service import (
    CharacterIdentityError,
    CharacterIdentityService,
)
from ai_novel_studio.domain.character_identity import CharacterIdentityMerge
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class SubjectMergeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SubjectMergePreview:
    source_character_id: str
    target_character_id: str
    source_canonical_name: str
    target_canonical_name: str
    aliases_to_preserve: tuple[str, ...]
    state_event_count: int
    shared_chapter_conflict_count: int
    reversible: bool


class SubjectMergeService:
    """Subject merge preview/commit facade over the existing merge transaction.

    The Harness proposes; this facade previews deterministically and the
    existing confirmed-by-user merge/undo remain the only commit surfaces.
    """

    def __init__(self, project: ProjectRepository) -> None:
        self._identity = CharacterIdentityService(project)
        self._memory = CharacterMemoryRepository(project)

    def preview(
        self, source_character_id: str, target_character_id: str
    ) -> SubjectMergePreview:
        try:
            source = self._memory.get_character(validate_id(source_character_id))
            target = self._memory.get_character(validate_id(target_character_id))
        except (KeyError, ValueError):
            raise SubjectMergeError("subject merge characters are unknown") from None
        if source.id == target.id:
            raise SubjectMergeError("cannot merge a character into itself")
        target_names = {target.canonical_name, *target.aliases}
        aliases_to_preserve = tuple(
            alias for alias in source.aliases if alias not in target_names
        )
        source_history = self._memory.state_history(source.id)
        target_chapters = {
            event.chapter_id for event in self._memory.state_history(target.id)
        }
        conflicts = sum(
            1 for event in source_history if event.chapter_id in target_chapters
        )
        return SubjectMergePreview(
            source_character_id=source.id,
            target_character_id=target.id,
            source_canonical_name=source.canonical_name,
            target_canonical_name=target.canonical_name,
            aliases_to_preserve=aliases_to_preserve,
            state_event_count=len(source_history),
            shared_chapter_conflict_count=conflicts,
            reversible=True,
        )

    def merge(
        self,
        source_character_id: str,
        target_character_id: str,
        *,
        reason: str,
        confirmed_by_user: bool,
        expected_revisions: tuple[tuple[str, int], ...] = (),
    ) -> CharacterIdentityMerge:
        expected_state_count = self._expected_state_count(
            source_character_id,
            expected_revisions,
        )
        try:
            return self._identity.merge(
                source_character_id,
                target_character_id,
                reason=reason,
                confirmed_by_user=confirmed_by_user,
                expected_source_state_event_count=expected_state_count,
            )
        except (CharacterIdentityError, PermissionError) as error:
            raise SubjectMergeError(str(error)) from error

    def undo(self, merge_id: str, *, confirmed_by_user: bool) -> CharacterIdentityMerge:
        try:
            return self._identity.undo(merge_id, confirmed_by_user=confirmed_by_user)
        except (CharacterIdentityError, PermissionError) as error:
            raise SubjectMergeError(str(error)) from error

    @staticmethod
    def _expected_state_count(
        source_character_id: str,
        expected_revisions: tuple[tuple[str, int], ...],
    ) -> int | None:
        if not isinstance(expected_revisions, tuple):
            raise SubjectMergeError("subject merge expected revisions are invalid")
        if not expected_revisions:
            return None
        expected_key = "subject.state_events:" + validate_id(source_character_id)
        if (
            len(expected_revisions) != 1
            or not isinstance(expected_revisions[0], tuple)
            or len(expected_revisions[0]) != 2
        ):
            raise SubjectMergeError("subject merge expected revisions are invalid")
        key, revision = expected_revisions[0]
        if (
            key != expected_key
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 0
        ):
            raise SubjectMergeError("subject merge expected revisions are invalid")
        return revision
