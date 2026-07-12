from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.core.context.token_budget import (
    ConservativeTokenEstimator,
    TokenEstimator,
)
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus, SummaryNode
from ai_novel_studio.infrastructure.llm import LLMMessage
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


@dataclass(frozen=True, slots=True)
class PlotMemorySelection:
    message: LLMMessage | None
    approved_count: int
    review_count: int
    estimated_tokens: int


class PlotMemoryContextService:
    """Select bounded pre-chapter summaries for ordinary plot discussion."""

    def __init__(
        self,
        project: ProjectRepository,
        estimator: TokenEstimator | None = None,
    ) -> None:
        self.project = project
        self.summaries = SummaryRepository(project)
        self.estimator = estimator or ConservativeTokenEstimator()

    def select(self, chapter_id: str, *, token_budget: int = 6_000) -> PlotMemorySelection:
        if token_budget <= 0:
            raise ValueError("剧情商讨前文预算必须大于 0")
        candidates = tuple(
            item
            for item in self.summaries.list_all()
            if item.status in {MemoryStatus.CURRENT, MemoryStatus.REVIEW}
            and item.source_chapter_ids
            and self.summaries.is_before(item, chapter_id)
        )
        selected_versions = self._select_scope_versions(candidates)
        ordered = sorted(selected_versions, key=self._order_key)
        chosen: list[tuple[SummaryNode, str]] = []
        used = 0
        for summary in reversed(ordered):
            rendered = self._render(summary)
            cost = self.estimator.estimate(rendered)
            if chosen and used + cost > token_budget:
                continue
            if not chosen and cost > token_budget:
                rendered = rendered[: max(200, token_budget * 3)]
                cost = self.estimator.estimate(rendered)
            chosen.append((summary, rendered))
            used += cost
        chosen.reverse()
        if not chosen:
            return PlotMemorySelection(None, 0, 0, 0)
        content = (
            "以下是当前章之前的小说前文记忆。标记为【已审查】的内容可作为可信剧情依据；"
            "标记为【待审查】的内容只是模型候选，可能遗漏或出错，不得当作正典。\n\n"
            + "\n\n".join(rendered for _item, rendered in chosen)
        )
        approved = sum(
            item.review_status in {ReviewStatus.APPROVED, ReviewStatus.LOCKED}
            for item, _rendered in chosen
        )
        return PlotMemorySelection(
            LLMMessage("system", content),
            approved,
            len(chosen) - approved,
            self.estimator.estimate(content),
        )

    @staticmethod
    def _select_scope_versions(
        summaries: tuple[SummaryNode, ...],
    ) -> tuple[SummaryNode, ...]:
        grouped: dict[tuple[str, str], list[SummaryNode]] = {}
        for summary in summaries:
            grouped.setdefault((summary.level.value, summary.scope_id), []).append(summary)
        selected: list[SummaryNode] = []
        for versions in grouped.values():
            trusted = [
                item
                for item in versions
                if item.review_status in {ReviewStatus.APPROVED, ReviewStatus.LOCKED}
            ]
            pool = trusted or [
                item for item in versions if item.review_status == ReviewStatus.REVIEW
            ]
            if pool:
                selected.append(max(pool, key=lambda item: (item.revision, item.created_at)))
        return tuple(selected)

    def _order_key(self, summary: SummaryNode) -> tuple[int, int, str]:
        placeholders = ",".join("?" for _ in summary.source_chapter_ids)
        with self.project.database.connect() as connection:
            row = connection.execute(
                f"SELECT v.sort_index, c.sort_index FROM chapters c "
                f"JOIN volumes v ON v.id = c.volume_id WHERE c.id IN ({placeholders}) "
                "ORDER BY v.sort_index DESC, c.sort_index DESC LIMIT 1",
                summary.source_chapter_ids,
            ).fetchone()
        return (int(row[0]), int(row[1]), summary.id) if row else (-1, -1, summary.id)

    @staticmethod
    def _render(summary: SummaryNode) -> str:
        label = (
            "已审查"
            if summary.review_status in {ReviewStatus.APPROVED, ReviewStatus.LOCKED}
            else "待审查"
        )
        return f"【{label}｜{summary.level.value}｜{summary.scope_id}】\n{summary.content}"
