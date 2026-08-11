import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
    FormalMaintenanceResult,
)
from ai_novel_studio.application.manuscript_memory_build_service import (
    ManuscriptMemoryBuildService,
    MemoryBuildProgress,
    MemoryBuildProgressPhase,
)
from ai_novel_studio.application.memory_analysis_service import (
    CanonCandidate,
    CharacterStateCandidate,
    ClueCandidate,
    KnowledgeCandidate,
    MemoryCandidateBundle,
    StyleCandidate,
    SummaryCandidate,
)
from ai_novel_studio.core.context.manuscript_chunking import (
    DEFAULT_MANUSCRIPT_CHUNK_POLICY,
    ManuscriptChunkPolicy,
)
from ai_novel_studio.domain.embedding import EmbeddingIndexIdentity
from ai_novel_studio.domain.memory import (
    ClueAction,
    ClueType,
    KnowledgeState,
    KnowledgeSubject,
    MemoryStatus,
    ReviewStatus,
    StyleScope,
    SummaryLevel,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository

_EMBEDDING_IDENTITY = EmbeddingIndexIdentity("provider-a", "embedding-model", 1)


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class FakeMemoryAnalyzer:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.inputs: list[tuple[str, int, str]] = []

    def extract_candidates(
        self, chapter_id: str, revision: int, text: str
    ) -> MemoryCandidateBundle:
        self.calls.append(chapter_id)
        self.inputs.append((chapter_id, revision, text))
        return MemoryCandidateBundle(
            source_chapter_id=chapter_id,
            source_revision=revision,
            source_hash=_source_hash(text),
            summary=SummaryCandidate("林默收到匿名旧信，线索指向旧港与失踪兄长。"),
            character_states=(
                CharacterStateCandidate(
                    character_name="林默",
                    motivation="确认旧信真伪",
                    psychology="警惕但被失踪兄长牵动",
                    current_goal="前往旧港档案室",
                    relationships="仍不信任来信者",
                    recent_activity="收到匿名旧信",
                    location="旧港档案室",
                    injury_status="无明显外伤",
                ),
            ),
            canon=(),
            clues=(),
            knowledge=(),
            style=(),
        )


class MismatchedSourceMemoryAnalyzer(FakeMemoryAnalyzer):
    def extract_candidates(
        self, chapter_id: str, revision: int, text: str
    ) -> MemoryCandidateBundle:
        return replace(
            super().extract_candidates(chapter_id, revision, text),
            source_hash="0" * 64,
        )


def test_build_all_creates_review_summaries_and_search_documents(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(
        volume.id,
        "第一章",
        "第1章",
        "林默收到一封没有署名的信。信里提到旧港、潮声和失踪的兄长。",
    )
    second = chapters.create_chapter(
        volume.id,
        "第二章",
        "第2章",
        "林默来到旧港档案室，发现兄长留下的暗号和一枚潮湿的指纹。",
    )

    report = ManuscriptMemoryBuildService().build_all(project)

    summaries = SummaryRepository(project).list_all()
    assert report.processed_chapters == 2
    assert report.created_summaries == 2
    assert report.indexed_documents == 2
    assert {summary.scope_id for summary in summaries} == {first.id, second.id}
    assert {summary.level for summary in summaries} == {SummaryLevel.CHAPTER}
    assert {summary.review_status for summary in summaries} == {ReviewStatus.REVIEW}
    assert {summary.status for summary in summaries} == {MemoryStatus.REVIEW}
    for summary in summaries:
        assert "## 剧情概况" in summary.content
        assert "## 细节摘录" in summary.content
        assert "## 伏笔与未决问题" not in summary.content
        assert summary.content.count("- 原文：") == 1
    with project.database.connect() as connection:
        rows = connection.execute(
            "SELECT source_id, document_type FROM memory_documents ORDER BY source_id"
        ).fetchall()
    search = SearchRepository(project)
    formal_by_chapter = {
        chapter.id: search.read_formal_manuscript_chunks(
            chapter.id,
            expected_revision=chapter.revision,
            expected_source_hash=_source_hash(chapters.read_content(chapter.id)),
            chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
        )
        for chapter in (first, second)
    }
    assert {(row["source_id"], row["document_type"]) for row in rows} == {
        (first.id, "CHAPTER"),
        (second.id, "CHAPTER"),
        (formal_by_chapter[first.id][0].source_id, "FORMAL_MANUSCRIPT"),
        (formal_by_chapter[second.id][0].source_id, "FORMAL_MANUSCRIPT"),
    }
    assert all(
        (
            documents[0].source_revision,
            documents[0].source_start,
            documents[0].source_end,
            documents[0].chunk_ordinal,
            documents[0].chunk_policy_version,
            documents[0].content,
        )
        == (
            chapter.revision,
            0,
            len(chapters.read_content(chapter.id)),
            0,
            DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
            chapters.read_content(chapter.id),
        )
        for chapter in (first, second)
        for documents in (formal_by_chapter[chapter.id],)
    )


def test_build_all_reuses_chapter_revision_maintainer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Shared maintainer")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "Body",
    )
    calls: list[tuple[str, int, str]] = []
    original = ChapterRevisionService.maintain_current_revision

    def track_maintenance(
        service: ChapterRevisionService,
        chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
    ) -> FormalMaintenanceResult:
        calls.append((chapter_id, expected_revision, expected_source_hash))
        return original(
            service,
            chapter_id,
            expected_revision=expected_revision,
            expected_source_hash=expected_source_hash,
        )

    monkeypatch.setattr(
        ChapterRevisionService,
        "maintain_current_revision",
        track_maintenance,
    )

    report = ManuscriptMemoryBuildService().build_all(project)

    assert calls == [(chapter.id, chapter.revision, _source_hash("Body"))]
    assert report.processed_chapters == 1
    assert report.indexed_documents == 1


def test_build_all_replay_preserves_formal_rows_vectors_fts_and_dependencies(
    tmp_path: Path,
) -> None:
    content = "第一段原文。\n\n第二段原文。"
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "第一章",
        "1",
        content,
    )
    service = ManuscriptMemoryBuildService()
    search = SearchRepository(project)

    first_report = service.build_all(project)
    first = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    source = search.embedding_source(first[0].id)
    search.save_embedding(
        first[0].id,
        _EMBEDDING_IDENTITY,
        (1.0, 0.0),
        expected_content_hash=source.content_hash,
    )
    with project.database.connect() as connection:
        before = (
            tuple(
                connection.execute(
                    "SELECT id, updated_at FROM memory_documents WHERE id = ?",
                    (first[0].id,),
                ).fetchone()
            ),
            tuple(
                connection.execute(
                    "SELECT rowid, title, content, participants "
                    "FROM memory_fts WHERE document_id = ?",
                    (first[0].id,),
                ).fetchone()
            ),
            tuple(
                connection.execute(
                    "SELECT id, source_revision, source_hash, status "
                    "FROM memory_dependencies "
                    "WHERE memory_type = 'SEARCH' AND memory_id = ?",
                    (first[0].id,),
                ).fetchone()
            ),
        )

    second_report = service.build_all(project)
    second = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    with project.database.connect() as connection:
        after = (
            tuple(
                connection.execute(
                    "SELECT id, updated_at FROM memory_documents WHERE id = ?",
                    (first[0].id,),
                ).fetchone()
            ),
            tuple(
                connection.execute(
                    "SELECT rowid, title, content, participants "
                    "FROM memory_fts WHERE document_id = ?",
                    (first[0].id,),
                ).fetchone()
            ),
            tuple(
                connection.execute(
                    "SELECT id, source_revision, source_hash, status "
                    "FROM memory_dependencies "
                    "WHERE memory_type = 'SEARCH' AND memory_id = ?",
                    (first[0].id,),
                ).fetchone()
            ),
        )

    assert first_report.indexed_documents == 1
    assert second_report.indexed_documents == 1
    assert second == first
    assert after == before
    assert search.get_embedding(first[0].id, _EMBEDDING_IDENTITY).vector == (1.0, 0.0)


