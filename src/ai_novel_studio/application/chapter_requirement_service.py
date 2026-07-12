from __future__ import annotations

from ai_novel_studio.domain.generation import ChapterRequirement
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)


class LockedRequirementError(PermissionError):
    pass


class ChapterRequirementService:
    def __init__(self, repository: ChapterRequirementRepository) -> None:
        self.repository = repository

    def get_or_create(self, chapter_id: str) -> ChapterRequirement:
        return self.repository.get_or_create(chapter_id)

    def save_user(
        self,
        chapter_id: str,
        content: str,
        *,
        is_locked: bool,
        expected_revision: int,
    ) -> ChapterRequirement:
        normalized = self._require_content(content)
        return self.repository.update(
            chapter_id,
            normalized,
            is_locked=is_locked,
            expected_revision=expected_revision,
        )

    def apply_model_candidate(
        self,
        chapter_id: str,
        content: str,
        *,
        expected_revision: int,
    ) -> ChapterRequirement:
        current = self.repository.get_or_create(chapter_id)
        if current.is_locked:
            raise LockedRequirementError("锁定的当前章要求不能被模型候选覆盖")
        normalized = self._require_content(content)
        return self.repository.update(
            chapter_id,
            normalized,
            is_locked=False,
            expected_revision=expected_revision,
        )

    @staticmethod
    def _require_content(content: str) -> str:
        normalized = content.strip()
        if not normalized:
            raise ValueError("当前章要求不能为空")
        return normalized
