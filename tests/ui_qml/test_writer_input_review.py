from types import SimpleNamespace

import pytest
from PySide6.QtCore import QMetaObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

from ai_novel_studio.application.novel_read_service import NovelEditorSnapshot, NovelReadService
from ai_novel_studio.application.novel_writer_service import NovelWriterService
from ai_novel_studio.infrastructure.llm import (
    LLMStreamEvent,
    ModelCapabilities,
    ModelRoute,
    StreamEventKind,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.note_repository import NoteRepository
from ai_novel_studio.infrastructure.storage.outline_repository import OutlineRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
from ai_novel_studio.ui_qml.bridge.codex_session_bridge import CodexSessionController
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade


def find(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        result = find(child, name)
        if result is not None:
            return result
    return None


@pytest.fixture
def review(tmp_path, qtbot, request):
    project = ProjectRepository.create(tmp_path / "novel", "输入确认界面")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id, "当前章", "1", "不得被候选覆盖的正式正文。"
    )
    outline = OutlineRepository(project).create("全书大纲", "# 全书原文\n当前事件\n独有末尾。")
    calls = []
    route = ModelRoute("provider", "writer")

    class Gateway:
        configuration = SimpleNamespace(
            routes=SimpleNamespace(resolve=lambda _: route),
            model=lambda _: SimpleNamespace(capabilities=ModelCapabilities(context_window=1000000)),
        )

        def stream(self, purpose, messages, output_token_limit):
            calls.append(messages)
            yield LLMStreamEvent(StreamEventKind.TEXT, text="新的候选。")
            yield LLMStreamEvent(StreamEventKind.COMPLETED)

    class Port:
        has_saved_thread = False

        def close(self):
            pass

    controller = CodexSessionController(session_factory=lambda _: Port())
    facade = MockNovelStudioFacade(codex_controller=controller)
    assert facade.openProject(str(project.layout.root)) == ""
    novel = NovelReadService(project)
    snapshot = NovelEditorSnapshot(
        chapter.id, chapter.title, chapter.revision, chapters.read_content_exact(chapter.id)
    )
    novel.update_editor(snapshot)
    controller._novel = novel
    controller.update_editor(snapshot)
    writer = NovelWriterService(
        project,
        novel,
        gateway_factory=Gateway,
        on_event=lambda event: controller._writer_event.emit(controller._epoch, event),
    )
    controller._writer = writer
    note_mode = getattr(request, "param", "NONE")
    if note_mode != "NONE":
        note = NoteRepository(project).create("场景细纲", "NOTE-ORIGINAL-UI-不应被误当成已发生正文")
        facade.notes.refresh()
        facade.notes.toggleSelected(note.id, True)
        facade.notes.setMode(note_mode)
    writer.begin_turn()
    writer.generate(
        chapter.id,
        chapter.revision,
        "根据事件展开场景。",
        recent_chapters=0,
        notes_summary="UI-SUMMARY-保持克制的语气。" if note_mode == "SUMMARY" else "",
    )
    facade.setReduceMotion(True)
    facade.toggleAiDrawer(True)
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
    _, theme = register_frontend_types(engine, facade)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    qtbot.waitUntil(lambda: find(window.contentItem(), "writerInputReviewButton") is not None)
    yield project, chapter, outline, writer, controller, facade, calls, window, warnings
    facade.closeProject()
    engine.deleteLater()
    qtbot.wait(30)


def test_actual_qml_confirmation_is_required_before_any_model_call(review, qtbot):
    project, chapter, outline, writer, controller, facade, calls, window, warnings = review
    assert calls == []
    QMetaObject.invokeMethod(find(window.contentItem(), "writerInputReviewButton"), "clicked")
    qtbot.waitUntil(lambda: find(window.contentItem(), "writerInputMessageChoice") is not None)
    choices = find(window.contentItem(), "writerInputMessageChoice")
    choices.setProperty("currentIndex", 1)
    text = find(window.contentItem(), "writerInputMessageText").property("text")
    assert "# 全书原文\n当前事件\n独有末尾。" in text
    assert calls == []
    QMetaObject.invokeMethod(find(window.contentItem(), "writerInputConfirmButton"), "clicked")
    qtbot.waitUntil(lambda: not controller.is_busy and bool(calls))
    assert len(calls) == 1
    assert "# 全书原文\n当前事件\n独有末尾。" in "\n".join(m.content for m in calls[0])
    assert ChapterRepository(project).read_content_exact(chapter.id) == "不得被候选覆盖的正式正文。"
    assert not [w for w in warnings if "WriterInputReview.qml" in w or "WriterTaskCard.qml" in w]


@pytest.mark.parametrize("review", ["FULL", "SUMMARY"], indirect=True)
def test_note_material_can_be_reviewed_before_the_exact_messages_are_sent(review, qtbot):
    project, chapter, _, _, _, _, calls, window, warnings = review
    assert calls == []
    QMetaObject.invokeMethod(find(window.contentItem(), "writerInputReviewButton"), "clicked")
    qtbot.waitUntil(lambda: find(window.contentItem(), "writerInputMessageChoice") is not None)
    choices = find(window.contentItem(), "writerInputMessageChoice")
    labels = choices.property("model")
    if hasattr(labels, "toVariant"):
        labels = labels.toVariant()
    index = next(i for i, label in enumerate(labels) if "[AUTHOR_NOTE" in label)
    choices.setProperty("currentIndex", index)
    displayed = find(window.contentItem(), "writerInputMessageText").property("text")
    assert "NOTE-ORIGINAL-UI" in displayed or "UI-SUMMARY" in displayed
    QMetaObject.invokeMethod(find(window.contentItem(), "writerInputConfirmButton"), "clicked")
    qtbot.waitUntil(lambda: bool(calls))
    actual = "\n".join(m.content for m in calls[0])
    assert displayed in actual
    if "UI-SUMMARY" in displayed:
        assert "NOTE-ORIGINAL-UI" not in actual
    assert not [w for w in warnings if "WriterInputReview" in w]
    assert ChapterRepository(project).read_content_exact(chapter.id) == "不得被候选覆盖的正式正文。"
    assert not [w for w in warnings if "WriterInputReview.qml" in w or "WriterTaskCard.qml" in w]


def test_changed_outline_cannot_be_confirmed_from_the_open_review(review, qtbot):
    project, chapter, outline, writer, controller, facade, calls, window, warnings = review
    QMetaObject.invokeMethod(find(window.contentItem(), "writerInputReviewButton"), "clicked")
    OutlineRepository(project).save(outline.version.document_id, "# 新大纲", expected_revision=1)
    QMetaObject.invokeMethod(find(window.contentItem(), "writerInputConfirmButton"), "clicked")
    qtbot.waitUntil(lambda: not controller.is_busy)
    assert calls == []
    assert any(row.state == "STALE" for row in controller._model.items())
