from __future__ import annotations

from dataclasses import replace

import pytest

from ai_novel_studio.core.context.manuscript_chunking import (
    DEFAULT_MANUSCRIPT_CHUNK_POLICY,
)
from ai_novel_studio.core.context.semantic_windowing import (
    DEFAULT_SEMANTIC_WINDOW_POLICY,
    SemanticWindow,
    SemanticWindowBoundaryKind,
    SemanticWindowPolicy,
    project_semantic_windows,
    semantic_window_source_id,
)
from ai_novel_studio.infrastructure.storage.formal_manuscript_projection import (
    formal_manuscript_chunk_source_id,
)

_CHAPTER_ID = "00000000-0000-0000-0000-000000000001"
_SOURCE_HASH = "a" * 64


class _GuardedText(str):
    max_slice: int

    def __new__(cls, value: str, *, max_slice: int) -> _GuardedText:
        instance = super().__new__(cls, value)
        instance.max_slice = max_slice
        return instance

    def __getitem__(self, key: int | slice) -> str:
        if isinstance(key, slice):
            start, stop, step = key.indices(len(self))
            if step == 1 and stop - start > self.max_slice:
                raise AssertionError("semantic projection copied an unbounded source slice")
        return super().__getitem__(key)


def test_default_policy_freezes_independent_semantic_window_contract() -> None:
    assert DEFAULT_SEMANTIC_WINDOW_POLICY == SemanticWindowPolicy()
    assert DEFAULT_SEMANTIC_WINDOW_POLICY.version == "semantic-window-v1"
    assert DEFAULT_SEMANTIC_WINDOW_POLICY.max_codepoints == 6_000
    assert DEFAULT_SEMANTIC_WINDOW_POLICY.overlap_codepoints == 600


def test_short_text_is_one_exact_immutable_semantic_window() -> None:
    content = "甲😀\r\n第二段"

    windows = project_semantic_windows(
        _CHAPTER_ID,
        source_revision=3,
        source_hash=_SOURCE_HASH,
        narrative_sequence=7,
        content=content,
    )

    assert len(windows) == 1
    window = windows[0]
    assert (
        window.source_id,
        window.chapter_id,
        window.source_revision,
        window.source_hash,
        window.narrative_sequence,
        window.window_ordinal,
        window.source_start,
        window.source_end,
        window.text,
        window.boundary_kind,
        window.policy_version,
    ) == (
        semantic_window_source_id(
            _CHAPTER_ID,
            3,
            DEFAULT_SEMANTIC_WINDOW_POLICY.version,
            0,
        ),
        _CHAPTER_ID,
        3,
        _SOURCE_HASH,
        7,
        0,
        0,
        len(content),
        content,
        SemanticWindowBoundaryKind.PARAGRAPH_WINDOW,
        "semantic-window-v1",
    )


@pytest.mark.parametrize("separator", ["***", "---", "＊ ＊ ＊", "* * *"])
def test_explicit_separator_line_belongs_to_preceding_semantic_unit(
    separator: str,
) -> None:
    content = f"第一幕😀\r\n{separator}\r\n第二幕"
    separator_end = content.index(separator) + len(separator) + len("\r\n")

    windows = project_semantic_windows(
        _CHAPTER_ID,
        source_revision=0,
        source_hash=_SOURCE_HASH,
        narrative_sequence=1,
        content=content,
    )

    assert [(window.source_start, window.source_end) for window in windows] == [
        (0, separator_end),
        (separator_end, len(content)),
    ]
    assert [window.text for window in windows] == [
        content[:separator_end],
        content[separator_end:],
    ]
    assert [window.boundary_kind for window in windows] == [
        SemanticWindowBoundaryKind.EXPLICIT_SCENE,
        SemanticWindowBoundaryKind.PARAGRAPH_WINDOW,
    ]


def test_multi_scene_projection_has_stable_ordinals_ids_and_exact_coverage() -> None:
    content = "场景一\n***\n场景二\r\n---\r\n场景三😀"

    first = project_semantic_windows(
        _CHAPTER_ID,
        source_revision=4,
        source_hash=_SOURCE_HASH,
        narrative_sequence=9,
        content=content,
    )
    replay = project_semantic_windows(
        _CHAPTER_ID,
        source_revision=4,
        source_hash=_SOURCE_HASH,
        narrative_sequence=9,
        content=content,
    )

    assert replay == first
    assert [window.window_ordinal for window in first] == [0, 1, 2]
    assert [window.source_id for window in first] == [
        semantic_window_source_id(
            _CHAPTER_ID,
            4,
            DEFAULT_SEMANTIC_WINDOW_POLICY.version,
            ordinal,
        )
        for ordinal in range(3)
    ]
    assert "".join(window.text for window in first) == content
    assert all(
        window.text == content[window.source_start : window.source_end]
        for window in first
    )


