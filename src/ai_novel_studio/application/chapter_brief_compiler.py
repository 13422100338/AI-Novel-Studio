from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.brief_context_provider import (
    BriefCompilationRequest,
    BriefConflict,
    BriefContextProvider,
)
from ai_novel_studio.core.brief.source_fingerprint import BriefSourceSnapshot
from ai_novel_studio.domain.generation import ChapterBrief
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    BriefDraftData,
    ChapterBriefRepository,
)


@dataclass(frozen=True, slots=True)
class CompiledBrief:
    brief: ChapterBrief
    sources: tuple[BriefSourceSnapshot, ...]
    conflicts: tuple[BriefConflict, ...]


class ChapterBriefCompiler:
    def __init__(
        self,
        context_provider: BriefContextProvider,
        repository: ChapterBriefRepository,
    ) -> None:
        self.context_provider = context_provider
        self.repository = repository

    def compile(self, request: BriefCompilationRequest) -> CompiledBrief:
        inputs = self.context_provider.collect(request)
        warnings = (*inputs.warnings, *(f"CONFLICT:{item.message}" for item in inputs.conflicts))
        data = BriefDraftData(
            chapter_id=request.chapter_id,
            mode=request.mode,
            dramatic_purpose=inputs.requirement.content,
            target_length=request.target_length,
            story_date=request.story_date,
            pov_character_id=request.pov_character_id,
            hard_events=(inputs.requirement.content,),
            soft_goals=inputs.character_states,
            prohibited_changes=(),
            creative_freedom=(),
            participants=request.participants,
            knowledge=inputs.knowledge,
            clue_actions=inputs.clue_actions,
            style_rules=(*inputs.style_rules, *inputs.history_evidence),
            warnings=warnings,
        )
        brief = self.repository.create_draft(data, inputs.sources)
        return CompiledBrief(brief, inputs.sources, inputs.conflicts)
