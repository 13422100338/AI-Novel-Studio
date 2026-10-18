from __future__ import annotations

from pathlib import Path


def test_backend_never_imports_harness() -> None:
    """Contract §3: Backend layers must never import the Harness package.

    domain/core hold the truth kernel; application/infrastructure are the
    facade and storage layers. Harness may call all of them, never the
    reverse.
    """
    package_root = Path(__file__).resolve().parents[3] / "src" / "ai_novel_studio"
    offenders: list[str] = []
    for layer in ("domain", "core", "application", "infrastructure"):
        for path in (package_root / layer).rglob("*.py"):
            if "ai_novel_studio.harness" in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(package_root).as_posix())

    assert offenders == []


def test_core_tools_never_import_storage_repositories() -> None:
    package_root = Path(__file__).resolve().parents[3] / "src" / "ai_novel_studio"
    source = (package_root / "harness" / "core_tools.py").read_text(
        encoding="utf-8"
    )

    assert "ai_novel_studio.infrastructure.storage" not in source
