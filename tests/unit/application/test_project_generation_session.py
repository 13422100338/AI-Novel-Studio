from __future__ import annotations

import inspect

from ai_novel_studio.application.project_generation_session import (
    ProjectGenerationSession,
)


def test_project_generation_session_has_no_pyside_dependency() -> None:
    source = inspect.getsource(inspect.getmodule(ProjectGenerationSession))

    assert "PySide6" not in source
    assert "QObject" not in source
    assert "Signal" not in source
