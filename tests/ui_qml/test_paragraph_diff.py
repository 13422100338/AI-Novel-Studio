"""Frontend Wave F7: paragraph diff and apply logic."""

from ai_novel_studio.ui_qml.bridge.paragraph_diff import (
    apply_diff_blocks,
    diff_paragraphs,
    split_paragraphs,
)


def test_split_paragraphs() -> None:
    assert split_paragraphs("") == ()
    assert split_paragraphs("  \n  ") == ()
    assert split_paragraphs("一段") == ("一段",)
    assert split_paragraphs("一段\n\n二段") == ("一段", "二段")


def test_no_changes_produces_only_unchanged() -> None:
    text = "第一段\n\n第二段"
    blocks = diff_paragraphs(text, text)
    assert [block.kind for block in blocks] == ["unchanged"]
    assert blocks[0].current_text == text


def test_replaced_paragraph() -> None:
    blocks = diff_paragraphs("第一段\n\n旧第二段\n\n第三段", "第一段\n\n新第二段\n\n第三段")
    kinds = [block.kind for block in blocks]
    assert "replaced" in kinds
    replaced = next(block for block in blocks if block.kind == "replaced")
    assert replaced.current_text == "旧第二段"
    assert replaced.draft_text == "新第二段"


def test_inserted_and_deleted_paragraphs() -> None:
    current = "第一段\n\n第三段"
    draft = "第一段\n\n新段\n\n第三段\n\n末尾段"
    blocks = diff_paragraphs(current, draft)
    kinds = [block.kind for block in blocks]
    assert "inserted" in kinds
    assert "deleted" not in kinds
    inserted = [block for block in blocks if block.kind == "inserted"]
    assert {block.draft_text for block in inserted} == {"新段", "末尾段"}

    blocks = diff_paragraphs(draft, current)
    kinds = [block.kind for block in blocks]
    assert "deleted" in kinds
    deleted = [block for block in blocks if block.kind == "deleted"]
    assert {block.current_text for block in deleted} == {"新段", "末尾段"}


def test_apply_replaced_block() -> None:
    current = "第一段\n\n旧第二段\n\n第三段"
    draft = "第一段\n\n新第二段\n\n第三段"
    blocks = diff_paragraphs(current, draft)
    replaced = next(block for block in blocks if block.kind == "replaced")

    result = apply_diff_blocks(current, blocks, {replaced.block_id})

    assert result == "第一段\n\n新第二段\n\n第三段"


def test_apply_inserted_block() -> None:
    current = "第一段\n\n第三段"
    draft = "第一段\n\n新段\n\n第三段"
    blocks = diff_paragraphs(current, draft)
    inserted = next(block for block in blocks if block.kind == "inserted")

    result = apply_diff_blocks(current, blocks, {inserted.block_id})

    assert result == "第一段\n\n新段\n\n第三段"


def test_apply_deleted_block() -> None:
    current = "第一段\n\n要删的段\n\n第三段"
    draft = "第一段\n\n第三段"
    blocks = diff_paragraphs(current, draft)
    deleted = next(block for block in blocks if block.kind == "deleted")

    result = apply_diff_blocks(current, blocks, {deleted.block_id})

    assert result == "第一段\n\n第三段"


def test_apply_ignored_blocks_keeps_original_text() -> None:
    current = "第一段\n\n旧第二段\n\n第三段"
    draft = "第一段\n\n新第二段\n\n插入段\n\n第三段"
    blocks = diff_paragraphs(current, draft)

    result = apply_diff_blocks(current, blocks, set())

    assert result == current


def test_apply_multiple_blocks_any_order() -> None:
    current = "A段\n\nB段\n\nC段"
    draft = "A段\n\nB新段\n\nX段\n\nC段"
    blocks = diff_paragraphs(current, draft)
    changed = [block.block_id for block in blocks if block.kind != "unchanged"]

    result = apply_diff_blocks(current, blocks, set(changed))

    assert result == draft


def test_empty_current_accepts_full_draft() -> None:
    blocks = diff_paragraphs("", "第一段\n\n第二段")
    changed = [block.block_id for block in blocks if block.kind != "unchanged"]

    result = apply_diff_blocks("", blocks, set(changed))

    assert result == "第一段\n\n第二段"

