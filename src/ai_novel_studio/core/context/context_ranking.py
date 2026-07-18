from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_novel_studio.core.context.context_builder import ContextBlock

MAX_CONTEXT_TASK_TYPE_LENGTH = 100
MAX_CONTEXT_QUERY_LENGTH = 20_000
MAX_CONTEXT_RANKING_TEXT_LENGTH = 50_000
MAX_RECORDED_MATCH_TERMS = 8

_ASCII_TERM = re.compile(r"[a-z0-9_]{2,}")
_CJK_SEQUENCE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


@dataclass(frozen=True, slots=True)
class ContextTask:
    task_type: str
    query_text: str

    def __post_init__(self) -> None:
        task_type = self.task_type.strip()
        query_text = self.query_text.strip()
        if not task_type:
            raise ValueError("context task type cannot be empty")
        if len(task_type) > MAX_CONTEXT_TASK_TYPE_LENGTH:
            raise ValueError(
                f"context task type cannot exceed {MAX_CONTEXT_TASK_TYPE_LENGTH} characters"
            )
        if not query_text:
            raise ValueError("context task query cannot be empty")
        object.__setattr__(self, "task_type", task_type)
        object.__setattr__(
            self,
            "query_text",
            query_text[:MAX_CONTEXT_QUERY_LENGTH],
        )


@dataclass(frozen=True, slots=True)
class RankedContextBlock:
    block: ContextBlock
    matched_terms: tuple[str, ...]
    task_applied: bool

    @property
    def ranking_note(self) -> str | None:
        if not self.task_applied:
            return None
        if not self.matched_terms:
            return "TASK_RELEVANCE:NO_MATCH"
        recorded = ",".join(self.matched_terms[:MAX_RECORDED_MATCH_TERMS])
        return f"TASK_RELEVANCE:{recorded}"

    @property
    def rationale(self) -> str:
        note = self.ranking_note
        if note is None:
            return self.block.rationale
        return f"{self.block.rationale}；{note}"


class ContextRanker:
    """Deterministic lexical reranker used before optional blocks compete for budget."""

    def rank(
        self,
        blocks: list[ContextBlock],
        task: ContextTask | None,
    ) -> tuple[RankedContextBlock, ...]:
        if task is None:
            return tuple(RankedContextBlock(block, (), False) for block in blocks)
        query_terms = _terms(task.query_text)
        ranked = tuple(
            RankedContextBlock(
                block,
                tuple(sorted(query_terms & _terms(block.content))),
                True,
            )
            for block in blocks
        )
        return tuple(
            sorted(
                ranked,
                key=lambda item: (
                    -len(item.matched_terms),
                    item.block.priority,
                    item.block.id,
                ),
            )
        )


def _terms(text: str) -> frozenset[str]:
    normalized = text[:MAX_CONTEXT_RANKING_TEXT_LENGTH].casefold()
    terms = set(_ASCII_TERM.findall(normalized))
    for sequence in _CJK_SEQUENCE.findall(normalized):
        terms.update(
            sequence[index : index + 2] for index in range(len(sequence) - 1)
        )
    return frozenset(terms)
