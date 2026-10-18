from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

SCHEMA_VERSION = "selection-patch-v1"
ANCHOR_CODEPOINTS = 64
MAX_SELECTION_CODEPOINTS = 20_000
MAX_REPLACEMENT_CODEPOINTS = 20_000
MAX_CAPTURE_PAYLOAD_BYTES = 100_000
MAX_PATCH_PAYLOAD_BYTES = 200_000

_HASH = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_CAPTURE_FIELDS = frozenset(
    {
        "schema_version",
        "chapter_id",
        "base_revision",
        "base_source_hash",
        "selection",
        "before_anchor",
        "after_anchor",
    }
)
_PATCH_FIELDS = _CAPTURE_FIELDS | {
    "replacement_candidate_id",
    "replacement_text",
    "replacement_hash",
    "result_hash",
}
_SPAN_FIELDS = frozenset({"start", "end", "text", "text_hash"})


class SelectionPatchValidationError(ValueError):
    """The untrusted patch shape or identity is invalid."""

    def __init__(self) -> None:
        super().__init__("selection patch is invalid")


class SelectionPatchStaleError(RuntimeError):
    """The patch no longer matches the exact formal source."""

    def __init__(self) -> None:
        super().__init__("selection patch is stale")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _invalid() -> SelectionPatchValidationError:
    return SelectionPatchValidationError()


def _payload_size(payload: Mapping[str, object]) -> int:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise _invalid() from None
    return len(encoded)


def _strict_mapping(value: object, fields: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or frozenset(value) != fields:
        raise _invalid()
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid()
    return value


def _hash(value: object) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise _invalid()
    return value


@dataclass(frozen=True, slots=True)
class SelectionPatchSpan:
    start: int
    end: int
    text: str
    text_hash: str

    def to_payload(self) -> dict[str, object]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "text_hash": self.text_hash,
        }


@dataclass(frozen=True, slots=True)
class SelectionPatchCapture:
    schema_version: str
    chapter_id: str
    base_revision: int
    base_source_hash: str
    selection: SelectionPatchSpan
    before_anchor: SelectionPatchSpan
    after_anchor: SelectionPatchSpan

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "chapter_id": self.chapter_id,
            "base_revision": self.base_revision,
            "base_source_hash": self.base_source_hash,
            "selection": self.selection.to_payload(),
            "before_anchor": self.before_anchor.to_payload(),
            "after_anchor": self.after_anchor.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class SelectionPatch(SelectionPatchCapture):
    replacement_candidate_id: str
    replacement_text: str
    replacement_hash: str
    result_hash: str

    def to_payload(self) -> dict[str, object]:
        payload = SelectionPatchCapture.to_payload(self)
        payload.update(
            {
                "replacement_candidate_id": self.replacement_candidate_id,
                "replacement_text": self.replacement_text,
                "replacement_hash": self.replacement_hash,
                "result_hash": self.result_hash,
            }
        )
        return payload


def _parse_span(value: object, *, maximum: int) -> SelectionPatchSpan:
    payload = _strict_mapping(value, _SPAN_FIELDS)
    start = _integer(payload["start"])
    end = _integer(payload["end"])
    text = payload["text"]
    if not isinstance(text, str) or end < start or end - start != len(text):
        raise _invalid()
    if len(text) > maximum or _hash(payload["text_hash"]) != _sha256(text):
        raise _invalid()
    return SelectionPatchSpan(start, end, text, str(payload["text_hash"]))


def parse_selection_patch_capture(
    value: Mapping[str, object],
) -> SelectionPatchCapture:
    payload = _strict_mapping(value, _CAPTURE_FIELDS)
    if _payload_size(payload) > MAX_CAPTURE_PAYLOAD_BYTES:
        raise _invalid()
    if payload["schema_version"] != SCHEMA_VERSION:
        raise _invalid()
    chapter_id = payload["chapter_id"]
    if not isinstance(chapter_id, str) or not chapter_id.strip():
        raise _invalid()
    selection = _parse_span(
        payload["selection"],
        maximum=MAX_SELECTION_CODEPOINTS,
    )
    before = _parse_span(payload["before_anchor"], maximum=ANCHOR_CODEPOINTS)
    after = _parse_span(payload["after_anchor"], maximum=ANCHOR_CODEPOINTS)
    if not selection.text or before.end != selection.start or after.start != selection.end:
        raise _invalid()
    return SelectionPatchCapture(
        SCHEMA_VERSION,
        chapter_id,
        _integer(payload["base_revision"]),
        _hash(payload["base_source_hash"]),
        selection,
        before,
        after,
    )


