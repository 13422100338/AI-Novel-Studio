from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.atomic_file import atomic_write_text
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@dataclass(frozen=True, slots=True)
class SelectedManifestItem:
    block_id: str
    category: str
    source_type: str
    source_id: str
    source_chapter_id: str | None
    source_revision: int | None
    source_hash: str
    rationale: str
    estimated_tokens: int
    used_fallback: bool


@dataclass(frozen=True, slots=True)
class OmittedManifestItem:
    block_id: str
    category: str
    source_type: str
    source_id: str
    source_chapter_id: str | None
    source_revision: int | None
    source_hash: str
    reason: str


@dataclass(frozen=True, slots=True)
class ContextManifest:
    id: str
    chapter_id: str
    run_id: str | None
    input_token_limit: int
    output_token_limit: int
    estimated_input_tokens: int
    selected: tuple[SelectedManifestItem, ...]
    omitted: tuple[OmittedManifestItem, ...]
    warnings: tuple[str, ...]
    created_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "chapter_id": self.chapter_id,
            "run_id": self.run_id,
            "input_token_limit": self.input_token_limit,
            "output_token_limit": self.output_token_limit,
            "estimated_input_tokens": self.estimated_input_tokens,
            "selected": [asdict(item) for item in self.selected],
            "omitted": [asdict(item) for item in self.omitted],
            "warnings": list(self.warnings),
            "created_at": self.created_at.isoformat(),
        }


def create_manifest_id() -> str:
    return new_id()


class ContextManifestRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def save(self, manifest: ContextManifest) -> Path:
        path = self.project.layout.pipeline / "manifests" / f"context_{manifest.id}.json"
        if path.exists():
            raise FileExistsError(f"上下文清单已存在：{manifest.id}")
        relative_path = path.relative_to(self.project.layout.root).as_posix()
        payload = json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n"
        atomic_write_text(path, payload)
        try:
            with self.project.database.connect() as connection, connection:
                connection.execute(
                    "INSERT INTO context_manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        manifest.id,
                        manifest.chapter_id,
                        manifest.run_id,
                        relative_path,
                        manifest.input_token_limit,
                        manifest.estimated_input_tokens,
                        manifest.output_token_limit,
                        "CURRENT",
                        manifest.created_at.isoformat(),
                    ),
                )
                recorded_chapters: set[str] = set()
                for item in manifest.selected:
                    if (
                        item.source_chapter_id is None
                        or item.source_revision is None
                        or not item.source_hash
                        or item.source_chapter_id in recorded_chapters
                    ):
                        continue
                    connection.execute(
                        "INSERT INTO memory_dependencies VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            new_id(),
                            "MANIFEST",
                            manifest.id,
                            item.source_chapter_id,
                            item.source_revision,
                            item.source_hash,
                            "CURRENT",
                        ),
                    )
                    recorded_chapters.add(item.source_chapter_id)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path

    def load(self, manifest_id: str) -> ContextManifest:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM context_manifests WHERE id = ? AND status = 'CURRENT'",
                (manifest_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown context manifest: {manifest_id}")
        path = (self.project.layout.root / row["content_path"]).resolve()
        root = self.project.layout.root.resolve()
        if not path.is_relative_to(root):
            raise ValueError("上下文清单路径越出项目目录")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ContextManifest(
            id=payload["id"],
            chapter_id=payload["chapter_id"],
            run_id=payload["run_id"],
            input_token_limit=payload["input_token_limit"],
            output_token_limit=payload["output_token_limit"],
            estimated_input_tokens=payload["estimated_input_tokens"],
            selected=tuple(SelectedManifestItem(**item) for item in payload["selected"]),
            omitted=tuple(OmittedManifestItem(**item) for item in payload["omitted"]),
            warnings=tuple(payload["warnings"]),
            created_at=datetime.fromisoformat(payload["created_at"]),
        )

    def latest_for_chapter(self, chapter_id: str) -> ContextManifest | None:
        with self.project.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id
                FROM context_manifests
                WHERE chapter_id = ? AND status = 'CURRENT'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (chapter_id,),
            ).fetchone()
        return None if row is None else self.load(str(row["id"]))


def utc_now() -> datetime:
    return datetime.now(UTC)
