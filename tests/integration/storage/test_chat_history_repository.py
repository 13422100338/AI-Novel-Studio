from ai_novel_studio.application.chat_context_service import ChatContextService
from ai_novel_studio.infrastructure.storage.chat_history_repository import (
    ChatHistoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def test_project_chat_history_survives_reopen_and_preserves_original_messages(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    root = tmp_path / "novel"
    project = ProjectRepository.create(root, "Chat History")
    repository = ChatHistoryRepository(project)
    session = repository.get_or_create_default()
    repository.append(session.id, "user", "讨论开场", chapter_id=None)
    repository.append(session.id, "assistant", "建议从雨夜开始", chapter_id=None)
    repository.update_summary(
        session.id,
        "已确认从雨夜开始。",
        through_sequence=0,
        expected_revision=0,
    )

    reopened = ProjectRepository.open(root)
    reopened_repository = ChatHistoryRepository(reopened)
    restored = reopened_repository.get_or_create_default()

    assert restored.summary == "已确认从雨夜开始。"
    assert [item.content for item in reopened_repository.list_messages(restored.id)] == [
        "讨论开场",
        "建议从雨夜开始",
    ]


def test_dynamic_chat_context_keeps_summary_and_recent_full_messages(tmp_path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Chat Context")
    repository = ChatHistoryRepository(project)
    session = repository.get_or_create_default()
    for index in range(8):
        repository.append(
            session.id,
            "user" if index % 2 == 0 else "assistant",
            f"第 {index} 条消息 " + "内容" * 30,
            chapter_id=None,
        )
    session = repository.update_summary(
        session.id,
        "早期讨论确认了主角必须前往旧港。",
        through_sequence=3,
        expected_revision=0,
    )

    selection = ChatContextService().select(
        session,
        repository.list_messages(session.id),
        token_budget=150,
    )

    assert selection.messages[0].role == "system"
    assert "旧港" in selection.messages[0].content
    assert selection.included_sequences
    assert selection.included_sequences[-1] == 7
    assert selection.omitted_messages > 0
    assert len(repository.list_messages(session.id)) == 8

    candidate = ChatContextService().compression_candidate(
        session,
        repository.list_messages(session.id),
        retain_recent_tokens=40,
        minimum_source_tokens=20,
    )
    assert candidate is not None
    assert candidate.through_sequence < 7
    assert "第 4 条消息" in candidate.transcript
