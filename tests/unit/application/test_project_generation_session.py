from __future__ import annotations

import inspect
from dataclasses import fields

from ai_novel_studio.application.project_generation_session import (
    ProjectGenerationSession,
)
from ai_novel_studio.application.project_runtime import ProjectRuntime


def test_project_generation_session_has_no_pyside_dependency() -> None:
    source = inspect.getsource(inspect.getmodule(ProjectGenerationSession))

    assert "PySide6" not in source
    assert "QObject" not in source
    assert "Signal" not in source


def test_project_runtime_owns_framework_neutral_generation_session() -> None:
    source = inspect.getsource(inspect.getmodule(ProjectRuntime))
    field_names = {field.name for field in fields(ProjectRuntime)}

    assert "PySide6" not in source
    assert "ai_novel_studio.ui" not in source
    assert "project_generation_runtime" not in source
    assert "generation_session" in field_names
    assert "generation_runtime" not in field_names
