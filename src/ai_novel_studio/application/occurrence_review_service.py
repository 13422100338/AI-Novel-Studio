from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.memory import ReviewStatus
from ai_novel_studio.domain.occurrence import Occurrence, SubjectOccurrenceLink
from ai_novel_studio.infrastructure.storage.occurrence_repository import (
    OccurrenceRepository,
    OccurrenceRepositoryError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class OccurrenceReviewError(RuntimeError):
    pass


class OccurrenceNotFoundError(OccurrenceReviewError):
    pass


class OccurrenceStaleError(OccurrenceReviewError):
    pass


class OccurrenceConflictError(OccurrenceReviewError):
    pass


class OccurrenceCorruptionError(OccurrenceReviewError):
    pass


@dataclass(frozen=True, slots=True)
class ReviewOccurrenceRequest:
    occurrence_id: str
    expected_updated_at: str
    decision: ReviewStatus
    confirmed_by_user: bool


@dataclass(frozen=True, slots=True)
class ReviewOccurrenceResult:
    occurrence: Occurrence


@dataclass(frozen=True, slots=True)
class ReviewLinkRequest:
    link_id: str
    expected_updated_at: str
    decision: ReviewStatus
    confirmed_by_user: bool


@dataclass(frozen=True, slots=True)
class ReviewLinkResult:
    link: SubjectOccurrenceLink


class OccurrenceReviewService:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project
        self.repository = OccurrenceRepository(project)

    def review_occurrence(
        self,
        occurrence_id: str,
        *,
        expected_updated_at: str,
        decision: ReviewStatus,
        confirmed_by_user: bool,
    ) -> ReviewOccurrenceResult:
        if confirmed_by_user is not True:
            raise PermissionError("occurrence review must be confirmed by user")
        try:
            occurrence = self.repository.review_occurrence(
                occurrence_id,
                expected_updated_at=expected_updated_at,
                decision=decision,
            )
        except ValueError as error:
            raise OccurrenceReviewError("occurrence review request is invalid") from error
        except OccurrenceRepositoryError as error:
            message = str(error)
            if message == "occurrence not found":
                raise OccurrenceNotFoundError("occurrence not found") from None
            if message == "occurrence source changed":
                raise OccurrenceStaleError("occurrence source changed") from None
            if message == "occurrence already reviewed":
                raise OccurrenceConflictError("occurrence already reviewed") from None
            if message in {
                "stored occurrence is invalid",
                "stored occurrence link is invalid",
                "occurrence records could not be read",
            }:
                raise OccurrenceCorruptionError(message) from None
            if message == "occurrence review could not be saved":
                raise OccurrenceReviewError("occurrence review could not be saved") from None
            raise OccurrenceReviewError(message) from None
        return ReviewOccurrenceResult(occurrence=occurrence)

    def review_link(
        self,
        link_id: str,
        *,
        expected_updated_at: str,
        decision: ReviewStatus,
        confirmed_by_user: bool,
    ) -> ReviewLinkResult:
        if confirmed_by_user is not True:
            raise PermissionError("link review must be confirmed by user")
        try:
            link = self.repository.review_link(
                link_id,
                expected_updated_at=expected_updated_at,
                decision=decision,
            )
        except ValueError as error:
            raise OccurrenceReviewError("occurrence review request is invalid") from error
        except OccurrenceRepositoryError as error:
            message = str(error)
            if message == "link not found":
                raise OccurrenceNotFoundError("link not found") from None
            if message == "link source changed":
                raise OccurrenceStaleError("link source changed") from None
            if message == "link already reviewed":
                raise OccurrenceConflictError("link already reviewed") from None
            if message in {
                "stored occurrence is invalid",
                "stored occurrence link is invalid",
                "occurrence records could not be read",
            }:
                raise OccurrenceCorruptionError(message) from None
            if message == "occurrence review could not be saved":
                raise OccurrenceReviewError("occurrence review could not be saved") from None
            raise OccurrenceReviewError(message) from None
        return ReviewLinkResult(link=link)

    def review_occurrence_request(
        self, request: ReviewOccurrenceRequest
    ) -> ReviewOccurrenceResult:
        return self.review_occurrence(
            request.occurrence_id,
            expected_updated_at=request.expected_updated_at,
            decision=request.decision,
            confirmed_by_user=request.confirmed_by_user,
        )

    def review_link_request(self, request: ReviewLinkRequest) -> ReviewLinkResult:
        return self.review_link(
            request.link_id,
            expected_updated_at=request.expected_updated_at,
            decision=request.decision,
            confirmed_by_user=request.confirmed_by_user,
        )
