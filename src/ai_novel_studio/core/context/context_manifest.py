from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.atomic_file import atomic_write_text
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

LEGACY_CONTEXT_MANIFEST_SCHEMA_VERSION = 1
PREVIOUS_CONTEXT_MANIFEST_SCHEMA_VERSION = 2
CONTEXT_MANIFEST_SCHEMA_VERSION = 3
CONTEXT_COMPILER_VERSION = "context-compiler/2.0"
_MAX_TRACE_TEXT = 512
_MAX_TRACE_HASH = 256
_MAX_EXPANDED_DOCUMENTS = 64
_MAX_RETRIEVAL_ROUTES = 16
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_VALID_RETRIEVAL_ROUTES = frozenset(
    {"EXACT_PHRASE", "KEYWORD", "EMBEDDING", "SUBJECT"}
)


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


def _bounded_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= _MAX_TRACE_TEXT
    )


@dataclass(frozen=True, slots=True)
class RetrievalTraceItem:
    """Diagnostic retrieval provenance for one candidate context block.

    Ranges are zero-based half-open code-point offsets; routes and scores
    are recorded verbatim for explainability only and never authorize
    content. No manuscript body text is stored here.
    """

    block_id: str
    selected: bool
    omission_reason: str | None
    document_id: str
    expanded_document_ids: tuple[str, ...]
    source_id: str
    chapter_id: str | None
    volume_id: str | None
    revision: int | None
    source_hash: str
    start: int | None
    end: int | None
    retrieval_routes: tuple[str, ...]
    lexical_score: float
    semantic_score: float
    participant_boost: float
    pinned_weight: float
    recency_score: float
    stale_penalty: float
    total_score: float

    def __post_init__(self) -> None:
        if isinstance(self.expanded_document_ids, list):
            object.__setattr__(
                self,
                "expanded_document_ids",
                tuple(self.expanded_document_ids),
            )
        if isinstance(self.retrieval_routes, list):
            object.__setattr__(
                self,
                "retrieval_routes",
                tuple(self.retrieval_routes),
            )
        if (
            not _bounded_text(self.block_id)
            or not isinstance(self.selected, bool)
            or not _bounded_text(self.document_id)
            or not _bounded_text(self.source_id)
            or not isinstance(self.source_hash, str)
            or not _SHA256_PATTERN.match(self.source_hash)
        ):
            raise ValueError("retrieval trace item is invalid")
        if self.selected:
            if self.omission_reason is not None:
                raise ValueError("retrieval trace item is invalid")
        elif not _bounded_text(self.omission_reason):
            raise ValueError("retrieval trace item is invalid")
        if (
            not isinstance(self.expanded_document_ids, tuple)
            or len(self.expanded_document_ids) < 1
            or len(self.expanded_document_ids) > _MAX_EXPANDED_DOCUMENTS
            or len(set(self.expanded_document_ids)) != len(self.expanded_document_ids)
            or any(not _bounded_text(item) for item in self.expanded_document_ids)
            or self.document_id not in self.expanded_document_ids
        ):
            raise ValueError("retrieval trace item is invalid")
        if (
            not isinstance(self.retrieval_routes, tuple)
            or len(self.retrieval_routes) < 1
            or len(self.retrieval_routes) > _MAX_RETRIEVAL_ROUTES
            or len(set(self.retrieval_routes)) != len(self.retrieval_routes)
            or any(route not in _VALID_RETRIEVAL_ROUTES for route in self.retrieval_routes)
        ):
            raise ValueError("retrieval trace item is invalid")
        for optional_id in (self.chapter_id, self.volume_id):
            if optional_id is not None and not _bounded_text(optional_id):
                raise ValueError("retrieval trace item is invalid")
        if self.revision is not None and (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ValueError("retrieval trace item is invalid")
        if (self.start is None) != (self.end is None):
            raise ValueError("retrieval trace item is invalid")
        if self.start is not None or self.end is not None:
            if (
                isinstance(self.start, bool)
                or isinstance(self.end, bool)
                or not isinstance(self.start, int)
                or not isinstance(self.end, int)
                or self.start < 0
                or self.end <= self.start
            ):
                raise ValueError("retrieval trace item is invalid")
        for score in (
            self.lexical_score,
            self.semantic_score,
            self.participant_boost,
            self.pinned_weight,
            self.recency_score,
            self.stale_penalty,
            self.total_score,
        ):
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
            ):
                raise ValueError("retrieval trace item is invalid")


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
    schema_version: int = CONTEXT_MANIFEST_SCHEMA_VERSION
    compiler_version: str | None = CONTEXT_COMPILER_VERSION
    target_chapter_revision: int | None = None
    requirement_revision: int | None = None
    retrieval_trace: tuple[RetrievalTraceItem, ...] = ()

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version
            not in {
                LEGACY_CONTEXT_MANIFEST_SCHEMA_VERSION,
                PREVIOUS_CONTEXT_MANIFEST_SCHEMA_VERSION,
                CONTEXT_MANIFEST_SCHEMA_VERSION,
            }
        ):
            raise ValueError("context manifest schema version is invalid")

        if self.schema_version != CONTEXT_MANIFEST_SCHEMA_VERSION and (
            self.retrieval_trace
        ):
            raise ValueError("context manifest retrieval trace is invalid")
        if len(set(item.block_id for item in self.retrieval_trace)) != len(
            self.retrieval_trace
        ) or any(
            not isinstance(item, RetrievalTraceItem)
            for item in self.retrieval_trace
        ):
            raise ValueError("context manifest retrieval trace is invalid")

        selected_ids = [item.block_id for item in self.selected]
        omitted_ids = [item.block_id for item in self.omitted]
        if len(set(selected_ids)) != len(selected_ids) or len(
            set(omitted_ids)
        ) != len(omitted_ids):
            raise ValueError("context manifest block identity is invalid")
        selected_set = set(selected_ids)
        omitted_set = set(omitted_ids)
        if selected_set & omitted_set:
            raise ValueError("context manifest block identity is invalid")
        for item in self.retrieval_trace:
            members, others = (
                (selected_set, omitted_set)
                if item.selected
                else (omitted_set, selected_set)
            )
            if item.block_id not in members or item.block_id in others:
                raise ValueError("context manifest retrieval trace is invalid")

        if self.schema_version == LEGACY_CONTEXT_MANIFEST_SCHEMA_VERSION:
            if (
                self.compiler_version is not None
                or self.target_chapter_revision is not None
                or self.requirement_revision is not None
            ):
                raise ValueError("context manifest legacy metadata is invalid")
            return

        if self.compiler_version != CONTEXT_COMPILER_VERSION:
            raise ValueError("context manifest compiler version is invalid")

        for revision_name, revision_value in (
            ("target chapter", self.target_chapter_revision),
            ("requirement", self.requirement_revision),
        ):
            if revision_value is not None and (
                isinstance(revision_value, bool)
                or not isinstance(revision_value, int)
                or revision_value < 0
            ):
                raise ValueError(f"context manifest {revision_name} revision is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "compiler_version": self.compiler_version,
            "id": self.id,
            "chapter_id": self.chapter_id,
            "run_id": self.run_id,
            "target_chapter_revision": self.target_chapter_revision,
            "requirement_revision": self.requirement_revision,
            "input_token_limit": self.input_token_limit,
            "output_token_limit": self.output_token_limit,
            "estimated_input_tokens": self.estimated_input_tokens,
            "selected": [asdict(item) for item in self.selected],
            "omitted": [asdict(item) for item in self.omitted],
            "retrieval_trace": [asdict(item) for item in self.retrieval_trace],
            "warnings": list(self.warnings),
            "created_at": self.created_at.isoformat(),
        }


