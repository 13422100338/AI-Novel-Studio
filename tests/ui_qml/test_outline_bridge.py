import pytest
from PySide6.QtCore import QUrl

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
