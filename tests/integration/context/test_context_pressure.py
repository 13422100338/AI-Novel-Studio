from pathlib import Path

from ai_novel_studio.core.context.context_builder import (
    ContextBlock,
    ContextBuilder,
    ContextBuildRequest,
)
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository


class CharacterEstimator:
    def estimate(self, text: str) -> int:
        return len(text)


def test_hundred_chapter_history_remains_retrievable_and_budgeted_as_whole_blocks(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "pressure-project", "压力测试")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    created = tuple(
        chapters.create_chapter(
            volume.id,
            f"第 {index} 章",
            str(index),
            "远古信号首次出现" if index == 1 else f"章节内容 {index}",
        )
        for index in range(1, 106)
    )
    search = SearchRepository(project)
    for chapter in created[:-1]:
        search.index_chapter(chapter.id, chapter.title, chapters.read_content(chapter.id))

    hits = HistoryRetriever(search).search("远古信号", created[-1].id, limit=5)

    assert [hit.chapter_id for hit in hits] == [created[0].id]

    blocks = (
        ContextBlock(
            id="hard-rules",
            category="hard_constraint",
            content="R" * 100,
            priority=0,
            required=True,
            source_type="RULE",
            source_id="rules",
            source_chapter_id=None,
            source_revision=None,
            source_hash="rules-hash",
            rationale="必须保留的写作约束",
        ),
        *tuple(
            ContextBlock(
                id=f"chapter-{index:03d}",
                category="recent_full_chapter" if index >= 102 else "history",
                content=str(index) * 100,
                priority=106 - index,
                required=False,
                source_type="CHAPTER",
                source_id=created[index - 1].id,
                source_chapter_id=created[index - 1].id,
                source_revision=0,
                source_hash=f"hash-{index}",
                rationale="近期全文优先，较早章节使用摘要回退",
                fallback_content=f"摘要-{index}",
            )
            for index in range(1, 105)
        ),
    )
    built = ContextBuilder(CharacterEstimator()).build(
        ContextBuildRequest(
            chapter_id=created[-1].id,
            run_id="pressure-run",
            budget=TokenBudget(1_000, 200, 100),
            blocks=blocks,
        )
    )

    assert built.manifest.estimated_input_tokens <= 700
    assert built.manifest.selected[1].block_id == "chapter-104"
    assert built.manifest.selected[1].used_fallback is False
    assert built.manifest.omitted
    blocks_by_id = {block.id: block for block in blocks}
    for item in built.manifest.selected:
        block = blocks_by_id[item.block_id]
        selected_content = block.fallback_content if item.used_fallback else block.content
        assert selected_content is not None
        assert item.estimated_tokens == len(selected_content)
