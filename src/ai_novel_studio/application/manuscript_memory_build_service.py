from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
    FormalMaintenanceStatus,
)
from ai_novel_studio.application.memory_analysis_service import (
    MemoryCandidateBundle,
)
from ai_novel_studio.application.memory_candidate_ingest import (
    MemoryCandidateIngestService,
)
from ai_novel_studio.core.context.manuscript_chunking import (
    DEFAULT_MANUSCRIPT_CHUNK_POLICY,
    ManuscriptChunkPolicy,
)
from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.domain.memory import (
    Authority,
    ReviewStatus,
    SummaryLevel,
    SummaryNode,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
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


class MemoryBuildProgressPhase(StrEnum):
    SCANNING = "SCANNING"
    MODEL_CALL = "MODEL_CALL"


@dataclass(frozen=True, slots=True)
class MemoryBuildProgress:
    phase: MemoryBuildProgressPhase
    current: int
    total: int
    chapter_title: str

    def __post_init__(self) -> None:
        if self.current < 1 or self.total < 1 or self.current > self.total:
            raise ValueError("记忆整理进度必须位于有效章节范围内")
        if not self.chapter_title.strip():
            raise ValueError("记忆整理进度必须包含章节标题")


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
    pending_upgrade_summaries: int = 0
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

    def __init__(
        self,
        analyzer: MemoryAnalyzer | None = None,
        *,
        chunk_policy: ManuscriptChunkPolicy = DEFAULT_MANUSCRIPT_CHUNK_POLICY,
    ) -> None:
        self.analyzer = analyzer
        self.chunk_policy = chunk_policy
        self._ingest = MemoryCandidateIngestService()

    def build_all(
        self,
        project: ProjectRepository,
        *,
        progress: Callable[[MemoryBuildProgress], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ManuscriptMemoryBuildReport:
        chapters = ChapterRepository(project)
        summaries = SummaryRepository(project)
        search = SearchRepository(project)
        revision_maintenance = ChapterRevisionService(
            project,
            chunk_policy=self.chunk_policy,
        )
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
            current = processed + 1
            if progress is not None:
                progress(
                    MemoryBuildProgress(
                        MemoryBuildProgressPhase.SCANNING,
                        current,
                        total,
                        chapter.title,
                    )
                )
            exact_content = chapters.read_content_exact(chapter.id)
            maintenance = revision_maintenance.maintain_current_revision(
                chapter.id,
                expected_revision=chapter.revision,
                expected_source_hash=hashlib.sha256(
                    exact_content.encode("utf-8")
                ).hexdigest(),
            )
            if maintenance.status not in {
                FormalMaintenanceStatus.CURRENT,
                FormalMaintenanceStatus.REPAIRED,
            }:
                message = (
                    maintenance.failure.message
                    if maintenance.failure is not None
                    else "formal manuscript projection requires recovery"
                )
                raise RuntimeError(message)
            content = exact_content
            processed += 1
            if content.strip():
                search.index_chapter(chapter.id, chapter.title, content)
                indexed += 1
                current_summaries = self._current_summaries(summaries, chapter.id)
                fallback = self._upgradable_fallback(current_summaries)
                if current_summaries and fallback is None:
                    skipped += 1
                else:
                    if progress is not None and self.analyzer is not None:
                        progress(
                            MemoryBuildProgress(
                                MemoryBuildProgressPhase.MODEL_CALL,
                                current,
                                total,
                                chapter.title,
                            )
                        )
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
                        if bundle is not None:
                            report = self._ingest.ingest(
                                project,
                                chapter_id=chapter.id,
                                bundle=bundle,
                                fallback_summary=fallback,
                            )
                            upgraded_summaries += 1
                            created_character_states += report.created_character_states
                            created_canon += report.created_canon
                            created_clues += report.created_clues
                            created_knowledge += report.created_knowledge
                            created_style_rules += report.created_style_rules
                        elif error is None:
                            skipped += 1
                    else:
                        if bundle is not None:
                            report = self._ingest.ingest(
                                project,
                                chapter_id=chapter.id,
                                bundle=bundle,
                            )
                            created += 1
                            created_character_states += report.created_character_states
                            created_canon += report.created_canon
                            created_clues += report.created_clues
                            created_knowledge += report.created_knowledge
                            created_style_rules += report.created_style_rules
                        else:
                            fallback_summaries += 1
                            summaries.add_candidate(
                                SummaryLevel.CHAPTER,
                                chapter.id,
                                self._extractive_summary(chapter.title, content),
                                (chapter.id,),
                                model_profile_id=self.fallback_model_profile_id,
                            )
                            created += 1
        pending_upgrade_summaries = self._pending_upgrade_count(
            summaries, chapter_rows
        )

        return ManuscriptMemoryBuildReport(
            processed_chapters=processed,
            created_summaries=created,
            skipped_current_summaries=skipped,
            indexed_documents=indexed,
            created_character_states=created_character_states,
            fallback_summaries=fallback_summaries,
            upgraded_summaries=upgraded_summaries,
            pending_upgrade_summaries=pending_upgrade_summaries,
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
            bundle = self.analyzer.extract_candidates(chapter_id, revision, content)
            if (
                bundle.source_chapter_id != chapter_id
                or bundle.source_revision != revision
                or bundle.source_hash
                != hashlib.sha256(content.encode("utf-8")).hexdigest()
            ):
                raise ValueError(
                    "memory candidates do not match the current manuscript source"
                )
            return bundle, None
        except Exception as error:
            return None, error

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

    def _pending_upgrade_count(
        self,
        repository: SummaryRepository,
        chapters: list[Chapter],
    ) -> int:
        if not chapters:
            return 0
        chapter_ids = tuple(chapter.id for chapter in chapters)
        current_sources = {
            chapter_id: (revision, content_hash)
            for chapter_id, revision, content_hash in repository.source_revisions(
                chapter_ids
            )
        }
        current_by_scope: dict[str, list[SummaryNode]] = {}
        for summary in repository.list_all():
            source = current_sources.get(summary.scope_id)
            if (
                summary.level == SummaryLevel.CHAPTER
                and source is not None
                and summary.source_chapter_ids == (summary.scope_id,)
                and summary.source_revisions == ((summary.scope_id, *source),)
            ):
                current_by_scope.setdefault(summary.scope_id, []).append(summary)
        return sum(
            self._upgradable_fallback(tuple(current_by_scope.get(chapter_id, ())))
            is not None
            for chapter_id in current_sources
        )

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
