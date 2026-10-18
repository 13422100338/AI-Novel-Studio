"""Read-only chat quotes must not depend on an exact replacement span."""

import json

from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade

from .test_selection_reference import _SOURCE
from .test_writer_chat_ui import make_ui


def context(facade, selection="清晨的雾港", content=None):
    return json.dumps(
        dict(
            chapter_id=facade.currentChapterId,
            base_revision=facade.currentRevision,
            content=facade.currentChapterBody if content is None else content,
            selection=selection,
        ),
        ensure_ascii=False,
    )


def test_readonly_quote_accepts_noncanonical_import_and_unsaved_edits():
    facade = MockNovelStudioFacade(demo_mode=True)
    facade.setChatSelectionJson(context(facade, "清晨的雾港"))
    assert facade.hasSelectionReference
    assert "清晨的雾港" in facade.selectionReferencePreview
    assert facade._selection_reference is None  # No replacement authority.
    revised = _SOURCE + "\n新写的一句。"
    facade.setChatSelectionJson(context(facade, "新写的一句。", revised))
    assert facade.currentChapterBody == revised
    assert facade._editor_state == "DIRTY"
    assert "新写的一句。" in facade.selectionReferencePreview


def test_readonly_quote_rejects_stale_revision_and_clears_on_chapter_switch():
    facade = MockNovelStudioFacade(demo_mode=True)
    payload = json.loads(context(facade))
    facade.setChatSelectionJson(json.dumps(payload))
    facade.selectChapter(2)
    assert not facade.hasSelectionReference
    before = facade.currentChapterBody
    facade.setChatSelectionJson(json.dumps(payload))
    assert not facade.hasSelectionReference
    assert facade.currentChapterBody == before


def test_selected_quote_is_frozen_for_a_turn_and_visible_in_chat(qtbot):
    engine, facade, theme, controller, messages = make_ui(qtbot)
    facade._demo_mode = True
    # This fixture has no chapter. Test the controller boundary directly.
    from ai_novel_studio.application.novel_read_service import NovelEditorSnapshot

    class Reader:
        def update_editor(self, snapshot):
            self.snapshot = snapshot

    reader = Reader()
    controller._novel = reader
    snapshot = NovelEditorSnapshot("chapter-1", "雾港", 3, _SOURCE, False, "清晨的雾港")
    controller.update_editor(snapshot)
    controller.start("润色这段")
    controller.update_editor(NovelEditorSnapshot())
    assert reader.snapshot == snapshot
    user = next(row for row in controller._model.items() if row.kind == "user_text")
    assert "清晨的雾港" in user.text
    qtbot.waitUntil(lambda: not controller.is_busy)


def test_invalid_quote_payloads_cannot_change_editor_or_keep_an_old_quote():
    facade = MockNovelStudioFacade(demo_mode=True)
    before = facade.currentChapterBody
    for invalid in [
        "[]",
        "{}",
        context(facade, "字" * 20_001),
        context(facade, "\x00"),
        context(facade, "\ud800"),
    ]:
        facade.setChatSelectionJson(context(facade))
        facade.setChatSelectionJson(invalid)
        assert not facade.hasSelectionReference
        assert facade.currentChapterBody == before


def test_autosave_refreshes_quote_revision_without_dropping_it(qtbot, tmp_path):
    from .test_qml_shell import _create_temp_project

    root = _create_temp_project(tmp_path / "quote-project")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    edited = facade.currentChapterBody + "\n\n窗外起风了。"
    facade.setChatSelectionJson(context(facade, "这是测试正文。", edited))
    revision = facade.currentRevision
    facade.saveFromEditor(facade.currentChapterId, revision, facade.currentChapterBody)
    assert facade.currentRevision > revision
    assert facade.hasSelectionReference
    assert facade._chat_selection.revision == facade.currentRevision
    facade.editorTextChanged(facade.currentChapterBody + "新写的一句。")
    assert not facade.hasSelectionReference
