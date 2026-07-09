from pytestqt.qtbot import QtBot

from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.main_window import MainWindow
from ai_novel_studio.ui.pages.audit_window import AuditWindow
from ai_novel_studio.ui.pages.memory_window import MemoryWindow
from ai_novel_studio.ui.pages.style_rules_window import StyleRulesWindow


def _tab_titles(window_tabs: object) -> list[str]:
    tabs = window_tabs
    return [tabs.tabText(index) for index in range(tabs.count())]  # type: ignore[attr-defined]


def test_memory_window_explains_system_and_exposes_editable_layers(qtbot: QtBot) -> None:
    window = MemoryWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    assert "AI 生成前" in window.explanation_label.text()
    assert _tab_titles(window.tabs) == [
        "压缩前文",
        "人物状态",
        "人物知识",
        "读者知识",
        "正典",
        "叙事线索",
        "过期依赖",
    ]
    editor = window.editors["人物知识"]
    assert editor.isReadOnly() is False
    editor.appendPlainText("人工修订")
    assert "人工修订" in editor.toPlainText()


def test_style_window_separates_rules_samples_and_candidates(qtbot: QtBot) -> None:
    window = StyleRulesWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    assert _tab_titles(window.tabs) == ["分层规则", "人工样章", "AI 候选"]
    assert window.rules_table.rowCount() == 3
    assert window.human_sample.isReadOnly() is True
    assert window.candidate_editor.isReadOnly() is False


def test_audit_window_separates_deterministic_and_model_findings(qtbot: QtBot) -> None:
    window = AuditWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    assert _tab_titles(window.tabs) == ["确定性检查", "模型审校"]
    assert window.deterministic_table.rowCount() == 1
    assert window.model_table.rowCount() == 1
    assert window.repair_button.isEnabled() is False
    assert "阶段 6" in window.repair_button.toolTip()
    assert window.run_deterministic_audit_button.isEnabled() is True


def test_main_window_reuses_memory_style_and_audit_windows(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.chapter_sidebar.memory_button.click()
    memory = window.memory_window
    window.chapter_sidebar.memory_button.click()
    assert memory is not None
    assert window.memory_window is memory

    window.chapter_sidebar.style_button.click()
    assert window.style_rules_window is not None

    window.manuscript_panel.audit_requested.emit()
    assert window.audit_window is not None


def test_main_window_runs_deterministic_audit_on_current_editor(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_audit_window()
    assert window.audit_window is not None
    window.manuscript_panel.chapter_requirement.setPlainText("must: find the letter")
    window.manuscript_panel.editor.setPlainText("Of course, here is the chapter.")

    window.audit_window.run_deterministic_audit_button.click()

    assert window.audit_window.deterministic_table.rowCount() >= 2
    evidence = [
        window.audit_window.deterministic_table.item(row, 2).text()
        for row in range(window.audit_window.deterministic_table.rowCount())
    ]
    assert any("find the letter" in item for item in evidence)
