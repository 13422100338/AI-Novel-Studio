from __future__ import annotations

from pathlib import Path


def test_application_has_no_pyside_dependencies() -> None:
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

    assert pyside_modules == []
