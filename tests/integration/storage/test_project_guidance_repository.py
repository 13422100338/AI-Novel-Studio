import pytest

from ai_novel_studio.application.project_guidance_service import (
    ProjectGuidanceService,
)
from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
    ProjectGuidanceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def test_highest_system_prompt_survives_project_reopen(tmp_path) -> None:
    root = tmp_path / "novel"
    project = ProjectRepository.create(root, "Guidance")
    service = ProjectGuidanceService(ProjectGuidanceRepository(project))

    initial = service.load()
    prompt = "  主题：人在失去中学习承担。\n视角：第三人称限知。\n"
    saved = service.save_manual(
        prompt,
        expected_revision=initial.revision,
    )

    reopened = ProjectRepository.open(root)
    restored_service = ProjectGuidanceService(ProjectGuidanceRepository(reopened))
    restored = restored_service.load()

    assert saved.revision == 1
    assert restored.highest_system_prompt == prompt
    assert restored.revision == 1
    assert restored_service.read_highest_system_prompt() == restored.highest_system_prompt


def test_stale_manual_edit_cannot_overwrite_newer_project_guidance(tmp_path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Guidance")
    service = ProjectGuidanceService(ProjectGuidanceRepository(project))
    service.save_manual("第一版", expected_revision=0)

    with pytest.raises(RuntimeError, match="已经被其他操作更新"):
        service.save_manual("过期编辑", expected_revision=0)

    assert service.read_highest_system_prompt() == "第一版"
