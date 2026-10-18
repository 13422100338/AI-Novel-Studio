import pytest
from PySide6.QtCore import QPointF

from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.readonly_views import CharacterJourneyViewDto, CharacterViewDto

from .test_agent_timeline_geometry import _find_all
from .test_qml_shell import _load_engine


@pytest.mark.parametrize("width", [1100, 1440])
def test_character_rows_and_journeys_contain_content_and_fit_details(qtbot, width):
    facade = MockNovelStudioFacade()
    journey = CharacterJourneyViewDto(
        "state-1",
        "chapter-1",
        motivation="寻找失踪的同伴",
        psychology="保持警觉",
        goal="调查旧港口",
        recent_activity="收到来信",
    )
    facade._characters_model.set_items(
        [
            CharacterViewDto("person-1", "艾瑞克·冯·温德米尔", journey=(journey,)),
            CharacterViewDto(
                "person-2", "带有很长姓名的人物" * 4, profile="人物档案" * 35, goal="人物目标" * 20
            ),
            CharacterViewDto("person-3", "只有姓名"),
        ]
    )
    engine, facade, theme = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]
    window.setWidth(width)
    facade.toggleAiDrawer(True)
    facade.setActiveNav("library")
    facade.selectCharacter(0)
    qtbot.waitUntil(lambda: len(_find_all(window.contentItem(), "characterName")) >= 2)
    cards = _find_all(window.contentItem(), "characterCard")
    assert cards
    for card in cards:
        assert card.height() >= 56
        for name in _find_all(card, "characterName"):
            point = name.mapToItem(card, QPointF(0, 0))
            assert point.y() >= 8
            assert point.y() + name.height() <= card.height() - 8
            assert name.width() <= card.width() - 16
    page = _find_all(window.contentItem(), "charactersPage")[0]
    listing = _find_all(window.contentItem(), "charactersList")[0]
    detail = _find_all(window.contentItem(), "characterDetail")[0]
    for item in (listing, detail):
        point = item.mapToItem(page, QPointF(0, 0))
        assert point.x() >= 0 and point.x() + item.width() <= page.width() + 1
        assert point.y() >= 0 and point.y() + item.height() <= page.height() + 1
    qtbot.waitUntil(lambda: bool(_find_all(window.contentItem(), "characterJourneyCard")))
    card = _find_all(window.contentItem(), "characterJourneyCard")[0]
    assert card.height() >= 48