def test_oversized_scene_prefers_latest_paragraph_boundary_and_overlaps() -> None:
    content = "甲" * 8 + "\r\n\r\n" + "乙" * 8 + "\r\n\r\n" + "尾声"
    policy = SemanticWindowPolicy("semantic-window-test-v2", 15, 3)

    windows = project_semantic_windows(
        _CHAPTER_ID,
        source_revision=0,
        source_hash=_SOURCE_HASH,
        narrative_sequence=1,
        content=content,
        policy=policy,
    )

    assert [(window.source_start, window.source_end) for window in windows] == [
        (0, 12),
        (9, 24),
        (21, len(content)),
    ]
    assert [window.boundary_kind for window in windows] == [
        SemanticWindowBoundaryKind.PARAGRAPH_WINDOW,
        SemanticWindowBoundaryKind.PARAGRAPH_WINDOW,
        SemanticWindowBoundaryKind.PARAGRAPH_WINDOW,
    ]
    assert all(
        window.text == content[window.source_start : window.source_end]
        for window in windows
    )


def test_oversized_unbroken_scene_hard_splits_with_progress_and_coverage() -> None:
    content = "a😀bcdefghijk"
    policy = SemanticWindowPolicy("semantic-window-test-v2", 5, 2)

    windows = project_semantic_windows(
        _CHAPTER_ID,
        source_revision=0,
        source_hash=_SOURCE_HASH,
        narrative_sequence=1,
        content=content,
        policy=policy,
    )

    assert [(window.source_start, window.source_end) for window in windows] == [
        (0, 5),
        (3, 8),
        (6, 11),
        (9, len(content)),
    ]
    assert [window.boundary_kind for window in windows] == [
        SemanticWindowBoundaryKind.HARD_WINDOW,
        SemanticWindowBoundaryKind.HARD_WINDOW,
        SemanticWindowBoundaryKind.HARD_WINDOW,
        SemanticWindowBoundaryKind.PARAGRAPH_WINDOW,
    ]
    assert all(len(window.text) <= policy.max_codepoints for window in windows)
    assert all(
        current.source_start > previous.source_start
        and current.source_start <= previous.source_end
        and previous.source_end - current.source_start
        == policy.overlap_codepoints
        for previous, current in zip(windows, windows[1:], strict=False)
    )
    assert windows[0].source_start == 0
    assert windows[-1].source_end == len(content)
    assert all(
        any(window.source_start <= index < window.source_end for window in windows)
        for index, character in enumerate(content)
        if not character.isspace()
    )


@pytest.mark.parametrize("content", ["", " ", "\t\r\n  \n"])
def test_whitespace_only_content_produces_no_semantic_windows(content: str) -> None:
    assert (
        project_semantic_windows(
            _CHAPTER_ID,
            source_revision=0,
            source_hash=_SOURCE_HASH,
            narrative_sequence=1,
            content=content,
        )
        == ()
    )


def test_semantic_identity_is_independent_from_formal_chunk_identity_and_policy() -> None:
    base = semantic_window_source_id(
        _CHAPTER_ID,
        1,
        "semantic-window-v1",
        0,
    )
    changed_revision = semantic_window_source_id(
        _CHAPTER_ID,
        2,
        "semantic-window-v1",
        0,
    )
    changed_policy = semantic_window_source_id(
        _CHAPTER_ID,
        1,
        "semantic-window-v2",
        0,
    )
    formal = formal_manuscript_chunk_source_id(
        _CHAPTER_ID,
        1,
        DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
        0,
    )

    assert len({base, changed_revision, changed_policy, formal}) == 4
    assert base.startswith("SEMANTIC_WINDOW:")
    assert formal.startswith("FORMAL_MANUSCRIPT:")
    assert (
        DEFAULT_SEMANTIC_WINDOW_POLICY.max_codepoints,
        DEFAULT_SEMANTIC_WINDOW_POLICY.overlap_codepoints,
    ) == (6_000, 600)
    assert (
        DEFAULT_MANUSCRIPT_CHUNK_POLICY.max_codepoints,
        DEFAULT_MANUSCRIPT_CHUNK_POLICY.overlap_codepoints,
    ) == (1_600, 200)


def test_source_id_helper_rejects_window_ordinal_at_hard_limit() -> None:
    with pytest.raises(ValueError, match="window ordinal"):
        semantic_window_source_id(
            _CHAPTER_ID,
            0,
            "semantic-window-v1",
            10_000,
        )


def test_blank_line_dense_input_never_copies_or_materializes_the_whole_unit() -> None:
    policy = SemanticWindowPolicy("semantic-window-test-v2", 64, 8)
    content = _GuardedText(
        "段落😀\r\n\r\n" * 2_000,
        max_slice=policy.max_codepoints,
    )

    windows = project_semantic_windows(
        _CHAPTER_ID,
        source_revision=0,
        source_hash=_SOURCE_HASH,
        narrative_sequence=1,
        content=content,
        policy=policy,
    )

    assert windows
    assert all(len(window.text) <= policy.max_codepoints for window in windows)
    assert windows[0].source_start == 0
    assert windows[-1].source_end == len(content)
    assert all(
        window.text == str(content)[window.source_start : window.source_end]
        for window in windows
    )


