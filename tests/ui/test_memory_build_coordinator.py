from pathlib import Path

from pytestqt.qtbot import QtBot

from ai_novel_studio.application.manuscript_memory_build_service import (
    ManuscriptMemoryBuildReport,
)
from ai_novel_studio.application.memory_build_coordinator import MemoryBuildCoordinator
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class FakeBuildService:
    def build_all(self, project, *, progress=None, should_cancel=None):  # type: ignore[no-untyped-def]
        assert project is not None
        assert progress is not None
        progress(1, 1, "第一章")
        return ManuscriptMemoryBuildReport(1, 1, 0, 1)


def test_memory_build_runs_outside_ui_and_emits_progress(
    qtbot: QtBot, tmp_path: Path
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    coordinator = MemoryBuildCoordinator(FakeBuildService())  # type: ignore[arg-type]
    progress: list[tuple[int, int, str]] = []
    reports: list[ManuscriptMemoryBuildReport] = []
    coordinator.progress_changed.connect(
        lambda done, total, title: progress.append((done, total, title))
    )
    coordinator.completed.connect(reports.append)

    coordinator.start(project)

    qtbot.waitUntil(lambda: bool(reports), timeout=3_000)
    assert progress == [(1, 1, "第一章")]
    assert reports[0].processed_chapters == 1
    assert coordinator.is_running is False
