"""Strict selection-patch-v1 capture validation for the WebEngine boundary."""

from __future__ import annotations

import json

from ai_novel_studio.application.selection_patch import (
    MAX_CAPTURE_PAYLOAD_BYTES,
    SelectionPatchCapture,
    SelectionPatchValidationError,
    parse_selection_patch_capture,
)


def parse_selection_reference(payload_json: str) -> SelectionPatchCapture | None:
    """Parse one untrusted Web selection capture, failing closed."""
    if not isinstance(payload_json, str):
        return None
    if len(payload_json.encode("utf-8")) > MAX_CAPTURE_PAYLOAD_BYTES:
        return None
    try:
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            return None
        return parse_selection_patch_capture(payload)
    except (TypeError, ValueError, SelectionPatchValidationError):
        return None
