"""Phase 1: editor runtime script generation and asset staging."""

from ai_novel_studio.ui_qml.editor_runtime import (
    LoadDocumentPayload,
    apply_theme_script,
    ensure_qwebchannel_js,
    load_document_script,
)


def test_load_document_script_embeds_payload_safely() -> None:
    payload = LoadDocumentPayload("chapter-1", 3, "正文")

    script = load_document_script(payload)

    assert script.startswith("window.__novelEditor && ")
    assert '"chapterId": "chapter-1"' in script
    assert '"baseRevision": 3' in script
    assert "正文" in script


def test_apply_theme_script_embeds_tokens() -> None:
    script = apply_theme_script({"--editor-bg": "#ffffff"})

    assert script.startswith("window.__novelEditor && ")
    assert "--editor-bg" in script


def test_ensure_qwebchannel_js_is_idempotent() -> None:
    ensure_qwebchannel_js()
    ensure_qwebchannel_js()
    # Second call must not raise; the source asset exists in src/.
    assert True

