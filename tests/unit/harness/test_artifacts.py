from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.harness.artifacts import (
    ArtifactKind,
    ArtifactStore,
    FileArtifactBackend,
    ProjectArtifactBackend,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def test_put_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    store = ArtifactStore(FileArtifactBackend(tmp_path))

    first = store.put(ArtifactKind.TOOL_RESULT, "run-1", b"hello")
    again = store.put(ArtifactKind.DRAFT_CANDIDATE, "run-2", b"hello")

    assert first.artifact_id == again.artifact_id
    assert first.kind is ArtifactKind.TOOL_RESULT
    assert first.run_id == "run-1"
    assert first.content == b"hello"
    assert store.exists(first.artifact_id)


def test_get_returns_round_tripped_content(tmp_path: Path) -> None:
    store = ArtifactStore(FileArtifactBackend(tmp_path))

    artifact = store.put(
        ArtifactKind.PARTIAL_DRAFT, "run-1", "残稿".encode(), content_type="text/markdown"
    )
    loaded = store.get(artifact.artifact_id)

    assert loaded == artifact
    assert loaded.content.decode() == "残稿"
    assert loaded.content_type == "text/markdown"


def test_different_content_has_different_addresses(tmp_path: Path) -> None:
    store = ArtifactStore(FileArtifactBackend(tmp_path))

    left = store.put(ArtifactKind.TOOL_RESULT, "run-1", b"a")
    right = store.put(ArtifactKind.TOOL_RESULT, "run-1", b"b")

    assert left.artifact_id != right.artifact_id


def test_unknown_artifact_raises(tmp_path: Path) -> None:
    store = ArtifactStore(FileArtifactBackend(tmp_path))

    with pytest.raises(KeyError):
        store.get("sha256:" + "0" * 64)
    assert not store.exists("sha256:" + "0" * 64)


def test_project_backend_roots_artifacts_under_pipeline(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Project artifacts")
    store = ArtifactStore(ProjectArtifactBackend(project))

    artifact = store.put(ArtifactKind.DRAFT_CHECKPOINT, "run-1", "正文".encode())

    expected_dir = project.layout.root / ".ai_pipeline" / "artifacts"
    assert (
        expected_dir / f"{artifact.artifact_id.removeprefix('sha256:')}.bin"
    ).is_file()
    assert store.get(artifact.artifact_id).kind is ArtifactKind.DRAFT_CHECKPOINT
