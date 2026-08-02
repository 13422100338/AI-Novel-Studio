from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from ai_novel_studio.application.deterministic_audit_service import (
    CharacterGoalConflictAuditSource,
    CharacterInjuryConflictAuditSource,
    CharacterLocationConflictAuditSource,
    DeterministicAuditRequest,
    DeterministicAuditService,
    ReaderViewAuditSource,
)
from ai_novel_studio.domain.audit import (
    AuditFinding,
    AuditRun,
    AuditRunStatus,
    AuditTargetKind,
)
from ai_novel_studio.domain.generation import AuditPolicy, CreationMode
from ai_novel_studio.domain.memory import ReviewStatus
from ai_novel_studio.domain.view import ViewType
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
)

DETERMINISTIC_AUDIT_PROMPT_VERSION = "deterministic-audit-v1"


@dataclass(frozen=True, slots=True)
class AuditWorkflowResult:
    run: AuditRun
    findings: tuple[AuditFinding, ...]


@dataclass(frozen=True, slots=True)
class _CharacterStateConflictProjection:
    character_id: str
    source_boundary_chapter_id: str
    values: tuple[str, ...]
    state_event_ids: tuple[str, ...]


class AuditWorkflowService:
    def __init__(
        self,
        chapters: ChapterRepository,
        requirements: ChapterRequirementRepository,
        audits: AuditRepository,
        deterministic: DeterministicAuditService | None = None,
        view_assertions: ViewAssertionRepository | None = None,
        character_memory: CharacterMemoryRepository | None = None,
    ) -> None:
        self.chapters = chapters
        self.requirements = requirements
        self.audits = audits
        self.deterministic = deterministic or DeterministicAuditService()
        self.view_assertions = view_assertions
        self.character_memory = character_memory

    def run_deterministic_for_formal_chapter(
        self,
        chapter_id: str,
        *,
        mode: CreationMode,
        audit_policy: AuditPolicy = AuditPolicy.MINIMAL,
        requirement_content: str | None = None,
    ) -> AuditWorkflowResult:
        chapter = self.chapters.get_chapter(chapter_id, include_deleted=False)
        text = self.chapters.read_content(chapter_id)
        return self._run_deterministic(
            chapter_id=chapter_id,
            target_kind=AuditTargetKind.FORMAL_CHAPTER,
            target_id=chapter_id,
            target_text=text,
            target_revision=chapter.revision,
            mode=mode,
            audit_policy=audit_policy,
            requirement_content=requirement_content,
        )

    def run_deterministic_for_draft(
        self,
        *,
        chapter_id: str,
        generation_run_id: str,
        draft_text: str,
        base_chapter_revision: int,
        mode: CreationMode,
        audit_policy: AuditPolicy = AuditPolicy.MINIMAL,
        requirement_content: str | None = None,
    ) -> AuditWorkflowResult:
        return self._run_deterministic(
            chapter_id=chapter_id,
            target_kind=AuditTargetKind.GENERATED_DRAFT,
            target_id=generation_run_id,
            target_text=draft_text,
            target_revision=base_chapter_revision,
            mode=mode,
            audit_policy=audit_policy,
            requirement_content=requirement_content,
        )

    def _run_deterministic(
        self,
        *,
        chapter_id: str,
        target_kind: AuditTargetKind,
        target_id: str,
        target_text: str,
        target_revision: int,
        mode: CreationMode,
        audit_policy: AuditPolicy,
        requirement_content: str | None,
    ) -> AuditWorkflowResult:
        target_hash = _hash(target_text)
        run = self.audits.create_run(
            chapter_id=chapter_id,
            target_kind=target_kind,
            target_id=target_id,
            target_revision=target_revision,
            target_hash=target_hash,
            mode=mode,
            audit_policy=audit_policy,
            status=AuditRunStatus.PREPARING,
            prompt_version=DETERMINISTIC_AUDIT_PROMPT_VERSION,
        )
        current_requirement = None
        if requirement_content is None:
            current_requirement = self.requirements.get_or_create(chapter_id)
            requirement_content = current_requirement.content
        else:
            try:
                current_requirement = self.requirements.get(chapter_id)
            except KeyError:
                pass
        requirement_source = (
            current_requirement
            if current_requirement is not None
            and requirement_content == current_requirement.content
            else None
        )
        chapter_sequence = len(self.chapters.list_before(chapter_id)) + 1
        candidates = self.deterministic.run(
            DeterministicAuditRequest(
                chapter_id=chapter_id,
                target_text=target_text,
                target_revision=target_revision,
                target_hash=target_hash,
                requirement_content=requirement_content,
                requirement_id=(
                    requirement_source.id if requirement_source is not None else None
                ),
                requirement_revision=(
                    requirement_source.revision
                    if requirement_source is not None
                    else None
                ),
                requirement_content_hash=(
                    requirement_source.content_hash
                    if requirement_source is not None
                    else None
                ),
                chapter_sequence=chapter_sequence,
                reader_view_sources=self._reader_view_sources(
                    chapter_sequence=chapter_sequence
                ),
                character_location_conflict_sources=(
                    self._character_location_conflict_sources(chapter_id)
                ),
                character_injury_conflict_sources=(
                    self._character_injury_conflict_sources(chapter_id)
                ),
                character_goal_conflict_sources=(
                    self._character_goal_conflict_sources(chapter_id)
                ),
            )
        )
        findings = tuple(
            self.audits.add_finding(
                run_id=run.id,
                category=candidate.category,
                severity=candidate.severity,
                source=candidate.source,
                location_json=candidate.location_json,
                evidence=candidate.evidence,
                explanation=candidate.explanation,
                related_source_json=candidate.related_source_json,
                confidence=candidate.confidence,
            )
            for candidate in candidates
        )
        completed = self.audits.update_run_status(run.id, AuditRunStatus.COMPLETED)
        return AuditWorkflowResult(completed, findings)

    def _reader_view_sources(
        self,
        *,
        chapter_sequence: int,
    ) -> tuple[ReaderViewAuditSource, ...]:
        if self.view_assertions is None:
            return ()
        trusted_statuses = {ReviewStatus.APPROVED, ReviewStatus.LOCKED}
        sources: list[ReaderViewAuditSource] = []
        for assertion in self.view_assertions.list_context_candidates(
            view_type=ViewType.READER_VIEW
        ):
            visible_from = assertion.narrative_visible_from_sequence
            if (
                assertion.review_status not in trusted_statuses
                or assertion.stale
                or assertion.source_changed
                or visible_from is None
                or visible_from <= chapter_sequence
                or not self._source_revision_is_current(
                    assertion.source_id,
                    assertion.source_revision,
                )
            ):
                continue
            sources.append(
                ReaderViewAuditSource(
                    assertion_id=assertion.id,
                    content=assertion.content,
                    visible_from_sequence=visible_from,
                )
            )
        return tuple(sources)

    def _character_location_conflict_sources(
        self,
        chapter_id: str,
    ) -> tuple[CharacterLocationConflictAuditSource, ...]:
        return tuple(
            CharacterLocationConflictAuditSource(
                character_id=projection.character_id,
                source_boundary_chapter_id=projection.source_boundary_chapter_id,
                locations=projection.values,
                state_event_ids=projection.state_event_ids,
            )
            for projection in self._character_state_conflict_projections(
                chapter_id,
                field="location",
            )
        )

    def _character_injury_conflict_sources(
        self,
        chapter_id: str,
    ) -> tuple[CharacterInjuryConflictAuditSource, ...]:
        return tuple(
            CharacterInjuryConflictAuditSource(
                character_id=projection.character_id,
                source_boundary_chapter_id=projection.source_boundary_chapter_id,
                injury_statuses=projection.values,
                state_event_ids=projection.state_event_ids,
            )
            for projection in self._character_state_conflict_projections(
                chapter_id,
                field="injury_status",
            )
        )

    def _character_goal_conflict_sources(
        self,
        chapter_id: str,
    ) -> tuple[CharacterGoalConflictAuditSource, ...]:
        return tuple(
            CharacterGoalConflictAuditSource(
                character_id=projection.character_id,
                source_boundary_chapter_id=projection.source_boundary_chapter_id,
                current_goals=projection.values,
                state_event_ids=projection.state_event_ids,
            )
            for projection in self._character_state_conflict_projections(
                chapter_id,
                field="current_goal",
            )
        )

    def _character_state_conflict_projections(
        self,
        chapter_id: str,
        *,
        field: Literal["location", "injury_status", "current_goal"],
    ) -> tuple[_CharacterStateConflictProjection, ...]:
        if self.character_memory is None:
            return ()
        characters = self.character_memory.list_characters()
        states_by_character = self.character_memory.state_candidates_before_many(
            tuple(character.id for character in characters),
            chapter_id,
            inclusive=False,
        )
        field_attributes: dict[
            Literal["location", "injury_status", "current_goal"],
            Literal["location", "injury_status", "current_goal"],
        ] = {
            "location": "location",
            "injury_status": "injury_status",
            "current_goal": "current_goal",
        }
        selected_attribute = field_attributes[field]
        projections: list[_CharacterStateConflictProjection] = []
        for character in characters:
            states = states_by_character.get(character.id, ())
            if len(states) < 2:
                continue
            state_values = tuple(
                (state, getattr(state, selected_attribute).strip())
                for state in states
            )
            conflict_values = tuple(
                dict.fromkeys(
                    value for _, value in state_values if value
                )
            )
            if len(conflict_values) < 2:
                continue
            projections.append(
                _CharacterStateConflictProjection(
                    character_id=character.id,
                    source_boundary_chapter_id=states[0].chapter_id,
                    values=conflict_values,
                    state_event_ids=tuple(
                        state.id for state, value in state_values if value
                    ),
                )
            )
        return tuple(projections)

    def _source_revision_is_current(
        self,
        source_id: str,
        source_revision: int,
    ) -> bool:
        try:
            source_chapter = self.chapters.get_chapter(
                source_id,
                include_deleted=True,
            )
        except (KeyError, ValueError):
            return True
        return (
            not source_chapter.is_deleted
            and source_chapter.revision == source_revision
        )


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
