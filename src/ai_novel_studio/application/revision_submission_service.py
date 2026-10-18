from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
    SubmittedRevision,
)
from ai_novel_studio.domain.identifiers import validate_id


@dataclass(frozen=True, slots=True)
class RevisionSubmissionRequest:
    """Bounded request for the submit_revision facade (H0 step 4)."""

    chapter_id: str
    content: str
    source: str
    reason: str
    expected_revision: int
    invalidate_memory: bool = True

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self, "chapter_id", validate_id(self.chapter_id)
            )
        except ValueError:
            raise ValueError("revision submission chapter id is invalid") from None
        if not self.content.strip():
            raise ValueError("revision submission content cannot be empty")
        for field in ("source", "reason"):
            value = getattr(self, field).strip()
            if not value:
                raise ValueError(f"revision submission {field} cannot be empty")
            object.__setattr__(self, field, value)
        if (
            isinstance(self.expected_revision, bool)
            or not isinstance(self.expected_revision, int)
            or self.expected_revision < 0
        ):
            raise ValueError("revision submission expected_revision is invalid")


class RevisionSubmissionService:
    """submit_revision facade over the existing unified revision boundary."""

    def __init__(self, revisions: ChapterRevisionService) -> None:
        if not isinstance(revisions, ChapterRevisionService):
            raise TypeError("chapter revision service is invalid")
        self._revisions = revisions

    def run(self, request: RevisionSubmissionRequest) -> SubmittedRevision:
        if not isinstance(request, RevisionSubmissionRequest):
            raise TypeError("revision submission request is invalid")
        return self._revisions.submit_revision(
            request.chapter_id,
            request.content,
            source=request.source,
            reason=request.reason,
            expected_revision=request.expected_revision,
            invalidate_memory=request.invalidate_memory,
        )
