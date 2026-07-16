from __future__ import annotations

from ai_novel_studio.domain.character_identity import CharacterIdentityMerge
from ai_novel_studio.infrastructure.storage.character_identity_repository import (
    CharacterIdentityRepository,
    CharacterIdentityRepositoryError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class CharacterIdentityError(RuntimeError):
    pass


class CharacterIdentityService:
    """Applies only explicit, user-confirmed character identity decisions."""

    def __init__(self, project: ProjectRepository) -> None:
        self.repository = CharacterIdentityRepository(project)

    def merge(
        self,
        source_character_id: str,
        target_character_id: str,
        *,
        reason: str,
        confirmed_by_user: bool,
    ) -> CharacterIdentityMerge:
        if not confirmed_by_user:
            raise PermissionError("人物归并必须由用户明确确认")
        if source_character_id == target_character_id:
            raise CharacterIdentityError("不能把同一张人物卡归并到自身")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise CharacterIdentityError("人物归并原因不能为空")
        try:
            return self.repository.apply_merge(
                source_character_id,
                target_character_id,
                reason=normalized_reason,
            )
        except (KeyError, CharacterIdentityRepositoryError) as error:
            raise CharacterIdentityError(str(error)) from error
    def undo(self, merge_id: str, *, confirmed_by_user: bool) -> CharacterIdentityMerge:
        if not confirmed_by_user:
            raise PermissionError("撤销人物归并必须由用户明确确认")
        try:
            return self.repository.reverse_merge(merge_id)
        except (KeyError, CharacterIdentityRepositoryError) as error:
            raise CharacterIdentityError(str(error)) from error
