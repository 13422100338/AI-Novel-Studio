from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

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
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository
from ai_novel_studio.infrastructure.storage.summary_repository import (
    MODEL_RETRY_PROFILE_ID,
    SummaryRepository,
)


class MemoryAnalyzer(Protocol):
    def extract_candidates(
        self, chapter_id: str, revision: int, text: str
    ) -> MemoryCandidateBundle: ...


@dataclass(frozen=True, slots=True)
class ManuscriptMemoryBuildFailure:
    chapter_id: str
    chapter_title: str
    message: str


@dataclass(frozen=True, slots=True)
class ManuscriptMemoryBuildReport:
    processed_chapters: int
    created_summaries: int
    skipped_current_summaries: int
    indexed_documents: int
    created_character_states: int = 0
    fallback_summaries: int = 0
    upgraded_summaries: int = 0
    created_canon: int = 0
    created_clues: int = 0
    created_knowledge: int = 0
    created_style_rules: int = 0
    failures: tuple[ManuscriptMemoryBuildFailure, ...] = ()
    cancelled: bool = False


class ManuscriptMemoryBuildService:
    """Build the first reviewable memory layer from imported manuscript chapters."""

    fallback_model_profile_id = "local-import-baseline"
    model_profile_id = "memory-extraction"

    def __init__(self, analyzer: MemoryAnalyzer | None = None) -> None:
        self.analyzer = analyzer

    def build_all(
        self,
        project: ProjectRepository,
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ManuscriptMemoryBuildReport:
        chapters = ChapterRepository(project)
        summaries = SummaryRepository(project)
        characters = CharacterMemoryRepository(project)
        search = SearchRepository(project)
        processed = 0
        created = 0
        skipped = 0
        indexed = 0
        created_character_states = 0
        fallback_summaries = 0
        upgraded_summaries = 0
        created_canon = 0
        created_clues = 0
        created_knowledge = 0
        created_style_rules = 0
        failures: list[ManuscriptMemoryBuildFailure] = []
        cancelled = False

        chapter_rows = [
            chapter
            for volume in project.list_volumes()
            for chapter in chapters.list_chapters(volume.id)
        ]
        total = len(chapter_rows)

        for chapter in chapter_rows:
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
            content = chapters.read_content(chapter.id)
            processed += 1
            if content.strip():
                search.index_chapter(chapter.id, chapter.title, content)
                indexed += 1
                current_summaries = self._current_summaries(summaries, chapter.id)
                fallback = self._upgradable_fallback(current_summaries)
                if current_summaries and fallback is None:
                    skipped += 1
                else:
                    bundle, error = self._extract_model_bundle(
                        chapter.id, chapter.revision, content
                    )
                    if error is not None:
                        failures.append(
                            ManuscriptMemoryBuildFailure(
                                chapter.id,
                                chapter.title,
                                _safe_failure_message(error),
                            )
                        )
                    if fallback is not None:
                        if bundle is None:
                            skipped += 1
                        else:
                            summaries.replace_model_candidate(
                                fallback.id,
                                bundle.summary.content,
                                model_profile_id=self.model_profile_id,
                                expected_revision=fallback.revision,
                            )
                            upgraded_summaries += 1
                            created_character_states += self._save_character_states(
                                characters, chapter.id, bundle
                            )
                            ledger_counts = self._save_ledger_candidates(
                                project, chapter.id, bundle
                            )
                            created_canon += ledger_counts[0]
                            created_clues += ledger_counts[1]
                            created_knowledge += ledger_counts[2]
                            created_style_rules += ledger_counts[3]
                    else:
                        summary_content = (
                            bundle.summary.content
                            if bundle is not None
                            else self._extractive_summary(chapter.title, content)
                        )
                        if bundle is None:
                            fallback_summaries += 1
                        summaries.add_candidate(
                            SummaryLevel.CHAPTER,
                            chapter.id,
                            summary_content,
                            (chapter.id,),
                            model_profile_id=(
                                self.model_profile_id
                                if bundle is not None
                                else self.fallback_model_profile_id
                            ),
                        )
                        created += 1
                        if bundle is not None:
                            created_character_states += self._save_character_states(
                                characters, chapter.id, bundle
                            )
                            ledger_counts = self._save_ledger_candidates(
                                project, chapter.id, bundle
                            )
                            created_canon += ledger_counts[0]
                            created_clues += ledger_counts[1]
                            created_knowledge += ledger_counts[2]
                            created_style_rules += ledger_counts[3]
            if progress is not None:
                progress(processed, total, chapter.title)

        return ManuscriptMemoryBuildReport(
            processed_chapters=processed,
            created_summaries=created,
            skipped_current_summaries=skipped,
            indexed_documents=indexed,
            created_character_states=created_character_states,
            fallback_summaries=fallback_summaries,
            upgraded_summaries=upgraded_summaries,
            created_canon=created_canon,
            created_clues=created_clues,
            created_knowledge=created_knowledge,
            created_style_rules=created_style_rules,
            failures=tuple(failures),
            cancelled=cancelled,
        )

    def _extract_model_bundle(
        self, chapter_id: str, revision: int, content: str
    ) -> tuple[MemoryCandidateBundle | None, BaseException | None]:
        if self.analyzer is None:
            return None, None
        try:
            return self.analyzer.extract_candidates(chapter_id, revision, content), None
        except Exception as error:
            return None, error

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

    @staticmethod
    def _current_summaries(
        repository: SummaryRepository, chapter_id: str
    ) -> tuple[SummaryNode, ...]:
        return tuple(
            summary
            for summary in repository.list_scope(SummaryLevel.CHAPTER, chapter_id)
            if summary.source_revisions == repository.source_revisions((chapter_id,))
        )

    def _upgradable_fallback(
        self, summaries: tuple[SummaryNode, ...]
    ) -> SummaryNode | None:
        if len(summaries) != 1:
            return None
        summary = summaries[0]
        if (
            (
                summary.model_profile_id == MODEL_RETRY_PROFILE_ID
                or (
                    summary.model_profile_id == self.fallback_model_profile_id
                    and summary.revision == 0
                )
            )
            and summary.authority == Authority.MODEL_EXTRACTED
            and summary.review_status == ReviewStatus.REVIEW
        ):
            return summary
        return None

    @staticmethod
    def _extractive_summary(title: str, content: str) -> str:
        normalized = " ".join(line.strip() for line in content.splitlines() if line.strip())
        opening = normalized[:240]
        ending = normalized[-240:] if len(normalized) > 240 else normalized
        details = f"- 原文：{opening}"
        if ending != opening:
            details += f"\n- 原文：{ending}"
        return (
            "【待模型整理：当前仅保存原文定位，不作为有效剧情摘要】\n"
            f"## 剧情概况\n《{title}》尚未完成模型整理。\n\n"
            "## 关键情节点\n- 待模型整理\n\n"
            "## 人物成长\n- 待模型整理\n\n"
            "## 连续性要点\n- 待模型整理\n\n"
            f"## 细节摘录\n{details}"
        )


def _safe_failure_message(error: BaseException) -> str:
    message = str(error).strip() or type(error).__name__
    return message[:500]


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
            "AND source_type = 'MODEL' AND review_status = 'REVIEW'",
            (
                character_id,
                chapter_id,
                candidate.motivation,
                candidate.psychology,
                candidate.current_goal,
                candidate.relationships,
                candidate.recent_activity,
            ),
        ).fetchone()
    return row is not None
