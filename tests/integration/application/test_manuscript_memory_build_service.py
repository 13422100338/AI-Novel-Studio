from pathlib import Path

from ai_novel_studio.application.manuscript_memory_build_service import (
    ManuscriptMemoryBuildService,
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
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


class FakeMemoryAnalyzer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def extract_candidates(
        self, chapter_id: str, revision: int, text: str
    ) -> MemoryCandidateBundle:
        self.calls.append(chapter_id)
        return MemoryCandidateBundle(
            source_chapter_id=chapter_id,
            source_revision=revision,
            source_hash="hash",
            summary=SummaryCandidate("林默收到匿名旧信，线索指向旧港与失踪兄长。"),
            character_states=(
                CharacterStateCandidate(
                    character_name="林默",
                    motivation="确认旧信真伪",
                    psychology="警惕但被失踪兄长牵动",
                    current_goal="前往旧港档案室",
                    relationships="仍不信任来信者",
                    recent_activity="收到匿名旧信",
                ),
            ),
            canon=(),
            clues=(),
            knowledge=(),
            style=(),
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
    with project.database.connect() as connection:
        rows = connection.execute(
            "SELECT source_id, document_type FROM memory_documents ORDER BY source_id"
        ).fetchall()
    assert {(row["source_id"], row["document_type"]) for row in rows} == {
        (first.id, "CHAPTER"),
        (second.id, "CHAPTER"),
    }


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


class FailingAnalyzer:
    def extract_candidates(self, chapter_id: str, revision: int, text: str):  # type: ignore[no-untyped-def]
        raise ValueError("invalid structured memory")


def test_build_reports_model_failures_and_supports_progress_and_cancel(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    chapters.create_chapter(volume.id, "第一章", "第1章", "正文一")
    chapters.create_chapter(volume.id, "第二章", "第2章", "正文二")
    progress: list[tuple[int, int, str]] = []

    report = ManuscriptMemoryBuildService(FailingAnalyzer()).build_all(
        project,
        progress=lambda done, total, title: progress.append((done, total, title)),
        should_cancel=lambda: bool(progress),
    )

    assert report.processed_chapters == 1
    assert report.cancelled is True
    assert len(report.failures) == 1
    assert "invalid structured memory" in report.failures[0].message
    assert progress == [(1, 2, "第一章")]


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
    assert report.created_style_rules == 1
    with project.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM canon_entries").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM narrative_clues").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM style_rules").fetchone()[0] == 1
