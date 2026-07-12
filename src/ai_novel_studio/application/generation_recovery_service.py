from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.generation import (
    GenerationCheckpoint,
    GenerationRun,
    GenerationStatus,
)
from ai_novel_studio.infrastructure.storage.checkpoint_repository import CheckpointRepository
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository

RECOVERABLE_GENERATION_STATUSES = (
    GenerationStatus.PREPARING,
    GenerationStatus.READY,
    GenerationStatus.STREAMING,
    GenerationStatus.PARTIAL,
)


@dataclass(frozen=True, slots=True)
class RecoverableGeneration:
    run: GenerationRun
    latest_checkpoint: GenerationCheckpoint | None
    draft_text: str | None


class GenerationRecoveryService:
    def __init__(
        self,
        runs: GenerationRepository,
        checkpoints: CheckpointRepository,
    ) -> None:
        self.runs = runs
        self.checkpoints = checkpoints

    def scan(self) -> tuple[RecoverableGeneration, ...]:
        recovered: list[RecoverableGeneration] = []
        for run in self.runs.list_by_statuses(RECOVERABLE_GENERATION_STATUSES):
            checkpoint = self.checkpoints.latest(run.id)
            draft_text = self.checkpoints.read(checkpoint.id) if checkpoint else None
            recovered.append(
                RecoverableGeneration(
                    run=run,
                    latest_checkpoint=checkpoint,
                    draft_text=draft_text,
                )
            )
        return tuple(recovered)
