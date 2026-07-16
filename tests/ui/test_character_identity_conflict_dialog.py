from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from ai_novel_studio.application.character_identity_service import (
    CharacterIdentityService,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui.pages.character_identity_conflict_dialog import (
    CharacterIdentityConflictDialog,
)


def _service_with_duplicate_cards(tmp_path: Path) -> CharacterIdentityService:
    project = ProjectRepository.create(tmp_path / "project", "人物冲突界面测试")
    memory = CharacterMemoryRepository(project)
    memory.create_character("艾瑞克", profile="简称人物卡")
    memory.create_character("艾瑞克·温德米尔", profile="完整人物卡")
    return CharacterIdentityService(project)


def test_dialog_requires_confirmation_then_exposes_merge_undo(
    qtbot: QtBot, tmp_path: Path, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    service = _service_with_duplicate_cards(tmp_path)
    dialog = CharacterIdentityConflictDialog(service)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    assert dialog.candidate_selector.count() == 1
    assert "简称" in dialog.reason_label.text()
    assert "艾瑞克" in dialog.left_details.toPlainText()
    assert "艾瑞克" in dialog.right_details.toPlainText()
    assert dialog.right_radio.isChecked()

    qtbot.mouseClick(dialog.left_radio, Qt.MouseButton.LeftButton)
    assert dialog.left_radio.isChecked()
    assert not dialog.right_radio.isChecked()

    qtbot.mouseClick(dialog.right_radio, Qt.MouseButton.LeftButton)

    qtbot.mouseClick(dialog.merge_button, Qt.MouseButton.LeftButton)

    assert dialog.candidate_selector.count() == 0
    assert dialog.recent_selector.count() == 1
    assert "已归并" in dialog.status_label.text()
    assert len(service.memory_repository.list_characters()) == 1

    qtbot.mouseClick(dialog.undo_button, Qt.MouseButton.LeftButton)

    assert dialog.candidate_selector.count() == 1
    assert dialog.recent_selector.count() == 0
    assert "已撤销" in dialog.status_label.text()
    assert len(service.memory_repository.list_characters()) == 2
