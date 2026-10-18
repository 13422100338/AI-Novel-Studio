import hashlib
from uuid import uuid4

import pytest

from ai_novel_studio.application.novel_read_service import NovelReadService
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@pytest.fixture
def novel(tmp_path):
    project = ProjectRepository.create(tmp_path / "novel", "批量阅读测试")
    repository = ChapterRepository(project)
    chapters = [
        repository.create_chapter(
            project.list_volumes()[0].id, f"第{i}章", str(i), f"正式正文{i}。" * 10
        )
        for i in range(1, 35)
    ]
    return NovelReadService(project), repository, chapters


def test_whole_novel_and_requested_range_are_read_in_one_request(novel):
    reader, repository, chapters = novel
    result = reader.call("read_novel_chapters")
    assert result["domain_kind"] == "FORMAL_MANUSCRIPT"
    assert result["chapter_count"] == 34
    assert result["next_cursor"] is None and not result["truncated"]
    assert [entry["chapter_id"] for entry in result["chapters"]] == [
        chapter.id for chapter in chapters
    ]
    for entry in result["chapters"]:
        text = repository.read_content_exact(entry["chapter_id"])
        assert entry["content"] == text
        assert entry["source_hash"] == hashlib.sha256(text.encode()).hexdigest()
    selected = reader.call("read_novel_chapters", offset=5, limit=3)
    assert [entry["chapter_id"] for entry in selected["chapters"]] == [
        chapter.id for chapter in chapters[5:8]
    ]


def test_explicit_chapters_preserve_book_order_and_never_return_others(novel):
    reader, repository, chapters = novel
    result = reader.call("read_novel_chapters", chapter_ids=[chapters[8].id, chapters[2].id])
    assert [entry["chapter_id"] for entry in result["chapters"]] == [chapters[2].id, chapters[8].id]


def test_bounded_batches_can_resume_without_missing_or_repeating_text(novel):
    reader, repository, chapters = novel
    parts = {chapters[0].id: [], chapters[1].id: []}
    cursor = {}
    for _ in range(40):
        result = reader.call("read_novel_chapters", limit=2, max_chars=13, **cursor)
        assert result["chars_read"] <= 13
        for entry in result["chapters"]:
            parts[entry["chapter_id"]].append(entry["content"])
        if result["next_cursor"] is None:
            break
        cursor = result["next_cursor"]
    else:
        pytest.fail("cursor did not finish")
    for chapter in chapters[:2]:
        assert "".join(parts[chapter.id]) == repository.read_content_exact(chapter.id)


@pytest.mark.parametrize(
    "params",
    [
        dict(chapter_ids=[str(uuid4())]),
        dict(chapter_ids=["../secret"]),
        dict(offset=True),
        dict(max_chars=1_000_000),
        dict(limit=0),
        dict(cursor_start=1_000_000),
        dict(chapter_ids=[]),
    ],
)
def test_invalid_selection_and_limits_are_rejected(novel, params):
    reader, repository, chapters = novel
    with pytest.raises((ValueError, KeyError)):
        reader.call("read_novel_chapters", **params)
