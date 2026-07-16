from pathlib import Path

from ai_novel_studio.application.reader_knowledge_summary_service import (
    ReaderKnowledgeSummaryService,
)
from ai_novel_studio.domain.memory import (
    Authority,
    KnowledgeState,
    KnowledgeSubject,
    ReviewStatus,
    SourceType,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _add_reader_fact(
    memory: CharacterMemoryRepository,
    project_id: str,
    chapter_id: str,
    title: str,
    detail: str,
    state: KnowledgeState,
) -> str:
    item = memory.create_knowledge_item(
        title,
        detail,
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    event = memory.append_knowledge_event(
        item.id,
        KnowledgeSubject.READER,
        project_id,
        chapter_id,
        state,
        "正文证据",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    return event.id


def test_reader_summary_is_one_plain_language_time_bounded_card(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "第一章", "1", "body")
    second = chapters.create_chapter(volume.id, "第二章", "2", "body")
    current = chapters.create_chapter(volume.id, "第三章", "3", "body")
    memory = CharacterMemoryRepository(project)
    first_id = _add_reader_fact(
        memory,
        project.project.id,
        first.id,
        "失踪案",
        "读者已经看到兄长在旧港出现。",
        KnowledgeState.KNOWN,
    )
    second_id = _add_reader_fact(
        memory,
        project.project.id,
        second.id,
        "来信者",
        "读者怀疑来信者来自钟楼。",
        KnowledgeState.SUSPECTED,
    )
    _add_reader_fact(
        memory,
        project.project.id,
        second.id,
        "作废线索",
        "读者已经遗忘这条信息。",
        KnowledgeState.FORGOTTEN,
    )
    _add_reader_fact(
        memory,
        project.project.id,
        current.id,
        "当前章秘密",
        "不能提前进入摘要。",
        KnowledgeState.KNOWN,
    )

    summary = ReaderKnowledgeSummaryService(project).summary_before(current.id)

    assert summary is not None
    assert summary.content.startswith("【读者当前知识摘要】")
    assert "读者已经知道：失踪案。读者已经看到兄长在旧港出现。" in summary.content
    assert "读者目前怀疑：来信者。读者怀疑来信者来自钟楼。" in summary.content
    assert summary.content.index("失踪案") < summary.content.index("来信者")
    assert "作废线索" not in summary.content
    assert "当前章秘密" not in summary.content
    assert summary.source_event_ids == (first_id, second_id)
