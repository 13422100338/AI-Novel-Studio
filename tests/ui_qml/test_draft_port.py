"""Frontend Wave F4: real draft port over ProjectGenerationSession."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ai_novel_studio.application.project_generation_session import (
    ProjectGenerationSession,
)
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.domain.generation import GenerationStatus
from ai_novel_studio.infrastructure.llm import (
    LLMStreamEvent,
    StreamEventKind,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.llm.config_repository import ModelConfiguration
from ai_novel_studio.infrastructure.llm.provider_profile import (
    ProviderProfile,
    TaskRoutes,
)
from ai_novel_studio.infrastructure.llm.schemas import (
    ModelCapabilities,
    ModelProfile,
    ModelRoute,
)
from ai_novel_studio.infrastructure.llm.usage_tracker import UsageTracker
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository
from ai_novel_studio.ui_qml.bridge.draft_port import (
    GenerationConfig,
    ProjectSessionDraftPort,
)


class StubGateway:
    def __init__(self, events: tuple[LLMStreamEvent, ...]) -> None:
        self.configuration = ModelConfiguration(
            providers=(
                ProviderProfile(
                    id="provider",
                    name="测试连接",
                    base_url="https://example.test/v1",
                    credential_id="cred",
                ),
            ),
            models=(
                ModelProfile(
                    provider_id="provider",
                    model_id="writer",
                    capabilities=ModelCapabilities(
                        context_window=32_000,
                        max_output_tokens=16_000,
                        streaming=True,
                    ),
                ),
            ),
            routes=TaskRoutes(
                plot=None,
                prose=ModelRoute(provider_id="provider", model_id="writer"),
            ),
        )
        self.events = events
        self.stream_calls: list[TaskPurpose] = []
        self.usage_tracker = UsageTracker()

    def stream(
        self,
        purpose: TaskPurpose,
        messages: tuple[object, ...],
        output_token_limit: int,
        **_: object,
    ) -> Iterator[LLMStreamEvent]:
        self.stream_calls.append(purpose)
        yield from self.events


def _session(
    tmp_path: Path,
    events: tuple[LLMStreamEvent, ...],
) -> tuple[ProjectGenerationSession, str, int]:
    project = ProjectRepository.create(tmp_path / "project", "生成测试")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(volume.id, "第一章 起风", "第 1 章", "旧正文")
    requirements = ChapterRequirementRepository(project)
    requirement = requirements.get_or_create(chapter.id)
    requirements.update(
        chapter.id,
        "写雨夜相认",
        is_locked=False,
        expected_revision=requirement.revision,
    )
    gateway = StubGateway(events)
    session = ProjectGenerationSession(
        project,
        gateway,  # type: ignore[arg-type]
        HistoryRetriever(SearchRepository(project)),
    )
    return session, chapter.id, chapter.revision


def _completed_events() -> tuple[LLMStreamEvent, ...]:
    return (
        LLMStreamEvent(StreamEventKind.TEXT, text="雨夜的码头，"),
        LLMStreamEvent(StreamEventKind.TEXT, text="灯影在水面上碎成一片。"),
        LLMStreamEvent(StreamEventKind.COMPLETED),
    )


def test_full_generation_accept_cycle_persists_draft(tmp_path: Path) -> None:
    session, chapter_id, revision = _session(tmp_path, _completed_events())
    port = ProjectSessionDraftPort(session)

    run_id = port.prepare(chapter_id, revision, GenerationConfig(target_words=800))
    draft_text, error = port.generate(run_id)

    assert error == ""
    assert draft_text == "雨夜的码头，灯影在水面上碎成一片。"
    assert session.runs.get(run_id).status == GenerationStatus.COMPLETED

    accepted = port.accept_current()

    assert accepted.text == draft_text
    assert accepted.chapter_revision == revision + 1
    assert session.runs.get(run_id).status == GenerationStatus.ACCEPTED
    # The chapter on disk now contains the accepted draft.
    project = session.project
    chapters = ChapterRepository(project)
    workspace = chapters.get_chapter(
        chapter_id,
        include_deleted=False,
    )
    assert chapters.read_content(chapter_id) == draft_text
    assert workspace.revision == revision + 1


def test_discard_marks_run_discarded(tmp_path: Path) -> None:
    session, chapter_id, revision = _session(tmp_path, _completed_events())
    port = ProjectSessionDraftPort(session)

    run_id = port.prepare(chapter_id, revision, GenerationConfig(target_words=800))
    assert port.discard_current() is True

    assert session.runs.get(run_id).status == GenerationStatus.DISCARDED


def test_generate_partial_failure_returns_draft_and_error(tmp_path: Path) -> None:
    events = (
        LLMStreamEvent(StreamEventKind.TEXT, text="只生成了一半。"),
        LLMStreamEvent(StreamEventKind.PARTIAL_FAILURE, error="provider timed out"),
    )
    session, chapter_id, revision = _session(tmp_path, events)
    port = ProjectSessionDraftPort(session)

    run_id = port.prepare(chapter_id, revision, GenerationConfig(target_words=800))
    draft_text, error = port.generate(run_id)

    assert draft_text == "只生成了一半。"
    assert error != ""
    assert session.runs.get(run_id).status == GenerationStatus.PARTIAL


def test_discard_without_run_is_false(tmp_path: Path) -> None:
    session, chapter_id, revision = _session(tmp_path, _completed_events())
    port = ProjectSessionDraftPort(session)

    assert port.discard_current() is False


def test_usage_snapshot_mirrors_tracker(tmp_path: Path) -> None:
    session, chapter_id, revision = _session(tmp_path, _completed_events())
    port = ProjectSessionDraftPort(session)

    usage = port.usage_snapshot()

    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.cost == 0
    assert usage.call_count == 0
