from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.audit_workflow_service import (
    AuditWorkflowResult,
    AuditWorkflowService,
)
from ai_novel_studio.domain.audit import AuditTargetKind
from ai_novel_studio.domain.generation import AuditPolicy, CreationMode
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@dataclass(frozen=True, slots=True)
class AuditClaimsRequest:
    """Bounded request for the deterministic audit facade (H0 step 4).

    FORMAT_CHAPTER targets must point at the audited chapter itself; the
    workflow reads the formal text, so target_text is only used for drafts.
    """

    chapter_id: str
    target_kind: AuditTargetKind
    target_id: str
    target_revision: int
    mode: CreationMode
    target_text: str = ""
    audit_policy: AuditPolicy = AuditPolicy.MINIMAL
    requirement_content: str | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "chapter_id", validate_id(self.chapter_id))
            object.__setattr__(self, "target_id", validate_id(self.target_id))
        except ValueError:
            raise ValueError("audit claims identifiers are invalid") from None
        if not isinstance(self.target_kind, AuditTargetKind):
            raise ValueError("audit claims target kind is invalid")
        if not isinstance(self.mode, CreationMode):
            raise ValueError("audit claims mode is invalid")
        if not isinstance(self.audit_policy, AuditPolicy):
            raise ValueError("audit claims audit policy is invalid")
        if isinstance(self.target_revision, bool) or not isinstance(
            self.target_revision, int
        ) or self.target_revision < 0:
            raise ValueError("audit claims target revision is invalid")
        if self.target_kind is AuditTargetKind.FORMAL_CHAPTER:
            if self.target_id != self.chapter_id:
                raise ValueError("formal chapter audit must target its own chapter")
        elif not self.target_text.strip():
            raise ValueError("draft audit requires target text")
        if self.requirement_content is not None and not self.requirement_content:
            object.__setattr__(self, "requirement_content", None)


class AuditClaimService:
    """audit_claims facade over the existing deterministic audit workflow."""

    def __init__(self, workflow: AuditWorkflowService) -> None:
        if not isinstance(workflow, AuditWorkflowService):
            raise TypeError("audit workflow is invalid")
        self._workflow = workflow

    @classmethod
    def for_project(cls, project: ProjectRepository) -> AuditClaimService:
        return cls(
            AuditWorkflowService(
                ChapterRepository(project),
                ChapterRequirementRepository(project),
                AuditRepository(project),
            )
        )

    def run(self, request: AuditClaimsRequest) -> AuditWorkflowResult:
        if not isinstance(request, AuditClaimsRequest):
            raise TypeError("audit claims request is invalid")
        if request.target_kind is AuditTargetKind.FORMAL_CHAPTER:
            return self._workflow.run_deterministic_for_formal_chapter(
                request.chapter_id,
                mode=request.mode,
                audit_policy=request.audit_policy,
                requirement_content=request.requirement_content,
            )
        return self._workflow.run_deterministic_for_draft(
            chapter_id=request.chapter_id,
            generation_run_id=request.target_id,
            draft_text=request.target_text,
            base_chapter_revision=request.target_revision,
            mode=request.mode,
            audit_policy=request.audit_policy,
            requirement_content=request.requirement_content,
        )
