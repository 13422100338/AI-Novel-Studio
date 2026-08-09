from __future__ import annotations

import pytest

from ai_novel_studio.core.context.manuscript_chunking import (
    DEFAULT_MANUSCRIPT_CHUNK_POLICY,
    ManuscriptChunkPolicy,
    project_formal_manuscript_chunks,
)
from ai_novel_studio.infrastructure.storage.formal_manuscript_projection import (
    formal_manuscript_chunk_source_id,
)

_CHAPTER_ID = "00000000-0000-0000-0000-000000000001"


def test_default_policy_freezes_paragraph_codepoint_v1_contract() -> None:
    assert DEFAULT_MANUSCRIPT_CHUNK_POLICY == ManuscriptChunkPolicy()
    assert DEFAULT_MANUSCRIPT_CHUNK_POLICY.version == "paragraph-codepoint-v1"
    assert DEFAULT_MANUSCRIPT_CHUNK_POLICY.max_codepoints == 1_600
    assert DEFAULT_MANUSCRIPT_CHUNK_POLICY.overlap_codepoints == 200


@pytest.mark.parametrize(
    ("version", "maximum", "overlap"),
    [
        ("", 10, 2),
        (" leading-space", 10, 2),
        ("trailing-space ", 10, 2),
        ("v" * 101, 10, 2),
        ("custom-v1", 0, 0),
        ("custom-v1", True, 0),
        ("custom-v1", 10, -1),
        ("custom-v1", 10, 10),
        ("custom-v1", 10, True),
        ("paragraph-codepoint-v1", 1_599, 200),
        ("paragraph-codepoint-v1", 1_600, 199),
    ],
)
def test_policy_rejects_invalid_or_reinterpreted_contracts(
    version: str,
    maximum: int,
    overlap: int,
) -> None:
    with pytest.raises(ValueError):
        ManuscriptChunkPolicy(version, maximum, overlap)


def test_distinct_policy_version_may_use_a_distinct_numeric_contract() -> None:
    policy = ManuscriptChunkPolicy("paragraph-codepoint-test-v2", 10, 2)

    assert policy.max_codepoints == 10
    assert policy.overlap_codepoints == 2


def test_projection_prefers_blank_line_boundaries_and_preserves_exact_unicode_slices(
) -> None:
    content = "甲😀\r\n\r\n第二段\r\n\r\n尾声"
    policy = ManuscriptChunkPolicy("paragraph-codepoint-test-v2", 10, 2)

    chunks = project_formal_manuscript_chunks(
        _CHAPTER_ID,
        revision=3,
        content=content,
        policy=policy,
    )

    assert [(chunk.source_start, chunk.source_end) for chunk in chunks] == [
        (0, 6),
        (4, 13),
        (11, len(content)),
    ]
    assert [chunk.content for chunk in chunks] == [
        content[0:6],
        content[4:13],
        content[11:],
    ]
    assert [chunk.ordinal for chunk in chunks] == [0, 1, 2]
    assert [chunk.source_id for chunk in chunks] == [
        formal_manuscript_chunk_source_id(
            _CHAPTER_ID,
            3,
            policy.version,
            ordinal,
        )
        for ordinal in range(3)
    ]


def test_oversized_paragraph_hard_splits_with_overlap_and_complete_coverage() -> None:
    content = "a😀bcdefghijk"
    policy = ManuscriptChunkPolicy("paragraph-codepoint-test-v2", 5, 2)

    first = project_formal_manuscript_chunks(
        _CHAPTER_ID,
        revision=0,
        content=content,
        policy=policy,
    )
    replay = project_formal_manuscript_chunks(
        _CHAPTER_ID,
        revision=0,
        content=content,
        policy=policy,
    )

    assert replay == first
    assert [(chunk.source_start, chunk.source_end) for chunk in first] == [
        (0, 5),
        (3, 8),
        (6, 11),
        (9, len(content)),
    ]
    assert first[0].content == "a😀bcd"
    assert all(chunk.content == content[chunk.source_start : chunk.source_end] for chunk in first)
    assert all(len(chunk.content) <= policy.max_codepoints for chunk in first)
    assert all(
        current.source_start > previous.source_start
        and current.source_start <= previous.source_end
        and previous.source_end - current.source_start
        == policy.overlap_codepoints
        for previous, current in zip(first, first[1:], strict=False)
    )
    assert first[0].source_start == 0
    assert first[-1].source_end == len(content)


@pytest.mark.parametrize("content", ["", " ", "\t\r\n  \n"])
def test_whitespace_only_chapter_produces_no_chunks(content: str) -> None:
    assert (
        project_formal_manuscript_chunks(
            _CHAPTER_ID,
            revision=0,
            content=content,
        )
        == ()
    )
