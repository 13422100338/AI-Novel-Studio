from __future__ import annotations

from pathlib import Path

from ai_novel_studio.core.context.context_manifest import (
    ContextManifest,
    ContextManifestRepository,
    create_manifest_id,
    utc_now,
)
from ai_novel_studio.domain.generation import CreationMode, GenerationStatus
from ai_novel_studio.harness.artifacts import (
    ArtifactKind,
    ArtifactStore,
    ProjectArtifactBackend,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.checkpoint_repository import (
    CheckpointRepository,
)
from ai_novel_studio.infrastructure.storage.generation_repository import (
    GenerationRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _legacy_streaming(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Shared checkpoints")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(volume.id, "旧管线章", "1")
    runs = GenerationRepository(project)
    preparing = runs.create_preparing(
        chapter_id=chapter.id,
        mode=CreationMode.BASIC,
        brief_id=None,
        brief_revision=None,
        model_provider_id="provider-1",
        model_id="writer-1",
        output_token_limit=16_000,
        prompt_version="prose-v1",
    )
    manifest = ContextManifest(
        create_manifest_id(),
        chapter.id,
        preparing.id,
        100_000,
        16_000,
        0,
        (),
        (),
        (),
        utc_now(),
    )
    ContextManifestRepository(project).save(manifest)
    ready = runs.transition(
        preparing.id,
        GenerationStatus.PREPARING,
        GenerationStatus.READY,
        context_manifest_id=manifest.id,
    )
    streaming = runs.transition(
        ready.id, GenerationStatus.READY, GenerationStatus.STREAMING
    )
    return project, streaming, runs


def test_harness_and_legacy_checkpoints_share_recovery_tree(tmp_path: Path) -> None:
    project, streaming, runs = _legacy_streaming(tmp_path)

    legacy = CheckpointRepository(project, runs)
    legacy.append(streaming.id, "旧管线检查点正文")

    store = ArtifactStore(ProjectArtifactBackend(project))
    artifact = store.put(
        ArtifactKind.DRAFT_CHECKPOINT,
        "harness-run-1",
        "新编排检查点正文".encode(),
    )

    root = project.layout.root
    artifacts_dir = root / ".ai_pipeline" / "artifacts"
    checkpoints_dir = root / ".ai_pipeline" / "checkpoints"
    assert artifacts_dir.is_dir()
    assert checkpoints_dir.is_dir()
    assert (
        artifacts_dir / f"{artifact.artifact_id.removeprefix('sha256:')}.bin"
    ).is_file()
    assert any(checkpoints_dir.glob("run_*/checkpoint_*.md"))
    loaded = store.get(artifact.artifact_id)
    assert loaded.kind is ArtifactKind.DRAFT_CHECKPOINT
    assert loaded.content.decode() == "新编排检查点正文"


def test_project_backend_creates_directory_on_first_write(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "First write")
    expected_dir = project.layout.root / ".ai_pipeline" / "artifacts"
    assert not expected_dir.exists()

    store = ArtifactStore(ProjectArtifactBackend(project))
    artifact = store.put(ArtifactKind.TOOL_RESULT, "run-1", "结果".encode())

    assert expected_dir.is_dir()
    assert (
        expected_dir / f"{artifact.artifact_id.removeprefix('sha256:')}.json"
    ).is_file()
