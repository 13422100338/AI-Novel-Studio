import hashlib
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

import ai_novel_studio.infrastructure.storage.outline_repository as outline_module
from ai_novel_studio.infrastructure.storage.outline_repository import (
    OutlineConflictError,
    OutlineIntegrityError,
    OutlineRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@pytest.fixture
def project(tmp_path: Path) -> ProjectRepository:
    return ProjectRepository.create(tmp_path / "novel", "雪花小说")


def test_create_and_reopen_preserve_exact_markdown(project: ProjectRepository) -> None:
    raw = "\ufeff# 全书\r\n\r\n1. **事件**  \r\n<!-- anchor -->\r\n[正文](chapter.md)\r\n"
    repository = OutlineRepository(project)
    created = repository.create("全书", raw)
    reopened = OutlineRepository(ProjectRepository.open(project.layout.root))
    restored = reopened.read(created.version.document_id)
    assert restored == created
    document = reopened.get(created.version.document_id)
    assert document.title == "全书"
    assert document.revision == 1
    assert (project.layout.root / "outlines" / f"{document.id}.md").read_bytes() == raw.encode()


def test_noop_save_preserves_version_and_file(project: ProjectRepository) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "# 原文\n")
    document_id = created.version.document_id
    path = project.layout.root / "outlines" / f"{document_id}.md"
    before = path.stat().st_mtime_ns
    assert repository.save(document_id, created.content, expected_revision=1) == created
    assert len(repository.list_versions(document_id)) == 1
    assert path.stat().st_mtime_ns == before


def test_save_keeps_old_versions_and_rejects_stale_editor(project: ProjectRepository) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "旧大纲")
    document_id = created.version.document_id
    saved = repository.save(document_id, "新大纲", expected_revision=1)
    with pytest.raises(OutlineConflictError):
        OutlineRepository(project).save(document_id, "过期的编辑", expected_revision=1)
    assert repository.read(document_id) == saved
    assert repository.read_version(document_id, 1) == created
    assert [v.revision for v in repository.list_versions(document_id)] == [1, 2]


def test_document_order_follows_import_order(project: ProjectRepository) -> None:
    repository = OutlineRepository(project)
    first = repository.create("总览", "总览")
    second = repository.create("第二部", "事件 25")
    assert [d.id for d in repository.list_documents()] == [
        first.version.document_id,
        second.version.document_id,
    ]


def test_external_edits_block_reads_and_saves_without_overwrite(project: ProjectRepository) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "登记原文")
    document_id = created.version.document_id
    path = project.layout.root / "outlines" / f"{document_id}.md"
    path.write_bytes("外部修改\r\n".encode())
    with pytest.raises(OutlineIntegrityError):
        repository.read(document_id)
    with pytest.raises(OutlineConflictError):
        repository.save(document_id, "不能覆盖", expected_revision=1)
    assert path.read_bytes() == "外部修改\r\n".encode()
    assert repository.get(document_id).revision == 1
    assert repository.read_version(document_id, 1) == created


def test_recovery_requires_reviewed_disk_hash(project: ProjectRepository) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "旧")
    document_id = created.version.document_id
    path = project.layout.root / "outlines" / f"{document_id}.md"
    path.write_bytes("新内容".encode())
    reviewed_hash = hashlib.sha256(
        repository.inspect_working_copy(document_id).encode()
    ).hexdigest()
    path.write_bytes("再次编辑".encode())
    with pytest.raises(OutlineConflictError):
        repository.recover_from_disk(
            document_id, expected_revision=1, expected_disk_hash=reviewed_hash
        )
    assert path.read_bytes() == "再次编辑".encode()
    assert repository.get(document_id).revision == 1


