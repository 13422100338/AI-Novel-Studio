import tomllib
from importlib import import_module
from pathlib import Path

import ai_novel_studio


def test_planned_package_boundaries_are_importable() -> None:
    modules = (
        "ai_novel_studio.application",
        "ai_novel_studio.domain",
        "ai_novel_studio.pipelines",
        "ai_novel_studio.core.context",
        "ai_novel_studio.core.memory",
        "ai_novel_studio.infrastructure.llm",
        "ai_novel_studio.infrastructure.storage",
        "ai_novel_studio.ui",
    )

    for module in modules:
        assert import_module(module) is not None


def test_phase_one_storage_api_is_exported() -> None:
    storage = import_module("ai_novel_studio.infrastructure.storage")

    expected = {
        "BackupService",
        "ChapterRepository",
        "IntegrityChecker",
        "MigrationManager",
        "ProjectLayout",
        "ProjectLock",
        "ProjectRepository",
    }
    assert expected <= set(storage.__all__)
    assert all(hasattr(storage, name) for name in expected)


def test_phase_one_modules_are_importable() -> None:
    modules = (
        "ai_novel_studio.application.legacy_import",
        "ai_novel_studio.domain.chapter",
        "ai_novel_studio.domain.identifiers",
        "ai_novel_studio.domain.project",
        "ai_novel_studio.domain.volume",
        "ai_novel_studio.infrastructure.storage.atomic_file",
        "ai_novel_studio.infrastructure.storage.backup_service",
        "ai_novel_studio.infrastructure.storage.chapter_repository",
        "ai_novel_studio.infrastructure.storage.database",
        "ai_novel_studio.infrastructure.storage.integrity",
        "ai_novel_studio.infrastructure.storage.migration_manager",
        "ai_novel_studio.infrastructure.storage.project_layout",
        "ai_novel_studio.infrastructure.storage.project_lock",
        "ai_novel_studio.infrastructure.storage.project_repository",
    )

    for module in modules:
        assert import_module(module) is not None


def test_phase_five_package_version_matches_build_metadata() -> None:
    root = Path(__file__).parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert ai_novel_studio.__version__ == "0.5.0"
    assert metadata["project"]["version"] == ai_novel_studio.__version__
