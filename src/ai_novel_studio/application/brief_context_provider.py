from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ai_novel_studio.application.reader_knowledge_summary_service import (
    ReaderKnowledgeSummaryService,
)
from ai_novel_studio.core.brief.source_fingerprint import BriefSourceSnapshot
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.core.context.style_retriever import StyleRetriever
from ai_novel_studio.core.memory.canon_ledger import CanonLedger
from ai_novel_studio.core.memory.character_timeline import CharacterTimeline
from ai_novel_studio.core.memory.narrative_clue_ledger import NarrativeClueLedger
from ai_novel_studio.domain.generation import ChapterRequirement, CreationMode
from ai_novel_studio.domain.memory import (
    CanonEntry,
    CharacterStateEvent,
    KnowledgeStateEvent,
)
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    ChapterBriefRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
    StaleRequirementError,
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


@dataclass(frozen=True, slots=True)
class BriefCompilationRequest:
    chapter_id: str
    mode: CreationMode
    expected_requirement_revision: int
    target_length: int
    story_date: str
    pov_character_id: str | None
    participants: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.chapter_id.strip():
            raise ValueError("章节 ID 不能为空")
        if self.expected_requirement_revision < 0:
            raise ValueError("要求修订号不能为负数")
        if self.target_length <= 0:
            raise ValueError("目标长度必须大于零")


@dataclass(frozen=True, slots=True)
class BriefConflict:
    category: str
    subject_id: str
    source_ids: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class BriefCompilationInputs:
    requirement: ChapterRequirement
    sources: tuple[BriefSourceSnapshot, ...]
    character_states: tuple[str, ...]
    knowledge: tuple[str, ...]
    clue_actions: tuple[str, ...]
    style_rules: tuple[str, ...]
    history_evidence: tuple[str, ...]
    conflicts: tuple[BriefConflict, ...]
    warnings: tuple[str, ...]


