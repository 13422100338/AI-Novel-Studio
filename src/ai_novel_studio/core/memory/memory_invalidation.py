from __future__ import annotations

from ai_novel_studio.infrastructure.storage.memory_dependency_repository import (
    MemoryDependencyRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class MemoryInvalidationService:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def invalidate_chapter(
        self,
        chapter_id: str,
        new_revision: int,
        new_hash: str,
    ) -> tuple[tuple[str, str], ...]:
        with self.project.database.connect() as connection, connection:
            return MemoryDependencyRepository.invalidate_in_connection(
                connection, chapter_id, new_revision, new_hash
            )

