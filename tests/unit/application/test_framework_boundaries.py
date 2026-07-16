from __future__ import annotations

from pathlib import Path


def test_application_pyside_dependencies_are_limited_to_model_runtime() -> None:
    application_root = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "ai_novel_studio"
        / "application"
    )
    pyside_modules = sorted(
        path.relative_to(application_root).as_posix()
        for path in application_root.rglob("*.py")
        if "PySide6" in path.read_text(encoding="utf-8")
    )

    assert pyside_modules == [
        "model_settings_controller.py",
        "model_task_coordinator.py",
    ]
