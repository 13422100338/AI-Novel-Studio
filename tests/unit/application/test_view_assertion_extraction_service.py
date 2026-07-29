import json
from pathlib import Path

import pytest

from ai_novel_studio.application.view_assertion_extraction_service import (
    ViewAssertionExtractionService,
)
from ai_novel_studio.application.view_assertion_service import (
    ViewAssertionExtractionError,
)
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType
from ai_novel_studio.infrastructure.llm.contract_runner import LLMContractRunner
from ai_novel_studio.infrastructure.llm.schemas import LLMResponse, TaskPurpose
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
)


class _Gateway:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[TaskPurpose] = []

    def complete(self, purpose, messages, output_token_limit, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(purpose)
        return LLMResponse(self.responses.pop(0), "test-model")


class _ChapterMutatingGateway(_Gateway):
    def __init__(self, responses: list[str], project: ProjectRepository, chapter_id: str) -> None:
        super().__init__(responses)
        self._project = project
        self._chapter_id = chapter_id

    def complete(self, purpose, messages, output_token_limit, **kwargs):  # type: ignore[no-untyped-def]
        if not self.calls:
            ChapterRepository(self._project).save_content(
                self._chapter_id,
                "Changed while the model request was in flight.",
                source="test",
                reason="concurrency test",
            )
        return super().complete(purpose, messages, output_token_limit, **kwargs)


def _project(tmp_path: Path) -> tuple[ProjectRepository, str, str, str]:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    chapters.create_chapter(volume.id, "First", "1", "Earlier")
    chapter = chapters.create_chapter(volume.id, "Second", "2", "Chapter body")
    characters = CharacterMemoryRepository(project)
    subject = characters.create_character("Subject")
    viewer = characters.create_character("Viewer")
    return project, chapter.id, subject.id, viewer.id


def _payload(*, subject_id: str, viewer_id: str) -> str:
    return json.dumps(
        {
            "assertions": [
                {
                    "subject_id": subject_id,
                    "view_type": "CHARACTER_VIEW",
                    "viewer_subject_id": viewer_id,
                    "epistemic_status": "KNOWS",
                    "content": "The viewer saw the subject leave the archive.",
                },
                {
                    "subject_id": subject_id,
                    "view_type": "READER_VIEW",
                    "content": "The reader has seen the archive clue.",
                },
            ]
        }
    )


def test_extracts_validated_model_candidates_with_deterministic_provenance(
    tmp_path: Path,
) -> None:
    project, chapter_id, subject_id, viewer_id = _project(tmp_path)
    gateway = _Gateway([_payload(subject_id=subject_id, viewer_id=viewer_id)])

    result = ViewAssertionExtractionService(LLMContractRunner(gateway)).extract(
        project, chapter_id
    )

    assert gateway.calls == [TaskPurpose.MEMORY_EXTRACTION]
    assert len(result) == 2
    assert {item.authority for item in result} == {Authority.MODEL_EXTRACTED}
    assert {item.review_status for item in result} == {ReviewStatus.REVIEW}
    assert {item.source_type for item in result} == {SourceType.MODEL}
    assert {item.source_id for item in result} == {chapter_id}
    assert {item.source_revision for item in result} == {0}
    assert {item.narrative_visible_from_sequence for item in result} == {3}


def test_rejects_source_revision_change_during_model_call_without_writing(
    tmp_path: Path,
) -> None:
    project, chapter_id, subject_id, viewer_id = _project(tmp_path)
    gateway = _ChapterMutatingGateway(
        [_payload(subject_id=subject_id, viewer_id=viewer_id)], project, chapter_id
    )

    with pytest.raises(ViewAssertionExtractionError, match="来源章节"):
        ViewAssertionExtractionService(LLMContractRunner(gateway)).extract(project, chapter_id)

    assert ViewAssertionRepository(project).list_model_review_candidates() == ()


@pytest.mark.parametrize(
    "payload",
    [
        '{"assertions": [{"subject_id": "unknown", "view_type": "READER_VIEW", "content": "x"}]}',
        (
            '{"assertions": [{"subject_id": "unknown", '
            '"view_type": "CHARACTER_VIEW", "content": "x"}]}'
        ),
    ],
)
def test_rejects_invalid_output_without_creating_candidates(
    tmp_path: Path, payload: str
) -> None:
    project, chapter_id, _, _ = _project(tmp_path)
    gateway = _Gateway([payload, payload])

    with pytest.raises(ValueError):
        ViewAssertionExtractionService(LLMContractRunner(gateway)).extract(project, chapter_id)

    assert gateway.calls == [TaskPurpose.MEMORY_EXTRACTION, TaskPurpose.MEMORY_EXTRACTION]
    assert ViewAssertionRepository(project).list_model_review_candidates() == ()


def test_rejects_candidate_count_above_bound_without_writing(tmp_path: Path) -> None:
    project, chapter_id, subject_id, _ = _project(tmp_path)
    payload = json.dumps(
        {
            "assertions": [
                {
                    "subject_id": subject_id,
                    "view_type": "READER_VIEW",
                    "content": f"candidate {index}",
                }
                for index in range(13)
            ]
        }
    )
    gateway = _Gateway([payload, payload])

    with pytest.raises(ValueError, match="at most"):
        ViewAssertionExtractionService(LLMContractRunner(gateway)).extract(project, chapter_id)

    assert ViewAssertionRepository(project).list_model_review_candidates() == ()


@pytest.mark.parametrize(
    "item",
    [
        {
            "view_type": "CHARACTER_VIEW",
            "content": "Missing required viewer and epistemic status.",
        },
        {
            "view_type": "READER_VIEW",
            "content": "Inverted range.",
            "valid_from_sequence": 4,
            "valid_to_sequence": 2,
        },
    ],
)
def test_rejects_invalid_view_shape_or_range_without_writing(
    tmp_path: Path, item: dict[str, object]
) -> None:
    project, chapter_id, subject_id, _ = _project(tmp_path)
    payload_item = {"subject_id": subject_id, **item}
    payload = json.dumps({"assertions": [payload_item]})
    gateway = _Gateway([payload, payload])

    with pytest.raises(ValueError):
        ViewAssertionExtractionService(LLMContractRunner(gateway)).extract(project, chapter_id)

    assert gateway.calls == [TaskPurpose.MEMORY_EXTRACTION, TaskPurpose.MEMORY_EXTRACTION]
    assert ViewAssertionRepository(project).list_model_review_candidates() == ()
