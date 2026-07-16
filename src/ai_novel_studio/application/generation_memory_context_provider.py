from __future__ import annotations

import hashlib

from ai_novel_studio.application.canon_card_context_service import (
    CanonCardContextService,
)
from ai_novel_studio.application.character_card_context_service import (
    CharacterCardContextService,
)
from ai_novel_studio.application.plot_memory_context_service import (
    PlotMemoryContextService,
)
from ai_novel_studio.application.reader_knowledge_summary_service import (
    ReaderKnowledgeSummaryService,
)
from ai_novel_studio.core.context.context_builder import ContextBlock
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.core.context.style_retriever import StyleRetriever
from ai_novel_studio.core.memory.narrative_clue_ledger import NarrativeClueLedger
from ai_novel_studio.domain.context_pin import ChapterContextPin
from ai_novel_studio.domain.memory import Character, SummaryNode
from ai_novel_studio.infrastructure.storage.chapter_context_pin_repository import (
    ChapterContextPinRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository


class GenerationMemoryContextProvider:
    """Builds bounded, pre-chapter memory blocks for prose generation."""

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project
        self.characters = CharacterMemoryRepository(project)
        self.character_cards = CharacterCardContextService(project)
        self.canon_cards = CanonCardContextService(project)
        self.reader_summary = ReaderKnowledgeSummaryService(project)
        self.chapters = ChapterRepository(project)
        self.pins = ChapterContextPinRepository(project)
        self.narrative = NarrativeMemoryRepository(project)
        self.styles = StyleRepository(project)
        self.history = HistoryRetriever(SearchRepository(project))
        self.summaries = PlotMemoryContextService(project)

    def blocks(
        self,
        chapter_id: str,
        requirement: str,
        recent_chapter_texts: tuple[str, ...],
        participant_ids: tuple[str, ...] = (),
    ) -> tuple[ContextBlock, ...]:
        reference_text = "\n".join((requirement, *recent_chapter_texts[:2]))
        participants = self._relevant_characters(reference_text, participant_ids)
        manual = self._manual_pin_blocks(chapter_id)
        automatic: list[ContextBlock] = []
        automatic.extend(self._character_blocks(chapter_id))
        automatic.extend(self._reader_summary_blocks(chapter_id))
        automatic.extend(self._canon_blocks(chapter_id))
        automatic.extend(self._clue_blocks(chapter_id))
        automatic.extend(self._style_blocks(chapter_id, participants))
        automatic.extend(self._history_blocks(chapter_id, requirement, participants))
        automatic.extend(self._summary_blocks(chapter_id))
        return (*manual, *self._without_manual_duplicates(manual, tuple(automatic)))

    def _manual_pin_blocks(self, chapter_id: str) -> tuple[ContextBlock, ...]:
        chapter_positions = self._chapter_positions()
        summaries = {
            summary.id: summary for summary in self.summaries.summaries.list_all()
        }
        pins = sorted(
            self.pins.list_for_chapter(chapter_id),
            key=lambda pin: self._manual_pin_order_key(
                pin, chapter_positions, summaries
            ),
        )
        return tuple(
            ContextBlock(
                f"manual-pin-{pin.id}",
                pin.context_category,
                f"人工固定记忆：{pin.title}\n{pin.content}",
                5 + index,
                True,
                f"MANUAL_PIN/{pin.source_type}",
                pin.source_id,
                pin.source_chapter_id,
                pin.source_revision,
                pin.source_hash,
                f"作者要求本次生成必须采用：{pin.title}",
            )
            for index, pin in enumerate(pins)
        )

    def _manual_pin_order_key(
        self,
        pin: ChapterContextPin,
        chapter_positions: dict[str, tuple[int, int]],
        summaries: dict[str, SummaryNode],
    ) -> tuple[int, int, int, float, str]:
        if pin.source_type == "SUMMARY":
            summary = summaries.get(pin.source_id)
            if summary is not None:
                positions = tuple(
                    chapter_positions[chapter_id]
                    for chapter_id in summary.source_chapter_ids
                    if chapter_id in chapter_positions
                )
                if positions:
                    volume_order, chapter_order = max(positions)
                    return (
                        0,
                        volume_order,
                        chapter_order,
                        pin.created_at.timestamp(),
                        pin.id,
                    )
        return (1, 0, 0, pin.created_at.timestamp(), pin.id)

    def _chapter_positions(self) -> dict[str, tuple[int, int]]:
        volume_order = {
            volume.id: volume.sort_index for volume in self.project.list_volumes()
        }
        return {
            chapter.id: (volume_order.get(chapter.volume_id, 0), chapter.sort_index)
            for chapter in self.chapters.list_chapters()
        }

    @staticmethod
    def _without_manual_duplicates(
        manual: tuple[ContextBlock, ...], automatic: tuple[ContextBlock, ...]
    ) -> tuple[ContextBlock, ...]:
        pinned_source_ids = {block.source_id for block in manual}
        pinned_hashes = {block.source_hash for block in manual if block.source_hash}
        seen_contents: set[str] = set()
        selected: list[ContextBlock] = []
        for block in automatic:
            if block.source_id in pinned_source_ids:
                continue
            if block.source_hash and block.source_hash in pinned_hashes:
                continue
            normalized = " ".join(block.content.split())
            if normalized in seen_contents:
                continue
            seen_contents.add(normalized)
            selected.append(block)
        return tuple(selected)

    def _relevant_characters(
        self,
        text: str,
        participant_ids: tuple[str, ...],
    ) -> tuple[Character, ...]:
        characters = self.characters.list_characters()
        by_id = {character.id: character for character in characters}
        explicit = [by_id[value] for value in participant_ids if value in by_id]
        explicit_ids = {character.id for character in explicit}
        matches: list[tuple[int, Character]] = []
        for character in characters:
            if character.id in explicit_ids:
                continue
            positions = [
                text.find(name)
                for name in (character.canonical_name, *character.aliases)
                if name and name in text
            ]
            if positions:
                matches.append((min(positions), character))
        inferred = [
            character for _position, character in sorted(matches, key=lambda x: x[0])
        ]
        return tuple((*explicit, *inferred)[:8])

    def _character_blocks(
        self,
        chapter_id: str,
    ) -> tuple[ContextBlock, ...]:
        blocks = [
            ContextBlock(
                f"character-card-{item.character_id}",
                "MEMORY",
                item.content,
                8 + index,
                False,
                "CHARACTER_STATE",
                item.character_id,
                item.source_chapter_id,
                0,
                item.content_hash,
                "当前章之前按人物聚合的已审查状态卡",
            )
            for index, item in enumerate(self.character_cards.items_before(chapter_id))
        ]
        return tuple(blocks)

    def _canon_blocks(self, chapter_id: str) -> tuple[ContextBlock, ...]:
        return tuple(
            ContextBlock(
                f"canon-card-{card.category.value.casefold()}",
                "MEMORY",
                card.content,
                14 + index,
                False,
                "CANON_CARD",
                card.category.value,
                None,
                0,
                card.content_hash,
                f"当前章之前已审查的聚合正典：{card.title}",
            )
            for index, card in enumerate(self.canon_cards.cards_before(chapter_id))
            if card.content
        )

    def _reader_summary_blocks(self, chapter_id: str) -> tuple[ContextBlock, ...]:
        summary = self.reader_summary.summary_before(chapter_id)
        if summary is None:
            return ()
        return (
            ContextBlock(
                "reader-knowledge-summary",
                "MEMORY",
                summary.content,
                13,
                False,
                "READER_SUMMARY",
                self.project.project.id,
                summary.source_chapter_id,
                0,
                summary.content_hash,
                "当前章之前已审查的读者知识大摘要",
            ),
        )

    def _clue_blocks(self, chapter_id: str) -> tuple[ContextBlock, ...]:
        timelines = sorted(
            NarrativeClueLedger(self.narrative).active_before(chapter_id),
            key=lambda timeline: (timeline.events[-1].created_at, timeline.clue.id),
            reverse=True,
        )[:12]
        blocks: list[ContextBlock] = []
        for index, timeline in enumerate(timelines):
            latest = timeline.events[-1]
            content = (
                f"活跃伏笔/{timeline.clue.clue_type.value}/{latest.action.value}："
                f"{timeline.clue.title}（{timeline.clue.detail}）"
            )
            blocks.append(
                ContextBlock(
                    f"active-clue-{timeline.clue.id}",
                    "MEMORY",
                    content,
                    16 + index,
                    False,
                    "NARRATIVE_CLUE",
                    timeline.clue.id,
                    latest.chapter_id,
                    0,
                    _hash(content),
                    f"当前章之前仍未解决的伏笔：{timeline.clue.title}",
                )
            )
        return tuple(blocks)

    def _style_blocks(
        self,
        chapter_id: str,
        participants: tuple[Character, ...],
    ) -> tuple[ContextBlock, ...]:
        compiled = StyleRetriever(self.styles).for_task(
            self.project.project.id,
            None,
            tuple(character.id for character in participants),
            chapter_id,
        )
        blocks: list[ContextBlock] = []
        for index, rule in enumerate(compiled.rules):
            content = f"文风规则/{rule.rule_type}：{rule.rule_text}"
            blocks.append(
                ContextBlock(
                    f"style-rule-{rule.id}",
                    "MEMORY",
                    content,
                    20 + index,
                    False,
                    "STYLE_RULE",
                    rule.id,
                    None,
                    0,
                    _hash(content),
                    f"适用于当前写作任务的文风规则：{rule.rule_type}",
                )
            )
        for index, sample in enumerate(compiled.samples):
            content = f"人工样章/{sample.title}：\n{sample.content}"
            blocks.append(
                ContextBlock(
                    f"style-sample-{sample.id}",
                    "MEMORY",
                    content,
                    24 + index,
                    False,
                    "STYLE_SAMPLE",
                    sample.id,
                    None,
                    0,
                    sample.content_hash,
                    f"适用于当前写作任务的人工文风样章：{sample.title}",
                )
            )
        return tuple(blocks)

    def _history_blocks(
        self,
        chapter_id: str,
        requirement: str,
        participants: tuple[Character, ...],
    ) -> tuple[ContextBlock, ...]:
        hits = self.history.search(
            requirement,
            chapter_id,
            participants=tuple(character.id for character in participants),
            limit=12,
        )
        return tuple(
            ContextBlock(
                f"history-{hit.document_id}",
                "HISTORY",
                f"检索证据/{hit.document_type}/{hit.title}：{hit.excerpt}",
                26 + index,
                False,
                f"HISTORY_{hit.document_type}",
                hit.source_id,
                hit.chapter_id,
                hit.source_revision,
                hit.source_hash,
                f"与当前章要求相关的记忆检索证据：{hit.title}",
            )
            for index, hit in enumerate(hits)
        )

    def _summary_blocks(self, chapter_id: str) -> tuple[ContextBlock, ...]:
        summaries = self.summaries.select_summary_nodes(
            chapter_id,
            token_budget=12_000,
        )
        return tuple(
            ContextBlock(
                f"summary-{summary.id}",
                "HISTORY",
                self.summaries.render(summary),
                40 + index,
                False,
                "SUMMARY",
                summary.id,
                summary.source_chapter_ids[-1] if summary.source_chapter_ids else None,
                summary.revision,
                summary.content_hash,
                f"分层压缩前文：{summary.level.value} / {summary.scope_id}",
            )
            for index, summary in enumerate(summaries)
        )


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
