from __future__ import annotations

from dataclasses import dataclass

import pytest

from ai_novel_studio.application.shared_semantic_import_service import (
    SharedSemanticChapterResult,
    SharedSemanticImportService,
)
from ai_novel_studio.core.context.semantic_windowing import (
    SemanticWindow,
    SemanticWindowPolicy,
    project_semantic_windows,
)
from ai_novel_studio.core.context.shared_semantic_result import SharedSemanticResult
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@dataclass
class RecordingAnalyzer:
    calls: list[SemanticWindow]

    def extract(self, window: SemanticWindow) -> SharedSemanticResult:
        self.calls.append(window)
        return SharedSemanticResult(window=window)


def test_analyzes_each_window_once_in_canonical_chapter_order(tmp_path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    second_volume = project.create_volume("Second")
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(
        project.list_volumes()[0].id,
        "First",
        "1",
        "A" * 9,
    )
    second = chapters.create_chapter(
        second_volume.id,
        "Second",
        "2",
        "B" * 5,
    )
    analyzer = RecordingAnalyzer([])
    service = SharedSemanticImportService(
        analyzer,
        window_policy=SemanticWindowPolicy(
            version="semantic-window-test",
            max_codepoints=4,
            overlap_codepoints=1,
        ),
    )

    report = service.analyze_all(project)

    assert [item.chapter_id for item in report.chapters] == [first.id, second.id]
    assert [item.narrative_sequence for item in report.chapters] == [1, 2]
    assert [len(item.results) for item in report.chapters] == [3, 2]
    assert analyzer.calls == [
        result.window
        for chapter_result in report.chapters
        for result in chapter_result.results
    ]
    assert report.processed_chapters == 2
    assert report.processed_windows == 5
    assert report.failures == ()
    assert report.cancelled is False


def test_whitespace_chapter_is_a_successful_zero_window_result(tmp_path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Empty",
        "1",
        " \r\n ",
    )
    analyzer = RecordingAnalyzer([])

    report = SharedSemanticImportService(analyzer).analyze_all(project)

    assert report.processed_chapters == 1
    assert report.processed_windows == 0
    assert report.chapters[0].chapter_id == chapter.id
    assert report.chapters[0].results == ()
    assert analyzer.calls == []


def test_cancellation_between_windows_discards_partial_chapter(tmp_path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Long",
        "1",
        "A" * 9,
    )
    analyzer = RecordingAnalyzer([])
    service = SharedSemanticImportService(
        analyzer,
        window_policy=SemanticWindowPolicy(
            version="semantic-window-test",
            max_codepoints=4,
            overlap_codepoints=1,
        ),
    )

    report = service.analyze_all(
        project,
        should_cancel=lambda: bool(analyzer.calls),
    )

    assert len(analyzer.calls) == 1
    assert report.chapters == ()
    assert report.processed_chapters == 0
    assert report.processed_windows == 0
    assert report.cancelled is True


def test_wrong_window_result_fails_chapter_without_exposing_content(tmp_path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Chapter",
        "1",
        "PRIVATE-BODY",
    )

    class WrongWindowAnalyzer:
        def extract(self, window: SemanticWindow) -> SharedSemanticResult:
            return SharedSemanticResult(
                window=project_semantic_windows(
                    window.chapter_id,
                    window.source_revision,
                    window.source_hash,
                    window.narrative_sequence + 1,
                    window.text,
                    policy=SemanticWindowPolicy(
                        version=window.policy_version,
                        max_codepoints=len(window.text),
                        overlap_codepoints=0,
                    ),
                )[0]
            )

    report = SharedSemanticImportService(WrongWindowAnalyzer()).analyze_all(project)

    assert report.chapters == ()
    assert len(report.failures) == 1
    assert report.failures[0].code == "ANALYSIS_FAILED"
    assert report.failures[0].message == "shared semantic analysis failed"
    assert "PRIVATE-BODY" not in report.failures[0].message


def test_source_change_after_window_analysis_discards_whole_chapter(tmp_path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Chapter",
        "1",
        "original",
    )

    class MutatingAnalyzer:
        def extract(self, window: SemanticWindow) -> SharedSemanticResult:
            chapters.save_content(
                chapter.id,
                "changed",
                source="test",
                reason="source race",
                expected_revision=chapter.revision,
            )
            return SharedSemanticResult(window=window)

    report = SharedSemanticImportService(MutatingAnalyzer()).analyze_all(project)

    assert report.chapters == ()
    assert report.processed_chapters == 0
    assert len(report.failures) == 1
    assert report.failures[0].code == "SOURCE_CHANGED"
    assert report.failures[0].message == "chapter source changed during analysis"


def test_multi_window_source_race_discards_every_partial_result(tmp_path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Chapter",
        "1",
        "A" * 9,
    )

    class MutatingAfterFirstWindowAnalyzer:
        def __init__(self) -> None:
            self.calls = 0

        def extract(self, window: SemanticWindow) -> SharedSemanticResult:
            self.calls += 1
            if self.calls == 2:
                chapters.save_content(
                    chapter.id,
                    "changed",
                    source="test",
                    reason="source race",
                    expected_revision=chapter.revision,
                )
            return SharedSemanticResult(window=window)

    analyzer = MutatingAfterFirstWindowAnalyzer()
    report = SharedSemanticImportService(
        analyzer,
        window_policy=SemanticWindowPolicy(
            version="semantic-window-test",
            max_codepoints=4,
            overlap_codepoints=1,
        ),
    ).analyze_all(project)

    assert analyzer.calls == 3
    assert report.chapters == ()
    assert report.processed_windows == 0
    assert [item.code for item in report.failures] == ["SOURCE_CHANGED"]


def test_analyzer_failure_is_sanitized_and_later_chapter_continues(tmp_path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(
        project.list_volumes()[0].id,
        "First",
        "1",
        "PRIVATE-FIRST",
    )
    second = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Second",
        "2",
        "Second body",
    )

    class FailingOnceAnalyzer:
        def extract(self, window: SemanticWindow) -> SharedSemanticResult:
            if window.chapter_id == first.id:
                raise RuntimeError("C:\\private\\chapter.md PRIVATE-FIRST")
            return SharedSemanticResult(window=window)

    report = SharedSemanticImportService(FailingOnceAnalyzer()).analyze_all(project)

    assert [item.chapter_id for item in report.chapters] == [second.id]
    assert len(report.failures) == 1
    assert report.failures[0].chapter_id == first.id
    assert report.failures[0].message == "shared semantic analysis failed"
    assert "PRIVATE-FIRST" not in report.failures[0].message
    assert "C:\\" not in report.failures[0].message


def test_invalid_analyzer_is_rejected_before_project_access() -> None:
    with pytest.raises(TypeError, match="analyzer"):
        SharedSemanticImportService(object())  # type: ignore[arg-type]


def test_chapter_result_rejects_missing_or_reordered_windows() -> None:
    windows = project_semantic_windows(
        "00000000-0000-0000-0000-000000000001",
        0,
        "a" * 64,
        1,
        "A" * 9,
        policy=SemanticWindowPolicy(
            version="semantic-window-test",
            max_codepoints=4,
            overlap_codepoints=1,
        ),
    )

    with pytest.raises(ValueError, match="chapter result"):
        SharedSemanticChapterResult(
            chapter_id=windows[0].chapter_id,
            source_revision=0,
            source_hash="a" * 64,
            narrative_sequence=1,
            results=(
                SharedSemanticResult(window=windows[1]),
                SharedSemanticResult(window=windows[0]),
            ),
        )


def test_base_exception_from_analyzer_is_not_swallowed(tmp_path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Chapter",
        "1",
        "body",
    )

    class InterruptedAnalyzer:
        def extract(self, window: SemanticWindow) -> SharedSemanticResult:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        SharedSemanticImportService(InterruptedAnalyzer()).analyze_all(project)


def test_exact_crlf_emoji_slices_and_no_persistence(tmp_path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Imported Novel")
    content = "第一段🙂\r\n\r\n第二段\r\n"
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Chapter",
        "1",
        content,
    )
    analyzer = RecordingAnalyzer([])
    with project.database.connect() as connection:
        before = {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in (
                "summary_nodes",
                "character_state_events",
                "canon_entries",
                "narrative_clues",
                "view_assertions",
            )
        }

    report = SharedSemanticImportService(analyzer).analyze_all(project)

    result = report.chapters[0]
    assert result.chapter_id == chapter.id
    assert "".join(
        window.text
        for window in analyzer.calls
        if window.source_start == 0 or window.source_start >= analyzer.calls[
            analyzer.calls.index(window) - 1
        ].source_end
    ) == content
    assert all(
        window.text == content[window.source_start : window.source_end]
        for window in analyzer.calls
    )
    with project.database.connect() as connection:
        after = {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in before
        }
    assert after == before
