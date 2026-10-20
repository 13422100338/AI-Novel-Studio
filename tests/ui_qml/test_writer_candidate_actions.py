import json

from PySide6.QtCore import QMetaObject

from ai_novel_studio.application.codex_session_service import CodexSessionService
from ai_novel_studio.application.novel_writer_service import NovelWriterService
from ai_novel_studio.infrastructure.codex.session_index import CodexSessionIndex
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bridge.codex_session_bridge import CodexSessionController

from .test_writer_input_review import find
from .test_writer_input_review import review as review


def completed(work, qtbot):
    _, _, _, _, controller, facade, calls, _, _ = work
    pending = next(row for row in controller._model.items() if row.state == "AWAITING_CONFIRMATION")
    assert facade.confirmWriterInput(pending.id)
    qtbot.waitUntil(lambda: not controller.is_busy and bool(calls))
    return next(row for row in controller._model.items() if row.state == "COMPLETED")


def card(window, item_id):
    def search(item):
        if item.objectName() == "writerTaskCard" and item.property("itemId") == item_id:
            return item
        for child in item.childItems():
            found = search(child)
            if found is not None:
                return found
        return None

    return search(window.contentItem())


def test_qml_adopt_commits_candidate_and_refreshes_editor(review, qtbot):
    project, chapter, _, _, controller, facade, calls, window, warnings = review
    row = completed(review, qtbot)
    qtbot.waitUntil(lambda: card(window, row.id) is not None)
    button = find(card(window, row.id), "writerCandidateAdoptButton")
    assert button is not None and button.property("visible")
    QMetaObject.invokeMethod(button, "clicked")
    assert ChapterRepository(project).read_content_exact(chapter.id) == "新的候选。"
    assert facade.currentChapterBody == "新的候选。"
    assert facade.currentRevision == chapter.revision + 1
    assert any(item.state == "ACCEPTED" for item in controller._model.items())
    assert len(calls) == 1
    assert not [w for w in warnings if "WriterTaskCard.qml" in w]


def test_project_reopening_retains_writer_lock_without_connecting_codex(tmp_path, qtbot):
    project = ProjectRepository.create(tmp_path / "novel", "重开互斥")
    controller = CodexSessionController(
        session_factory=lambda project_id: CodexSessionService(
            project_id,
            CodexSessionIndex(tmp_path / "sessions.json"),
            tmp_path / "codex",
        )
    )
    controller.bind_project(project.project.id, project)
    old = controller._writer
    shared = old.outline_writer._lock
    controller.bind_project(None)
    controller.bind_project(project.project.id, project)
    assert controller._writer is not old
    assert controller._writer.outline_writer._lock is shared
    assert controller._writer.candidates._lock is shared
    controller.close()


def test_facade_adoption_rejects_unsaved_edits(review, qtbot):
    project, chapter, _, _, _, facade, _, _, _ = review
    row = completed(review, qtbot)
    facade.editorTextChanged("之后手工修改的内容。")
    assert not facade.adoptWriterDraft(row.id, False)
    assert facade.currentChapterBody == "之后手工修改的内容。"
    assert ChapterRepository(project).read_content_exact(chapter.id) == "不得被候选覆盖的正式正文。"


def test_qml_discard_retains_manuscript_and_snapshot(review, qtbot):
    project, chapter, _, writer, controller, facade, calls, window, _ = review
    row = completed(review, qtbot)
    run_id = json.loads(row.data)["run_id"]
    qtbot.waitUntil(lambda: card(window, row.id) is not None)
    button = find(card(window, row.id), "writerCandidateDiscardButton")
    assert button is not None and button.property("visible")
    QMetaObject.invokeMethod(button, "clicked")
    assert GenerationRepository(project).get(run_id).status == "DISCARDED"
    assert ChapterRepository(project).read_content_exact(chapter.id) == "不得被候选覆盖的正式正文。"
    assert writer.preview_candidate_input(run_id)["messages"]
    assert any(item.state == "DISCARDED" for item in controller._model.items())
    assert len(calls) == 1


def test_recovery_after_history_clear_restores_one_card_and_original_input(review, qtbot):
    project, _, _, writer, controller, facade, calls, window, _ = review
    row = completed(review, qtbot)
    frozen = facade.writerInputPreview(row.id)["messages"]
    # A new writer has no in-memory proposal map, as on project reopening.
    writer.revoke()
    controller._writer = NovelWriterService(
        project,
        controller._novel,
        gateway_factory=writer.gateway_factory,
        on_event=lambda event: controller._writer_event.emit(controller._epoch, event),
    )
    controller._on_history(controller._epoch, [])
    button = find(window.contentItem(), "restoreWriterCandidatesButton")
    assert button is not None
    QMetaObject.invokeMethod(button, "clicked")
    qtbot.waitUntil(lambda: not controller.is_busy and bool(controller._writer_ids))
    restored = next(item for item in controller._model.items() if item.kind == "writer_task")
    assert restored.draft_text == "新的候选。"
    assert facade.writerInputPreview(restored.id)["messages"] == frozen
    assert facade.restoreWriterDrafts()
    qtbot.waitUntil(lambda: not controller.is_busy)
    assert len([item for item in controller._model.items() if item.kind == "writer_task"]) == 1
    assert len(calls) == 1


def test_selection_capture_survives_chat_quote_and_adopts_only_original_span(review, qtbot):
    project, chapter, _, writer, controller, facade, calls, _, _ = review
    pending = next(row for row in controller._model.items() if row.state == "AWAITING_CONFIRMATION")
    assert facade.rejectWriterInput(pending.id)
    original = facade.currentChapterBody
    start, end = original.index("候选"), original.index("候选") + 2
    facade.setPlainTextSelection(start, end)
    # A less strict chat quote must not override the exact captured range.
    facade.setChatSelectionJson(
        json.dumps(
            {
                "chapter_id": chapter.id,
                "base_revision": chapter.revision,
                "content": original,
                "selection": original,
            }
        )
    )
    assert controller._editor.selection == "候选"
    assert controller._editor.selection_capture is not None
    writer.begin_turn()
    writer.generate(chapter.id, chapter.revision, "只润色选文。", recent_chapters=0)
    row = completed(review, qtbot)
    assert json.loads(row.data)["scope"] == "SELECTION"
    assert facade.adoptWriterDraft(row.id, False)
    assert (
        ChapterRepository(project).read_content_exact(chapter.id)
        == original[:start] + "新的候选。" + original[end:]
    )
    assert len(calls) == 1
