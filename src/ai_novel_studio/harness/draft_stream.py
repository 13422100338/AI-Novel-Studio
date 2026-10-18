from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.harness.artifacts import Artifact, ArtifactKind, ArtifactStore
from ai_novel_studio.harness.cancel_token import CancelToken
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.model_adapter import HarnessModelAdapter
from ai_novel_studio.harness.model_roles import ModelRole
from ai_novel_studio.harness.run_state import HarnessRun, RunEventType, RunStage
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMMessage,
    LLMUsage,
    StreamEventKind,
)

DEFAULT_CHECKPOINT_CHARS = 2_000


class DraftStreamFailureError(RuntimeError):
    """The chapter draft stream failed or produced no prose."""


@dataclass(frozen=True, slots=True)
class DraftCandidateResult:
    """Complete draft candidate produced by the chapter draft stream (§42)."""

    artifact: Artifact
    text: str
    usage: LLMUsage | None


class ChapterDraftStreamService:
    """Harness-owned chapter draft candidate stream (design v0.3 §42, §47, §54).

    Streams the CHAPTER_DRAFT role through the run-frozen adapter, appends
    the CHAPTER_STREAM_* run events,     saves deterministic character-count
    checkpoints as DRAFT_CHECKPOINT artifacts (§53.1), and stores the
    complete draft as a DRAFT_CANDIDATE. Reasoning deltas are never
    persisted (design §65). Cancellation and failure save the non-empty
    partial draft as PARTIAL_DRAFT before re-raising; a cancelled run is
    closed, so late stream events are rejected by the event store
    (design §54, §64).
    """

    def __init__(
        self,
        store: HarnessEventStore,
        artifacts: ArtifactStore,
        adapter: HarnessModelAdapter,
        *,
        checkpoint_chars: int = DEFAULT_CHECKPOINT_CHARS,
    ) -> None:
        if checkpoint_chars <= 0:
            raise ValueError("checkpoint_chars must be positive")
        self._store = store
        self._artifacts = artifacts
        self._adapter = adapter
        self._checkpoint_chars = checkpoint_chars

    def __call__(
        self,
        run: HarnessRun,
        token: CancelToken,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
    ) -> DraftCandidateResult:
        if not messages:
            raise ValueError("draft stream messages cannot be empty")
        if not 1 <= output_token_limit <= 200_000:
            raise ValueError("output token limit must be between 1 and 200000")
        self._store.append(
            run.id,
            RunEventType.CHAPTER_STREAM_STARTED,
            {
                "chapter_id": run.active_chapter_id,
                "output_token_limit": output_token_limit,
                "message_count": len(messages),
            },
        )
        text_parts: list[str] = []
        usage: LLMUsage | None = None
        last_checkpoint = 0
        try:
            for event in self._adapter.stream(
                ModelRole.CHAPTER_DRAFT, messages, output_token_limit
            ):
                token.raise_if_cancelled()
                if event.kind is StreamEventKind.TEXT:
                    text_parts.append(event.text)
                    length = sum(len(part) for part in text_parts)
                    # Design §67: full delta text never enters the event table;
                    # it lives only in the DRAFT_CHECKPOINT artifacts. The
                    # payload carries counts (schema_version 2 contract for
                    # CHAPTER_STREAM_DELTA events; the table is unchanged).
                    self._store.append(
                        run.id,
                        RunEventType.CHAPTER_STREAM_DELTA,
                        {
                            "delta_length": len(event.text),
                            "cumulative_chars": length,
                        },
                        schema_version=2,
                    )
                    if length - last_checkpoint >= self._checkpoint_chars:
                        last_checkpoint = length
                        self._checkpoint(run, "".join(text_parts))
                elif event.kind is StreamEventKind.USAGE:
                    if event.usage is not None:
                        usage = event.usage
                elif event.kind is StreamEventKind.COMPLETED:
                    if event.usage is not None:
                        usage = event.usage
                elif event.kind is StreamEventKind.PARTIAL_FAILURE:
                    raise DraftStreamFailureError(
                        event.error or "chapter draft stream failed"
                    )
                # REASONING deltas are never persisted (design §65)
            text = "".join(text_parts)
            if not text.strip():
                raise DraftStreamFailureError("chapter draft model produced no prose")
            token.raise_if_cancelled()
        except Exception:
            partial = "".join(text_parts)
            if partial.strip():
                self._artifacts.put(
                    ArtifactKind.PARTIAL_DRAFT, run.id, partial.encode("utf-8")
                )
            raise
        artifact = self._artifacts.put(
            ArtifactKind.DRAFT_CANDIDATE, run.id, text.encode("utf-8")
        )
        self._store.append(
            run.id,
            RunEventType.CHAPTER_STREAM_COMPLETED,
            {
                "artifact_id": artifact.artifact_id,
                "character_count": len(text),
                "input_tokens": usage.input_tokens if usage else None,
                "output_tokens": usage.output_tokens if usage else None,
            },
        )
        self._store.transition(run.id, RunStage.DRAFT_SAVED)
        return DraftCandidateResult(artifact=artifact, text=text, usage=usage)

    def _checkpoint(self, run: HarnessRun, text: str) -> None:
        artifact = self._artifacts.put(
            ArtifactKind.DRAFT_CHECKPOINT, run.id, text.encode("utf-8")
        )
        self._store.append(
            run.id,
            RunEventType.CHAPTER_STREAM_CHECKPOINT_SAVED,
            {"artifact_id": artifact.artifact_id, "character_count": len(text)},
        )
