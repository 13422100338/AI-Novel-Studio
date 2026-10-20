from pathlib import Path

import pytest

from ai_novel_studio.application.outline_service import OutlineService
from ai_novel_studio.infrastructure.storage.outline_repository import (
    OutlineConflictError,
    OutlineRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def test_export_preserves_editor_text_without_overwriting_existing_file(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "大纲工作区")
    service = OutlineService(OutlineRepository(project))
    raw = "\ufeff# 完整大纲\r\n<!-- 注释 -->\r\n[章节](../manuscript/chapter.md)\r\n"
    destination = tmp_path / "导出.md"
    service.export_text(raw, destination)
    assert destination.read_bytes() == raw.encode("utf-8")
    with pytest.raises(FileExistsError):
        service.export_text("不能覆盖", destination)
    assert destination.read_bytes() == raw.encode("utf-8")


def test_document_reorder_is_explicit_and_keeps_content_versions(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "大纲工作区")
    repository = OutlineRepository(project)
    first = repository.create("总览", "总览原文")
    second = repository.create("分卷", "事件原文")
    before = tuple(d.id for d in repository.list_documents())
    repository.reorder(tuple(reversed(before)), expected_order=before)
    assert [d.id for d in repository.list_documents()] == list(reversed(before))
    assert repository.read(first.version.document_id) == first
    assert repository.read(second.version.document_id) == second
    with pytest.raises(OutlineConflictError):
        repository.reorder(before, expected_order=before)


def test_invalid_document_order_does_not_drop_documents(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "大纲工作区")
    repository = OutlineRepository(project)
    repository.create("总览", "原文")
    before = tuple(d.id for d in repository.list_documents())
    with pytest.raises(ValueError):
        repository.reorder((), expected_order=before)
    assert tuple(d.id for d in repository.list_documents()) == before