def test_build_all_revision_change_replaces_only_that_chapters_formal_projection(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    chapters = ChapterRepository(project)
    volume = project.list_volumes()[0]
    changed = chapters.create_chapter(volume.id, "First", "1", "Old first body")
    untouched = chapters.create_chapter(volume.id, "Second", "2", "Stable second body")
    service = ManuscriptMemoryBuildService()
    search = SearchRepository(project)

    service.build_all(project)
    old_changed = search.read_formal_manuscript_chunks(
        changed.id,
        expected_revision=changed.revision,
        expected_source_hash=_source_hash("Old first body"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    old_untouched = search.read_formal_manuscript_chunks(
        untouched.id,
        expected_revision=untouched.revision,
        expected_source_hash=_source_hash("Stable second body"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    old_source = search.embedding_source(old_changed[0].id)
    search.save_embedding(
        old_changed[0].id,
        _EMBEDDING_IDENTITY,
        (1.0, 0.0),
        expected_content_hash=old_source.content_hash,
    )

    current = chapters.save_content(
        changed.id,
        "New first body",
        source="manual",
        reason="rewrite",
    )
    report = service.build_all(project)
    new_changed = search.read_formal_manuscript_chunks(
        current.id,
        expected_revision=current.revision,
        expected_source_hash=_source_hash("New first body"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    new_untouched = search.read_formal_manuscript_chunks(
        untouched.id,
        expected_revision=untouched.revision,
        expected_source_hash=_source_hash("Stable second body"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )

    assert report.indexed_documents == 2
    assert new_changed[0].id != old_changed[0].id
    assert new_changed[0].content == "New first body"
    assert new_untouched == old_untouched
    with pytest.raises(KeyError):
        search.get(old_changed[0].id)
    with pytest.raises(KeyError):
        search.get_embedding(old_changed[0].id, _EMBEDDING_IDENTITY)
    with project.database.connect() as connection:
        legacy = connection.execute(
            "SELECT chapter_id, content, status FROM memory_documents "
            "WHERE document_type = 'CHAPTER' ORDER BY chapter_id"
        ).fetchall()
    assert {(row["chapter_id"], row["content"], row["status"]) for row in legacy} == {
        (changed.id, "New first body", "CURRENT"),
        (untouched.id, "Stable second body", "CURRENT"),
    }


def test_build_all_policy_change_replaces_only_formal_projection_identity(
    tmp_path: Path,
) -> None:
    content = "甲" * 1_700
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "First",
        "1",
        content,
    )
    search = SearchRepository(project)

    ManuscriptMemoryBuildService().build_all(project)
    default_documents = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    alternate_policy = ManuscriptChunkPolicy("paragraph-codepoint-v2", 800, 100)

    report = ManuscriptMemoryBuildService(chunk_policy=alternate_policy).build_all(
        project
    )
    alternate_documents = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=alternate_policy.version,
    )

    assert report.indexed_documents == 1
    assert len(default_documents) == 2
    assert len(alternate_documents) == 3
    assert {document.source_id for document in default_documents}.isdisjoint(
        document.source_id for document in alternate_documents
    )
    for document in default_documents:
        with pytest.raises(KeyError):
            search.get(document.id)
    with project.database.connect() as connection:
        legacy_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_documents "
                "WHERE document_type = 'CHAPTER' AND chapter_id = ?",
                (chapter.id,),
            ).fetchone()[0]
        )
    assert legacy_count == 1


def test_build_all_whitespace_revision_removes_prior_formal_projection(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "First",
        "1",
        "Previously indexed body",
    )
    service = ManuscriptMemoryBuildService()
    search = SearchRepository(project)

    service.build_all(project)
    prior = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash("Previously indexed body"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    current = chapters.save_content(
        chapter.id,
        " \r\n\t ",
        source="manual",
        reason="clear chapter",
    )

    report = service.build_all(project)

    assert report.processed_chapters == 1
    assert report.indexed_documents == 0
    assert (
        search.read_formal_manuscript_chunks(
            current.id,
            expected_revision=current.revision,
            expected_source_hash=_source_hash(" \r\n\t "),
            chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
        )
        == ()
    )
    with pytest.raises(KeyError):
        search.get(prior[0].id)


def test_build_all_formal_chunks_are_pending_for_embedding_without_writing_vectors(
    tmp_path: Path,
) -> None:
    content = "甲" * 1_700
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "First",
        "1",
        content,
    )
    search = SearchRepository(project)

    ManuscriptMemoryBuildService().build_all(project)

    formal = search.read_formal_manuscript_chunks(
        chapter.id,
        expected_revision=chapter.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    pending = search.pending_embedding_sources(_EMBEDDING_IDENTITY, limit=10)
    with project.database.connect() as connection:
        embedding_count = int(
            connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
        )

    assert len(formal) == 2
    assert {source.document_id for source in pending}.issuperset(
        document.id for document in formal
    )
    assert embedding_count == 0


def test_build_all_uses_model_memory_candidates_and_updates_character_states(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(
        volume.id,
        "第一章",
        "第 1 章",
        "林默收到一封匿名旧信，信里提到旧港和失踪兄长。",
    )

    report = ManuscriptMemoryBuildService(FakeMemoryAnalyzer()).build_all(project)

    summary = SummaryRepository(project).list_scope(SummaryLevel.CHAPTER, chapter.id)[0]
    characters = CharacterMemoryRepository(project)
    character = characters.list_characters()[0]
    state = characters.state_history(character.id)[0]

    assert report.created_summaries == 1
    assert report.created_character_states == 1
    assert summary.content == "林默收到匿名旧信，线索指向旧港与失踪兄长。"
    assert "基础章节摘要候选" not in summary.content
    assert character.canonical_name == "林默"
    assert state.psychology == "警惕但被失踪兄长牵动"
    assert state.current_goal == "前往旧港档案室"
    assert state.location == "旧港档案室"
    assert state.injury_status == "无明显外伤"
    assert state.review_status == ReviewStatus.REVIEW


def test_build_all_skips_current_summary_candidates_on_rerun(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    volume = project.list_volumes()[0]
    ChapterRepository(project).create_chapter(volume.id, "第一章", "第1章", "正文")
    service = ManuscriptMemoryBuildService()

    first = service.build_all(project)
    second = service.build_all(project)

    assert first.created_summaries == 1
    assert second.created_summaries == 0
    assert second.skipped_current_summaries == 1
    assert len(SummaryRepository(project).list_all()) == 1


def test_model_build_upgrades_a_previous_fallback_summary_and_adds_character_state(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(
        volume.id,
        "第一章",
        "第1章",
        "林默收到匿名旧信，准备前往旧港档案室。",
    )

    fallback = ManuscriptMemoryBuildService().build_all(project)
    upgraded = ManuscriptMemoryBuildService(FakeMemoryAnalyzer()).build_all(project)

    summaries = SummaryRepository(project).list_scope(SummaryLevel.CHAPTER, chapter.id)
    characters = CharacterMemoryRepository(project).list_characters()

    assert fallback.fallback_summaries == 1
    assert upgraded.created_summaries == 0
    assert upgraded.upgraded_summaries == 1
    assert len(summaries) == 1
    assert summaries[0].content == "林默收到匿名旧信，线索指向旧港与失踪兄长。"
    assert upgraded.created_character_states == 1
    assert [character.canonical_name for character in characters] == ["林默"]


def test_rerun_does_not_call_model_for_current_model_summary(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    volume = project.list_volumes()[0]
    ChapterRepository(project).create_chapter(volume.id, "第一章", "第1章", "正文")
    analyzer = FakeMemoryAnalyzer()
    service = ManuscriptMemoryBuildService(analyzer)

    service.build_all(project)
    second = service.build_all(project)

    assert len(analyzer.calls) == 1
    assert second.skipped_current_summaries == 1


def test_build_all_passes_exact_shared_chapter_source_to_analyzer_once(
    tmp_path: Path,
) -> None:
    content = "艾瑞克进入大厅。\r\n克莉丝汀随后抵达。\r\n国王举起🗝️。"
    project = ProjectRepository.create(tmp_path / "novel", "Shared semantic import")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Shared scene",
        "1",
        content,
    )
    analyzer = FakeMemoryAnalyzer()

    ManuscriptMemoryBuildService(analyzer).build_all(project)

    assert analyzer.inputs == [(chapter.id, chapter.revision, content)]
    with project.database.connect() as connection:
        indexed = connection.execute(
            "SELECT content FROM memory_documents "
            "WHERE document_type = 'CHAPTER' AND chapter_id = ?",
            (chapter.id,),
        ).fetchone()
    assert indexed is not None
    assert indexed["content"] == content


def test_build_all_rejects_model_bundle_for_a_different_source_snapshot(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Source identity guard")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "林默打开旧信。",
    )

    report = ManuscriptMemoryBuildService(
        MismatchedSourceMemoryAnalyzer()
    ).build_all(project)

    summaries = SummaryRepository(project).list_scope(SummaryLevel.CHAPTER, chapter.id)
    assert len(report.failures) == 1
    assert report.failures[0].message == (
        "memory candidates do not match the current manuscript source"
    )
    assert report.created_character_states == 0
    assert report.fallback_summaries == 1
    assert len(summaries) == 1
    assert summaries[0].model_profile_id == "local-import-baseline"


def test_requested_retry_reprocesses_only_the_target_model_summary(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "First", "1", "First chapter body")
    chapters.create_chapter(volume.id, "Second", "2", "Second chapter body")
    analyzer = FakeMemoryAnalyzer()
    service = ManuscriptMemoryBuildService(analyzer)

    first_run = service.build_all(project)
    repository = SummaryRepository(project)
    summary = repository.list_scope(SummaryLevel.CHAPTER, first.id)[0]
    promoted = repository.promote(summary.id, expected_revision=summary.revision)
    repository.request_model_retry(summary.id, expected_revision=promoted.revision)
    second_run = service.build_all(project)

    assert first_run.created_summaries == 2
    assert analyzer.calls.count(first.id) == 2
    assert len(analyzer.calls) == 3
    assert second_run.upgraded_summaries == 1
    assert second_run.skipped_current_summaries == 1
    assert repository.get(summary.id).review_status == ReviewStatus.REVIEW


class FailingAnalyzer:
    def extract_candidates(self, chapter_id: str, revision: int, text: str):  # type: ignore[no-untyped-def]
        raise ValueError("invalid structured memory")


def test_failed_fallback_retry_is_not_counted_as_unchanged_summary(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(
        volume.id, "Problem Chapter", "1", "Chapter body"
    )
    repository = SummaryRepository(project)

    ManuscriptMemoryBuildService().build_all(project)
    before = repository.list_scope(SummaryLevel.CHAPTER, chapter.id)[0]
    report = ManuscriptMemoryBuildService(FailingAnalyzer()).build_all(project)
    after = repository.get(before.id)

    assert len(report.failures) == 1
    assert report.skipped_current_summaries == 0
    assert report.upgraded_summaries == 0
    assert after.content == before.content


def test_stale_fallback_is_historical_and_not_double_counted_as_pending_upgrade(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(volume.id, "Problem Chapter", "1", "Old body")
    repository = SummaryRepository(project)

    first = ManuscriptMemoryBuildService().build_all(project)
    chapters.save_content(
        chapter.id,
        "Rewritten body",
        source="manual",
        reason="rewrite",
    )
    second = ManuscriptMemoryBuildService(FailingAnalyzer()).build_all(project)
    stored = repository.list_scope(SummaryLevel.CHAPTER, chapter.id)

    assert first.pending_upgrade_summaries == 1
    assert second.pending_upgrade_summaries == 1
    assert len(stored) == 2
    assert sum(item.status == MemoryStatus.STALE for item in stored) == 1
    assert sum(item.status == MemoryStatus.REVIEW for item in stored) == 1


def test_progress_distinguishes_chapter_scan_from_actual_model_call(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "First", "1", "First body")
    second = chapters.create_chapter(volume.id, "Second", "2", "Second body")
    SummaryRepository(project).add_candidate(
        SummaryLevel.CHAPTER,
        first.id,
        "Current summary",
        (first.id,),
        model_profile_id="memory-extraction",
    )
    analyzer = FakeMemoryAnalyzer()
    progress: list[MemoryBuildProgress] = []

    report = ManuscriptMemoryBuildService(analyzer).build_all(
        project,
        progress=progress.append,
    )

    assert analyzer.calls == [second.id]
    assert [
        (item.phase, item.current, item.total, item.chapter_title) for item in progress
    ] == [
        (MemoryBuildProgressPhase.SCANNING, 1, 2, "First"),
        (MemoryBuildProgressPhase.SCANNING, 2, 2, "Second"),
        (MemoryBuildProgressPhase.MODEL_CALL, 2, 2, "Second"),
    ]
    assert report.pending_upgrade_summaries == 0


def test_build_reports_model_failures_and_supports_progress_and_cancel(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    chapters.create_chapter(volume.id, "第一章", "第1章", "正文一")
    chapters.create_chapter(volume.id, "第二章", "第2章", "正文二")
    progress: list[MemoryBuildProgress] = []

    report = ManuscriptMemoryBuildService(FailingAnalyzer()).build_all(
        project,
        progress=progress.append,
        should_cancel=lambda: bool(progress),
    )

    assert report.processed_chapters == 1
    assert report.cancelled is True
    assert len(report.failures) == 1
    assert "invalid structured memory" in report.failures[0].message
    assert [item.phase for item in progress] == [
        MemoryBuildProgressPhase.SCANNING,
        MemoryBuildProgressPhase.MODEL_CALL,
    ]
    assert {(item.current, item.total, item.chapter_title) for item in progress} == {
        (1, 2, "第一章")
    }


class FullMemoryAnalyzer(FakeMemoryAnalyzer):
    def extract_candidates(
        self, chapter_id: str, revision: int, text: str
    ) -> MemoryCandidateBundle:
        base = super().extract_candidates(chapter_id, revision, text)
        return MemoryCandidateBundle(
            source_chapter_id=base.source_chapter_id,
            source_revision=base.source_revision,
            source_hash=base.source_hash,
            summary=base.summary,
            character_states=base.character_states,
            canon=(CanonCandidate("旧港规则", "午夜后档案室关闭。"),),
            clues=(
                ClueCandidate(
                    ClueType.FORESHADOW,
                    "潮湿指纹",
                    "指纹与失踪兄长有关。",
                    ClueAction.PLANT,
                ),
            ),
            knowledge=(
                KnowledgeCandidate(
                    KnowledgeSubject.CHARACTER,
                    "林默",
                    "暗号来源",
                    "林默认出暗号属于兄长。",
                    KnowledgeState.KNOWN,
                ),
                KnowledgeCandidate(
                    KnowledgeSubject.READER,
                    "reader",
                    "来信者身份",
                    "读者已经知道来信者来自旧港。",
                    KnowledgeState.KNOWN,
                ),
            ),
            style=(
                StyleCandidate(
                    StyleScope.CHAPTER,
                    chapter_id,
                    "节奏",
                    "短句推进调查压力。",
                ),
            ),
        )


def test_build_persists_all_structured_memory_candidate_categories(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    volume = project.list_volumes()[0]
    ChapterRepository(project).create_chapter(
        volume.id, "第一章", "第1章", "林默在旧港发现兄长留下的暗号。"
    )

    report = ManuscriptMemoryBuildService(FullMemoryAnalyzer()).build_all(project)

    assert report.created_character_states == 1
    assert report.created_canon == 1
    assert report.created_clues == 1
    assert report.created_knowledge == 1
    assert report.created_style_rules == 0
    with project.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM canon_entries").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM narrative_clues").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0] == 1
        subjects = connection.execute(
            "SELECT DISTINCT subject_type FROM knowledge_state_events"
        ).fetchall()
        assert [row["subject_type"] for row in subjects] == ["READER"]
        assert connection.execute("SELECT COUNT(*) FROM style_rules").fetchone()[0] == 0
