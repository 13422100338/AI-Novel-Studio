from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.application.subject_inspection_service import (
    SubjectInspectionRequest,
    SubjectInspectionService,
)
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.subject import SubjectType
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository


def _service(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Subject inspection")
    return SubjectInspectionService(SubjectRepository(project)), project


def test_inspection_returns_subject_with_aliases(tmp_path: Path) -> None:
    service, project = _service(tmp_path)
    character = CharacterMemoryRepository(project).create_character(
        "艾瑞克", aliases=("温德米尔",)
    )
    subject_id = SubjectRepository(project).resolve_character_name("艾瑞克")[0].id

    inspections = service.inspect(SubjectInspectionRequest((subject_id,)))

    assert len(inspections) == 1
    inspection = inspections[0]
    assert inspection.subject_id == subject_id
    assert inspection.canonical_name == "艾瑞克"
    assert inspection.subject_type is SubjectType.CHARACTER
    assert inspection.active is True
    assert "温德米尔" in inspection.aliases
    assert character.id


def test_inspection_rejects_unknown_subject(tmp_path: Path) -> None:
    service, _project = _service(tmp_path)

    with pytest.raises(ValueError):
        service.inspect(SubjectInspectionRequest((str(new_id()),)))


def test_request_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SubjectInspectionRequest(())
    with pytest.raises(ValueError):
        SubjectInspectionRequest(("not-a-uuid",))
    duplicated = str(new_id())
    with pytest.raises(ValueError):
        SubjectInspectionRequest((duplicated, duplicated))
