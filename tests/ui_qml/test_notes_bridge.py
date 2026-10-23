import pytest
from PySide6.QtCore import QUrl

from ai_novel_studio.infrastructure.storage.note_repository import NoteRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bridge.notes_bridge import NotesBridge


@pytest.fixture
def book(tmp_path, qapp):
    project = ProjectRepository.create(tmp_path / "novel", "笔记界面验证")
    bridge = NotesBridge()
    bridge.bind_project(project)
    return project, bridge


def test_create_edit_reopen_and_explicit_writer_selection(book):
    project, bridge = book
    assert bridge.createNote("政变场景细纲", "OUTLINE")
    bridge.edit("# 细纲\n\n**动机**与因果。")
    assert bridge.state["dirty"]
    assert bridge.flush()
    identity = bridge.state["currentId"]
    assert bridge.state["mode"] == "NONE"
    assert bridge.toggleSelected(identity, True)
    assert bridge.state["mode"] == "FULL"
    assert bridge.setMode("SUMMARY")
    assert bridge.current_selection.mode == "SUMMARY"
    bridge.bind_project(None)
    bridge.bind_project(project)
    assert bridge.state["text"].endswith("因果。")
    assert bridge.state["mode"] == "NONE"


def test_conflict_preserves_editor_and_blocks_switching(book, tmp_path):
    project, bridge = book
    assert bridge.createNote("人物", "CHARACTER")
    identity = bridge.state["currentId"]
    other = NoteRepository(project).create("文风", "文风原文")
    bridge.edit("本地未保存修改")
    NoteRepository(project).save(identity, "另一个窗口的新版", expected_revision=1)
    assert not bridge.selectDocument(other.id)
    assert bridge.state["currentId"] == identity
    assert bridge.state["text"] == "本地未保存修改"
    destination = tmp_path / "本地编辑.md"
    assert bridge.exportFile(QUrl.fromLocalFile(str(destination)))
    assert destination.read_text(encoding="utf-8") == "本地未保存修改"
    assert bridge.reload()
    assert bridge.state["text"] == "另一个窗口的新版"


def test_import_preserves_raw_markdown_and_export_never_overwrites(book, tmp_path):
    project, bridge = book
    raw = "\ufeff# 文风\r\n保留作者原样。\r\n"
    source = tmp_path / "原文.md"
    source.write_bytes(raw.encode())
    assert bridge.importFile(QUrl.fromLocalFile(str(source)))
    identity = bridge.state["currentId"]
    assert NoteRepository(project).read(identity).content == raw
    assert not bridge.exportFile(QUrl.fromLocalFile(str(source)))
    assert source.read_bytes() == raw.encode()
