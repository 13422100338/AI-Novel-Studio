from __future__ import annotations

import hashlib

from ai_novel_studio.application.plot_memory_context_service import (
    PlotMemoryContextService,
)
from ai_novel_studio.core.context.context_builder import ContextBlock
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.core.context.style_retriever import StyleRetriever
from ai_novel_studio.core.memory.narrative_clue_ledger import NarrativeClueLedger
from ai_novel_studio.domain.memory import Character, KnowledgeSubject
from ai_novel_studio.infrastructure.storage.chapter_context_pin_repository import (
    ChapterContextPinRepository,
)
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
        blocks: list[ContextBlock] = []
        blocks.extend(self._manual_pin_blocks(chapter_id))
        blocks.extend(self._character_blocks(chapter_id, participants))
        blocks.extend(self._clue_blocks(chapter_id))
        blocks.extend(self._style_blocks(chapter_id, participants))
        blocks.extend(self._history_blocks(chapter_id, requirement, participants))
        blocks.extend(self._summary_blocks(chapter_id))
        return tuple(blocks)

    def _manual_pin_blocks(self, chapter_id: str) -> tuple[ContextBlock, ...]:
        return tuple(
            ContextBlock(
                f"manual-pin-{pin.id}",
                pin.context_category,
                f"人工固定记忆：{pin.title}\n{pin.content}",
                5 + min(index, 2),
                False,
                f"MANUAL_PIN/{pin.source_type}",
                pin.source_id,
                pin.source_chapter_id,
                pin.source_revision,
                pin.source_hash,
                f"人工固定到当前章：{pin.title}",
            )
            for index, pin in enumerate(self.pins.list_for_chapter(chapter_id))
        )

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
        participants: tuple[Character, ...],
    ) -> tuple[ContextBlock, ...]:
        if not participants:
            return ()
        states = self.characters.state_candidates_before_many(
            tuple(character.id for character in participants),
            chapter_id,
        )
        blocks: list[ContextBlock] = []
        for index, character in enumerate(participants):
            candidates = states.get(character.id, ())
            if len(candidates) == 1:
                event = candidates[0]
                content = (
                    f"人物状态/{character.canonical_name}：动机={event.motivation}；"
                    f"心理={event.psychology}；目标={event.current_goal}；"
                    f"关系={event.relationships}；最近活动={event.recent_activity}"
                )
                blocks.append(
                    ContextBlock(
                        f"character-state-{event.id}",
                        "MEMORY",
                        content,
                        8 + index,
                        False,
                        "CHARACTER_STATE",
                        event.id,
                        event.chapter_id,
                        0,
                        _hash(content),
                        f"相关人物 {character.canonical_name} 在当前章之前的最新已审查状态",
                    )
                )
            for knowledge_index, entry in enumerate(
                self.characters.knowledge_before(
                    KnowledgeSubject.CHARACTER,
                    character.id,
                    chapter_id,
                )[:8]
            ):
                content = (
                    f"人物知识/{character.canonical_name}/{entry.event.state.value}："
                    f"{entry.item.title}（{entry.item.detail}）"
                )
                blocks.append(
                    ContextBlock(
                        f"character-knowledge-{entry.event.id}",
                        "MEMORY",
                        content,
                        16 + index + knowledge_index,
                        False,
                        "KNOWLEDGE_EVENT",
                        entry.event.id,
                        entry.event.chapter_id,
                        0,
                        _hash(content),
                        f"相关人物 {character.canonical_name} 在当前章之前的知识边界",
                    )
                )
        return tuple(blocks)

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
        selection = self.summaries.select(chapter_id, token_budget=12_000)
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
            for index, summary in enumerate(selection.summaries)
        )


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
