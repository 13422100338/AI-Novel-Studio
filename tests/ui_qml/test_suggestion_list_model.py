from ai_novel_studio.ui_qml.bridge.dtos import SuggestionDto
from ai_novel_studio.ui_qml.bridge.models.suggestion_list_model import (
    ROLE_BODY,
    ROLE_LABEL,
    SuggestionListModel,
)


def test_add_and_read_suggestion() -> None:
    model = SuggestionListModel()
    item = SuggestionDto(id="s1", label="润色建议", body="建议正文")
    model.add_item(item)
    assert model.rowCount() == 1
    assert model.data(model.index(0), ROLE_LABEL) == "润色建议"
    assert model.data(model.index(0), ROLE_BODY) == "建议正文"
    assert model.item_at_row(0).id == "s1"


def test_remove_suggestion() -> None:
    model = SuggestionListModel()
    model.add_item(SuggestionDto(id="s1", label="a", body="b"))
    model.add_item(SuggestionDto(id="s2", label="c", body="d"))
    model.remove_item(0)
    assert model.rowCount() == 1
    assert model.item_at_row(0).id == "s2"
    model.remove_item(99)
    assert model.rowCount() == 1


def test_items_snapshot() -> None:
    model = SuggestionListModel()
    model.add_item(SuggestionDto(id="s1", label="a", body="b"))
    assert model.items()[0].id == "s1"