def test_atomic_write_failure_keeps_committed_version(
    project: ProjectRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "旧内容")
    document_id = created.version.document_id

    def fail_write(path: Path, content: str) -> None:
        raise OSError("simulated disk full")

    original_atomic = outline_module.atomic_write_text
    monkeypatch.setattr(outline_module, "atomic_write_text", fail_write)
    with pytest.raises(OSError):
        repository.save(document_id, "新内容", expected_revision=1)
    assert repository.read_version(document_id, 1) == created
    assert len(repository.list_versions(document_id)) == 1
    with pytest.raises(OutlineIntegrityError):
        repository.read(document_id)
    monkeypatch.setattr(outline_module, "atomic_write_text", original_atomic)
    assert repository.restore_missing_working_copy(document_id, expected_revision=1) == created
    assert repository.read(document_id) == created


def test_database_abort_keeps_new_text_for_explicit_recovery(project: ProjectRepository) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "已提交的旧内容")
    document_id = created.version.document_id
    with project.database.connect() as connection:
        connection.execute(
            "CREATE TRIGGER block_outline_save BEFORE UPDATE ON outline_documents "
            "BEGIN SELECT RAISE(ABORT, 'simulated database failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        repository.save(document_id, "刚写入的新内容", expected_revision=1)
    assert repository.get(document_id).revision == 1
    assert repository.read_version(document_id, 1) == created
    with pytest.raises(OutlineIntegrityError):
        repository.read(document_id)
    recovered_text = repository.inspect_working_copy(document_id)
    assert recovered_text == "刚写入的新内容"
    with project.database.connect() as connection:
        connection.execute("DROP TRIGGER block_outline_save")
    recovered = repository.recover_from_disk(
        document_id,
        expected_revision=1,
        expected_disk_hash=hashlib.sha256(recovered_text.encode()).hexdigest(),
    )
    assert recovered.version.revision == 2
    assert repository.read(document_id).content == recovered_text
    assert repository.read_version(document_id, 1) == created


def test_corrupt_snapshot_is_never_used(project: ProjectRepository) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "原文")
    version = created.version
    path = project.layout.pipeline / "outline_versions" / version.document_id / f"{version.id}.md"
    path.write_bytes("损坏内容".encode())
    with pytest.raises(OutlineIntegrityError):
        repository.read_version(version.document_id, 1)
    with pytest.raises(OutlineIntegrityError):
        repository.read(version.document_id)
    with pytest.raises(OutlineIntegrityError):
        repository.save(version.document_id, "新内容", expected_revision=1)


def test_unknown_project_and_invalid_ids_cannot_access_files(
    project: ProjectRepository, tmp_path: Path
) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "原文")
    other = OutlineRepository(ProjectRepository.create(tmp_path / "other", "另一本"))
    with pytest.raises(KeyError):
        other.read(created.version.document_id)
    with pytest.raises(ValueError):
        repository.save("../manuscript/chapter", "不能写入", expected_revision=1)
    assert repository.read(created.version.document_id) == created


@pytest.mark.parametrize("content", ["bad\x00text", "x" * 20_000_001], ids=["nul", "oversize"])
def test_invalid_input_creates_no_documents(project: ProjectRepository, content: str) -> None:
    repository = OutlineRepository(project)
    with pytest.raises(ValueError):
        repository.create("全书", content)
    assert repository.list_documents() == ()


def test_redirected_outline_directory_is_rejected(
    project: ProjectRepository, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = project.layout.root / "outlines"
    if os.name == "nt":
        subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OutlineIntegrityError):
        OutlineRepository(project).create("全书", "不能写到外面")
    assert list(outside.iterdir()) == []


