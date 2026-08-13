from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

from ai_novel_studio.domain.identifiers import validate_id

SEMANTIC_WINDOW_V1 = "semantic-window-v1"
_SEMANTIC_WINDOW_V1_MAX = 6_000
_SEMANTIC_WINDOW_V1_OVERLAP = 600
_MAX_POLICY_VERSION_CHARS = 100
_MAX_CODEPOINTS = 50_000
_MAX_OVERLAP_CODEPOINTS = 10_000
_MAX_CONTENT_CODEPOINTS = 20_000_000
_MAX_WINDOWS = 10_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_BLANK_LINE = re.compile(r"(?:\r\n|\n|\r)[^\S\r\n]*(?:\r\n|\n|\r)")
_LINE_END = re.compile(r"\r\n|\n|\r")
_EXPLICIT_SCENE_SEPARATORS = frozenset({"***", "---", "＊ ＊ ＊", "* * *"})


class SemanticWindowBoundaryKind(StrEnum):
    EXPLICIT_SCENE = "EXPLICIT_SCENE"
    PARAGRAPH_WINDOW = "PARAGRAPH_WINDOW"
    HARD_WINDOW = "HARD_WINDOW"


@dataclass(frozen=True, slots=True)
class SemanticWindowPolicy:
    version: str = SEMANTIC_WINDOW_V1
    max_codepoints: int = _SEMANTIC_WINDOW_V1_MAX
    overlap_codepoints: int = _SEMANTIC_WINDOW_V1_OVERLAP

    def __post_init__(self) -> None:
        if (
            not isinstance(self.version, str)
            or not self.version
            or self.version != self.version.strip()
            or len(self.version) > _MAX_POLICY_VERSION_CHARS
        ):
            raise ValueError("semantic window policy version is invalid")
        if (
            isinstance(self.max_codepoints, bool)
            or not isinstance(self.max_codepoints, int)
            or not 1 <= self.max_codepoints <= _MAX_CODEPOINTS
        ):
            raise ValueError("semantic window policy maximum is invalid")
        if (
            isinstance(self.overlap_codepoints, bool)
            or not isinstance(self.overlap_codepoints, int)
            or not 0 <= self.overlap_codepoints < self.max_codepoints
            or self.overlap_codepoints > _MAX_OVERLAP_CODEPOINTS
        ):
            raise ValueError("semantic window policy overlap is invalid")
        if self.version == SEMANTIC_WINDOW_V1 and (
            self.max_codepoints != _SEMANTIC_WINDOW_V1_MAX
            or self.overlap_codepoints != _SEMANTIC_WINDOW_V1_OVERLAP
        ):
            raise ValueError(
                "semantic window policy semantic-window-v1 cannot be reinterpreted"
            )


DEFAULT_SEMANTIC_WINDOW_POLICY = SemanticWindowPolicy()


@dataclass(frozen=True, slots=True)
class SemanticWindow:
    source_id: str
    chapter_id: str
    source_revision: int
    source_hash: str
    narrative_sequence: int
    window_ordinal: int
    source_start: int
    source_end: int
    text: str
    boundary_kind: SemanticWindowBoundaryKind
    policy_version: str

    def __post_init__(self) -> None:
        chapter_id = _chapter_id(self.chapter_id)
        revision = _nonnegative_integer(self.source_revision, "source revision")
        source_hash = _source_hash(self.source_hash)
        narrative_sequence = _positive_integer(
            self.narrative_sequence,
            "narrative sequence",
        )
        ordinal = _bounded_nonnegative_integer(
            self.window_ordinal,
            "window ordinal",
            upper_bound=_MAX_WINDOWS,
        )
        source_start = _bounded_nonnegative_integer(
            self.source_start,
            "range start",
            upper_bound=_MAX_CONTENT_CODEPOINTS,
        )
        source_end = _positive_integer(self.source_end, "range end")
        policy_version = _policy_version(self.policy_version)
        if source_end <= source_start or source_end > _MAX_CONTENT_CODEPOINTS:
            raise ValueError("semantic window range is invalid")
        if (
            not isinstance(self.text, str)
            or len(self.text) > _MAX_CODEPOINTS
            or len(self.text) != source_end - source_start
        ):
            raise ValueError("semantic window text does not match its range")
        if not isinstance(self.boundary_kind, SemanticWindowBoundaryKind):
            raise TypeError("semantic window boundary kind is invalid")
        expected_source_id = semantic_window_source_id(
            chapter_id,
            revision,
            policy_version,
            ordinal,
        )
        if self.source_id != expected_source_id:
            raise ValueError("semantic window source ID is not deterministic")
        object.__setattr__(self, "source_hash", source_hash)
        object.__setattr__(self, "narrative_sequence", narrative_sequence)


