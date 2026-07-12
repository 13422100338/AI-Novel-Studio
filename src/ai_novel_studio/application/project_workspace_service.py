from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRepository,
    StaleChapterRevisionError,
)
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
    StaleRequirementError,
)
from ai_novel_studio.infrastructure.storage.project_lock import ProjectLock
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class WorkspaceNotOpenError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    id: str
    title: str
    root: Path


@dataclass(frozen=True, slots=True)
class ChapterTreeItem:
    id: str
    declared_number: str
    title: str
    word_count: int
    revision: int


@dataclass(frozen=True, slots=True)
class VolumeTreeItem:
    id: str
    title: str
    chapters: tuple[ChapterTreeItem, ...]


@dataclass(frozen=True, slots=True)
class ChapterWorkspace:
    id: str
    title: str
    declared_number: str
    content: str
    revision: int
    requirement_content: str
    requirement_revision: int
    requirement_locked: bool


@dataclass(frozen=True, slots=True)
class SaveChapterResult:
    chapter_id: str
    revision: int
    requirement_revision: int


class ProjectWorkspaceService:
    def __init__(self) -> None:
        self.project: ProjectRepository | None = None
        self._lock: ProjectLock | None = None

    def create_project(self, root: Path, title: str) -> ProjectSummary:
        self.close_project()
        project = ProjectRepository.create(root, title)
        self._set_project(project)
        return self.summary()

    def open_project(self, root: Path) -> ProjectSummary:
        self.close_project()
        project = ProjectRepository.open(root)
        self._set_project(project)
        return self.summary()

    def close_project(self) -> None:
        if self._lock is not None:
            self._lock.release()
        self._lock = None
        self.project = None

    def summary(self) -> ProjectSummary:
        project = self._project()
        return ProjectSummary(
            project.project.id,
            project.project.title,
            project.layout.root,
        )

    def volume_tree(self) -> tuple[VolumeTreeItem, ...]:
        project = self._project()
        chapters = ChapterRepository(project)
        return tuple(
            VolumeTreeItem(
                volume.id,
                volume.title,
                tuple(
                    ChapterTreeItem(
                        chapter.id,
                        chapter.declared_number,
                        chapter.title,
                        _word_count(chapters.read_content(chapter.id)),
                        chapter.revision,
                    )
                    for chapter in chapters.list_chapters(volume.id)
                ),
            )
            for volume in project.list_volumes()
        )

    def create_volume(self, title: str) -> VolumeTreeItem:
        volume = self._project().create_volume(title)
        return VolumeTreeItem(volume.id, volume.title, ())

    def create_chapter(
        self,
        volume_id: str,
        title: str,
        declared_number: str = "",
    ) -> ChapterTreeItem:
        project = self._project()
        chapter = ChapterRepository(project).create_chapter(
            volume_id,
            title,
            declared_number,
        )
        return ChapterTreeItem(
            chapter.id,
            chapter.declared_number,
            chapter.title,
            0,
            chapter.revision,
        )

    def rename_volume(self, volume_id: str, title: str) -> VolumeTreeItem:
        volume = self._project().rename_volume(volume_id, title)
        chapters = next(
            item.chapters for item in self.volume_tree() if item.id == volume.id
        )
        return VolumeTreeItem(volume.id, volume.title, chapters)

    def rename_chapter(self, chapter_id: str, title: str) -> ChapterTreeItem:
        project = self._project()
        chapter = ChapterRepository(project).rename_chapter(chapter_id, title)
        return ChapterTreeItem(
            chapter.id,
            chapter.declared_number,
            chapter.title,
            _word_count(ChapterRepository(project).read_content(chapter.id)),
            chapter.revision,
        )

    def delete_chapter(self, chapter_id: str) -> None:
        ChapterRepository(self._project()).delete_chapter(chapter_id)

    def delete_volume(self, volume_id: str) -> str:
        project = self._project()
        volumes = project.list_volumes()
        if len(volumes) <= 1:
            raise ValueError("项目必须至少保留一个卷")
        try:
            index = next(i for i, volume in enumerate(volumes) if volume.id == volume_id)
        except StopIteration as error:
            raise KeyError(f"unknown volume: {volume_id}") from error
        target = volumes[index - 1] if index > 0 else volumes[1]
        ChapterRepository(project).delete_volume(volume_id, target.id)
        return target.id

    def load_chapter(self, chapter_id: str) -> ChapterWorkspace:
        project = self._project()
        chapters = ChapterRepository(project)
        requirements = ChapterRequirementRepository(project)
        chapter = chapters.get_chapter(chapter_id, include_deleted=False)
        requirement = requirements.get_or_create(chapter_id)
        return ChapterWorkspace(
            chapter.id,
            chapter.title,
            chapter.declared_number,
            chapters.read_content(chapter.id),
            chapter.revision,
            requirement.content,
            requirement.revision,
            requirement.is_locked,
        )

    def save_chapter(
        self,
        chapter_id: str,
        content: str,
        *,
        expected_revision: int,
        requirement_content: str | None = None,
        expected_requirement_revision: int | None = None,
        requirement_locked: bool = False,
    ) -> SaveChapterResult:
        project = self._project()
        chapters = ChapterRepository(project)
        requirements = ChapterRequirementRepository(project)
        try:
            chapter = chapters.save_content(
                chapter_id,
                content,
                source="user_edit",
                reason="manual editor save",
                expected_revision=expected_revision,
            )
        except StaleChapterRevisionError as exc:
            raise RuntimeError("chapter revision is stale") from exc
        requirement = requirements.get_or_create(chapter_id)
        if requirement_content is not None:
            if expected_requirement_revision is None:
                expected_requirement_revision = requirement.revision
            try:
                requirement = requirements.update(
                    chapter_id,
                    requirement_content,
                    is_locked=requirement_locked,
                    expected_revision=expected_requirement_revision,
                )
            except StaleRequirementError as exc:
                raise RuntimeError("chapter requirement revision is stale") from exc
        return SaveChapterResult(chapter.id, chapter.revision, requirement.revision)

    def _set_project(self, project: ProjectRepository) -> None:
        lock = ProjectLock(project.layout)
        lock.acquire()
        self.project = project
        self._lock = lock

    def _project(self) -> ProjectRepository:
        if self.project is None:
            raise WorkspaceNotOpenError("project workspace is not open")
        return self.project


def _word_count(text: str) -> int:
    return sum(1 for character in text if not character.isspace())
