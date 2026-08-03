"""Editor bridge for the Phase 1 WebEngine prototype.

Downlink (Python -> JS) uses ``WebEngineView.runJavaScript`` against the
``window.__novelEditor`` surface; uplink (JS -> Python) uses QWebChannel with a
single registered ``pythonBridge`` object. The bridge validates every payload
coming from the page before emitting; JavaScript is never trusted.
"""

from __future__ import annotations

import json
from hashlib import sha256 as _sha256

from PySide6.QtCore import QObject, Signal, Slot

_PROTOCOL_VERSION = 1
_ALLOWED_CAPABILITIES = {"markdown-v1", "selection-v1", "decorations-v1"}


class EditorBridge(QObject):
    """QML/WebChannel-facing editor controller (protocol v1)."""

    editor_ready = Signal(int, str)
    save_requested = Signal(str, int, str, str)
    selection_changed = Signal(int, int)
    error = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.protocol_version = _PROTOCOL_VERSION
        self.capabilities: frozenset[str] = frozenset()
        self.last_save_revision: int | None = None

    @Slot(int, str)
    def editorReady(self, protocol_version: int, capabilities_json: str) -> None:
        """Called by the page once it is connected and ready."""
        try:
            capabilities = frozenset(json.loads(capabilities_json))
        except (TypeError, ValueError):
            self.error.emit("INVALID_CAPABILITIES", "能力声明不是有效 JSON")
            return
        if protocol_version != _PROTOCOL_VERSION:
            self.error.emit(
                "PROTOCOL_MISMATCH",
                f"协议版本不兼容：页面 {protocol_version}，宿主 {_PROTOCOL_VERSION}",
            )
            return
        unknown = capabilities - _ALLOWED_CAPABILITIES
        if unknown:
            self.error.emit(
                "UNKNOWN_CAPABILITY",
                f"未知能力：{', '.join(sorted(unknown))}",
            )
            return
        self.capabilities = capabilities
        self.editor_ready.emit(protocol_version, capabilities_json)

    @Slot(str, int, str, str)
    def saveRequested(
        self,
        chapter_id: str,
        base_revision: int,
        markdown: str,
        content_hash: str,
    ) -> None:
        """Called by the page when the debounced save fires."""
        if not chapter_id.strip():
            self.error.emit("INVALID_CHAPTER_ID", "章节 ID 不能为空")
            return
        if base_revision < 0:
            self.error.emit("INVALID_REVISION", "修订号不能为负数")
            return
        if len(markdown.encode("utf-8")) > 5_000_000:
            self.error.emit("PAYLOAD_TOO_LARGE", "保存内容超过 5MB 上限")
            return
        if not validate_content_hash(markdown, content_hash):
            self.error.emit("HASH_MISMATCH", "内容哈希不一致，拒绝保存")
            return
        self.last_save_revision = base_revision
        self.save_requested.emit(chapter_id, base_revision, markdown, content_hash)

    @Slot(int, int)
    def selectionChanged(self, from_pos: int, to_pos: int) -> None:
        if from_pos < 0 or to_pos < 0:
            return
        self.selection_changed.emit(from_pos, to_pos)


def sha256(text: str) -> str:
    return _sha256(text.encode("utf-8")).hexdigest()


def fnv1a_hash(text: str) -> str:
    """Reproduce the JS-side FNV-1a fingerprint used by the Phase 1 prototype."""
    hash_value = 0x811C9DC5
    for character in text:
        hash_value ^= ord(character)
        hash_value = (hash_value * 0x01000193) & 0xFFFFFFFF
    return f"fnv1a:{hash_value:08x}"


def validate_content_hash(markdown: str, content_hash: str) -> bool:
    """Accept the prototype FNV fingerprint or a real SHA-256 hex digest.

    The Phase 1 page computes a synchronous FNV change fingerprint; the real
    SHA-256 path is kept so the production codec can switch without changing
    the bridge contract (see docs/2026-08-03-phase1-editor-bridge-delivery.md).
    """
    if content_hash.startswith("fnv1a:"):
        return content_hash == fnv1a_hash(markdown)
    return content_hash == sha256(markdown)
