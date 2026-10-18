"""2026-08-26 ticket: Python chapter sync must match the real QML signature.

QML-declared ``function loadChapter(payloadJson)`` exposes its parameter as
``QVariant`` in the metaobject. Invoking with ``Q_ARG(str)`` fails silently
("No such method ... loadChapter(QString)"). This test exercises a real
QQmlEngine-created object so the signature convention cannot regress.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Q_ARG, QMetaObject, Qt
from PySide6.QtQml import QQmlComponent, QQmlEngine

_ROOT = Path(__file__).resolve().parents[2] / "src" / "ai_novel_studio" / "ui_qml"
_WEBVIEW_QML = _ROOT / "qml" / "components" / "NovelEditorView.qml"

_PROBE = """\
import QtQuick
Item {
    property string lastPayload: ""
    property int callCount: 0
    function loadChapter(payloadJson) {
        lastPayload = payloadJson
        callCount += 1
        return true
    }
}
"""


def test_production_view_declares_loadchapter_as_qml_function() -> None:
    source = _WEBVIEW_QML.read_text(encoding="utf-8")
    assert "function loadChapter(payloadJson)" in source


def test_qml_function_signature_accepts_variant_not_str(qapp) -> None:
    engine = QQmlEngine()
    probe_path = _ROOT / "_editor_sync_probe.qml"
    try:
        probe_path.write_text(_PROBE, encoding="utf-8")
        component = QQmlComponent(engine, str(probe_path))
        obj = component.create()
    finally:
        probe_path.unlink(missing_ok=True)
    assert obj is not None, component.errors()
    try:
        payload = json.dumps(
            {"chapterId": "ch-1", "baseRevision": 3, "markdown": "正文"},
            ensure_ascii=False,
        )

        str_ok = QMetaObject.invokeMethod(
            obj,
            "loadChapter",
            Qt.ConnectionType.DirectConnection,
            Q_ARG(str, payload),
        )
        assert str_ok is False or obj.property("callCount") == 0, (
            "Q_ARG(str) must not reach the QML loadChapter(QVariant) function"
        )
        assert "No such method" not in (obj.property("lastPayload") or "")

        variant_ok = QMetaObject.invokeMethod(
            obj,
            "loadChapter",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", payload),
        )
        assert variant_ok is True
        assert obj.property("callCount") == 1
        assert obj.property("lastPayload") == payload
    finally:
        obj.deleteLater()
        engine.deleteLater()
