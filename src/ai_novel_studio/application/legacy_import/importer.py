import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_novel_studio.application.legacy_import.docx_reader import (
    LegacyDocumentError,
    read_docx_text,
)
from ai_novel_studio.application.legacy_import.models import (
    MigrationIssue,
    MigrationPreview,
    MigrationReport,
)
from ai_novel_studio.infrastructure.storage.atomic_file import atomic_write_text
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class LegacyProjectImporter:
    def import_project(self, preview: MigrationPreview, destination: Path) -> MigrationReport:
        project = ProjectRepository.create(destination, preview.title)
        chapters = ChapterRepository(project)
        default_volume = project.list_volumes()[0]
        issues = list(preview.issues)
        chapter_hashes: dict[str, str] = {}
        memory_by_chapter: dict[str, str] = {}
        imported_volumes: list[str] = []

        for volume in preview.volumes:
            new_volume = project.create_volume(volume.title, volume.synopsis)
            imported_volumes.append(new_volume.id)
            for chapter in volume.chapters:
                if chapter.source_hash is None:
                    continue
                source = preview.source_root / Path(chapter.source)
                try:
                    current_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                    if current_hash != chapter.source_hash:
                        issues.append(
                            MigrationIssue(
                                "source_changed",
                                "document changed after migration preview",
                                chapter.source,
                            )
                        )
                        continue
                    content = read_docx_text(source)
                except (OSError, LegacyDocumentError):
                    issues.append(
                        MigrationIssue(
                            "document_unreadable",
                            "document became unreadable during import",
                            chapter.source,
                        )
                    )
                    continue
                imported = chapters.create_chapter(
                    new_volume.id,
                    chapter.title,
                    chapter.declared_number,
                    content,
                    chapter.synopsis,
                )
                chapter_hashes[imported.id] = hashlib.sha256(content.encode("utf-8")).hexdigest()
                if chapter.ai_synopsis:
                    memory_by_chapter[imported.id] = chapter.ai_synopsis

        if imported_volumes:
            chapters.delete_volume(default_volume.id, imported_volumes[0])

        report = MigrationReport(
            project_id=project.project.id,
            imported_volumes=len(imported_volumes),
            imported_chapters=len(chapter_hashes),
            skipped_chapters=preview.chapter_count - len(chapter_hashes),
            chapter_hashes=chapter_hashes,
            issues=tuple(issues),
            preserved_memory={
                "global_synopsis": preview.global_synopsis,
                "characters": list(preview.characters),
                "chapter_ai_synopses": memory_by_chapter,
            },
        )
        self._write_report(project, report)
        return report

    def _write_report(self, project: ProjectRepository, report: MigrationReport) -> None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        report_path = project.layout.reports / f"legacy-import-{timestamp}.json"
        payload: dict[str, Any] = asdict(report)
        atomic_write_text(
            report_path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