def test_external_edit_at_replacement_boundary_is_retained(
    project: ProjectRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "登记旧版")
    document_id = created.version.document_id
    working = project.layout.root / "outlines" / f"{document_id}.md"
    original_atomic = outline_module.atomic_write_text
    original_rename = os.rename

    def external_before_atomic(path: Path, content: str) -> None:
        if path == working:
            working.write_bytes("外部最后一刻修改".encode())
        original_atomic(path, content)

    def external_before_rename(source: Path, destination: Path) -> None:
        if source == working:
            working.write_bytes("外部最后一刻修改".encode())
        original_rename(source, destination)

    monkeypatch.setattr(outline_module, "atomic_write_text", external_before_atomic)
    monkeypatch.setattr(outline_module.os, "rename", external_before_rename)
    with pytest.raises(OutlineConflictError):
        repository.save(document_id, "本次候选修改", expected_revision=1)
    assert working.read_bytes() == "外部最后一刻修改".encode()
    assert repository.read_version(document_id, 1) == created
    assert repository.get(document_id).revision == 1


def test_external_recreation_during_publish_is_not_replaced(
    project: ProjectRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "登记旧版")
    document_id = created.version.document_id
    working = project.layout.root / "outlines" / f"{document_id}.md"
    original_atomic = outline_module.atomic_write_text
    original_link = os.link

    def external_before_atomic(path: Path, content: str) -> None:
        if path == working:
            working.write_bytes("外部重建的文件".encode())
        original_atomic(path, content)

    def external_before_link(source: Path, destination: Path) -> None:
        if destination == working:
            working.write_bytes("外部重建的文件".encode())
        original_link(source, destination)

    monkeypatch.setattr(outline_module, "atomic_write_text", external_before_atomic)
    monkeypatch.setattr(outline_module.os, "link", external_before_link)
    with pytest.raises(OutlineConflictError):
        repository.save(document_id, "本次候选修改", expected_revision=1)
    assert working.read_bytes() == "外部重建的文件".encode()
    assert repository.read_version(document_id, 1) == created
    assert repository.get(document_id).revision == 1


def test_missing_working_copy_can_only_be_restored_exclusively(project: ProjectRepository) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "已登记的原文")
    document_id = created.version.document_id
    working = project.layout.root / "outlines" / f"{document_id}.md"
    working.unlink()
    with pytest.raises(OutlineConflictError):
        repository.restore_missing_working_copy(document_id, expected_revision=2)
    assert not working.exists()
    assert repository.restore_missing_working_copy(document_id, expected_revision=1) == created
    working.write_bytes("外部重建".encode())
    with pytest.raises(OutlineConflictError):
        repository.restore_missing_working_copy(document_id, expected_revision=1)
    assert working.read_bytes() == "外部重建".encode()


def test_create_database_failure_retains_unregistered_assets(project: ProjectRepository) -> None:
    repository = OutlineRepository(project)
    with project.database.connect() as connection:
        connection.execute(
            "CREATE TRIGGER block_outline_create BEFORE INSERT ON outline_versions "
            "BEGIN SELECT RAISE(ABORT, 'simulated create failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        repository.create("全书", "创建失败也要保留的内容")
    assert repository.list_documents() == ()
    files = list((project.layout.root / "outlines").glob("*.md"))
    assert len(files) == 1
    assert files[0].read_bytes() == "创建失败也要保留的内容".encode()


def test_recovery_rejects_stale_revision(project: ProjectRepository) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "旧版")
    document_id = created.version.document_id
    saved = repository.save(document_id, "新版", expected_revision=1)
    with pytest.raises(OutlineConflictError):
        repository.recover_from_disk(
            document_id, expected_revision=1, expected_disk_hash=saved.version.content_hash
        )
    assert repository.read(document_id) == saved


def test_retained_disk_copy_is_independent_of_working_file(project: ProjectRepository) -> None:
    repository = OutlineRepository(project)
    created = repository.create("全书", "旧版本原文")
    document_id = created.version.document_id
    repository.save(document_id, "新版本原文", expected_revision=1)
    retained = list((project.layout.pipeline / "outline_versions" / document_id).glob("disk_*.md"))
    assert len(retained) == 1
    working = project.layout.root / "outlines" / f"{document_id}.md"
    working.write_bytes("外部原地编辑".encode())
    assert retained[0].read_bytes() == "旧版本原文".encode()
    assert repository.read_version(document_id, 1) == created
