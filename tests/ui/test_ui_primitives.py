from dataclasses import FrozenInstanceError

import pytest
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.theme import application_stylesheet
from ai_novel_studio.ui.widgets.chat_bubble import ChatBubble
from ai_novel_studio.ui.widgets.collapsible_section import CollapsibleSection
from ai_novel_studio.ui.widgets.metric_chip import MetricChip


def test_theme_defines_draggable_scrollbar_handles() -> None:
    stylesheet = application_stylesheet()

    assert "QScrollBar::handle:vertical" in stylesheet
    assert "QScrollBar::handle:horizontal" in stylesheet
    assert "min-height" in stylesheet
    assert "min-width" in stylesheet


def test_demo_data_is_immutable_and_populated() -> None:
    data = WorkspaceDemoData.sample()

    assert data.volumes
    assert data.characters
    assert data.messages
    assert data.brief.sections
    with pytest.raises(FrozenInstanceError):
        data.project_title = "Changed"  # type: ignore[misc]


def test_collapsible_section_controls_content_visibility(qtbot: QtBot) -> None:
    content = QLabel("content")
    section = CollapsibleSection("人物状态", content)
    qtbot.addWidget(section)

    assert section.is_expanded() is True
    section.set_expanded(False)
    assert section.is_expanded() is False
    assert content.isHidden() is True
    section.set_expanded(True)
    assert content.isHidden() is False


def test_chat_bubble_exposes_role_for_styling(qtbot: QtBot) -> None:
    assistant = ChatBubble("assistant", "你好")
    user = ChatBubble("user", "继续")
    qtbot.addWidget(assistant)
    qtbot.addWidget(user)

    assert assistant.property("chatRole") == "assistant"
    assert user.property("chatRole") == "user"
    assert assistant.text() == "你好"


def test_metric_chip_updates_value(qtbot: QtBot) -> None:
    metric = MetricChip("输入", "12.4K")
    qtbot.addWidget(metric)

    metric.set_value("13.1K")

    assert metric.value_text() == "13.1K"