def create_manifest_id() -> str:
    return new_id()


class ContextManifestRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def save(self, manifest: ContextManifest) -> Path:
        if manifest.schema_version != CONTEXT_MANIFEST_SCHEMA_VERSION:
            raise ValueError("new context manifest must use schema version 3")
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
        (
            schema_version,
            compiler_version,
            target_chapter_revision,
            requirement_revision,
        ) = self._schema_metadata(payload)
        if schema_version == CONTEXT_MANIFEST_SCHEMA_VERSION:
            raw_trace = payload.get("retrieval_trace", ())
            if not isinstance(raw_trace, list):
                raise ValueError("retrieval trace item is invalid")
            try:
                retrieval_trace = tuple(
                    RetrievalTraceItem(**item)
                    for item in raw_trace
                    if isinstance(item, dict)
                )
            except TypeError:
                raise ValueError("retrieval trace item is invalid") from None
            if len(retrieval_trace) != len(raw_trace):
                raise ValueError("retrieval trace item is invalid")
        else:
            retrieval_trace = ()
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
            schema_version=schema_version,
            compiler_version=compiler_version,
            target_chapter_revision=target_chapter_revision,
            requirement_revision=requirement_revision,
            retrieval_trace=retrieval_trace,
        )

    @staticmethod
    def _schema_metadata(
        payload: dict[str, object],
    ) -> tuple[int, str | None, int | None, int | None]:
        if "schema_version" not in payload:
            return (LEGACY_CONTEXT_MANIFEST_SCHEMA_VERSION, None, None, None)
        schema_value = payload["schema_version"]
        if isinstance(schema_value, bool) or not isinstance(schema_value, int):
            raise ValueError("context manifest schema version is invalid")
        if schema_value == LEGACY_CONTEXT_MANIFEST_SCHEMA_VERSION:
            return (LEGACY_CONTEXT_MANIFEST_SCHEMA_VERSION, None, None, None)
        if schema_value not in {
            PREVIOUS_CONTEXT_MANIFEST_SCHEMA_VERSION,
            CONTEXT_MANIFEST_SCHEMA_VERSION,
        }:
            raise ValueError("unsupported context manifest schema version")
        compiler_version = payload.get("compiler_version")
        if not isinstance(compiler_version, str) or not compiler_version.strip():
            raise ValueError("context manifest compiler version is invalid")
        return (
            schema_value,
            compiler_version,
            ContextManifestRepository._optional_revision(
                payload,
                "target_chapter_revision",
            ),
            ContextManifestRepository._optional_revision(
                payload,
                "requirement_revision",
            ),
        )

    @staticmethod
    def _optional_revision(payload: dict[str, object], field: str) -> int | None:
        value = payload.get(field)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"context manifest {field} is invalid")
        return value

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
