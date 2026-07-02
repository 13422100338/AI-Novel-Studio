import subprocess
from pathlib import Path


def test_powershell_helper_prefers_project_virtual_environment() -> None:
    project_root = Path(__file__).parents[2]
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ". ./scripts/resolve_python.ps1; Resolve-ProjectPython",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )

    assert Path(result.stdout.strip()).resolve() == (
        project_root / ".venv" / "Scripts" / "python.exe"
    ).resolve()


def test_build_and_release_scripts_use_resolved_interpreter() -> None:
    project_root = Path(__file__).parents[2]

    for name in ("build_windows.ps1", "verify_release.ps1"):
        content = (project_root / "scripts" / name).read_text(encoding="utf-8")
        assert "$Python = Resolve-ProjectPython" in content
        assert "& $Python -m" in content
