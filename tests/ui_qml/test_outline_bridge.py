import pytest
from PySide6.QtCore import QUrl

from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.outline_repository import OutlineRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bridge.outline_bridge import OutlineBridge


@pytest.fixture
def workspace(tmp_path, qapp):
    project = ProjectRepository.create(tmp_path / "novel", "大纲工作区")
    bridge = OutlineBridge()
    bridge.bind_project(project)
    yield project, bridge
    bridge.bind_project(None)
    bridge.deleteLater()


def test_import_load_is_clean_and_edit_save_preserves_original_format(workspace, tmp_path):
    project, bridge = workspace
    source = tmp_path / "大纲.md"
    raw = "\ufeff# 全书\r\n旧段\n尾段\r\n"
    source.write_bytes(raw.encode())
    assert bridge.importFile(QUrl.fromLocalFile(str(source)))
    document_id = bridge.state["currentId"]
    bridge.edit(bridge.state["text"])
    assert not bridge.state["dirty"]
    assert bridge.state["revision"] == 1
    bridge.edit(bridge.state["text"].replace("旧段", "新段"))
    assert bridge.flush()
    assert OutlineRepository(project).read(document_id).content == raw.replace("旧段", "新段")
    assert source.read_bytes() == raw.encode()


def test_edit_is_autosaved(workspace, qtbot):
    project, bridge = workspace
    assert bridge.newDocument("总览")
    bridge.edit("# 第一部\n\n25. 政变\n")
    qtbot.waitUntil(lambda: bridge.state["dirty"] is False, timeout=4000)
    assert OutlineRepository(project).read(bridge.state["currentId"]).content.endswith("25. 政变\n")


def test_note_reference_is_versioned_markdown_and_keeps_the_note_unchanged(workspace):
    from ai_novel_studio.infrastructure.storage.note_repository import NoteRepository

    project, bridge = workspace
    note = NoteRepository(project).create("场景[细纲]", "作者的原始笔记")
    assert bridge.newDocument("全书")
    bridge.edit("# 全书\n\n## 事件一\n必须发生的事。\n")
    assert bridge.flush()
    bridge.set_note_documents([{"id": note.id, "title": note.title}])
    assert bridge.insertNoteLink(note.id, 3)
    snapshot = OutlineRepository(project).read(bridge.state["currentId"])
    assert f"(novel://note/{note.id})" in snapshot.content
    assert "场景\\[细纲\\]" in snapshot.content
    assert bridge.references[0]["refs"][0]["title"] == note.title
    assert NoteRepository(project).read(note.id).content == "作者的原始笔记"
    assert not bridge.insertNoteLink("../../other-project", 3)


def test_outline_note_link_opens_the_note_without_selecting_it_for_writing(tmp_path, qapp):
    from ai_novel_studio.infrastructure.storage.note_repository import NoteRepository
    from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade

    project = ProjectRepository.create(tmp_path / "book", "笔记链接")
    note = NoteRepository(project).create("细纲", "只讨论，不生成")
    OutlineRepository(project).create("全书", f"## 事件\n[细纲](novel://note/{note.id})\n")
    facade = MockNovelStudioFacade()
    assert facade.openProject(str(project.layout.root)) == ""
    assert facade.outline.references[0]["refs"][0]["available"] is True
    assert facade.openOutlineNote(note.id)
    assert facade.activeNav == "notes" and facade.notes.state["currentId"] == note.id
    assert facade.notes.current_selection.mode == "NONE"
    facade.closeProject()


def test_failed_save_blocks_document_switch_and_keeps_exportable_buffer(workspace, tmp_path):
    project, bridge = workspace
    assert bridge.newDocument("第一份")
    first = bridge.state["currentId"]
    second = OutlineRepository(project).create("第二份", "第二份原文").version.document_id
    bridge.edit("未保存的本地编辑")
    working = project.layout.root / "outlines" / f"{first}.md"
    working.write_bytes("外部改动".encode())
    assert not bridge.selectDocument(second)
    assert bridge.state["currentId"] == first
    assert bridge.state["text"] == "未保存的本地编辑"
    assert bridge.state["dirty"]
    destination = tmp_path / "本地副本.md"
    assert bridge.exportFile(QUrl.fromLocalFile(str(destination)))
    assert destination.read_text(encoding="utf-8") == "未保存的本地编辑"
    assert working.read_bytes() == "外部改动".encode()


def test_reimport_requires_preview_and_stale_preview_cannot_replace_edits(workspace, tmp_path):
    project, bridge = workspace
    assert bridge.newDocument("总览")
    source = tmp_path / "新版.md"
    source.write_text("# 新版\n", encoding="utf-8")
    assert bridge.previewReimport(QUrl.fromLocalFile(str(source)))
    assert OutlineRepository(project).read(bridge.state["currentId"]).content == ""
    bridge.edit("预览后新增的编辑")
    assert not bridge.applyPreview()
    assert bridge.state["text"] == "预览后新增的编辑"
    assert bridge.flush()
    assert bridge.previewReimport(QUrl.fromLocalFile(str(source)))
    assert bridge.applyPreview()
    assert bridge.state["text"] == "# 新版\n"
    assert bridge.state["revision"] == 3


