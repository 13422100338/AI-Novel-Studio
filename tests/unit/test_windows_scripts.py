import subprocess
from pathlib import Path


def test_powershell_helper_resolves_runnable_interpreter() -> None:
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

    resolved = Path(result.stdout.strip()).resolve()
    virtual_environment = (project_root / ".venv" / "Scripts" / "python.exe").resolve()
    if virtual_environment.is_file():
        assert resolved == virtual_environment
    else:
        common_dir = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=project_root,
            check=True,
            capture_output=True,
            encoding="utf-8",
        )
        shared_environment = (
            Path(common_dir.stdout.strip()).parent / ".venv" / "Scripts" / "python.exe"
        )
        if shared_environment.is_file():
            assert resolved == shared_environment.resolve()
        else:
            assert resolved.is_file()
            assert resolved.name.casefold() == "python.exe"


def test_build_and_release_scripts_use_resolved_interpreter() -> None:
    project_root = Path(__file__).parents[2]

    for name in ("build_windows.ps1", "verify_release.ps1"):
        content = (project_root / "scripts" / name).read_text(encoding="utf-8")
        assert "$Python = Resolve-ProjectPython" in content
        assert "& $Python -m" in content


def test_shared_interpreter_resolves_under_windows_chinese_codepage(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[2]
    common_dir = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=project_root,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    expected = Path(common_dir.stdout.strip()).parent / ".venv" / "Scripts" / "python.exe"
    if not expected.is_file():
        import pytest

        pytest.skip("requires the shared development environment")
    destination = str(tmp_path / "resolved.txt").replace("'", "''")
    script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::GetEncoding(936); "
        ". ./scripts/resolve_python.ps1; $resolvedPython = Resolve-ProjectPython; "
        f"[System.IO.File]::WriteAllText('{destination}', $resolvedPython, "
        "[System.Text.UTF8Encoding]::new($false)); "
        "if ([Console]::OutputEncoding.CodePage -ne 936) { exit 2 }"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    resolved = Path((tmp_path / "resolved.txt").read_text(encoding="utf-8")).resolve()
    assert resolved == expected.resolve()


def test_release_scripts_fail_on_native_errors_and_build_uses_controlled_temp() -> None:
    project_root = Path(__file__).parents[2]
    build = (project_root / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    release = (project_root / "scripts" / "verify_release.ps1").read_text(
        encoding="utf-8"
    )

    assert "$LASTEXITCODE" in build
    assert "$LASTEXITCODE" in release
    assert "--basetemp" in build
    assert "Split-Path -Parent $testTemp" in build