def test_long_line_never_copies_the_whole_line() -> None:
    policy = SemanticWindowPolicy("semantic-window-test-v3", 64, 8)
    content = _GuardedText("长" * 500, max_slice=policy.max_codepoints)

    windows = project_semantic_windows(
        _CHAPTER_ID,
        source_revision=0,
        source_hash=_SOURCE_HASH,
        narrative_sequence=1,
        content=content,
        policy=policy,
    )

    assert windows
    assert windows[-1].source_end == len(content)


@pytest.mark.parametrize(
    ("version", "maximum", "overlap"),
    [
        ("", 10, 2),
        (" leading", 10, 2),
        ("trailing ", 10, 2),
        ("v" * 101, 10, 2),
        ("semantic-window-test-v2", 0, 0),
        ("semantic-window-test-v2", True, 0),
        ("semantic-window-test-v2", 50_001, 0),
        ("semantic-window-test-v2", 10, -1),
        ("semantic-window-test-v2", 10, 10),
        ("semantic-window-test-v2", 20_000, 10_001),
        ("semantic-window-test-v2", 10, True),
        ("semantic-window-v1", 5_999, 600),
        ("semantic-window-v1", 6_000, 599),
    ],
)
def test_policy_rejects_invalid_or_reinterpreted_contracts(
    version: str,
    maximum: int,
    overlap: int,
) -> None:
    with pytest.raises(ValueError, match="semantic window policy"):
        SemanticWindowPolicy(version, maximum, overlap)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chapter_id", "not-a-canonical-id"),
        ("source_revision", True),
        ("source_revision", -1),
        ("source_hash", "not-a-hash"),
        ("narrative_sequence", True),
        ("narrative_sequence", 0),
        ("window_ordinal", True),
        ("window_ordinal", -1),
        ("source_start", True),
        ("source_start", -1),
        ("source_end", True),
        ("source_end", 0),
        ("policy_version", " trailing "),
    ],
)
def test_projection_rejects_invalid_input_without_echoing_values(
    field: str,
    value: object,
) -> None:
    arguments: dict[str, object] = {
        "chapter_id": _CHAPTER_ID,
        "source_revision": 0,
        "source_hash": _SOURCE_HASH,
        "narrative_sequence": 1,
        "content": "body",
    }
    if field in {"window_ordinal", "source_start", "source_end", "policy_version"}:
        valid = _valid_window()
        with pytest.raises((TypeError, ValueError), match="semantic window") as captured:
            replace(valid, **{field: value})
    else:
        arguments[field] = value
        with pytest.raises((TypeError, ValueError), match="semantic window") as captured:
            project_semantic_windows(**arguments)  # type: ignore[arg-type]
    assert str(value) not in str(captured.value)


def test_dto_rejects_wrong_identity_range_text_and_boundary_kind() -> None:
    valid = _valid_window()

    for change in (
        {"source_id": "FORMAL_MANUSCRIPT:wrong"},
        {"source_end": 3},
        {"source_start": 4},
        {"text": "no"},
        {"boundary_kind": "PARAGRAPH_WINDOW"},
    ):
        with pytest.raises((TypeError, ValueError), match="semantic window"):
            replace(valid, **change)


def test_dto_rejects_absolute_window_range_and_text_limits() -> None:
    valid = _valid_window()

    for change in (
        {"window_ordinal": 10_000},
        {"source_start": 20_000_000},
        {"source_end": 20_000_001, "text": "x"},
        {"source_end": 50_001, "text": "x" * 50_001},
    ):
        with pytest.raises(ValueError, match="semantic window"):
            replace(valid, **change)


def test_content_and_window_count_hard_caps_fail_before_unbounded_projection() -> None:
    too_large = "SENSITIVE MANUSCRIPT " * 1_000_001
    with pytest.raises(ValueError, match="content exceeds safety limit") as captured:
        project_semantic_windows(
            _CHAPTER_ID,
            source_revision=0,
            source_hash=_SOURCE_HASH,
            narrative_sequence=1,
            content=too_large,
        )
    assert "SENSITIVE MANUSCRIPT" not in str(captured.value)
    assert _SOURCE_HASH not in str(captured.value)

    with pytest.raises(ValueError, match="window count exceeds safety limit"):
        project_semantic_windows(
            _CHAPTER_ID,
            source_revision=0,
            source_hash=_SOURCE_HASH,
            narrative_sequence=1,
            content="a" * 10_001,
            policy=SemanticWindowPolicy("semantic-window-test-v2", 1, 0),
        )


def _valid_window() -> SemanticWindow:
    return SemanticWindow(
        semantic_window_source_id(
            _CHAPTER_ID,
            0,
            "semantic-window-v1",
            0,
        ),
        _CHAPTER_ID,
        0,
        _SOURCE_HASH,
        1,
        0,
        0,
        4,
        "body",
        SemanticWindowBoundaryKind.PARAGRAPH_WINDOW,
        "semantic-window-v1",
    )