def _hash_parts(*values: object) -> str:
    text = "\x1f".join(str(value) for value in values)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BriefContextProvider:
    def __init__(
        self,
        project: ProjectRepository,
        requirements: ChapterRequirementRepository,
        characters: CharacterMemoryRepository,
        narrative: NarrativeMemoryRepository,
        styles: StyleRepository,
        search: SearchRepository,
        briefs: ChapterBriefRepository,
    ) -> None:
        self.project = project
        self.requirements = requirements
        self.characters = characters
        self.narrative = narrative
        self.styles = styles
        self.search = search
        self.briefs = briefs
        self.reader_summary = ReaderKnowledgeSummaryService(project)

    def collect(self, request: BriefCompilationRequest) -> BriefCompilationInputs:
        requirement = self.requirements.get(request.chapter_id)
        if requirement.revision != request.expected_requirement_revision:
            raise StaleRequirementError(
                f"当前章要求修订已变化，当前为 {requirement.revision}，"
                f"提交为 {request.expected_requirement_revision}"
            )
        if not requirement.content.strip():
            raise ValueError("当前章要求不能为空")
        sources: list[BriefSourceSnapshot] = [
            BriefSourceSnapshot(
                "CHAPTER_REQUIREMENT",
                requirement.id,
                requirement.revision,
                requirement.content_hash,
                True,
            )
        ]
        canon_texts: list[str] = []
        conflicts: list[BriefConflict] = []
        canon_resolution = CanonLedger(self.narrative).resolve(
            requirement.content.strip(), request.chapter_id
        )
        if canon_resolution.entry is not None:
            canon_entry = canon_resolution.entry
            canon_texts.append(f"正典/{canon_entry.title}：{canon_entry.detail}")
            sources.append(self._canon_source(canon_entry))
        if canon_resolution.conflicts:
            sources.extend(
                self._canon_source(conflicting_entry)
                for conflicting_entry in canon_resolution.conflicts
            )
            conflicts.append(
                BriefConflict(
                    "CANON",
                    requirement.content.strip(),
                    tuple(entry.id for entry in canon_resolution.conflicts),
                    f"正典 {requirement.content.strip()} 存在同权冲突",
                )
            )
        character_texts: list[str] = []
        knowledge_texts: list[str] = []
        warnings: list[str] = []
        for snapshot in CharacterTimeline(self.characters).snapshot(
            request.participants, request.chapter_id
        ):
            if snapshot.state is None and not snapshot.conflicting_states:
                warnings.append(
                    f"MISSING_REQUIRED:人物 {snapshot.character.canonical_name} 缺少当前状态"
                )
            if snapshot.state is not None:
                state = snapshot.state
                character_texts.append(
                    f"{snapshot.character.canonical_name}：动机={state.motivation}；"
                    f"心理={state.psychology}；目标={state.current_goal}；"
                    f"关系={state.relationships}；最近活动={state.recent_activity}"
                )
                sources.append(self._state_source(state))
            if snapshot.conflicting_states:
                sources.extend(self._state_source(state) for state in snapshot.conflicting_states)
                conflicts.append(
                    BriefConflict(
                        "CHARACTER_STATE",
                        snapshot.character.id,
                        tuple(state.id for state in snapshot.conflicting_states),
                        f"人物 {snapshot.character.canonical_name} 在同一节点存在多个已审查状态",
                    )
                )
        reader_summary = self.reader_summary.summary_before(request.chapter_id)
        if reader_summary is not None:
            knowledge_texts.append(reader_summary.content)
            sources.extend(
                self._knowledge_source(entry.event, entry.item.title, entry.item.detail)
                for entry in reader_summary.entries
            )

        clue_texts: list[str] = []
        for timeline in NarrativeClueLedger(self.narrative).active_before(request.chapter_id):
            latest = timeline.events[-1]
            clue_texts.append(
                f"{timeline.clue.clue_type.value}/{latest.action.value}："
                f"{timeline.clue.title}（{timeline.clue.detail}）"
            )
            sources.append(
                BriefSourceSnapshot(
                    "NARRATIVE_CLUE",
                    timeline.clue.id,
                    0,
                    _hash_parts(
                        timeline.clue.clue_type.value,
                        timeline.clue.title,
                        timeline.clue.detail,
                        *(
                            (event.id, event.action.value, event.detail)
                            for event in timeline.events
                        ),
                    ),
                    False,
                )
            )

        compiled_style = StyleRetriever(self.styles).for_task(
            self.project.project.id,
            None,
            request.participants,
            request.chapter_id,
        )
        style_texts: list[str] = []
        for rule in compiled_style.rules:
            style_texts.append(f"{rule.rule_type}：{rule.rule_text}")
            sources.append(
                BriefSourceSnapshot(
                    "STYLE_RULE",
                    rule.id,
                    0,
                    _hash_parts(
                        rule.scope_type.value,
                        rule.scope_id,
                        rule.rule_type,
                        rule.rule_text,
                    ),
                    False,
                )
            )
        for sample in compiled_style.samples:
            style_texts.append(f"样章/{sample.title}：{sample.content}")
            sources.append(
                BriefSourceSnapshot(
                    "STYLE_SAMPLE", sample.id, 0, sample.content_hash, False
                )
            )

        history_texts: list[str] = []
        for hit in HistoryRetriever(self.search).search(
            requirement.content.strip(),
            request.chapter_id,
            participants=request.participants,
            limit=10,
        ):
            history_texts.append(f"{hit.document_type}/{hit.title}：{hit.excerpt}")
            sources.append(
                BriefSourceSnapshot(
                    f"HISTORY_{hit.document_type}",
                    hit.source_id,
                    hit.source_revision,
                    hit.source_hash,
                    False,
                )
            )

        return BriefCompilationInputs(
            requirement,
            tuple(sources),
            tuple(character_texts),
            tuple(knowledge_texts),
            tuple(clue_texts),
            tuple(style_texts),
            (*canon_texts, *history_texts),
            tuple(conflicts),
            tuple(warnings),
        )

    def current_sources(self, brief_id: str) -> tuple[BriefSourceSnapshot, ...]:
        brief = self.briefs.get(brief_id)
        requirement = self.requirements.get(brief.chapter_id)
        return self.collect(
            BriefCompilationRequest(
                brief.chapter_id,
                brief.mode,
                requirement.revision,
                brief.target_length,
                brief.story_date,
                brief.pov_character_id,
                brief.participants,
            )
        ).sources

    @staticmethod
    def _state_source(event: CharacterStateEvent) -> BriefSourceSnapshot:
        return BriefSourceSnapshot(
            "CHARACTER_STATE",
            event.id,
            0,
            _hash_parts(
                event.motivation,
                event.psychology,
                event.current_goal,
                event.relationships,
                event.recent_activity,
            ),
            True,
        )

    @staticmethod
    def _canon_source(entry: CanonEntry) -> BriefSourceSnapshot:
        return BriefSourceSnapshot(
            "CANON",
            entry.id,
            0,
            _hash_parts(
                entry.title,
                entry.detail,
                entry.source_chapter_id,
                entry.source_paragraph_id,
                entry.confidence,
                entry.authority.value,
                entry.status.value,
                entry.review_status.value,
            ),
            True,
        )

    @staticmethod
    def _knowledge_source(
        event: KnowledgeStateEvent, title: str, detail: str
    ) -> BriefSourceSnapshot:
        return BriefSourceSnapshot(
            "KNOWLEDGE_EVENT",
            event.id,
            0,
            _hash_parts(
                title,
                detail,
                event.subject_type.value,
                event.subject_id,
                event.state.value,
                event.evidence,
            ),
            True,
        )
