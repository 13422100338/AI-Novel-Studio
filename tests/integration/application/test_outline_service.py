from pathlib import Path

import pytest

from ai_novel_studio.application.outline_service import OutlineService
from ai_novel_studio.infrastructure.storage.outline_repository import (
    OutlineConflictError,
    OutlineRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def test_import_and_reimport_preserve_source_and_full_text(tmp_path: Path) -> None:
    source = tmp_path / "全书.md"
    raw = ("# 全书\r\n\r\n## 25. 政变\r\n<!-- keep -->\r\n" * 1000).encode()
    source.write_bytes(raw)
    project = ProjectRepository.create(tmp_path / "novel", "Outline")
    repository = OutlineRepository(project)
    service = OutlineService(repository)
    imported = service.import_file(source)
    document_id = imported.version.document_id
    assert imported.content.encode() == raw
    assert source.read_bytes() == raw
    assert repository.get(document_id).title == "全书"
    assert service.reimport_file(document_id, source, expected_revision=1) == imported
    source.write_bytes("# 新版\r\n".encode())
    saved = service.reimport_file(document_id, source, expected_revision=1)
    assert saved.version.revision == 2
    with pytest.raises(OutlineConflictError):
        service.reimport_file(document_id, source, expected_revision=1)
    assert repository.read_version(document_id, 1) == imported


def test_restore_old_version_creates_new_revision(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Outline")
    repository = OutlineRepository(project)
    service = OutlineService(repository)
    created = repository.create("全书", "旧大纲")
    document_id = created.version.document_id
    repository.save(document_id, "新大纲", expected_revision=1)
    restored = service.restore_version(document_id, 1, expected_revision=2)
    assert restored.content == "旧大纲"
    assert restored.version.revision == 3
    assert repository.read_version(document_id, 2).content == "新大纲"
    assert len(repository.list_versions(document_id)) == 3


def test_invalid_utf8_and_nul_are_rejected_without_partial_import(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Outline")
    repository = OutlineRepository(project)
    service = OutlineService(repository)
    for payload in (b"\xff", b"before\x00after"):
        source = tmp_path / "bad.md"
        source.write_bytes(payload)
        with pytest.raises(ValueError):
            service.import_file(source)
        assert source.read_bytes() == payload
        assert repository.list_documents() == ()
