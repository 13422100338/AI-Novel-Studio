from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from ai_novel_studio.application.confirmed_subject_resolver import (
    ConfirmedSubjectResolutionError,
    ConfirmedSubjectResolver,
)
from ai_novel_studio.application.shared_semantic_import_service import (
    SharedSemanticChapterResult,
)
from ai_novel_studio.core.context.shared_semantic_result import (
    ResolvedSubjectReference,
    SharedSemanticResult,
    SubjectMentionCandidate,
    ViewDifferenceCandidate,
)
from ai_novel_studio.domain.view import ViewAssertionDraft, ViewType
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
    ViewAssertionRepositoryError,
)

_FAILURE_MESSAGES = {
    "INVALID_CANDIDATE": "shared semantic view candidate is invalid",
    "PERSISTENCE_FAILED": "shared semantic view binding could not be persisted",
}


class SharedSemanticViewBindingStatus(StrEnum):
    APPLIED = "APPLIED"
    FAILED = "FAILED"


class SharedSemanticViewFailureCode(StrEnum):
    INVALID_CANDIDATE = "INVALID_CANDIDATE"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"


class SharedSemanticViewIssueCode(StrEnum):
    UNRESOLVED_SUBJECT = "UNRESOLVED_SUBJECT"
    AMBIGUOUS_SUBJECT = "AMBIGUOUS_SUBJECT"
    SUBJECT_UNAVAILABLE = "SUBJECT_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class SharedSemanticViewBindingIssue:
    candidate_source_id: str
    code: SharedSemanticViewIssueCode


@dataclass(frozen=True, slots=True)
class SharedSemanticViewFailure:
    code: SharedSemanticViewFailureCode
    message: str


@dataclass(frozen=True, slots=True)
class SharedSemanticChapterViewBindingResult:
    chapter_id: str
    source_revision: int
    status: SharedSemanticViewBindingStatus
    accepted_assertion_ids: tuple[str, ...]
    issues: tuple[SharedSemanticViewBindingIssue, ...]
    failure: SharedSemanticViewFailure | None