def test_history_restore_and_project_reopen(workspace):
    project, bridge = workspace
    assert bridge.newDocument("总览")
    bridge.edit("旧版")
    assert bridge.flush()
    bridge.edit("新版")
    assert bridge.flush()
    assert bridge.previewVersion(2)
    assert bridge.applyPreview()
    assert bridge.state["text"] == "旧版"
    assert bridge.state["revision"] == 4
    bridge.bind_project(project)
    assert bridge.state["text"] == "旧版"


def test_corrupt_first_document_is_not_shown_as_loaded(workspace):
    project, bridge = workspace
    snapshot = OutlineRepository(project).create("缺失的大纲", "原文")
    document_id = snapshot.version.document_id
    (project.layout.root / "outlines" / f"{document_id}.md").unlink()
    bridge.bind_project(project)
    assert bridge.state["currentId"] == document_id
    assert bridge.state["text"] == ""
    assert not bridge.state["loaded"]
    assert bridge.restoreMissing()
    assert bridge.state["text"] == "原文"


def test_remote_import_is_rejected_without_dropping_current_document(workspace):
    project, bridge = workspace
    assert bridge.newDocument("总览")
    current = bridge.state["currentId"]
    assert not bridge.importFile(QUrl("https://example.invalid/book.md"))
    assert bridge.state["currentId"] == current
    assert len(OutlineRepository(project).list_documents()) == 1


def test_reimport_cannot_adopt_a_server_revision_the_author_has_not_seen(workspace, tmp_path):
    project, bridge = workspace
    assert bridge.newDocument("总览")
    current = bridge.state["currentId"]
    repository = OutlineRepository(project)
    repository.save(current, "另一个编辑器保存的新版", expected_revision=1)
    source = tmp_path / "replace.md"
    source.write_text("不能覆盖未审阅的修改", encoding="utf-8")
    assert not bridge.previewReimport(QUrl.fromLocalFile(str(source)))
    assert repository.read(current).content == "另一个编辑器保存的新版"


def test_same_project_structure_refresh_keeps_pending_outline_edits(workspace):
    project, bridge = workspace
    assert bridge.newDocument("总览")
    current = bridge.state["currentId"]
    bridge.edit("尚未保存的事件设计")
    bridge.bind_project(project)
    assert bridge.state["currentId"] == current
    assert bridge.state["text"] == "尚未保存的事件设计"
    assert bridge.state["dirty"]


def test_navigation_includes_child_scenes_and_groups_repeated_chapters(workspace):
    project, bridge = workspace
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id, "旧信", "1", "正式原文。"
    )
    assert bridge.newDocument("总览")
    bridge.edit(
        "# 全书\n## 第一卷\n### 事件一\n#### 场景一\n细节一。\n"
        "#### 场景二\n细节二。\n### 事件二\n后续。\n"
    )
    assert bridge.flush()
    for title in ("场景一", "场景二"):
        line = next(h["line"] for h in bridge.state["headings"] if h["title"] == title)
        assert bridge.insertChapterLink(chapter.id, line)
    event = next(h for h in bridge.state["headings"] if h["title"] == "事件一")
    bridge.selectHeading(event["line"])
    assert len(bridge.navigation["chapters"]) == 1
    assert bridge.navigation["chapters"][0]["linkCount"] == 2
    assert not bridge.navigation["chapters"][0]["confirmed"]
    scene = next(h for h in bridge.state["headings"] if h["title"] == "场景二")
    bridge.selectHeading(scene["line"])
    assert bridge.navigation["chapters"][0]["linkCount"] == 1
    following = next(h for h in bridge.state["headings"] if h["title"] == "事件二")
    bridge.selectHeading(following["line"])
    assert bridge.navigation["chapters"] == []


def test_navigation_uses_utf16_and_resets_when_switching_documents(workspace):
    _, bridge = workspace
    assert bridge.newDocument("第一份")
    source = "# 全书😀\n\n第一段🌊\n\n## 第二事件\n正文。"
    bridge.edit(source)
    assert bridge.flush()
    heading = bridge.state["headings"][-1]
    bridge.selectHeading(heading["line"])
    expected = len(source[: source.index("## 第二事件")].encode("utf-16-le")) // 2
    assert bridge.navigation["sourcePosition"] == expected
    assert bridge.navigation["sourceLine"] == heading["line"]
    bridge.setSourceCursor(10000)
    assert bridge.navigation["sourcePosition"] == expected
    bridge.edit("短")
    assert bridge.navigation["sourcePosition"] == 1
    assert bridge.newDocument("第二份")
    assert bridge.navigation["sourcePosition"] == 0
    assert bridge.navigation["chapters"] == []
