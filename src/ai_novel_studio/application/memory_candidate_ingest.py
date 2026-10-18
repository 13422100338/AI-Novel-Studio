from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ai_novel_studio.application.memory_analysis_service import (
    CharacterStateCandidate,
    MemoryCandidateBundle,
)
from ai_novel_studio.domain.memory import (
    Authority,
    Character,
    KnowledgeSubject,
    ReviewStatus,
    SourceType,
    SummaryLevel,
    SummaryNode,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


@dataclass(frozen=True, slots=True)
class MemoryCandidateIngestReport:
    summary_created: bool
    summary_upgraded: bool
    created_character_states: int
    created_canon: int
    created_clues: int
    created_knowledge: int
    created_style_rules: int


class MemoryCandidateIngestService:
    """Deterministic write half of memory extraction (design §4, DCP step 5.4).

    The model only proposes; this service validates the bundle against the
    current manuscript source and executes the candidate writes. The Harness
    owns the model call and feeds the validated bundle through ingest().
    """

    def __init__(self, *, model_profile_id: str = "memory-extraction") -> None:
        self.model_profile_id = model_profile_id

    def ingest(
        self,
        project: ProjectRepository,
        *,
        chapter_id: str,
        bundle: MemoryCandidateBundle,
        fallback_summary: SummaryNode | None = None,
    ) -> MemoryCandidateIngestReport:
        if not isinstance(bundle, MemoryCandidateBundle):
            raise TypeError("memory candidate bundle is invalid")
        chapters = ChapterRepository(project)
        chapter = chapters.get_chapter(chapter_id, include_deleted=False)
        content = chapters.read_content_exact(chapter.id)
        if (
            bundle.source_chapter_id != chapter.id
            or bundle.source_revision != chapter.revision
            or bundle.source_hash
            != hashlib.sha256(content.encode("utf-8")).hexdigest()
        ):
            raise ValueError("memory candidates do not match the current manuscript source")
        summaries = SummaryRepository(project)
        characters = CharacterMemoryRepository(project)

        summary_created = False
        summary_upgraded = False
        if fallback_summary is not None:
            summaries.replace_model_candidate(
                fallback_summary.id,
                bundle.summary.content,
                model_profile_id=self.model_profile_id,
                expected_revision=fallback_summary.revision,
            )
            summary_upgraded = True
        else:
            summaries.add_candidate(
                SummaryLevel.CHAPTER,
                chapter.id,
                bundle.summary.content,
                (chapter.id,),
                model_profile_id=self.model_profile_id,
            )
            summary_created = True

        created_character_states = self._save_character_states(
            characters, chapter.id, bundle
        )
        created_canon, created_clues, created_knowledge, created_style_rules = (
            self._save_ledger_candidates(project, chapter.id, bundle)
        )
        return MemoryCandidateIngestReport(
            summary_created=summary_created,
            summary_upgraded=summary_upgraded,
            created_character_states=created_character_states,
            created_canon=created_canon,
            created_clues=created_clues,
            created_knowledge=created_knowledge,
            created_style_rules=created_style_rules,
        )

    @staticmethod
    def _save_character_states(
        repository: CharacterMemoryRepository,
        chapter_id: str,
        bundle: MemoryCandidateBundle,
    ) -> int:
        created = 0
        for candidate in bundle.character_states:
            character = _find_or_create_character(repository, candidate.character_name)
            if _character_state_exists(repository, character.id, chapter_id, candidate):
                continue
            repository.append_state(
                character.id,
                chapter_id,
                motivation=candidate.motivation,
                psychology=candidate.psychology,
                current_goal=candidate.current_goal,
                relationships=candidate.relationships,
                recent_activity=candidate.recent_activity,
                location=candidate.location,
                injury_status=candidate.injury_status,
                confidence=0.8,
                source_type=SourceType.MODEL,
                review_status=ReviewStatus.REVIEW,
            )
            created += 1
        return created

    @staticmethod
    def _save_ledger_candidates(
        project: ProjectRepository,
        chapter_id: str,
        bundle: MemoryCandidateBundle,
    ) -> tuple[int, int, int, int]:
        narrative = NarrativeMemoryRepository(project)
        characters = CharacterMemoryRepository(project)
        canon_count = 0
        clue_count = 0
        knowledge_count = 0
        style_count = 0

        with project.database.connect() as connection:
            for canon_candidate in bundle.canon:
                exists = connection.execute(
                    "SELECT 1 FROM canon_entries WHERE source_chapter_id = ? "
                    "AND title = ? AND detail = ? AND review_status = 'REVIEW'",
                    (chapter_id, canon_candidate.title, canon_candidate.detail),
                ).fetchone()
                if exists is None:
                    narrative.add_canon(
                        canon_candidate.title,
                        canon_candidate.detail,
                        chapter_id,
                        confidence=0.8,
                        authority=Authority.MODEL_EXTRACTED,
                        review_status=ReviewStatus.REVIEW,
                    )
                    canon_count += 1

            for clue_candidate in bundle.clues:
                clue_row = connection.execute(
                    "SELECT id FROM narrative_clues WHERE title = ? "
                    "AND authority = 'MODEL_EXTRACTED' AND review_status = 'REVIEW' "
                    "ORDER BY created_at LIMIT 1",
                    (clue_candidate.title,),
                ).fetchone()
                if clue_row is None:
                    clue = narrative.add_clue(
                        clue_candidate.clue_type,
                        clue_candidate.title,
                        clue_candidate.detail,
                        Authority.MODEL_EXTRACTED,
                        ReviewStatus.REVIEW,
                    )
                    clue_count += 1
                else:
                    clue = narrative.get_clue(str(clue_row["id"]))
                event_exists = connection.execute(
                    "SELECT 1 FROM narrative_clue_events WHERE clue_id = ? "
                    "AND chapter_id = ? AND action = ? AND detail = ?",
                    (
                        clue.id,
                        chapter_id,
                        clue_candidate.action.value,
                        clue_candidate.detail,
                    ),
                ).fetchone()
                if event_exists is None:
                    narrative.append_clue_action(
                        clue.id,
                        chapter_id,
                        clue_candidate.action,
                        clue_candidate.detail,
                        SourceType.MODEL,
                        ReviewStatus.REVIEW,
                    )

            for knowledge_candidate in bundle.knowledge:
                if knowledge_candidate.subject_type != KnowledgeSubject.READER:
                    continue
                subject_id = project.project.id
                item_row = connection.execute(
                    "SELECT id FROM knowledge_items WHERE title = ? AND detail = ? "
                    "AND authority = 'MODEL_EXTRACTED' AND review_status = 'REVIEW' "
                    "ORDER BY created_at LIMIT 1",
                    (knowledge_candidate.title, knowledge_candidate.detail),
                ).fetchone()
                if item_row is None:
                    item = characters.create_knowledge_item(
                        knowledge_candidate.title,
                        knowledge_candidate.detail,
                        Authority.MODEL_EXTRACTED,
                        ReviewStatus.REVIEW,
                    )
                    knowledge_id = item.id
                    knowledge_count += 1
                else:
                    knowledge_id = str(item_row["id"])
                event_exists = connection.execute(
                    "SELECT 1 FROM knowledge_state_events WHERE knowledge_id = ? "
                    "AND subject_type = ? AND subject_id = ? AND chapter_id = ? "
                    "AND state = ?",
                    (
                        knowledge_id,
                        knowledge_candidate.subject_type.value,
                        subject_id,
                        chapter_id,
                        knowledge_candidate.state.value,
                    ),
                ).fetchone()
                if event_exists is None:
                    characters.append_knowledge_event(
                        knowledge_id,
                        knowledge_candidate.subject_type,
                        subject_id,
                        chapter_id,
                        knowledge_candidate.state,
                        knowledge_candidate.detail,
                        SourceType.MODEL,
                        ReviewStatus.REVIEW,
                    )

        return canon_count, clue_count, knowledge_count, style_count


def _find_or_create_character(
    repository: CharacterMemoryRepository, character_name: str
) -> Character:
    normalized = character_name.strip()
    for character in repository.list_characters():
        names = {character.canonical_name, *character.aliases}
        if normalized in names:
            return character
    return repository.create_character(normalized)


def _character_state_exists(
    repository: CharacterMemoryRepository,
    character_id: str,
    chapter_id: str,
    candidate: CharacterStateCandidate,
) -> bool:
    with repository.project.database.connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM character_state_events WHERE character_id = ? "
            "AND chapter_id = ? AND motivation = ? AND psychology = ? "
            "AND current_goal = ? AND relationships = ? AND recent_activity = ? "
            "AND location = ? AND injury_status = ? "
            "AND source_type = 'MODEL' AND review_status = 'REVIEW'",
            (
                character_id,
                chapter_id,
                candidate.motivation,
                candidate.psychology,
                candidate.current_goal,
                candidate.relationships,
                candidate.recent_activity,
                candidate.location,
                candidate.injury_status,
            ),
        ).fetchone()
    return row is not None
