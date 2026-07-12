from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ai_novel_studio.application.generation_acceptance_service import (
    GenerationAcceptanceService,
)
from ai_novel_studio.application.generation_context_service import (
    GenerationContextService,
    GenerationPreparationRequest,
)
from ai_novel_studio.application.generation_recovery_service import (
    GenerationRecoveryService,
)
from ai_novel_studio.application.prose_generation_service import ProseGenerationService
from ai_novel_studio.core.context.context_manifest import ContextManifestRepository
from ai_novel_studio.domain.generation import CreationMode, GenerationStatus
from ai_novel_studio.infrastructure.llm import (
    LLMMessage,
    LLMStreamEvent,
    LLMUsage,
    ModelCapabilities,
    StreamEventKind,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    ChapterBriefRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.checkpoint_repository import (
    CheckpointRepository,
)
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class SyntheticGateway:
    def __init__(self, chunks: tuple[str, ...]) -> None:
        self.chunks = chunks
        self.calls: list[tuple[TaskPurpose, tuple[LLMMessage, ...], int]] = []

    def stream(
        self,
        purpose: TaskPurpose,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        *,
        temperature: float = 0.7,
    ) -> Iterator[LLMStreamEvent]:
        self.calls.append((purpose, messages, output_token_limit))
        for chunk in self.chunks:
            yield LLMStreamEvent(StreamEventKind.TEXT, text=chunk)
        yield LLMStreamEvent(
            StreamEventKind.USAGE,
            usage=LLMUsage(input_tokens=12_000, output_tokens=6_000),
        )
        yield LLMStreamEvent(StreamEventKind.PARTIAL_FAILURE, error="synthetic stop")


class PreparedMessages:
    def __init__(self, messages: tuple[LLMMessage, ...]) -> None:
        self.messages = messages

    def messages_for(self, _run_id: str) -> tuple[LLMMessage, ...]:
        return self.messages


def test_phase_5_pipeline_handles_hundred_chapter_pressure_recovery_and_acceptance(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "phase 5 pressure")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    for index in range(1, 106):
        chapters.create_chapter(
            volume.id,
            f"Chapter {index}",
            str(index),
            f"chapter {index} body " * 60,
            synopsis=f"chapter {index} compressed summary",
        )
    current = chapters.create_chapter(volume.id, "Chapter 106", "106", "old formal text")
    requirements = ChapterRequirementRepository(project)
    empty_requirement = requirements.get_or_create(current.id)
    requirements.update(
        current.id,
        "Write the next chapter while preserving the hidden signal clue.",
        is_locked=True,
        expected_revision=empty_requirement.revision,
    )
    briefs = ChapterBriefRepository(project)
    runs = GenerationRepository(project)
    checkpoints = CheckpointRepository(project, runs)
    manifests = ContextManifestRepository(project)
    context = GenerationContextService(
        project,
        chapters,
        requirements,
        briefs,
        runs,
        manifests,
    )
    request = GenerationPreparationRequest(
        chapter_id=current.id,
        mode=CreationMode.BASIC,
        brief_id=None,
        output_token_limit=48_000,
        model_capabilities=ModelCapabilities(
            context_window=70_000,
            max_output_tokens=64_000,
        ),
        target_words=6000,
        model_provider_id="provider",
        model_id="writer",
    )
    prepared = context.prepare(request)

    assert prepared.run.status == GenerationStatus.READY
    assert prepared.manifest.run_id == prepared.run.id
    assert prepared.manifest.selected
    assert prepared.manifest.omitted
    assert prepared.run.output_token_limit == 48_000

    chunks = ("A" * 20, "B" * 20, "C" * 20, "D" * 20, "E" * 20, "F" * 20)
    gateway = SyntheticGateway(chunks)
    prose = ProseGenerationService(
        gateway,
        PreparedMessages(prepared.messages),
        runs,
        checkpoints,
        checkpoint_characters=25,
    )

    events = tuple(prose.stream(prepared.run.id))

    assert gateway.calls[0][0] == TaskPurpose.PROSE_GENERATION
    assert gateway.calls[0][2] == 48_000
    assert events[-2].status == GenerationStatus.PARTIAL
    assert len(checkpoints.list_for_run(prepared.run.id)) >= 3

    recovered = GenerationRecoveryService(runs, checkpoints).scan()
    assert [item.run.id for item in recovered] == [prepared.run.id]
    expected_draft = "".join(chunks)
    assert recovered[0].draft_text == expected_draft

    accepted = GenerationAcceptanceService(project, runs, checkpoints, chapters).accept(
        prepared.run.id,
        expected_chapter_revision=current.revision,
        allow_partial=True,
    )

    assert accepted.run.status == GenerationStatus.ACCEPTED
    assert chapters.read_content(current.id) == expected_draft


def test_package_version_is_phase_7_release() -> None:
    import ai_novel_studio

    assert ai_novel_studio.__version__ == "0.7.0"
