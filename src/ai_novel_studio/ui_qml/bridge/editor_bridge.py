"""Editor bridge for the Phase 1 WebEngine prototype.

Downlink (Python -> JS) uses ``WebEngineView.runJavaScript`` against the
``window.__novelEditor`` surface; uplink (JS -> Python) uses QWebChannel with a
single registered ``pythonBridge`` object. The bridge validates every payload
coming from the page before emitting; JavaScript is never trusted.
"""

from __future__ import annotations

import json
from typing import Protocol

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Qt, Signal, Slot

from ai_novel_studio.ui_qml.bridge.hash_utils import fnv1a_hash, sha256
from ai_novel_studio.ui_qml.bridge.models.selection_reference import (
    parse_selection_reference,
)

_PROTOCOL_VERSION = 1
_ALLOWED_CAPABILITIES = {"markdown-v1", "selection-v1", "decorations-v1"}


class _EngineLike(Protocol):
    def rootObjects(self) -> list[QObject]: ...


class _FacadeLike(Protocol):
    def property(self, name: str) -> object: ...


class WebEditorDocumentSync(QObject):
    """Push the current Facade chapter after WebChannel readiness.

    QML's page-load and WebChannel signals can arrive in either order. Keeping
    this tiny presentation controller in Python makes document delivery
    deterministic without moving any storage or manuscript authority into the
    UI layer.
    """

    def __init__(
        self,
        engine: _EngineLike,
        facade: _FacadeLike,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._facade = facade
        self._last_chapter_id = ""

    @Slot()
    def sync_force(self) -> None:
        self._sync(force=True)

    @Slot()
    def sync_if_chapter_changed(self) -> None:
        self._sync(force=False)

    def _sync(self, *, force: bool) -> None:
        roots = self._engine.rootObjects()
        if not roots:
            return
        chapter_id = str(self._facade.property("currentChapterId") or "")
        if not chapter_id or (not force and chapter_id == self._last_chapter_id):
            return
        view = roots[0].findChild(QObject, "novelEditorView")
        if view is None:
            return
        revision = self._facade.property("currentRevision")
        if isinstance(revision, bool) or not isinstance(revision, int):
            return
        payload = json.dumps(
            {
                "chapterId": chapter_id,
                "baseRevision": revision,
                "markdown": str(
                    self._facade.property("currentChapterBody") or ""
                ),
            },
            ensure_ascii=False,
        )
        # QML-declared functions expose parameters as QVariant in the
        # metaobject; invoking with Q_ARG(str) silently fails with
        # "No such method ... loadChapter(QString)" (2026-08-26 ticket).
        invoked = QMetaObject.invokeMethod(
            view,
            "loadChapter",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG("QVariant", payload),
        )
        if invoked:
            self._last_chapter_id = chapter_id


class EditorBridge(QObject):
    """QML/WebChannel-facing editor controller (protocol v1)."""

    editor_ready = Signal(int, str)
    save_requested = Signal(str, int, str, str)
    selection_changed = Signal(int, int)
    word_count_changed = Signal(int)
    selection_reference_changed = Signal(str)
    chat_selection_changed = Signal(str)
    documentReady = Signal()
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
        self.documentReady.emit()

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

    @Slot(int)
    def wordCountChanged(self, count: int) -> None:
        if count < 0:
            return
        self.word_count_changed.emit(count)

    @Slot(str)
    def chatSelectionChanged(self, payload_json: str) -> None:
        from ai_novel_studio.ui_qml.bridge.models.chat_selection import parse_chat_selection

        if parse_chat_selection(payload_json) is None:
            self.chat_selection_changed.emit("")
            self.error.emit("INVALID_CHAT_SELECTION", "选文引用无效或超过2万字，请重新选择")
            return
        self.chat_selection_changed.emit(payload_json)

    @Slot(str)
    def selectionReferenceChanged(self, payload_json: str) -> None:
        """Receive a validated-or-empty selection reference JSON from the editor."""
        reference = parse_selection_reference(payload_json)
        if reference is None:
            # Empty string is the explicit "no selection / chapter switched" signal.
            if payload_json.strip() == "":
                self.selection_reference_changed.emit("")
                return
            self.selection_reference_changed.emit("")
            self.error.emit(
                "INVALID_SELECTION_REFERENCE",
                "选区引用数据无效，已忽略",
            )
            return
        self.selection_reference_changed.emit(payload_json)


def validate_content_hash(markdown: str, content_hash: str) -> bool:
    """Accept the prototype FNV fingerprint or a real SHA-256 hex digest.

    The Phase 1 page computes a synchronous FNV change fingerprint; the real
    SHA-256 path is kept so the production codec can switch without changing
    the bridge contract (see docs/2026-08-03-phase1-editor-bridge-delivery.md).
    """
    if content_hash.startswith("fnv1a:"):
        return content_hash == fnv1a_hash(markdown)
    return content_hash == sha256(markdown)
