from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.compile_context_service import (
    CompileContextRequest,
    CompileContextService,
    CompiledContext,
    EvidenceNeed,
)
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_state import HarnessRun, RunEventType
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class CompileChapterMissingError(ValueError):
    """The run has no active chapter to compile against."""


@dataclass(frozen=True, slots=True)
class CompileStepAdapter:
    """B1 adapter wiring the backend CompileContextService into the
    HarnessRunEngine ContextCompileStep port (design v0.3 §21-§24,
    contract §6, ticket HARNESS-V1-B1).

    The adapter is a deterministic transformer plus run-event emission: it
    maps a HarnessRun onto a CompileContextRequest, appends the
    CONTEXT_COMPILATION_STARTED / CONTEXT_COMPILED events through the
    harness event store, and returns the backend CompiledContext. It never
    assembles context blocks itself and never keeps a second projection;
    the ContextManifest is the audit record.
    """

    service: CompileContextService
    store: HarnessEventStore
    budget: TokenBudget
    requirement: str = ""
    recent_chapter_texts: tuple[str, ...] = ()
    participant_ids: tuple[str, ...] = ()
    pov_character_id: str | None = None
    evidence_requests: tuple[EvidenceNeed, ...] = ()

    @classmethod
    def for_project(
        cls,
        project: ProjectRepository,
        *,
        budget: TokenBudget,
        requirement: str = "",
        recent_chapter_texts: tuple[str, ...] = (),
        participant_ids: tuple[str, ...] = (),
        pov_character_id: str | None = None,
        evidence_requests: tuple[EvidenceNeed, ...] = (),
    ) -> CompileStepAdapter:
        store = HarnessEventStore(HarnessEventRepository(project))
        return cls(
            CompileContextService.for_project(project),
            store,
            budget,
            requirement=requirement,
            recent_chapter_texts=recent_chapter_texts,
            participant_ids=participant_ids,
            pov_character_id=pov_character_id,
            evidence_requests=evidence_requests,
        )

    def __call__(self, run: HarnessRun) -> CompiledContext:
        chapter_id = run.active_chapter_id
        if chapter_id is None:
            raise CompileChapterMissingError(
                f"run {run.id} has no active chapter to compile"
            )
        validate_id(chapter_id)
        self.store.append(
            run.id,
            RunEventType.CONTEXT_COMPILATION_STARTED,
            {"chapter_id": chapter_id},
        )
        compiled = self.service.build(
            CompileContextRequest(
                chapter_id=chapter_id,
                budget=self.budget,
                run_id=run.id,
                requirement=self.requirement,
                recent_chapter_texts=self.recent_chapter_texts,
                participant_ids=self.participant_ids,
                pov_character_id=self.pov_character_id,
                evidence_requests=self.evidence_requests,
            )
        )
        self.store.append(
            run.id,
            RunEventType.CONTEXT_COMPILED,
            {
                "chapter_id": chapter_id,
                "manifest_id": compiled.manifest.id,
                "estimated_input_tokens": compiled.projection.estimated_input_tokens,
                "evidence_hit_count": compiled.projection.evidence_hit_count,
                "included_categories": [
                    list(item) for item in compiled.projection.included_categories
                ],
            },
        )
        return compiled