def parse_selection_patch(value: Mapping[str, object]) -> SelectionPatch:
    payload = _strict_mapping(value, _PATCH_FIELDS)
    if _payload_size(payload) > MAX_PATCH_PAYLOAD_BYTES:
        raise _invalid()
    capture = parse_selection_patch_capture({field: payload[field] for field in _CAPTURE_FIELDS})
    candidate_id = payload["replacement_candidate_id"]
    replacement = payload["replacement_text"]
    if (
        not isinstance(candidate_id, str)
        or _ARTIFACT_ID.fullmatch(candidate_id) is None
        or not isinstance(replacement, str)
        or not replacement.strip()
        or len(replacement) > MAX_REPLACEMENT_CODEPOINTS
    ):
        raise _invalid()
    replacement_hash = _hash(payload["replacement_hash"])
    if replacement_hash != _sha256(replacement) or candidate_id != f"sha256:{replacement_hash}":
        raise _invalid()
    return SelectionPatch(
        schema_version=capture.schema_version,
        chapter_id=capture.chapter_id,
        base_revision=capture.base_revision,
        base_source_hash=capture.base_source_hash,
        selection=capture.selection,
        before_anchor=capture.before_anchor,
        after_anchor=capture.after_anchor,
        replacement_candidate_id=candidate_id,
        replacement_text=replacement,
        replacement_hash=replacement_hash,
        result_hash=_hash(payload["result_hash"]),
    )


def _validate_capture(
    capture: SelectionPatchCapture,
    *,
    source: str,
    chapter_id: str,
    revision: int,
) -> None:
    selection = capture.selection
    before = capture.before_anchor
    after = capture.after_anchor
    if (
        chapter_id != capture.chapter_id
        or revision != capture.base_revision
        or _sha256(source) != capture.base_source_hash
        or selection.end > len(source)
        or before.start != max(0, selection.start - ANCHOR_CODEPOINTS)
        or after.end != min(len(source), selection.end + ANCHOR_CODEPOINTS)
        or source[selection.start : selection.end] != selection.text
        or source[before.start : before.end] != before.text
        or source[after.start : after.end] != after.text
    ):
        raise SelectionPatchStaleError()


def validate_selection_patch_capture(
    capture: SelectionPatchCapture,
    *,
    source: str,
    chapter_id: str,
    revision: int,
) -> str:
    """Verify one capture against exact formal Markdown before model use."""
    if not isinstance(capture, SelectionPatchCapture):
        raise _invalid()
    validated = parse_selection_patch_capture(capture.to_payload())
    if validated != capture:
        raise _invalid()
    _validate_capture(
        validated,
        source=source,
        chapter_id=chapter_id,
        revision=revision,
    )
    return validated.selection.text


def finalize_selection_patch(
    capture: SelectionPatchCapture,
    *,
    source: str,
    chapter_id: str,
    revision: int,
    replacement_candidate_id: str,
    replacement_text: str,
) -> SelectionPatch:
    validate_selection_patch_capture(
        capture,
        source=source,
        chapter_id=chapter_id,
        revision=revision,
    )
    replacement_hash = _sha256(replacement_text)
    if (
        not replacement_text.strip()
        or len(replacement_text) > MAX_REPLACEMENT_CODEPOINTS
        or replacement_candidate_id != f"sha256:{replacement_hash}"
    ):
        raise _invalid()
    selection = capture.selection
    result = source[: selection.start] + replacement_text + source[selection.end :]
    patch = SelectionPatch(
        schema_version=capture.schema_version,
        chapter_id=capture.chapter_id,
        base_revision=capture.base_revision,
        base_source_hash=capture.base_source_hash,
        selection=capture.selection,
        before_anchor=capture.before_anchor,
        after_anchor=capture.after_anchor,
        replacement_candidate_id=replacement_candidate_id,
        replacement_text=replacement_text,
        replacement_hash=replacement_hash,
        result_hash=_sha256(result),
    )
    if _payload_size(patch.to_payload()) > MAX_PATCH_PAYLOAD_BYTES:
        raise _invalid()
    return patch


def replay_selection_patch(
    patch: SelectionPatch,
    *,
    source: str,
    chapter_id: str,
    revision: int,
) -> str:
    if not isinstance(patch, SelectionPatch):
        raise _invalid()
    validated = parse_selection_patch(patch.to_payload())
    if validated != patch:
        raise _invalid()
    _validate_capture(
        validated,
        source=source,
        chapter_id=chapter_id,
        revision=revision,
    )
    selection = validated.selection
    result = source[: selection.start] + validated.replacement_text + source[selection.end :]
    if _sha256(result) != validated.result_hash:
        raise SelectionPatchStaleError()
    return result
