import runpy
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_python_module_launches_new_workbench_without_legacy_widgets(monkeypatch):
    def forbidden():
        raise AssertionError("default launch reached the retired widget workbench")

    monkeypatch.setitem(sys.modules, "ai_novel_studio.app", SimpleNamespace(main=forbidden))
    monkeypatch.setitem(
        sys.modules, "ai_novel_studio.ui_qml.bootstrap", SimpleNamespace(main=lambda: 23)
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module("ai_novel_studio", run_name="__main__")
    assert stopped.value.code == 23


def test_installed_default_and_explicit_legacy_commands_are_separate():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    commands = config["project"]["gui-scripts"]
    assert commands["ai-novel-studio"] == "ai_novel_studio.__main__:main"
    assert commands["ai-novel-studio-legacy"] == "ai_novel_studio.app:main"


@pytest.mark.parametrize(
    "resource",
    [
        "infrastructure/codex/skills/novel-edit/SKILL.md",
        "ui_qml/qml/pages/OutlinePage.qml",
        "ui_qml/qml/components/WriterInputReview.qml",
    ],
)
def test_frozen_bundle_includes_workflow_resources(resource):
    captured = {}

    def analysis(scripts, **options):
        captured.update(scripts=scripts, **options)
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    # Execute the spec declaration without running PyInstaller or scanning dependencies.
    spec = ROOT / "packaging" / "AI-Novel-Studio.spec"
    runpy.run_path(
        str(spec),
        init_globals={
            "SPECPATH": str(spec.parent),
            "Analysis": analysis,
            "PYZ": lambda *a, **kw: None,
            "EXE": lambda *a, **kw: None,
            "COLLECT": lambda *a, **kw: None,
        },
    )
    assert captured["scripts"] == [str(ROOT / "src" / "ai_novel_studio" / "__main__.py")]
    target = Path("ai_novel_studio") / resource
    matches = [
        Path(source) / target.relative_to(Path(destination))
        for source, destination in captured["datas"]
        if target.is_relative_to(Path(destination))
    ]
    assert matches == [ROOT / "src" / target]
    assert matches[0].is_file()
