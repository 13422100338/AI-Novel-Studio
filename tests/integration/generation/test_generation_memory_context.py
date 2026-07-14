from pathlib import Path

from ai_novel_studio.application.chapter_context_pin_service import (
    ChapterContextPinService,
)
from ai_novel_studio.application.generation_context_service import (
    GenerationContextService,
    GenerationPreparationRequest,
)
from ai_novel_studio.application.project_memory_workspace_gateway import (
    ProjectMemoryWorkspaceGateway,
)
from ai_novel_studio.core.context.context_manifest import ContextManifestRepository
from ai_novel_studio.domain.generation import CreationMode
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType, SummaryLevel
from ai_novel_studio.infrastructure.llm import ModelCapabilities
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    ChapterBriefRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_context_pin_repository import (
    ChapterContextPinRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


def test_basic_generation_includes_relevant_state_and_compressed_history(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "Opening", "1", "Eric found the sealed map.")
    chapters.create_chapter(volume.id, "Recent", "2", "Eric hid the map from Mara.")
    current = chapters.create_chapter(volume.id, "Visit", "3")

    requirements = ChapterRequirementRepository(project)
    initial = requirements.get_or_create(current.id)
    requirements.update(
        current.id,
        "Eric meets Mara but must not reveal the sealed map.",
        is_locked=True,
        expected_revision=initial.revision,
    )
    character_memory = CharacterMemoryRepository(project)
    eric = character_memory.create_character("Eric")
    character_memory.append_state(
        eric.id,
        first.id,
        motivation="Protect the map",
        psychology="Suspicious but composed",
        current_goal="Learn why Mara arrived",
        relationships="Does not yet trust Mara",
        recent_activity="Found and concealed the map",
        confidence=1.0,
        source_type=SourceType.HUMAN,
        review_status=ReviewStatus.APPROVED,
    )
    summary = SummaryRepository(project).add_human_summary(
        SummaryLevel.CHAPTER,
        first.id,
        "Eric found a sealed map and chose to hide it.",
        (first.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    summary_record = next(
        record
        for record in ProjectMemoryWorkspaceGateway(project).load_before("__all__")
        if record.id == summary.id
    )
    ChapterContextPinService(ChapterContextPinRepository(project)).pin(
        current.id, summary_record
    )

    service = GenerationContextService(
        project,
        chapters,
        requirements,
        ChapterBriefRepository(project),
        GenerationRepository(project),
        ContextManifestRepository(project),
    )
    prepared = service.prepare(
        GenerationPreparationRequest(
            chapter_id=current.id,
            mode=CreationMode.BASIC,
            brief_id=None,
            output_token_limit=8_000,
            model_capabilities=ModelCapabilities(
                context_window=128_000,
                max_output_tokens=16_000,
            ),
            target_words=3_500,
            model_provider_id="provider",
            model_id="writer",
        )
    )

    selected_types = {item.source_type for item in prepared.manifest.selected}
    assert "CHARACTER_STATE" in selected_types
    assert "SUMMARY" in selected_types
    assert "MANUAL_PIN/SUMMARY" in selected_types
    assert "Protect the map" in prepared.messages[5].content
    assert "Eric found a sealed map" in prepared.messages[6].content
    assert "人工固定记忆" in prepared.messages[6].content
