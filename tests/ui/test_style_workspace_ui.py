from pathlib import Path

from pytestqt.qtbot import QtBot

from ai_novel_studio.application.style_workspace_service import StyleWorkspaceService
from ai_novel_studio.domain.memory import ReviewStatus, StyleScope
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.pages.style_rules_window import StyleRulesWindow


def test_user_can_save_and_lock_project_style_sample(qtbot: QtBot, tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    service = StyleWorkspaceService(project)
    window = StyleRulesWindow(
        WorkspaceDemoData.empty(),
        service=service,
        default_scope_id=project.project.id,
    )
    qtbot.addWidget(window)

    window.tabs.setCurrentIndex(1)
    window.sample_title.setText("第一人称样章")
    window.human_sample.setPlainText("雨落在没有名字的旧站台上。")
    window.save_sample_button.click()

    samples = service.load().samples
    assert len(samples) == 1
    assert samples[0].scope_type == StyleScope.BOOK
    assert samples[0].content == "雨落在没有名字的旧站台上。"
    assert samples[0].immutable is False

    window.sample_selector.setCurrentIndex(1)
    window.lock_sample_button.click()

    locked = service.load().samples[0]
    assert locked.immutable is True
    assert locked.review_status == ReviewStatus.LOCKED
    assert window.human_sample.isReadOnly() is True
    assert window.delete_sample_button.isEnabled() is False


def test_user_can_create_and_edit_project_style_rule(qtbot: QtBot, tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    service = StyleWorkspaceService(project)
    window = StyleRulesWindow(
        WorkspaceDemoData.empty(),
        service=service,
        default_scope_id=project.project.id,
    )
    qtbot.addWidget(window)

    window.rule_type.setText("叙述节奏")
    window.rule_text.setPlainText("动作段落优先使用短句。")
    window.save_rule_button.click()

    rules = service.load().rules
    assert len(rules) == 1
    assert rules[0].rule_text == "动作段落优先使用短句。"

    window.rules_table.selectRow(0)
    window.rule_text.setPlainText("动作段落使用短句，避免连续心理解释。")
    window.save_rule_button.click()

    updated = service.load().rules[0]
    assert updated.id == rules[0].id
    assert updated.rule_text == "动作段落使用短句，避免连续心理解释。"
