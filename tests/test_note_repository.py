import hashlib
import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from ai_novel_studio.infrastructure.storage.backup_service import BackupService
from ai_novel_studio.infrastructure.storage.note_repository import (
    NoteRecoveryRequired,
    NoteRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@pytest.fixture
def notes(tmp_path):
    project = ProjectRepository.create(tmp_path / "novel", "创作笔记测试")
    return project, NoteRepository(project)


def test_reading_empty_notebook_does_not_create_storage(notes):
    project, repo = notes
    assert repo.list_notes() == ()
    assert not (project.layout.root / "notes").exists()


def test_note_markdown_and_every_saved_revision_are_preserved(notes):
    project, repo = notes
    content = "\ufeff# 事件细纲\r\n\r\n|人物|动机|\r\n|---|---|\r\n|林默|寻找旧信|\r\n"
    first = repo.create("第二事件细纲", content, kind="OUTLINE")
    assert first.content == content
    assert first.source_hash == hashlib.sha256(content.encode()).hexdigest()
    second = repo.save(first.id, "# 修改后的细纲\n", expected_revision=1)
    assert second.revision == 2
    assert repo.read(first.id, revision=1) == first
    assert repo.read(first.id) == second
    assert repo.list_notes() == (second,)
    assert len(list((project.layout.root / "notes").glob("*.json"))) == 2
    with pytest.raises(ValueError):
        repo.save(first.id, "过期编辑不能覆盖", expected_revision=1)
    assert repo.read(first.id) == second


@pytest.mark.parametrize("content", ["正文\x00", "正文\x01", "坏代理\ud800"])
def test_invalid_note_text_is_rejected_before_any_revision_is_saved(notes, content):
    _, repo = notes
    with pytest.raises(ValueError):
        repo.create("注意事项", content)
    assert repo.list_notes() == ()


def test_corrupt_history_is_not_silently_replaced_with_a_valid_head(notes):
    project, repo = notes
    note = repo.create("人物", "第一版")
    repo.save(note.id, "第二版", expected_revision=1)
    path = project.layout.root / "notes" / f"{note.id}.00000001.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["content"] = "被外部修改的旧版"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        repo.read(note.id)


def test_unknown_entries_and_traversal_fail_closed_without_deleting_content(notes):
    project, repo = notes
    note = repo.create("文风", "保留克制的对话")
    with pytest.raises(ValueError):
        repo.read("../../outside")
    unexpected = project.layout.root / "notes" / "作者自行放入的文件.md"
    unexpected.write_text("不能删除", encoding="utf-8")
    with pytest.raises(ValueError):
        repo.list_notes()
    assert unexpected.read_text(encoding="utf-8") == "不能删除"
    assert (project.layout.root / "notes" / f"{note.id}.00000001.json").exists()


def test_concurrent_editors_cannot_overwrite_the_same_revision(notes):
    project, repo = notes
    note = repo.create("细纲", "原始")

    def save(content):
        try:
            return NoteRepository(project).save(note.id, content, expected_revision=1)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["编辑器一", "编辑器二"]))
    assert sum(r is not None for r in results) == 1
    assert repo.read(note.id).revision == 2
    assert repo.read(note.id, revision=1).content == "原始"


def test_abandoned_partial_write_requires_explicit_recovery_and_keeps_evidence(notes):
    project, repo = notes
    note = repo.create("注意事项", "原文")
    name = f".{note.id}.00000002.{uuid4().hex}.tmp"
    partial = project.layout.root / "notes" / name
    partial.write_bytes(b"{partial")
    assert repo.read(note.id).content == "原文"
    with pytest.raises(NoteRecoveryRequired):
        repo.save(note.id, "不可静默越过恢复", expected_revision=1)
    assert len(repo.recoveries()) == 1
    repo.recover(name, restore=False)
    assert not partial.exists()
    assert [p.read_bytes() for p in (project.layout.root / "notes-recovery").iterdir()] == [
        b"{partial"
    ]
    assert repo.save(note.id, "恢复后继续", expected_revision=1).revision == 2


def test_complete_unpublished_revision_can_be_explicitly_restored(notes):
    project, repo = notes
    first = repo.create("细纲", "最初内容")
    second = repo.save(first.id, "已完整写入但尚未发布的内容", expected_revision=1)
    folder = project.layout.root / "notes"
    name = f".{first.id}.00000002.{uuid4().hex}.tmp"
    (folder / f"{first.id}.00000002.json").rename(folder / name)
    assert repo.read(first.id) == first
    assert repo.recover(name, restore=True) == second
    assert repo.read(first.id) == second
    assert repo.read(first.id, revision=1) == first


def test_failed_publication_never_exposes_a_partial_final_revision(notes, monkeypatch):
    project, repo = notes
    note = repo.create("人物", "原版")
    operation = "rename" if os.name == "nt" else "link"

    def fail(*args, **kwargs):
        raise OSError("模拟发布中断")

    with monkeypatch.context() as patch:
        patch.setattr(os, operation, fail)
        with pytest.raises(OSError):
            repo.save(note.id, "未完成保存", expected_revision=1)
    assert repo.read(note.id) == note
    assert not list((project.layout.root / "notes").glob("*.tmp"))


def test_project_backup_includes_all_note_revisions(notes):
    project, repo = notes
    note = repo.create("文风", "必须保留的笔记")
    repo.save(note.id, "新修订也要保留", expected_revision=1)
    archive = BackupService(project).create_backup()
    with zipfile.ZipFile(archive) as saved:
        for number in (1, 2):
            assert f"notes/{note.id}.{number:08d}.json" in saved.namelist()
