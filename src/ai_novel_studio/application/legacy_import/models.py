from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class MigrationIssue:
    code: str
    message: str
    source: str


@dataclass(frozen=True, slots=True)
class LegacyChapter:
    title: str
    synopsis: str
    ai_synopsis: str
    declared_number: str
    source: str
    source_hash: str | None


@dataclass(frozen=True, slots=True)
class LegacyVolume:
    title: str
    synopsis: str
    chapters: tuple[LegacyChapter, ...]


@dataclass(frozen=True, slots=True)
class MigrationPreview:
    source_root: Path = field(repr=False)
    title: str
    global_synopsis: str
    characters: tuple[dict[str, Any], ...]
    volumes: tuple[LegacyVolume, ...]
    issues: tuple[MigrationIssue, ...]

    @property
    def volume_count(self) -> int:
        return len(self.volumes)

    @property
    def chapter_count(self) -> int:
        return sum(len(volume.chapters) for volume in self.volumes)


@dataclass(frozen=True, slots=True)
class MigrationReport:
    project_id: str
    imported_volumes: int
    imported_chapters: int
    skipped_chapters: int
    chapter_hashes: dict[str, str]
    issues: tuple[MigrationIssue, ...]
    preserved_memory: dict[str, Any]
