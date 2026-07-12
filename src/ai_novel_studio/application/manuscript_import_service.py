from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_CHAPTER_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?P<number>第[\d零〇一二三四五六七八九十百千万]+章)\s*(?P<title>.*?)\s*$"
)
_VOLUME_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?P<title>第[\d零〇一二三四五六七八九十百千万]+卷.*?)\s*$"
)


@dataclass(frozen=True, slots=True)
class ParsedImportChapter:
    declared_number: str
    title: str
    content: str


@dataclass(frozen=True, slots=True)
class ParsedImportVolume:
    title: str
    chapters: tuple[ParsedImportChapter, ...]


@dataclass(frozen=True, slots=True)
class ManuscriptImportReport:
    source: Path
    imported_volumes: int
    imported_chapters: int
    first_chapter_id: str | None


class ManuscriptImportService:
    supported_suffixes = frozenset({".md", ".txt"})

    def import_file(self, project: ProjectRepository, source: Path) -> ManuscriptImportReport:
        source = source.resolve()
        volumes = self.parse_file(source)
        chapter_repository = ChapterRepository(project)
        first_chapter_id: str | None = None
        imported_chapters = 0

        for volume in volumes:
            created_volume = project.create_volume(volume.title)
            for chapter in volume.chapters:
                created_chapter = chapter_repository.create_chapter(
                    created_volume.id,
                    chapter.title,
                    chapter.declared_number,
                    chapter.content,
                )
                first_chapter_id = first_chapter_id or created_chapter.id
                imported_chapters += 1

        return ManuscriptImportReport(
            source=source,
            imported_volumes=len(volumes),
            imported_chapters=imported_chapters,
            first_chapter_id=first_chapter_id,
        )

    def parse_file(self, source: Path) -> tuple[ParsedImportVolume, ...]:
        if source.suffix.lower() not in self.supported_suffixes:
            raise ValueError("only .md and .txt manuscript imports are supported")
        text = self._read_text(source)
        return self.parse_text(text, fallback_title=source.stem)

    def parse_text(self, text: str, *, fallback_title: str) -> tuple[ParsedImportVolume, ...]:
        current_volume_title = f"导入：{fallback_title}"
        volume_chapters: list[ParsedImportChapter] = []
        volumes: list[ParsedImportVolume] = []
        current_number = ""
        current_title = fallback_title
        current_lines: list[str] = []
        has_chapter = False

        def flush_chapter() -> None:
            nonlocal current_lines, current_number, current_title, has_chapter
            content = "\n".join(current_lines).strip()
            if has_chapter or content:
                volume_chapters.append(
                    ParsedImportChapter(
                        declared_number=current_number,
                        title=current_title or current_number or fallback_title,
                        content=content,
                    )
                )
            current_lines = []
            current_number = ""
            current_title = fallback_title
            has_chapter = False

        def flush_volume() -> None:
            nonlocal volume_chapters
            if volume_chapters:
                volumes.append(
                    ParsedImportVolume(
                        title=current_volume_title,
                        chapters=tuple(volume_chapters),
                    )
                )
            volume_chapters = []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            volume_match = _VOLUME_RE.match(line)
            if volume_match and not has_chapter and not current_lines:
                current_volume_title = volume_match.group("title").strip()
                continue
            if volume_match:
                flush_chapter()
                flush_volume()
                current_volume_title = volume_match.group("title").strip()
                continue

            chapter_match = _CHAPTER_RE.match(line)
            if chapter_match and self._is_end_marker(chapter_match):
                continue
            if chapter_match:
                flush_chapter()
                current_number = chapter_match.group("number").strip()
                current_title = self._clean_title(
                    chapter_match.group("title").strip(),
                    fallback=current_number,
                )
                has_chapter = True
                continue
            current_lines.append(raw_line)

        flush_chapter()
        flush_volume()
        if volumes:
            return tuple(volumes)
        return (
            ParsedImportVolume(
                title=current_volume_title,
                chapters=(
                    ParsedImportChapter(
                        declared_number="",
                        title=fallback_title,
                        content=text.strip(),
                    ),
                ),
            ),
        )

    @staticmethod
    def _read_text(source: Path) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return source.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return source.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _clean_title(title: str, *, fallback: str) -> str:
        title = re.sub(r"^[：:\-\s]+", "", title).strip()
        return title or fallback

    @staticmethod
    def _is_end_marker(match: re.Match[str]) -> bool:
        title = match.group("title").strip()
        return title in {"完", "（完）", "(完)", "结束"}
