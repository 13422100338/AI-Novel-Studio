from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

from ai_novel_studio.infrastructure.storage.formal_manuscript_projection import (
    FormalManuscriptChunk,
    formal_manuscript_chunk_source_id,
)

PARAGRAPH_CODEPOINT_V1 = "paragraph-codepoint-v1"
_PARAGRAPH_CODEPOINT_V1_MAX = 1_600
_PARAGRAPH_CODEPOINT_V1_OVERLAP = 200
_MAX_POLICY_VERSION_CHARS = 100
_BLANK_LINE = re.compile(r"(?:\r\n|\n|\r)[^\S\r\n]*(?:\r\n|\n|\r)")


@dataclass(frozen=True, slots=True)
class ManuscriptChunkPolicy:
    version: str = PARAGRAPH_CODEPOINT_V1
    max_codepoints: int = _PARAGRAPH_CODEPOINT_V1_MAX
    overlap_codepoints: int = _PARAGRAPH_CODEPOINT_V1_OVERLAP

    def __post_init__(self) -> None:
        if (
            not isinstance(self.version, str)
            or not self.version
            or self.version != self.version.strip()
            or len(self.version) > _MAX_POLICY_VERSION_CHARS
        ):
            raise ValueError("manuscript chunk policy version is invalid")
        if (
            isinstance(self.max_codepoints, bool)
            or not isinstance(self.max_codepoints, int)
            or self.max_codepoints <= 0
        ):
            raise ValueError("manuscript chunk maximum is invalid")
        if (
            isinstance(self.overlap_codepoints, bool)
            or not isinstance(self.overlap_codepoints, int)
            or self.overlap_codepoints < 0
            or self.overlap_codepoints >= self.max_codepoints
        ):
            raise ValueError("manuscript chunk overlap is invalid")
        if self.version == PARAGRAPH_CODEPOINT_V1 and (
            self.max_codepoints != _PARAGRAPH_CODEPOINT_V1_MAX
            or self.overlap_codepoints != _PARAGRAPH_CODEPOINT_V1_OVERLAP
        ):
            raise ValueError(
                "paragraph-codepoint-v1 numeric contract cannot be reinterpreted"
            )


DEFAULT_MANUSCRIPT_CHUNK_POLICY = ManuscriptChunkPolicy()


def project_formal_manuscript_chunks(
    chapter_id: str,
    revision: int,
    content: str,
    *,
    policy: ManuscriptChunkPolicy = DEFAULT_MANUSCRIPT_CHUNK_POLICY,
) -> tuple[FormalManuscriptChunk, ...]:
    if not isinstance(policy, ManuscriptChunkPolicy):
        raise TypeError("manuscript chunk policy is invalid")
    if not isinstance(content, str):
        raise TypeError("manuscript content must be text")
    if not content.strip():
        return ()

    paragraph_boundaries = tuple(match.end() for match in _BLANK_LINE.finditer(content))
    chunks: list[FormalManuscriptChunk] = []
    source_start = 0
    ordinal = 0
    while source_start < len(content):
        hard_end = min(source_start + policy.max_codepoints, len(content))
        source_end = hard_end
        if hard_end < len(content):
            preferred_index = bisect_right(paragraph_boundaries, hard_end) - 1
            if (
                preferred_index >= 0
                and paragraph_boundaries[preferred_index]
                > source_start + policy.overlap_codepoints
            ):
                source_end = paragraph_boundaries[preferred_index]

        chunks.append(
            FormalManuscriptChunk(
                formal_manuscript_chunk_source_id(
                    chapter_id,
                    revision,
                    policy.version,
                    ordinal,
                ),
                ordinal,
                source_start,
                source_end,
                content[source_start:source_end],
            )
        )
        if source_end == len(content):
            break
        source_start = source_end - policy.overlap_codepoints
        ordinal += 1

    return tuple(chunks)
