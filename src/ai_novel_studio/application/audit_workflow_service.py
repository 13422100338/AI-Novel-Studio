from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ai_novel_studio.application.deterministic_audit_service import (
    DeterministicAuditRequest,
    DeterministicAuditService,
)
from ai_novel_studio.domain.audit import (
    AuditFinding,
    AuditRun,
    AuditRunStatus,
    AuditTargetKind,
)
from ai_novel_studio.domain.generation import AuditPolicy, CreationMode
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)

DETERMINISTIC_AUDIT_PROMPT_VERSION = "deterministic-audit-v1"


@dataclass(frozen=True, slots=True)
class AuditWorkflowResult:
    run: AuditRun
    findings: tuple[AuditFinding, ...]


class AuditWorkflowService:
    def __init__(
        self,
        chapters: ChapterRepository,
        requirements: ChapterRequirementRepository,
        audits: AuditRepository,
        deterministic: DeterministicAuditService | None = None,
    ) -> None:
        self.chapters = chapters
        self.requirements = requirements
        self.audits = audits
        self.deterministic = deterministic or DeterministicAuditService()

    def run_deterministic_for_formal_chapter(
        self,
        chapter_id: str,
        *,
        mode: CreationMode,
        audit_policy: AuditPolicy = AuditPolicy.MINIMAL,
        requirement_content: str | None = None,
    ) -> AuditWorkflowResult:
        chapter = self.chapters.get_chapter(chapter_id, include_deleted=False)
        text = self.chapters.read_content(chapter_id)
        return self._run_deterministic(
            chapter_id=chapter_id,
            target_kind=AuditTargetKind.FORMAL_CHAPTER,
            target_id=chapter_id,
            target_text=text,
            target_revision=chapter.revision,
            mode=mode,
            audit_policy=audit_policy,
            requirement_content=requirement_content,
        )

    def run_deterministic_for_draft(
        self,
        *,
        chapter_id: str,
        generation_run_id: str,
        draft_text: str,
        base_chapter_revision: int,
        mode: CreationMode,
        audit_policy: AuditPolicy = AuditPolicy.MINIMAL,
        requirement_content: str | None = None,
    ) -> AuditWorkflowResult:
        return self._run_deterministic(
            chapter_id=chapter_id,
            target_kind=AuditTargetKind.GENERATED_DRAFT,
            target_id=generation_run_id,
            target_text=draft_text,
            target_revision=base_chapter_revision,
            mode=mode,
            audit_policy=audit_policy,
            requirement_content=requirement_content,
        )

    def _run_deterministic(
        self,
        *,
        chapter_id: str,
        target_kind: AuditTargetKind,
        target_id: str,
        target_text: str,
        target_revision: int,
        mode: CreationMode,
        audit_policy: AuditPolicy,
        requirement_content: str | None,
    ) -> AuditWorkflowResult:
        target_hash = _hash(target_text)
        run = self.audits.create_run(
            chapter_id=chapter_id,
            target_kind=target_kind,
            target_id=target_id,
            target_revision=target_revision,
            target_hash=target_hash,
            mode=mode,
            audit_policy=audit_policy,
            status=AuditRunStatus.PREPARING,
            prompt_version=DETERMINISTIC_AUDIT_PROMPT_VERSION,
        )
        if requirement_content is None:
            requirement_content = self.requirements.get_or_create(chapter_id).content
        candidates = self.deterministic.run(
            DeterministicAuditRequest(
                chapter_id=chapter_id,
                target_text=target_text,
                target_revision=target_revision,
                target_hash=target_hash,
                requirement_content=requirement_content,
            )
        )
        findings = tuple(
            self.audits.add_finding(
                run_id=run.id,
                category=candidate.category,
                severity=candidate.severity,
                source=candidate.source,
                location_json=candidate.location_json,
                evidence=candidate.evidence,
                explanation=candidate.explanation,
                related_source_json=candidate.related_source_json,
                confidence=candidate.confidence,
            )
            for candidate in candidates
        )
        completed = self.audits.update_run_status(run.id, AuditRunStatus.COMPLETED)
        return AuditWorkflowResult(completed, findings)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
