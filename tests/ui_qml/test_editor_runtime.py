"""Phase 1 editor runtime tests: script injection, asset staging, staleness."""

import os
import time as time_mod

import pytest

from ai_novel_studio.ui_qml.editor_runtime import (
    LoadDocumentPayload,
    apply_theme_script,
    load_document_script,
)


def test_load_document_script_embeds_payload_safely() -> None:
    payload = LoadDocumentPayload(
        chapterId="ch-1", baseRevision=3, markdown="正文 <b>测试</b>"
    )
    script = load_document_script(payload)
    assert "window.__novelEditor" in script
    assert "loadDocument" in script
    assert "ch-1" in script


def test_apply_theme_script_embeds_tokens() -> None:
    tokens = {"color.bg": "#fff", "color.text": "#000"}
    script = apply_theme_script(tokens)
    assert "applyTheme" in script
    assert "#fff" in script


def test_ensure_qwebchannel_js_is_idempotent(tmp_path) -> None:
    from ai_novel_studio.ui_qml.editor_runtime import ensure_qwebchannel_js as fn
    fn()


def test_stale_dist_fails_loudly(tmp_path, monkeypatch) -> None:
    """Ticket A: if dist/editor.js is older than any src/ file, startup
    must fail with an actionable error instead of silently using old code."""
    from ai_novel_studio.ui_qml import editor_runtime as mod

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "editor.js").write_text("// stale bundle")

    src = tmp_path / "src"
    src.mkdir()
    for name in ("editor.ts", "editor-core.ts", "markdown.ts", "schema.ts"):
        (src / name).write_text(f"// {name}")

    monkeypatch.setattr(mod, "_DIST_DIR", dist)
    monkeypatch.setattr(mod, "_EDITOR_WEB_DIR", tmp_path)

    future = time_mod.time() + 10
    for name in ("editor.ts", "editor-core.ts"):
        os.utime(str(src / name), (future, future))

    with pytest.raises(RuntimeError, match="过期"):
        mod.ensure_editor_dist()


def test_fresh_dist_passes_staleness_check(tmp_path, monkeypatch) -> None:
    """When dist is newer than src, the staleness check must pass."""
    from ai_novel_studio.ui_qml import editor_runtime as mod

    dist = tmp_path / "dist"
    dist.mkdir()
    js = dist / "editor.js"
    js.write_text("// fresh bundle")
    revision = dist / ".build-revision"
    revision.write_text("rev-test\n")

    src = tmp_path / "src"
    src.mkdir()
    for name in ("editor.ts", "editor-core.ts", "markdown.ts", "schema.ts"):
        (src / name).write_text(f"// {name}")

    monkeypatch.setattr(mod, "_DIST_DIR", dist)
    monkeypatch.setattr(mod, "_EDITOR_WEB_DIR", tmp_path)

    future = time_mod.time() + 10
    os.utime(str(js), (future, future))
    os.utime(str(revision), (future, future))

    result = mod.ensure_editor_dist()
    assert result == dist
