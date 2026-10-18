"""Deterministic paragraph-level diff for draft review.

Frontend Wave F7: the AI drawer offers three draft views (current body, AI
draft, and paragraph diff). Diffing happens on presentation DTOs only; the
result is a candidate layer, never a second source of truth. Paragraph
acceptance applies accepted blocks into the editor buffer (DIRTY), which is
persisted later through the existing save path (F3), not through a new backend
interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True, slots=True)
class ParagraphDiffBlock:
    """One aligned diff region between the base body and the AI draft."""

    block_id: int
    kind: str  # unchanged | replaced | inserted | deleted
    current_text: str
    draft_text: str
    a_start: int
    a_end: int
    b_start: int
    b_end: int


def split_paragraphs(text: str) -> tuple[str, ...]:
    """Split on double newlines; whitespace-only text yields no paragraphs."""
    if not text.strip():
        return ()
    return tuple(text.split("\n\n"))


def diff_paragraphs(current: str, draft: str) -> tuple[ParagraphDiffBlock, ...]:
    """Align current and draft paragraphs and describe each region."""
    current_paragraphs = split_paragraphs(current)
    draft_paragraphs = split_paragraphs(draft)
    matcher = SequenceMatcher(None, current_paragraphs, draft_paragraphs, autojunk=False)
    blocks: list[ParagraphDiffBlock] = []
    for index, (tag, a1, a2, b1, b2) in enumerate(matcher.get_opcodes()):
        if tag == "equal":
            kind = "unchanged"
        elif tag == "replace":
            kind = "replaced"
        elif tag == "insert":
            kind = "inserted"
        else:
            kind = "deleted"
        blocks.append(
            ParagraphDiffBlock(
                block_id=index,
                kind=kind,
                current_text="\n\n".join(current_paragraphs[a1:a2]),
                draft_text="\n\n".join(draft_paragraphs[b1:b2]),
                a_start=a1,
                a_end=a2,
                b_start=b1,
                b_end=b2,
            )
        )
    return tuple(blocks)


def apply_diff_blocks(
    current: str,
    blocks: tuple[ParagraphDiffBlock, ...],
    accepted_ids: set[int],
) -> str:
    """Reassemble the base body applying only the accepted diff blocks.

    Rejected blocks keep their original paragraphs, so ignoring a suggestion
    never loses text.
    """
    current_paragraphs = split_paragraphs(current)
    output: list[str] = []
    for block in blocks:
        accepted = block.block_id in accepted_ids
        if block.kind == "unchanged":
            output.extend(current_paragraphs[block.a_start : block.a_end])
        elif block.kind == "replaced":
            if accepted:
                output.extend(block.draft_text.split("\n\n"))
            else:
                output.extend(current_paragraphs[block.a_start : block.a_end])
        elif block.kind == "inserted":
            if accepted and block.draft_text:
                output.extend(block.draft_text.split("\n\n"))
        elif block.kind == "deleted":
            if not accepted:
                output.extend(current_paragraphs[block.a_start : block.a_end])
    return "\n\n".join(output)
