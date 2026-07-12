from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.audit import (
    AuditFindingStatus,
    AuditRunStatus,
    AuditSeverity,
    AuditTargetKind,
)
from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.domain.generation import (
    CreationMode,
    GenerationCheckpoint,
    GenerationRun,
    GenerationStatus,
)
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.checkpoint_repository import CheckpointRepository
from ai_novel_studio.infrastructure.storage.generation_repository import (
    GenerationRepository,
    GenerationStateError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class GenerationAcceptanceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AcceptedGeneration:
    run: GenerationRun
    chapter: Chapter
    checkpoint: GenerationCheckpoint


class GenerationAcceptanceService:
    def __init__(
        self,
        project: ProjectRepository,
        runs: GenerationRepository | None = None,
        checkpoints: CheckpointRepository | None = None,
        chapters: ChapterRepository | None = None,
        audits: AuditRepository | None = None,
    ) -> None:
        self.project = project
        self.runs = runs or GenerationRepository(project)
        self.checkpoints = checkpoints or CheckpointRepository(project, self.runs)
        self.chapters = chapters or ChapterRepository(project)
        self.audits = audits or AuditRepository(project)

    def accept(
        self,
        run_id: str,
        expected_chapter_revision: int,
        *,
        allow_partial: bool = False,
    ) -> AcceptedGeneration:
        run = self.runs.get(run_id)
        self._validate_acceptance_status(run.status, allow_partial=allow_partial)
        checkpoint = self.checkpoints.latest(run.id)
        if checkpoint is None:
            raise GenerationAcceptanceError("generation run has no checkpoint to accept")
        draft = self.checkpoints.read(checkpoint.id)
        self._validate_strict_audit(run, checkpoint)
        chapter = self.chapters.save_content(
            run.chapter_id,
            draft,
            source="ai_generation",
            reason=f"accepted generation run {run.id}",
            expected_revision=expected_chapter_revision,
        )
        accepted = self.runs.transition(
            run.id,
            run.status,
            GenerationStatus.ACCEPTED,
            accepted_chapter_revision=chapter.revision,
        )
        return AcceptedGeneration(accepted, chapter, checkpoint)

    def discard(self, run_id: str) -> GenerationRun:
        run = self.runs.get(run_id)
        if run.status in {GenerationStatus.ACCEPTED, GenerationStatus.DISCARDED}:
            raise GenerationStateError(
                f"generation run is already terminal: {run.status.value}"
            )
        return self.runs.transition(run.id, run.status, GenerationStatus.DISCARDED)

    def _validate_strict_audit(
        self, run: GenerationRun, checkpoint: GenerationCheckpoint
    ) -> None:
        if run.mode != CreationMode.STRICT:
            return
        runs = self.audits.list_runs_for_target(
            target_kind=AuditTargetKind.GENERATED_DRAFT,
            target_id=run.id,
        )
        completed = tuple(
            audit_run
            for audit_run in runs
            if audit_run.status == AuditRunStatus.COMPLETED
            and audit_run.target_hash == checkpoint.content_hash
        )
        if not completed:
            raise GenerationAcceptanceError(
                "strict generation requires a completed audit for the current draft"
            )
        blockers = [
            finding
            for audit_run in completed
            for finding in self.audits.list_findings(audit_run.id)
            if finding.status == AuditFindingStatus.OPEN
            and finding.severity in {AuditSeverity.ERROR, AuditSeverity.BLOCKER}
        ]
        if blockers:
            raise GenerationAcceptanceError(
                "strict generation has blocking audit findings"
            )

    @staticmethod
    def _validate_acceptance_status(
        status: GenerationStatus, *, allow_partial: bool
    ) -> None:
        if status == GenerationStatus.ACCEPTED:
            raise GenerationAcceptanceError("generation run is already accepted")
        if status == GenerationStatus.DISCARDED:
            raise GenerationAcceptanceError("generation run is discarded")
        if status == GenerationStatus.PARTIAL and allow_partial:
            return
        if status == GenerationStatus.PARTIAL:
            raise GenerationAcceptanceError(
                "partial generation requires explicit allow_partial=True"
            )
        if status != GenerationStatus.COMPLETED:
            raise GenerationAcceptanceError(
                f"generation run cannot be accepted from {status.value}"
            )
