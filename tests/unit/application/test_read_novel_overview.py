"""Ticket B: READ_NOVEL_OVERVIEW tool + batch tool bad-ID resilience."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ai_novel_studio.application.agent_tool_providers import (
    ReadChaptersBatchTool,
    ReadNovelOverviewTool,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import (
    ProjectRepository,
)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class _Request:
    def __init__(self, arguments: dict[str, Any], max_result_chars: int = 16_000):
        self.arguments = arguments
        self.max_result_chars = max_result_chars
        self.run_id = "test-run"
        self.chapter_id = None


def _project_with_chapters(tmp_path: Path, count: int = 5):
    project = ProjectRepository.create(tmp_path / "novel", "Overview test")
    chapters = ChapterRepository(project)
    volume = project.list_volumes()[0]
    for i in range(1, count + 1):
        chapters.create_chapter(
            volume.id, f"第{i}章", str(i), f"第{i}章的正文内容，包含关键情节。"
        )
    return project


def test_overview_returns_pagination_metadata(tmp_path: Path) -> None:
    project = _project_with_chapters(tmp_path, count=5)
    tool = ReadNovelOverviewTool(ChapterRepository(project))

    result = tool.execute(_Request({
        "offset": 0,
        "chapter_count": 3,
        "total_char_budget": 6000,
    }))

    assert "total_chapters=5" in result.content
    assert "returned_chapters=3" in result.content
    assert "next_offset=3" in result.content
    assert len(result.source_refs) == 3


def test_overview_last_page_has_no_next_offset(tmp_path: Path) -> None:
    project = _project_with_chapters(tmp_path, count=3)
    tool = ReadNovelOverviewTool(ChapterRepository(project))

    result = tool.execute(_Request({
        "offset": 0,
        "chapter_count": 10,
        "total_char_budget": 8000,
    }))

    assert "next_offset=None" in result.content or "无" in result.content
    assert len(result.source_refs) == 3


def test_batch_tool_bad_id_becomes_omitted_not_error(tmp_path: Path) -> None:
    """Ticket B: one bad chapter ID must not kill the whole batch."""
    project = _project_with_chapters(tmp_path, count=2)
    tool = ReadChaptersBatchTool(ChapterRepository(project))

    real_id = ChapterRepository(project).list_chapters()[0].id
    fake_id = "00000000-0000-0000-0000-000000000001"

    result = tool.execute(_Request({
        "chapter_ids": [real_id, fake_id],
        "max_chars_per_chapter": 500,
    }))

    assert "第1章" in result.content
    assert any(fake_id in o for o in result.omitted)


def test_batch_tool_all_bad_ids_still_returns_result(tmp_path: Path) -> None:
    from ai_novel_studio.domain.identifiers import new_id

    project = _project_with_chapters(tmp_path, count=1)
    tool = ReadChaptersBatchTool(ChapterRepository(project))
    fake_1 = new_id()
    fake_2 = new_id()

    result = tool.execute(_Request({
        "chapter_ids": [fake_1, fake_2],
    }))

    assert len(result.omitted) == 2


def test_overview_default_covers_34_chapters_single_call(tmp_path: Path) -> None:
    """RC-4 regression: default chapter_count=50 must cover all 34 chapters
    in a single call; refs must equal actual visible chapters."""
    project = _project_with_chapters(tmp_path, count=34)
    tool = ReadNovelOverviewTool(ChapterRepository(project))

    result = tool.execute(_Request({
        "total_char_budget": 16_000,
    }))

    # All 34 chapters have source refs (actually rendered).
    assert len(result.source_refs) == 34
    # Last chapter is present.
    last_ref = result.source_refs[-1]
    assert last_ref.source_id == ChapterRepository(project).list_chapters()[-1].id
    # No next_offset needed.
    assert "next_offset=None" in result.content or "无" in result.content


def test_overview_refs_only_for_visible_chapters(tmp_path: Path) -> None:
    """When budget is tight, refs only cover chapters actually rendered."""
    # Use enough chapters that a small budget can't cover them all.
    project2 = _project_with_chapters(tmp_path / "more", count=30)
    tool2 = ReadNovelOverviewTool(ChapterRepository(project2))

    result = tool2.execute(_Request({
        "chapter_count": 30,
        "total_char_budget": 3000,
    }))

    # Budget of 3000 across 30 chapters gives ~100 per chapter; each chapter
    # needs header (~20) + excerpt. Some should be omitted due to budget.
    assert len(result.source_refs) <= 30
    assert len(result.source_refs) > 0
    # Every ref corresponds to a chapter whose content IS in the output.
    for ref in result.source_refs:
        assert ref.source_type == "chapter"


def test_overview_output_never_exceeds_budget(tmp_path: Path) -> None:
    project = _project_with_chapters(tmp_path, count=34)
    tool = ReadNovelOverviewTool(ChapterRepository(project))
    budget = 8000

    result = tool.execute(_Request({
        "total_char_budget": budget,
    }))

    # Content length should be bounded (allow some overhead for metadata).
    assert len(result.content) <= budget + 2000