class SharedSemanticViewService:
    """Binds one chapter's sparse shared semantic views (V1b).

    Observer and target references resolve only through confirmed active
    CHARACTER subjects; unresolved or ambiguous references become bounded
    issues instead of guesses. Exactly one existing View Assertion batch
    write boundary call happens per chapter, and reader visibility derives
    deterministically from the canonical chapter sequence.
    """

    def __init__(self, project: ProjectRepository) -> None:
        self._repository = ViewAssertionRepository(project)
        self._resolver = ConfirmedSubjectResolver(SubjectRepository(project))
        self._chapters = ChapterRepository(project)

    def bind_chapter_views(
        self,
        chapter: SharedSemanticChapterResult,
    ) -> SharedSemanticChapterViewBindingResult:
        if not isinstance(chapter, SharedSemanticChapterResult):
            raise TypeError("shared semantic view chapter result is invalid")
        _validate_envelope(chapter)
        try:
            sequence = self._chapters.get_chapter_sequence(chapter.chapter_id)
        except (KeyError, sqlite3.Error):
            return _failed(chapter, SharedSemanticViewFailureCode.PERSISTENCE_FAILED)
        issues: list[SharedSemanticViewBindingIssue] = []
        drafts: list[ViewAssertionDraft] = []
        try:
            for result in chapter.results:
                mentions = {
                    item.candidate_id: item for item in result.subject_mentions
                }
                for candidate in result.view_differences:
                    target = self._resolve_side(
                        candidate,
                        issues,
                        mentions,
                        reference=candidate.target,
                        mention_id=candidate.target_mention_candidate_id,
                    )
                    if target is None:
                        continue
                    observer = None
                    epistemic_status = None
                    if candidate.view_type is ViewType.CHARACTER_VIEW:
                        observer = self._resolve_side(
                            candidate,
                            issues,
                            mentions,
                            reference=candidate.observer,
                            mention_id=(
                                candidate.observer_mention_candidate_id
                            ),
                        )
                        if observer is None:
                            continue
                        epistemic_status = candidate.epistemic_status
                    try:
                        drafts.append(
                            ViewAssertionDraft(
                                subject_id=target,
                                view_type=candidate.view_type,
                                content=candidate.content,
                                viewer_subject_id=observer,
                                epistemic_status=epistemic_status,
                                narrative_visible_from_sequence=sequence + 1,
                            )
                        )
                    except ValueError:
                        return _failed(
                            chapter,
                            SharedSemanticViewFailureCode.INVALID_CANDIDATE,
                        )
        except ConfirmedSubjectResolutionError:
            return _failed(
                chapter, SharedSemanticViewFailureCode.PERSISTENCE_FAILED
            )
        try:
            created = self._repository.create_model_candidates_for_chapter(
                tuple(drafts),
                source_id=chapter.chapter_id,
                source_revision=chapter.source_revision,
            )
        except ViewAssertionRepositoryError:
            return _failed(
                chapter, SharedSemanticViewFailureCode.PERSISTENCE_FAILED
            )
        except sqlite3.Error:
            return _failed(
                chapter, SharedSemanticViewFailureCode.PERSISTENCE_FAILED
            )
        return SharedSemanticChapterViewBindingResult(
            chapter.chapter_id,
            chapter.source_revision,
            SharedSemanticViewBindingStatus.APPLIED,
            tuple(item.id for item in created),
            tuple(issues),
            None,
        )

    def _resolve_side(
        self,
        candidate: ViewDifferenceCandidate,
        issues: list[SharedSemanticViewBindingIssue],
        mentions: dict[str, SubjectMentionCandidate],
        *,
        reference: ResolvedSubjectReference | None,
        mention_id: str | None,
    ) -> str | None:
        if reference is not None:
            resolved = self._resolver.resolve_active_character(reference.subject_id)
            if resolved is None:
                issues.append(
                    SharedSemanticViewBindingIssue(
                        candidate.candidate_id,
                        SharedSemanticViewIssueCode.SUBJECT_UNAVAILABLE,
                    )
                )
                return None
            return resolved
        mention = mentions.get(mention_id or "")
        name = getattr(mention, "mention", None)
        if not isinstance(name, str):
            issues.append(
                SharedSemanticViewBindingIssue(
                    candidate.candidate_id,
                    SharedSemanticViewIssueCode.UNRESOLVED_SUBJECT,
                )
            )
            return None
        matches = self._resolver.resolve_name(name.strip())
        if not matches:
            issues.append(
                SharedSemanticViewBindingIssue(
                    candidate.candidate_id,
                    SharedSemanticViewIssueCode.UNRESOLVED_SUBJECT,
                )
            )
            return None
        if len(matches) > 1:
            issues.append(
                SharedSemanticViewBindingIssue(
                    candidate.candidate_id,
                    SharedSemanticViewIssueCode.AMBIGUOUS_SUBJECT,
                )
            )
            return None
        return matches[0]


def _validate_envelope(chapter: SharedSemanticChapterResult) -> None:
    if (
        not isinstance(chapter.results, tuple)
        or any(
            not isinstance(result, SharedSemanticResult)
            or result.window.chapter_id != chapter.chapter_id
            or result.window.source_revision != chapter.source_revision
            or result.window.source_hash != chapter.source_hash
            or result.window.narrative_sequence != chapter.narrative_sequence
            or result.window.window_ordinal != ordinal
            for ordinal, result in enumerate(chapter.results)
        )
    ):
        raise ValueError("shared semantic view chapter result is invalid")


def _failed(
    chapter: SharedSemanticChapterResult,
    code: SharedSemanticViewFailureCode,
) -> SharedSemanticChapterViewBindingResult:
    return SharedSemanticChapterViewBindingResult(
        chapter.chapter_id,
        chapter.source_revision,
        SharedSemanticViewBindingStatus.FAILED,
        (),
        (),
        SharedSemanticViewFailure(code, _FAILURE_MESSAGES[code.value]),
    )


__all__ = [
    "SharedSemanticChapterViewBindingResult",
    "SharedSemanticViewBindingIssue",
    "SharedSemanticViewBindingStatus",
    "SharedSemanticViewFailure",
    "SharedSemanticViewFailureCode",
    "SharedSemanticViewIssueCode",
    "SharedSemanticViewService",
]
