from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus

FORMAL_MANUSCRIPT_DOCUMENT_TYPE = "FORMAL_MANUSCRIPT"
MAX_FORMAL_STORED_CODEPOINTS = 8_000_000
MAX_FORMAL_STORAGE_AMPLIFICATION = 8
_MAX_CHUNK_POLICY_VERSION_CHARS = 100


@dataclass(frozen=True, slots=True)
class FormalManuscriptChunk:
    source_id: str
    ordinal: int
    source_start: int
    source_end: int
    content: str


def formal_manuscript_chunk_source_id(
    chapter_id: str,
    revision: int,
    chunk_policy_version: str,
    ordinal: int,
) -> str:
    canonical_chapter_id = validate_id(chapter_id)
    normalized_revision = _nonnegative_integer(revision, "chapter revision")
    normalized_policy = _chunk_policy_version(chunk_policy_version)
    normalized_ordinal = _nonnegative_integer(ordinal, "chunk ordinal")
    return (
        f"{FORMAL_MANUSCRIPT_DOCUMENT_TYPE}:"
        f"{canonical_chapter_id}:r{normalized_revision}:"
        f"{normalized_policy}:o{normalized_ordinal}"
    )


def _same_formal_projection(
    row: sqlite3.Row,
    *,
    chapter_id: str,
    chapter_volume_id: str,
    chapter_title: str,
    revision: int,
    source_hash: str,
    policy_version: str,
    chunk: FormalManuscriptChunk,
) -> bool:
    return all(
        (
            row["document_type"] == FORMAL_MANUSCRIPT_DOCUMENT_TYPE,
            row["source_id"] == chunk.source_id,
            row["chapter_id"] == chapter_id,
            row["volume_id"] == chapter_volume_id,
            row["source_revision"] == revision,
            row["source_hash"] == source_hash,
            row["title"] == chapter_title,
            row["content"] == chunk.content,
            row["participants"] == "",
            row["pinned_weight"] == 0,
            row["review_status"] == ReviewStatus.APPROVED.value,
            row["status"] == MemoryStatus.CURRENT.value,
            row["source_start"] == chunk.source_start,
            row["source_end"] == chunk.source_end,
            row["chunk_ordinal"] == chunk.ordinal,
            row["chunk_policy_version"] == policy_version,
        )
    )


def _validated_formal_chunks(
    chapter_id: str,
    revision: int,
    policy_version: str,
    current_content: str,
    chunks: tuple[FormalManuscriptChunk, ...],
) -> tuple[FormalManuscriptChunk, ...]:
    if any(not isinstance(chunk, FormalManuscriptChunk) for chunk in chunks):
        raise ValueError("formal manuscript chunks contain an invalid item")
    ordinals = [
        _nonnegative_integer(chunk.ordinal, "chunk ordinal") for chunk in chunks
    ]
    if len(ordinals) != len(set(ordinals)) or sorted(ordinals) != list(
        range(len(chunks))
    ):
        raise ValueError("formal manuscript chunk ordinal set is invalid")
    source_ids = [chunk.source_id for chunk in chunks]
    if any(
        not isinstance(source_id, str) or not source_id.strip()
        for source_id in source_ids
    ):
        raise ValueError("formal manuscript chunk source ID is invalid")
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("formal manuscript chunk source ID must be unique")
    normalized: list[FormalManuscriptChunk] = []
    for chunk in chunks:
        source_start = _nonnegative_integer(chunk.source_start, "chunk range start")
        source_end = _nonnegative_integer(chunk.source_end, "chunk range end")
        if not 0 <= source_start < source_end <= len(current_content):
            raise ValueError("formal manuscript chunk range is invalid")
        if not isinstance(chunk.content, str) or not chunk.content.strip():
            raise ValueError("formal manuscript chunk content must be nonempty")
        if current_content[source_start:source_end] != chunk.content:
            raise RuntimeError("formal manuscript chunk slice does not match current source")
        expected_source_id = formal_manuscript_chunk_source_id(
            chapter_id,
            revision,
            policy_version,
            chunk.ordinal,
        )
        if chunk.source_id != expected_source_id:
            raise ValueError("formal manuscript chunk source ID is not deterministic")
        normalized.append(
            FormalManuscriptChunk(
                expected_source_id,
                chunk.ordinal,
                source_start,
                source_end,
                chunk.content,
            )
        )
    aggregate_codepoints = sum(len(chunk.content) for chunk in normalized)
    storage_limit = min(
        MAX_FORMAL_STORED_CODEPOINTS,
        len(current_content) * MAX_FORMAL_STORAGE_AMPLIFICATION,
    )
    if aggregate_codepoints > storage_limit:
        raise ValueError(
            "formal manuscript aggregate stored code-point safety limit exceeded"
        )
    return tuple(sorted(normalized, key=lambda chunk: chunk.ordinal))


def _nonnegative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"formal manuscript {field} is invalid")
    return value


def _chunk_policy_version(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("formal manuscript chunk policy version is invalid")
    normalized = value.strip()
    if (
        not normalized
        or normalized != value
        or len(normalized) > _MAX_CHUNK_POLICY_VERSION_CHARS
    ):
        raise ValueError("formal manuscript chunk policy version is invalid")
    return normalized
