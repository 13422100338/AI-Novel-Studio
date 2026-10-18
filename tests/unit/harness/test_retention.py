from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_novel_studio.harness.artifacts import (
    ArtifactKind,
    ArtifactStore,
    FileArtifactBackend,
)
from ai_novel_studio.harness.retention import ArtifactRetentionService


def _store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(FileArtifactBackend(tmp_path))


def test_cleanup_removes_expired_tool_results_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    tool_result = store.put(ArtifactKind.TOOL_RESULT, "run-1", "工具结果".encode())
    summary = store.put(ArtifactKind.SUMMARY_REVISION, "run-1", "摘要".encode())
    candidate = store.put(ArtifactKind.DRAFT_CANDIDATE, "run-1", "候选稿".encode())
    checkpoint = store.put(ArtifactKind.DRAFT_CHECKPOINT, "run-1", "检查点".encode())
    partial = store.put(ArtifactKind.PARTIAL_DRAFT, "run-1", "残稿".encode())
    service = ArtifactRetentionService(store)
    now = datetime.now(UTC) + timedelta(days=31)

    result = service.cleanup(now=now)

    assert tool_result.artifact_id in result.removed
    assert summary.artifact_id in result.removed
    assert candidate.artifact_id in result.kept
    assert checkpoint.artifact_id in result.kept
    assert partial.artifact_id in result.kept
    assert not store.exists(tool_result.artifact_id)
    assert store.exists(candidate.artifact_id)


def test_cleanup_keeps_fresh_tool_results(tmp_path: Path) -> None:
    store = _store(tmp_path)
    tool_result = store.put(ArtifactKind.TOOL_RESULT, "run-1", "新结果".encode())
    service = ArtifactRetentionService(store)
    now = datetime.now(UTC) + timedelta(days=30)

    result = service.cleanup(now=now)

    assert tool_result.artifact_id in result.kept
    assert store.exists(tool_result.artifact_id)


def test_cleanup_returns_empty_when_no_artifacts(tmp_path: Path) -> None:
    store = _store(tmp_path)

    result = ArtifactRetentionService(store).cleanup()

    assert result.removed == ()
    assert result.kept == ()
