import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class BackupService:
    def __init__(self, project: ProjectRepository) -> None:
        self._project = project

    def create_backup(self) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        destination = self._project.layout.backups / f"backup-{timestamp}.zip"
        temporary_archive = destination.with_suffix(".zip.tmp")
        with tempfile.TemporaryDirectory(prefix="ai-novel-studio-backup-") as temporary_dir:
            snapshot = Path(temporary_dir) / "project.sqlite3"
            source_connection = self._project.database.connect()
            destination_connection = sqlite3.connect(snapshot)
            try:
                source_connection.backup(destination_connection)
            finally:
                destination_connection.close()
                source_connection.close()
            with zipfile.ZipFile(
                temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                archive.write(self._project.layout.manifest, "project.json")
                archive.write(snapshot, "project.sqlite3")
                for directory in (
                    self._project.layout.manuscript,
                    self._project.layout.assets,
                    self._project.layout.history,
                    self._project.layout.trash,
                ):
                    if not directory.exists():
                        continue
                    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
                        relative = path.relative_to(self._project.layout.root).as_posix()
                        archive.write(path, relative)
        temporary_archive.replace(destination)
        return destination

    def prune(self, keep: int) -> None:
        if keep < 1:
            raise ValueError("at least one backup must be kept")
        archives = sorted(self._project.layout.backups.glob("backup-*.zip"))
        for archive in archives[:-keep]:
            archive.unlink()
