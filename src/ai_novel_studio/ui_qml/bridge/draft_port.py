"""Draft generation port for the QML facade.

Frontend Wave F4 wires the AI drawer candidate layer to the real generation
session and acceptance service. The port keeps the facade independent of any
specific model runtime: tests inject a deterministic fake port, while the
production implementation wraps ``ProjectGenerationSession`` (and therefore
``GenerationAcceptanceService``) unchanged.

Note: ``ProjectSessionDraftPort.generate`` consumes the prose stream
synchronously. A background-task coordinator (frontend-owned, mirroring the
``ui/qt`` pattern without importing it) is a recorded follow-up so model calls
never block the UI thread.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from ai_novel_studio.application.project_generation_session import (
    AcceptedGeneration,
    ProjectGenerationSession,
)
from ai_novel_studio.application.prose_generation_service import (
    ProseEventKind,
    ProseGenerationEvent,
)
from ai_novel_studio.domain.generation import AuditPolicy, CreationMode, GenerationStatus
from ai_novel_studio.ui_qml.bridge.dtos import UsageDto

_DEFAULT_OUTPUT_TOKEN_LIMIT = 8192


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    """Presentation-layer generation options forwarded to the draft port.

    Values are validated by the facade setters; the port applies them verbatim
    through ``ProjectGenerationSession.prepare_generation``.
    """

    target_words: int = 800
    output_token_limit: int = _DEFAULT_OUTPUT_TOKEN_LIMIT
    mode: CreationMode = CreationMode.BASIC
    audit_policy: AuditPolicy = AuditPolicy.MINIMAL


class DraftPort(Protocol):
    """High-level generation operations the facade can invoke.

    Implementations own the full lifecycle: prepare a run, produce the draft
    text, accept it through the safe acceptance service, or discard it.
    """

    def prepare(
        self,
        chapter_id: str,
        revision: int,
        config: GenerationConfig,
    ) -> str: ...

    def generate(self, run_id: str) -> tuple[str, str]: ...

    def cancel(self, run_id: str) -> None: ...

    def usage_snapshot(self) -> UsageDto: ...

    def accept_current(self) -> AcceptedGeneration: ...

    def discard_current(self) -> bool: ...


class ProjectSessionDraftPort:
    """Production draft port backed by the framework-neutral generation session."""

    def __init__(self, session: ProjectGenerationSession) -> None:
        self.session = session

    def prepare(
        self,
        chapter_id: str,
        revision: int,
        config: GenerationConfig,
    ) -> str:
        self.session.select_chapter(chapter_id, revision)
        return self.session.prepare_generation(
            config.mode,
            config.output_token_limit,
            config.target_words,
            config.audit_policy,
        )

    def generate(self, run_id: str) -> tuple[str, str]:
        """Consume the prose stream to completion and return (draft, error)."""
        buffer: list[str] = []
        error = ""
        completed = False
        try:
            events: Iterator[ProseGenerationEvent] = self.session.prose.stream(run_id)
            for event in events:
                if event.kind is ProseEventKind.DRAFT_CHUNK:
                    buffer.append(event.text)
                elif event.kind is ProseEventKind.RUN_CHANGED:
                    if event.status is GenerationStatus.COMPLETED:
                        completed = True
                elif event.kind is ProseEventKind.FAILED:
                    error = event.message
        except (KeyError, RuntimeError, ValueError) as exc:
            return "".join(buffer), str(exc)
        text = "".join(buffer)
        if error:
            return text, error
        if not completed:
            return text, "生成未完成，请稍后重试"
        return text, ""

    def cancel(self, run_id: str) -> None:
        """Ask the underlying prose service to cancel the stream cooperatively."""
        self.session.prose.cancel(run_id)

    def usage_snapshot(self) -> UsageDto:
        """Mirror the real gateway usage tracker totals as a presentation DTO."""
        snapshot = self.session.gateway.usage_tracker.snapshot()
        return UsageDto(
            input_tokens=snapshot.input_tokens,
            output_tokens=snapshot.output_tokens,
            cached_input_tokens=snapshot.cached_input_tokens,
            cost=snapshot.cost,
            call_count=snapshot.call_count,
            failed_call_count=snapshot.failed_call_count,
            cache_known=snapshot.cache_known,
        )

    def accept_current(self) -> AcceptedGeneration:
        return self.session.accept_current()

    def discard_current(self) -> bool:
        return self.session.discard_current()
