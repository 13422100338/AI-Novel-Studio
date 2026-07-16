from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.canon_card_context_service import (
    CanonCardContextService,
)
from ai_novel_studio.application.character_card_context_service import (
    CharacterCardContextService,
)
from ai_novel_studio.application.project_guidance_service import ProjectGuidanceService
from ai_novel_studio.application.reader_knowledge_summary_service import (
    ReaderKnowledgeSummaryService,
)
from ai_novel_studio.core.context.token_budget import (
    ConservativeTokenEstimator,
    TokenEstimator,
)
from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus, SummaryNode
from ai_novel_studio.infrastructure.llm import LLMMessage
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
    ProjectGuidanceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


@dataclass(frozen=True, slots=True)
class PlotMemorySelection:
    message: LLMMessage | None
    approved_count: int
    review_count: int
    estimated_tokens: int
    summaries: tuple[SummaryNode, ...] = ()


class PlotMemoryContextService:
    """Build required shared plot context plus bounded pre-chapter summaries."""

    def __init__(
        self,
        project: ProjectRepository,
        estimator: TokenEstimator | None = None,
    ) -> None:
        self.project = project
        self.chapters = ChapterRepository(project)
        self.summaries = SummaryRepository(project)
        self.character_cards = CharacterCardContextService(project)
        self.canon_cards = CanonCardContextService(project)
        self.reader_summary = ReaderKnowledgeSummaryService(project)
        self.project_guidance = ProjectGuidanceService(
            ProjectGuidanceRepository(project)
        )
        self.estimator = estimator or ConservativeTokenEstimator()

    def select(self, chapter_id: str, *, token_budget: int = 6_000) -> PlotMemorySelection:
        if token_budget <= 0:
            raise ValueError("剧情商讨前文预算必须大于 0")
        recent_chapters = self._recent_chapters(chapter_id)
        required_sections = self._required_sections(recent_chapters)
        required_content = "\n\n".join(required_sections)
        optional_budget = max(
            0,
            token_budget - self.estimator.estimate(required_content),
        )
        card_sections: list[str] = []
        reader_summary = self.reader_summary.summary_before(chapter_id)
        if reader_summary is not None:
            cost = self.estimator.estimate(reader_summary.content)
            if cost <= optional_budget:
                card_sections.append(reader_summary.content)
                optional_budget -= cost
        for item in self.character_cards.items_before(chapter_id):
            cost = self.estimator.estimate(item.content)
            if cost > optional_budget:
                continue
            card_sections.append(item.content)
            optional_budget -= cost
        for card in self.canon_cards.cards_before(chapter_id):
            if not card.content:
                continue
            cost = self.estimator.estimate(card.content)
            if cost > optional_budget:
                continue
            card_sections.append(card.content)
            optional_budget -= cost
        chosen = self._choose_summaries(
            chapter_id,
            optional_budget,
            excluded_chapter_ids=frozenset(
                chapter.id for chapter in recent_chapters
            ),
        )
        if not chosen and not required_sections and not card_sections:
            return PlotMemorySelection(None, 0, 0, 0, ())
        sections = list(required_sections)
        sections.extend(card_sections)
        if chosen:
            sections.append(
                "以下是当前章之前的小说前文记忆。标记为【已审查】的内容可作为可信剧情依据；"
                "标记为【待审查】的内容只是模型候选，可能遗漏或出错，不得当作正典。\n\n"
                + "\n\n".join(rendered for _item, rendered in chosen)
            )
        content = "\n\n".join(sections)
        approved = sum(
            item.review_status in {ReviewStatus.APPROVED, ReviewStatus.LOCKED}
            for item, _rendered in chosen
        )
        return PlotMemorySelection(
            LLMMessage("system", content),
            approved,
            len(chosen) - approved,
            self.estimator.estimate(content),
            tuple(item for item, _rendered in chosen),
        )

    def select_summary_nodes(
        self, chapter_id: str, *, token_budget: int = 6_000
    ) -> tuple[SummaryNode, ...]:
        """Select summary nodes without spending budget on shared plot prefixes."""

        if token_budget <= 0:
            raise ValueError("前文摘要预算必须大于 0")
        recent_chapters = self._recent_chapters(chapter_id)
        return tuple(
            summary
            for summary, _rendered in self._choose_summaries(
                chapter_id,
                token_budget,
                excluded_chapter_ids=frozenset(
                    chapter.id for chapter in recent_chapters
                ),
            )
        )

    def _recent_chapters(self, chapter_id: str) -> tuple[Chapter, ...]:
        return tuple(self.chapters.list_before(chapter_id)[-3:])

    def _required_sections(
        self, recent_chapters: tuple[Chapter, ...]
    ) -> tuple[str, ...]:
        sections: list[str] = []
        guidance = self.project_guidance.load()
        if guidance.highest_system_prompt.strip():
            sections.append(
                f"【小说最高系统提示｜人工修订 {guidance.revision}】\n"
                f"{guidance.highest_system_prompt}"
            )
        for chapter in recent_chapters:
            content = self.chapters.read_content(chapter.id)
            if not content.strip():
                continue
            sections.append(
                f"【最近章节全文｜{chapter.title}｜修订 {chapter.revision}】\n{content}"
            )
        return tuple(sections)

    def _choose_summaries(
        self,
        chapter_id: str,
        token_budget: int,
        *,
        excluded_chapter_ids: frozenset[str] = frozenset(),
    ) -> tuple[tuple[SummaryNode, str], ...]:
        if token_budget <= 0:
            return ()
        candidates = tuple(
            item
            for item in self.summaries.list_all()
            if item.status in {MemoryStatus.CURRENT, MemoryStatus.REVIEW}
            and item.source_chapter_ids
            and self.summaries.is_before(item, chapter_id)
            and excluded_chapter_ids.isdisjoint(item.source_chapter_ids)
        )
        selected_versions = self._select_scope_versions(candidates)
        ordered = sorted(selected_versions, key=self._order_key)
        chosen: list[tuple[SummaryNode, str]] = []
        used = 0
        for summary in reversed(ordered):
            rendered = self.render(summary)
            cost = self.estimator.estimate(rendered)
            if chosen and used + cost > token_budget:
                continue
            if not chosen and cost > token_budget:
                rendered = rendered[: max(1, token_budget * 3)]
                cost = self.estimator.estimate(rendered)
            chosen.append((summary, rendered))
            used += cost
        chosen.reverse()
        return tuple(chosen)

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
    def render(summary: SummaryNode) -> str:
        label = (
            "已审查"
            if summary.review_status in {ReviewStatus.APPROVED, ReviewStatus.LOCKED}
            else "待审查"
        )
        return f"【{label}｜{summary.level.value}｜{summary.scope_id}】\n{summary.content}"
