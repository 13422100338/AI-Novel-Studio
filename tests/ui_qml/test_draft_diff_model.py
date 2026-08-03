from ai_novel_studio.ui_qml.bridge.models.draft_diff_model import (
    ROLE_BLOCK_ID,
    ROLE_CURRENT_TEXT,
    ROLE_DRAFT_TEXT,
    ROLE_KIND,
    DraftDiffModel,
)
from ai_novel_studio.ui_qml.bridge.paragraph_diff import diff_paragraphs


def _sample_blocks():
    return diff_paragraphs("第一段\n\n旧段", "第一段\n\n新段")


def test_model_exposes_roles() -> None:
    model = DraftDiffModel()
    model.set_blocks(_sample_blocks())

    assert model.rowCount() >= 2
    replaced = next(
        row
        for row in range(model.rowCount())
        if model.data(model.index(row), ROLE_KIND) == "replaced"
    )
    index = model.index(replaced)
    assert model.data(index, ROLE_BLOCK_ID) is not None
    assert model.data(index, ROLE_CURRENT_TEXT) == "旧段"
    assert model.data(index, ROLE_DRAFT_TEXT) == "新段"


def test_rebuild_replaces_blocks() -> None:
    model = DraftDiffModel()
    model.set_blocks(_sample_blocks())
    first_count = model.rowCount()

    model.set_blocks(_sample_blocks()[:1])

    assert model.rowCount() == 1
    assert first_count > 1


def test_empty_model() -> None:
    model = DraftDiffModel()
    assert model.rowCount() == 0
    assert model.blocks() == ()

