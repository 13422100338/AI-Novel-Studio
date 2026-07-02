import json
import zipfile
from pathlib import Path

import pytest

from ai_novel_studio.infrastructure.storage.backup_service import BackupService
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.integrity import IntegrityChecker
from ai_novel_studio.infrastructure.storage.project_lock import ProjectLock
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _project_with_chapter(tmp_path: Path) -> tuple[ProjectRepository, str]:
    project = ProjectRepository.create(tmp_path / "novel", "My Novel")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(project.list_volumes()[0].id, "Opening", "1", "body")
    return project, chapter.id


def test_integrity_report_detects_missing_canonical_manuscript(tmp_path: Path) -> None:
    project, chapter_id = _project_with_chapter(tmp_path)
    chapter = ChapterRepository(project).get_chapter(chapter_id)
    (project.layout.root / chapter.content_path).unlink()

    report = IntegrityChecker(project).check()

    assert report.ok is False
    assert [(issue.code, issue.entity_id) for issue in report.issues] == [
        ("chapter_content_missing", chapter_id)
    ]


def test_integrity_report_detects_content_hash_mismatch(tmp_path: Path) -> None:
    project, chapter_id = _project_with_chapter(tmp_path)
    chapter = ChapterRepository(project).get_chapter(chapter_id)
    (project.layout.root / chapter.content_path).write_text("changed outside app", encoding="utf-8")

    report = IntegrityChecker(project).check()

    assert any(issue.code == "chapter_hash_mismatch" for issue in report.issues)


def test_project_lock_rejects_second_writer_and_contains_no_path(tmp_path: Path) -> None:
    project, _ = _project_with_chapter(tmp_path)
    first = ProjectLock(project.layout)
    second = ProjectLock(project.layout)

    first.acquire()
    try:
        payload = json.loads(first.path.read_text(encoding="utf-8"))
        assert set(payload) == {"pid", "created_at"}
        with pytest.raises(RuntimeError, match="already open for writing"):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()


def test_backup_contains_manifest_database_and_canonical_manuscript(tmp_path: Path) -> None:
    project, chapter_id = _project_with_chapter(tmp_path)
    chapter = ChapterRepository(project).get_chapter(chapter_id)

    archive = BackupService(project).create_backup()

    with zipfile.ZipFile(archive) as backup:
        names = set(backup.namelist())
        assert "project.json" in names
        assert "project.sqlite3" in names
        assert chapter.content_path in names
        assert backup.read(chapter.content_path).decode("utf-8") == "body"


def test_backup_retention_prunes_oldest_archives(tmp_path: Path) -> None:
    project, _ = _project_with_chapter(tmp_path)
    backups = BackupService(project)
    created = [backups.create_backup() for _ in range(3)]

    backups.prune(keep=2)

    remaining = sorted(project.layout.backups.glob("*.zip"))
    assert len(remaining) == 2
    assert created[0] not in remaining