def semantic_window_source_id(
    chapter_id: str,
    source_revision: int,
    policy_version: str,
    window_ordinal: int,
) -> str:
    ordinal = _bounded_nonnegative_integer(
        window_ordinal,
        "window ordinal",
        upper_bound=_MAX_WINDOWS,
    )
    return (
        f"SEMANTIC_WINDOW:{_chapter_id(chapter_id)}:"
        f"r{_nonnegative_integer(source_revision, 'source revision')}:"
        f"{_policy_version(policy_version)}:"
        f"o{ordinal}"
    )


def project_semantic_windows(
    chapter_id: str,
    source_revision: int,
    source_hash: str,
    narrative_sequence: int,
    content: str,
    *,
    policy: SemanticWindowPolicy = DEFAULT_SEMANTIC_WINDOW_POLICY,
) -> tuple[SemanticWindow, ...]:
    canonical_chapter_id = _chapter_id(chapter_id)
    revision = _nonnegative_integer(source_revision, "source revision")
    canonical_hash = _source_hash(source_hash)
    canonical_sequence = _positive_integer(
        narrative_sequence,
        "narrative sequence",
    )
    if not isinstance(content, str):
        raise TypeError("semantic window content must be text")
    if len(content) > _MAX_CONTENT_CODEPOINTS:
        raise ValueError("semantic window content exceeds safety limit")
    if not isinstance(policy, SemanticWindowPolicy):
        raise TypeError("semantic window policy is invalid")
    if _is_whitespace_only(content, 0, len(content)):
        return ()
    windows: list[SemanticWindow] = []
    for unit_start, unit_end, explicit_boundary in _semantic_units(content):
        source_start = unit_start
        while source_start < unit_end:
            if len(windows) >= _MAX_WINDOWS:
                raise ValueError("semantic window count exceeds safety limit")
            hard_end = min(source_start + policy.max_codepoints, unit_end)
            source_end = hard_end
            boundary_kind = SemanticWindowBoundaryKind.HARD_WINDOW
            if hard_end == unit_end:
                boundary_kind = (
                    SemanticWindowBoundaryKind.EXPLICIT_SCENE
                    if explicit_boundary
                    else SemanticWindowBoundaryKind.PARAGRAPH_WINDOW
                )
            else:
                preferred_boundary = None
                for match in _BLANK_LINE.finditer(content, source_start, hard_end):
                    match_end = match.end()
                    if match_end > source_start + policy.overlap_codepoints:
                        preferred_boundary = match_end
                if preferred_boundary is not None:
                    source_end = preferred_boundary
                    boundary_kind = SemanticWindowBoundaryKind.PARAGRAPH_WINDOW
            ordinal = len(windows)
            windows.append(
                SemanticWindow(
                    semantic_window_source_id(
                        canonical_chapter_id,
                        revision,
                        policy.version,
                        ordinal,
                    ),
                    canonical_chapter_id,
                    revision,
                    canonical_hash,
                    canonical_sequence,
                    ordinal,
                    source_start,
                    source_end,
                    content[source_start:source_end],
                    boundary_kind,
                    policy.version,
                )
            )
            if source_end == unit_end:
                break
            next_start = source_end - policy.overlap_codepoints
            if next_start <= source_start:
                raise RuntimeError("semantic window projection did not make progress")
            source_start = next_start
    return tuple(windows)


def _semantic_units(content: str) -> Iterator[tuple[int, int, bool]]:
    unit_start = 0
    line_start = 0
    for line_end_match in _LINE_END.finditer(content):
        line_end = line_end_match.end()
        if _is_explicit_scene_separator(
            content,
            line_start,
            line_end_match.start(),
        ):
            yield unit_start, line_end, True
            unit_start = line_end
        line_start = line_end
    if _is_explicit_scene_separator(content, line_start, len(content)):
        yield unit_start, len(content), True
        unit_start = len(content)
    if unit_start < len(content):
        yield unit_start, len(content), False


def _is_whitespace_only(content: str, start: int, end: int) -> bool:
    return all(content[index].isspace() for index in range(start, end))


def _is_explicit_scene_separator(content: str, start: int, end: int) -> bool:
    while start < end and content[start].isspace():
        start += 1
    while end > start and content[end - 1].isspace():
        end -= 1
    return any(
        end - start == len(separator)
        and content.startswith(separator, start, end)
        for separator in _EXPLICIT_SCENE_SEPARATORS
    )


def _chapter_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("semantic window chapter ID is invalid")
    try:
        return validate_id(value)
    except ValueError:
        raise ValueError("semantic window chapter ID is invalid") from None


def _source_hash(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("semantic window source hash is invalid")
    return value


def _policy_version(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_POLICY_VERSION_CHARS
    ):
        raise ValueError("semantic window policy version is invalid")
    return value


def _nonnegative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"semantic window {field} is invalid")
    return value


def _bounded_nonnegative_integer(
    value: object,
    field: str,
    *,
    upper_bound: int,
) -> int:
    integer = _nonnegative_integer(value, field)
    if integer >= upper_bound:
        raise ValueError(f"semantic window {field} is invalid")
    return integer


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"semantic window {field} is invalid")
    return value
