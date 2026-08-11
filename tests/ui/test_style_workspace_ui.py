from pathlib import Path

from pytestqt.qtbot import QtBot

from ai_novel_studio.application.style_workspace_service import StyleWorkspaceService
from ai_novel_studio.domain.memory import Authority, ReviewStatus, StyleScope
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository
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


def test_style_reload_failure_clears_stale_workspace_state(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    service = StyleWorkspaceService(project)
    service.add_rule(StyleScope.BOOK, project.project.id, "人工规则", "旧规则正文")
    service.add_sample(StyleScope.BOOK, project.project.id, "人工样章", "旧样章正文")
    StyleRepository(project).add_rule(
        StyleScope.BOOK,
        project.project.id,
        "模型候选",
        "模型候选正文",
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REVIEW,
    )

    window = StyleRulesWindow(
        WorkspaceDemoData.empty(),
        service=service,
        default_scope_id=project.project.id,
    )
    qtbot.addWidget(window)

    assert window._rules
    assert window._samples
    assert window.rules_table.rowCount() == 2
    assert window.sample_selector.count() == 2
    window.sample_selector.setCurrentIndex(1)
    assert window.human_sample.toPlainText() == "旧样章正文"
    assert "模型候选正文" in window.candidate_editor.toPlainText()

    def fail_load() -> object:
        raise RuntimeError("secret-key C:\\private\\manuscript\\draft.md")

    monkeypatch.setattr(service, "load", fail_load)
    window.reload()

    assert window.status_label.text() == "文风工作区加载失败；请关闭后重新打开。"
    assert "secret-key" not in window.status_label.text()
    assert "private" not in window.status_label.text()
    assert window._rules == {}
    assert window._samples == {}
    assert window.rules_table.rowCount() == 0
    assert window.rules_table.currentRow() == -1
    assert window.sample_selector.count() == 0
    assert window.sample_selector.currentIndex() == -1
    assert window.rule_scope_id.text() == ""
    assert window.rule_type.text() == ""
    assert window.rule_text.toPlainText() == ""
    assert window.sample_scope_id.text() == ""
    assert window.sample_title.text() == ""
    assert window.human_sample.toPlainText() == ""
    assert window.candidate_editor.toPlainText() == ""
    assert window.human_sample.isReadOnly() is True
    for button in (
        window.new_rule_button,
        window.save_rule_button,
        window.delete_rule_button,
        window.new_sample_button,
        window.save_sample_button,
        window.lock_sample_button,
        window.delete_sample_button,
    ):
        assert button.isEnabled() is False
