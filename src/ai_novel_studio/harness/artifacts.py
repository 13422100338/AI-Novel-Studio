from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class ArtifactKind(StrEnum):
    """Kinds of content stored in the harness artifact store (design §20, §44).

    DRAFT_CHECKPOINT separates mid-stream stable checkpoints from
    PARTIAL_DRAFT (interrupted/cancelled remnants) per design §53.1; both
    share the same content-addressed store, object types stay distinct.
    """

    TOOL_RESULT = "TOOL_RESULT"
    DRAFT_CANDIDATE = "DRAFT_CANDIDATE"
    PARTIAL_DRAFT = "PARTIAL_DRAFT"
    DRAFT_CHECKPOINT = "DRAFT_CHECKPOINT"
    SUMMARY_REVISION = "SUMMARY_REVISION"


class ArtifactBackend(Protocol):
    """Pluggable content-addressed persistence for artifacts."""

    def exists(self, artifact_id: str) -> bool: ...

    def read(self, artifact_id: str) -> tuple[bytes, dict[str, object]]: ...

    def write(self, artifact_id: str, content: bytes, metadata: dict[str, object]) -> None: ...

    def list_ids(self) -> tuple[str, ...]: ...

    def delete(self, artifact_id: str) -> None: ...


def _artifact_id(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


@dataclass(frozen=True, slots=True)
class Artifact:
    """Content-addressed artifact record (design v0.3 §20, §67)."""

    artifact_id: str
    kind: ArtifactKind
    run_id: str
    content_type: str
    created_at: datetime
    content: bytes

    def __post_init__(self) -> None:
        if not self.artifact_id.startswith("sha256:") or len(self.artifact_id) != 71:
            raise ValueError("artifact_id must be a sha256 content address")
        if not isinstance(self.kind, ArtifactKind):
            raise ValueError("kind must be an ArtifactKind")
        if not self.run_id.strip():
            raise ValueError("run_id cannot be empty")
        if not self.content_type.strip():
            raise ValueError("content_type cannot be empty")


class ArtifactStore:
    """Content-addressed artifact storage with first-write dedup (design §20).

    Full tool results and draft candidates live here while the model context
    carries only excerpts plus the artifact_id. Identical content always maps
    to the same artifact_id, so repeated writes are idempotent and the first
    write's metadata wins.
    """

    def __init__(self, backend: ArtifactBackend) -> None:
        self._backend = backend

    def put(
        self,
        kind: ArtifactKind,
        run_id: str,
        content: bytes,
        *,
        content_type: str = "text/plain",
    ) -> Artifact:
        artifact_id = _artifact_id(content)
        now = datetime.now(UTC)
        metadata: dict[str, object] = {
            "kind": kind.value,
            "run_id": run_id,
            "content_type": content_type,
            "created_at": now.isoformat(),
        }
        if not self._backend.exists(artifact_id):
            self._backend.write(artifact_id, content, metadata)
        return self.get(artifact_id)

    def get(self, artifact_id: str) -> Artifact:
        content, metadata = self._backend.read(artifact_id)
        kind_value = metadata.get("kind")
        run_id = metadata.get("run_id")
        content_type = metadata.get("content_type")
        created_at = metadata.get("created_at")
        if not isinstance(kind_value, str) or not isinstance(run_id, str):
            raise ValueError(f"artifact {artifact_id} has invalid metadata")
        if not isinstance(content_type, str) or not isinstance(created_at, str):
            raise ValueError(f"artifact {artifact_id} has invalid metadata")
        return Artifact(
            artifact_id=artifact_id,
            kind=ArtifactKind(kind_value),
            run_id=run_id,
            content_type=content_type,
            created_at=datetime.fromisoformat(created_at),
            content=content,
        )

    def exists(self, artifact_id: str) -> bool:
        return self._backend.exists(artifact_id)

    def list_ids(self) -> tuple[str, ...]:
        return self._backend.list_ids()

    def delete(self, artifact_id: str) -> None:
        self._backend.delete(artifact_id)


class FileArtifactBackend:
    """File-based backend: <root>/artifacts/<sha256-hex>.bin + .json sidecar."""

    def __init__(self, root: Path) -> None:
        self._directory = Path(root) / "artifacts"

    def exists(self, artifact_id: str) -> bool:
        return self._content_path(artifact_id).exists()

    def read(self, artifact_id: str) -> tuple[bytes, dict[str, object]]:
        content_path = self._content_path(artifact_id)
        metadata_path = self._metadata_path(artifact_id)
        if not content_path.exists() or not metadata_path.exists():
            raise KeyError(f"unknown artifact: {artifact_id}")
        content = content_path.read_bytes()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError(f"artifact {artifact_id} has invalid metadata")
        return content, metadata

    def write(
        self, artifact_id: str, content: bytes, metadata: dict[str, object]
    ) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        self._content_path(artifact_id).write_bytes(content)
        self._metadata_path(artifact_id).write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )

    def list_ids(self) -> tuple[str, ...]:
        if not self._directory.is_dir():
            return ()
        return tuple(
            f"sha256:{path.stem}"
            for path in sorted(self._directory.glob("*.json"))
        )

    def delete(self, artifact_id: str) -> None:
        self._content_path(artifact_id).unlink(missing_ok=True)
        self._metadata_path(artifact_id).unlink(missing_ok=True)

    def _content_path(self, artifact_id: str) -> Path:
        return self._directory / f"{artifact_id.removeprefix('sha256:')}.bin"

    def _metadata_path(self, artifact_id: str) -> Path:
        return self._directory / f"{artifact_id.removeprefix('sha256:')}.json"


class ProjectArtifactBackend(FileArtifactBackend):
    """Project-rooted artifact backend (design v0.3 §53.1, §68).

    Artifacts live inside the project's shared recovery tree at
    `<project>/.ai_pipeline/artifacts/`, alongside the backend's
    `.ai_pipeline/checkpoints/` - one recovery directory family for both
    the harness and the domain side, with object types kept separate.
    The directory is created on first write.
    """

    def __init__(self, project: ProjectRepository) -> None:
        super().__init__(project.layout.pipeline)
