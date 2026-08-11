from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from ai_novel_studio.core.context.manuscript_chunking import (
    DEFAULT_MANUSCRIPT_CHUNK_POLICY,
    ManuscriptChunkPolicy,
    project_formal_manuscript_chunks,
)
from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRelocationExpectation,
    ChapterRepository,
    StaleChapterRevisionError,
)
from ai_novel_studio.infrastructure.storage.formal_manuscript_projection import (
    FormalManuscriptChunk,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import (
    SearchDocument,
    SearchRepository,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")


class ChapterMutationKind(StrEnum):
    CREATE = "CREATE"
    CONTENT = "CONTENT"
    RENAME = "RENAME"
    DELETE = "DELETE"
    RESTORE = "RESTORE"
    RELOCATE = "RELOCATE"


class FormalMaintenanceStatus(StrEnum):
    CURRENT = "CURRENT"
    REPAIRED = "REPAIRED"
    REMOVED = "REMOVED"
    PENDING = "PENDING"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class FormalMaintenanceFailureCode(StrEnum):
    SOURCE_SUPERSEDED = "SOURCE_SUPERSEDED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    REPAIR_FAILED = "REPAIR_FAILED"


_FAILURE_MESSAGES = {
    FormalMaintenanceFailureCode.SOURCE_SUPERSEDED: (
        "formal manuscript source changed before maintenance"
    ),
    FormalMaintenanceFailureCode.SOURCE_UNAVAILABLE: (
        "formal manuscript source is unavailable"
    ),
    FormalMaintenanceFailureCode.REPAIR_FAILED: (
        "formal manuscript projection requires recovery"
    ),
}


@dataclass(frozen=True, slots=True)
class RevisionSourceIdentity:
    revision: int
    content_hash: str
    is_deleted: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ValueError("revision source identity revision is invalid")
        if not isinstance(self.content_hash, str) or _SHA256.fullmatch(
            self.content_hash
        ) is None:
            raise ValueError("revision source identity hash is invalid")
        if not isinstance(self.is_deleted, bool):
            raise ValueError("revision source identity deletion state is invalid")


@dataclass(frozen=True, slots=True)
class RevisionImpact:
    operation: ChapterMutationKind
    chapter_id: str
    before: RevisionSourceIdentity | None
    after: RevisionSourceIdentity
    manuscript_committed: bool
    semantic_memory_invalidated: bool

    def __post_init__(self) -> None:
        validate_id(self.chapter_id)
        if not isinstance(self.operation, ChapterMutationKind):
            raise ValueError("revision impact operation is invalid")
        if self.before is not None and not isinstance(
            self.before, RevisionSourceIdentity
        ):
            raise ValueError("revision impact prior source is invalid")
        if not isinstance(self.after, RevisionSourceIdentity):
            raise ValueError("revision impact current source is invalid")
        if self.operation == ChapterMutationKind.CREATE:
            if self.before is not None:
                raise ValueError("created revision impact cannot have a prior source")
        elif self.before is None:
            raise ValueError("revision impact requires a prior source")
        if not isinstance(self.manuscript_committed, bool) or not isinstance(
            self.semantic_memory_invalidated, bool
        ):
            raise ValueError("revision impact commit flags are invalid")
        if self.operation == ChapterMutationKind.DELETE and not self.after.is_deleted:
            raise ValueError("deleted revision impact must mark the source deleted")
        if self.operation == ChapterMutationKind.RESTORE and self.after.is_deleted:
            raise ValueError("restored revision impact must mark the source current")


@dataclass(frozen=True, slots=True)
class FormalMaintenanceFailure:
    code: FormalMaintenanceFailureCode

    def __post_init__(self) -> None:
        if not isinstance(self.code, FormalMaintenanceFailureCode):
            raise ValueError("formal maintenance failure code is invalid")

    @property
    def message(self) -> str:
        return _FAILURE_MESSAGES[self.code]


@dataclass(frozen=True, slots=True)
class FormalMaintenanceResult:
    chapter_id: str
    source: RevisionSourceIdentity
    status: FormalMaintenanceStatus
    policy_version: str
    chunk_count: int
    recovery_required: bool
    failure: FormalMaintenanceFailure | None

    def __post_init__(self) -> None:
        validate_id(self.chapter_id)
        if not isinstance(self.source, RevisionSourceIdentity):
            raise ValueError("formal maintenance source is invalid")
        if not isinstance(self.status, FormalMaintenanceStatus):
            raise ValueError("formal maintenance status is invalid")
        if (
            not isinstance(self.policy_version, str)
            or not self.policy_version
            or self.policy_version != self.policy_version.strip()
        ):
            raise ValueError("formal maintenance policy version is invalid")
        if (
            isinstance(self.chunk_count, bool)
            or not isinstance(self.chunk_count, int)
            or self.chunk_count < 0
        ):
            raise ValueError("formal maintenance chunk count is invalid")
        if not isinstance(self.recovery_required, bool):
            raise ValueError("formal maintenance recovery flag is invalid")
        successful = {
            FormalMaintenanceStatus.CURRENT,
            FormalMaintenanceStatus.REPAIRED,
            FormalMaintenanceStatus.REMOVED,
        }
        if self.status in successful:
            if self.recovery_required or self.failure is not None:
                raise ValueError("successful formal maintenance cannot require recovery")
        elif (
            not self.recovery_required
            or not isinstance(self.failure, FormalMaintenanceFailure)
        ):
            raise ValueError("unsuccessful formal maintenance requires a failure")
        if self.status == FormalMaintenanceStatus.REMOVED and self.chunk_count != 0:
            raise ValueError("removed formal maintenance cannot retain chunks")


@dataclass(frozen=True, slots=True)
class SubmittedRevision:
    chapter: Chapter
    impact: RevisionImpact
    maintenance: FormalMaintenanceResult

    def __post_init__(self) -> None:
        if not isinstance(self.chapter, Chapter):
            raise ValueError("submitted revision chapter is invalid")
        if not isinstance(self.impact, RevisionImpact):
            raise ValueError("submitted revision impact is invalid")
        if not isinstance(self.maintenance, FormalMaintenanceResult):
            raise ValueError("submitted revision maintenance is invalid")
        if (
            self.impact.chapter_id != self.chapter.id
            or self.maintenance.chapter_id != self.chapter.id
            or self.impact.after.revision != self.chapter.revision
            or not self.impact.manuscript_committed
        ):
            raise ValueError("submitted revision contracts are inconsistent")


@dataclass(frozen=True, slots=True)
class SubmittedDeletion:
    impact: RevisionImpact
    maintenance: FormalMaintenanceResult

    def __post_init__(self) -> None:
        if not isinstance(self.impact, RevisionImpact):
            raise ValueError("submitted deletion impact is invalid")
        if not isinstance(self.maintenance, FormalMaintenanceResult):
            raise ValueError("submitted deletion maintenance is invalid")
        before = self.impact.before
        if (
            self.impact.operation != ChapterMutationKind.DELETE
            or before is None
            or not self.impact.manuscript_committed
            or self.impact.semantic_memory_invalidated
            or before.is_deleted
            or not self.impact.after.is_deleted
            or before.revision != self.impact.after.revision
            or before.content_hash != self.impact.after.content_hash
            or self.maintenance.chapter_id != self.impact.chapter_id
            or self.maintenance.source != self.impact.after
            or self.maintenance.status
            not in {FormalMaintenanceStatus.REMOVED, FormalMaintenanceStatus.PENDING}
        ):
            raise ValueError("submitted deletion contracts are inconsistent")


@dataclass(frozen=True, slots=True)
class SubmittedTitleRevision:
    chapter: Chapter
    revision: SubmittedRevision | None

    def __post_init__(self) -> None:
        if not isinstance(self.chapter, Chapter):
            raise ValueError("submitted title chapter is invalid")
        if self.revision is not None and (
            not isinstance(self.revision, SubmittedRevision)
            or self.revision.chapter != self.chapter
            or self.revision.impact.operation != ChapterMutationKind.RENAME
        ):
            raise ValueError("submitted title revision is inconsistent")


@dataclass(frozen=True, slots=True)
class SubmittedRelocation:
    target_volume_id: str
    revisions: tuple[SubmittedRevision, ...]

    def __post_init__(self) -> None:
        validate_id(self.target_volume_id)
        if not isinstance(self.revisions, tuple) or any(
            not isinstance(revision, SubmittedRevision) for revision in self.revisions
        ):
            raise ValueError("submitted relocation revisions are invalid")
        chapter_ids = tuple(revision.chapter.id for revision in self.revisions)
        if len(chapter_ids) != len(set(chapter_ids)):
            raise ValueError("submitted relocation chapters must be unique")
        for revision in self.revisions:
            before = revision.impact.before
            after = revision.impact.after
            if (
                revision.impact.operation != ChapterMutationKind.RELOCATE
                or before is None
                or revision.chapter.volume_id != self.target_volume_id
                or before.is_deleted
                or after.is_deleted
                or after.revision != before.revision + 1
                or after.content_hash != before.content_hash
                or not revision.impact.semantic_memory_invalidated
            ):
                raise ValueError("submitted relocation contracts are inconsistent")


@dataclass(frozen=True, slots=True)
class FormalRecoveryCursor:
    last_chapter_id: str

    def __post_init__(self) -> None:
        validate_id(self.last_chapter_id)


@dataclass(frozen=True, slots=True)
class FormalRecoveryFailure:
    chapter_id: str
    failure: FormalMaintenanceFailure

    def __post_init__(self) -> None:
        validate_id(self.chapter_id)
        if not isinstance(self.failure, FormalMaintenanceFailure):
            raise ValueError("formal recovery failure is invalid")


@dataclass(frozen=True, slots=True)
class FormalRecoveryReport:
    scanned_chapters: int
    current_chapters: int
    repaired_chapters: int
    removed_chapters: int
    pending_chapters: int
    failed_chapters: int
    failures: tuple[FormalRecoveryFailure, ...]
    cancelled: bool
    next_cursor: FormalRecoveryCursor | None

    def __post_init__(self) -> None:
        counts = (
            self.scanned_chapters,
            self.current_chapters,
            self.repaired_chapters,
            self.removed_chapters,
            self.pending_chapters,
            self.failed_chapters,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts
        ):
            raise ValueError("formal recovery counts are invalid")
        if self.scanned_chapters != sum(counts[1:]):
            raise ValueError("formal recovery counts are inconsistent")
        if not isinstance(self.failures, tuple) or any(
            not isinstance(failure, FormalRecoveryFailure)
            for failure in self.failures
        ):
            raise ValueError("formal recovery failures are invalid")
        if len(self.failures) != self.pending_chapters + self.failed_chapters:
            raise ValueError("formal recovery failures are inconsistent")
        if not isinstance(self.cancelled, bool):
            raise ValueError("formal recovery cancellation flag is invalid")
        if self.next_cursor is not None and not isinstance(
            self.next_cursor, FormalRecoveryCursor
        ):
            raise ValueError("formal recovery cursor is invalid")


class ChapterRevisionService:
    def __init__(
        self,
        project: ProjectRepository,
        *,
        chunk_policy: ManuscriptChunkPolicy = DEFAULT_MANUSCRIPT_CHUNK_POLICY,
    ) -> None:
        if not isinstance(chunk_policy, ManuscriptChunkPolicy):
            raise TypeError("chapter revision chunk policy is invalid")
        self.project = project
        self.chapters = ChapterRepository(project)
        self.search = SearchRepository(project)
        self.chunk_policy = chunk_policy

    def submit_creation(
        self,
        volume_id: str,
        title: str,
        declared_number: str = "",
        content: str = "",
        synopsis: str = "",
    ) -> SubmittedRevision:
        chapter = self.chapters.create_chapter(
            volume_id,
            title,
            declared_number,
            content,
            synopsis,
        )
        after = RevisionSourceIdentity(
            chapter.revision,
            _source_hash(content),
            is_deleted=False,
        )
        impact = RevisionImpact(
            ChapterMutationKind.CREATE,
            chapter.id,
            None,
            after,
            manuscript_committed=True,
            semantic_memory_invalidated=False,
        )
        try:
            maintenance = self.maintain_current_revision(
                chapter.id,
                expected_revision=after.revision,
                expected_source_hash=after.content_hash,
            )
        except Exception:
            maintenance = self._failed_result(
                chapter.id,
                after,
                FormalMaintenanceStatus.PENDING,
                FormalMaintenanceFailureCode.REPAIR_FAILED,
            )
        return SubmittedRevision(chapter, impact, maintenance)

    def submit_revision(
        self,
        chapter_id: str,
        content: str,
        *,
        source: str,
        reason: str,
        expected_revision: int,
        invalidate_memory: bool = True,
    ) -> SubmittedRevision:
        canonical_chapter_id = validate_id(chapter_id)
        before_chapter = self.chapters.get_chapter(
            canonical_chapter_id,
            include_deleted=False,
        )
        if before_chapter.revision != expected_revision:
            raise StaleChapterRevisionError(
                "chapter revision changed: "
                f"expected {expected_revision}, current {before_chapter.revision}"
            )
        before_content = self.chapters.read_content_exact(canonical_chapter_id)
        chapter = self.chapters.save_content(
            canonical_chapter_id,
            content,
            source=source,
            reason=reason,
            invalidate_memory=invalidate_memory,
            expected_revision=expected_revision,
        )
        before = RevisionSourceIdentity(
            before_chapter.revision,
            _source_hash(before_content),
            is_deleted=False,
        )
        after = RevisionSourceIdentity(
            chapter.revision,
            _source_hash(content),
            is_deleted=False,
        )
        impact = RevisionImpact(
            ChapterMutationKind.CONTENT,
            canonical_chapter_id,
            before,
            after,
            manuscript_committed=True,
            semantic_memory_invalidated=invalidate_memory,
        )
        try:
            maintenance = self.maintain_current_revision(
                canonical_chapter_id,
                expected_revision=after.revision,
                expected_source_hash=after.content_hash,
            )
        except Exception:
            maintenance = self._failed_result(
                canonical_chapter_id,
                after,
                FormalMaintenanceStatus.PENDING,
                FormalMaintenanceFailureCode.REPAIR_FAILED,
            )
        return SubmittedRevision(chapter, impact, maintenance)

    def submit_title_revision(
        self,
        chapter_id: str,
        title: str,
    ) -> SubmittedTitleRevision:
        canonical_chapter_id = validate_id(chapter_id)
        before_chapter = self.chapters.get_chapter(
            canonical_chapter_id,
            include_deleted=False,
        )
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("chapter title cannot be empty")
        if normalized_title == before_chapter.title:
            return SubmittedTitleRevision(before_chapter, revision=None)
        before_content = self.chapters.read_content_exact(canonical_chapter_id)
        source_hash = _source_hash(before_content)
        chapter = self.chapters.rename_chapter(
            canonical_chapter_id,
            normalized_title,
        )
        if chapter.revision == before_chapter.revision:
            return SubmittedTitleRevision(chapter, revision=None)
        before = RevisionSourceIdentity(
            before_chapter.revision,
            source_hash,
            is_deleted=False,
        )
        after = RevisionSourceIdentity(
            chapter.revision,
            source_hash,
            is_deleted=False,
        )
        impact = RevisionImpact(
            ChapterMutationKind.RENAME,
            canonical_chapter_id,
            before,
            after,
            manuscript_committed=True,
            semantic_memory_invalidated=True,
        )
        try:
            maintenance = self.maintain_current_revision(
                canonical_chapter_id,
                expected_revision=after.revision,
                expected_source_hash=after.content_hash,
            )
        except Exception:
            maintenance = self._failed_result(
                canonical_chapter_id,
                after,
                FormalMaintenanceStatus.PENDING,
                FormalMaintenanceFailureCode.REPAIR_FAILED,
            )
        submitted = SubmittedRevision(chapter, impact, maintenance)
        return SubmittedTitleRevision(chapter, revision=submitted)

    def submit_deletion(self, chapter_id: str) -> SubmittedDeletion:
        canonical_chapter_id = validate_id(chapter_id)
        chapter = self.chapters.get_chapter(
            canonical_chapter_id,
            include_deleted=False,
        )
        content = self.chapters.read_content_exact(canonical_chapter_id)
        source_hash = _source_hash(content)
        before = RevisionSourceIdentity(
            chapter.revision,
            source_hash,
            is_deleted=False,
        )
        self.chapters.delete_chapter(
            canonical_chapter_id,
            expected_revision=before.revision,
            expected_source_hash=before.content_hash,
        )
        after = RevisionSourceIdentity(
            before.revision,
            before.content_hash,
            is_deleted=True,
        )
        impact = RevisionImpact(
            ChapterMutationKind.DELETE,
            canonical_chapter_id,
            before,
            after,
            manuscript_committed=True,
            semantic_memory_invalidated=False,
        )
        try:
            self.search.remove_orphaned_formal_manuscript_chunks(
                canonical_chapter_id
            )
        except Exception:
            maintenance = self._failed_result(
                canonical_chapter_id,
                after,
                FormalMaintenanceStatus.PENDING,
                FormalMaintenanceFailureCode.REPAIR_FAILED,
            )
        else:
            maintenance = self._result(
                canonical_chapter_id,
                after,
                FormalMaintenanceStatus.REMOVED,
                0,
            )
        return SubmittedDeletion(impact, maintenance)

    def submit_volume_deletion(
        self,
        source_volume_id: str,
        target_volume_id: str,
    ) -> SubmittedRelocation:
        validate_id(source_volume_id)
        validate_id(target_volume_id)
        if source_volume_id == target_volume_id:
            raise ValueError("target volume must be different from deleted volume")
        before_chapters = tuple(self.chapters.list_chapters(source_volume_id))
        expectations = tuple(
            ChapterRelocationExpectation(
                chapter.id,
                chapter.revision,
                _source_hash(self.chapters.read_content_exact(chapter.id)),
            )
            for chapter in before_chapters
        )
        relocated = self.chapters.delete_volume(
            source_volume_id,
            target_volume_id,
            expected_sources=expectations,
        )
        submitted: list[SubmittedRevision] = []
        for chapter, prior in zip(relocated, expectations, strict=True):
            before = RevisionSourceIdentity(
                prior.revision,
                prior.content_hash,
                is_deleted=False,
            )
            after = RevisionSourceIdentity(
                chapter.revision,
                prior.content_hash,
                is_deleted=False,
            )
            impact = RevisionImpact(
                ChapterMutationKind.RELOCATE,
                chapter.id,
                before,
                after,
                manuscript_committed=True,
                semantic_memory_invalidated=True,
            )
            try:
                maintenance = self.maintain_current_revision(
                    chapter.id,
                    expected_revision=after.revision,
                    expected_source_hash=after.content_hash,
                )
            except Exception:
                maintenance = self._failed_result(
                    chapter.id,
                    after,
                    FormalMaintenanceStatus.PENDING,
                    FormalMaintenanceFailureCode.REPAIR_FAILED,
                )
            submitted.append(SubmittedRevision(chapter, impact, maintenance))
        return SubmittedRelocation(target_volume_id, tuple(submitted))

    def maintain_current_revision(
        self,
        chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
    ) -> FormalMaintenanceResult:
        canonical_chapter_id = validate_id(chapter_id)
        expected_source = RevisionSourceIdentity(
            expected_revision,
            expected_source_hash,
            is_deleted=False,
        )
        source = self._read_current_source(canonical_chapter_id, expected_source)
        if isinstance(source, FormalMaintenanceResult):
            return source
        content, current_source = source
        chunks = project_formal_manuscript_chunks(
            canonical_chapter_id,
            current_source.revision,
            content,
            policy=self.chunk_policy,
        )
        documents: tuple[SearchDocument, ...] | None
        try:
            documents = self.search.read_formal_manuscript_chunks(
                canonical_chapter_id,
                expected_revision=current_source.revision,
                expected_source_hash=current_source.content_hash,
                chunk_policy_version=self.chunk_policy.version,
            )
        except (KeyError, RuntimeError, ValueError):
            documents = None
        if documents is not None and _matches_expected_projection(documents, chunks):
            return self._result(
                canonical_chapter_id,
                current_source,
                FormalMaintenanceStatus.CURRENT,
                len(chunks),
            )
        try:
            self.search.invalidate_formal_manuscript_chunks(
                canonical_chapter_id,
                expected_revision=current_source.revision,
                expected_source_hash=current_source.content_hash,
            )
        except (
            KeyError,
            OSError,
            RuntimeError,
            UnicodeError,
            ValueError,
            sqlite3.Error,
        ):
            return self._storage_failure_result(
                canonical_chapter_id,
                current_source,
            )
        try:
            repaired = self.search.repair_formal_manuscript_chunks(
                canonical_chapter_id,
                expected_revision=current_source.revision,
                expected_source_hash=current_source.content_hash,
                chunk_policy_version=self.chunk_policy.version,
                chunks=chunks,
            )
        except (
            KeyError,
            OSError,
            RuntimeError,
            UnicodeError,
            ValueError,
            sqlite3.Error,
        ):
            return self._storage_failure_result(
                canonical_chapter_id,
                current_source,
            )
        if not _matches_expected_projection(repaired, chunks):
            return self._failed_result(
                canonical_chapter_id,
                current_source,
                FormalMaintenanceStatus.PENDING,
                FormalMaintenanceFailureCode.REPAIR_FAILED,
            )
        return self._result(
            canonical_chapter_id,
            current_source,
            FormalMaintenanceStatus.REPAIRED,
            len(repaired),
        )

    def recover_current_revisions(
        self,
        *,
        limit: int,
        cursor: FormalRecoveryCursor | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> FormalRecoveryReport:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("formal recovery limit must be between 1 and 100")
        if cursor is not None and not isinstance(cursor, FormalRecoveryCursor):
            raise TypeError("formal recovery cursor is invalid")
        if should_cancel is not None and not callable(should_cancel):
            raise TypeError("formal recovery cancellation callback is invalid")
        after_chapter_id = cursor.last_chapter_id if cursor is not None else None
        candidates = self.search.formal_manuscript_recovery_chapter_ids(
            after_chapter_id=after_chapter_id,
            limit=limit + 1,
        )
        page = candidates[:limit]
        has_more = len(candidates) > limit
        current_chapters = 0
        repaired_chapters = 0
        removed_chapters = 0
        pending_chapters = 0
        failed_chapters = 0
        failures: list[FormalRecoveryFailure] = []
        last_processed = after_chapter_id
        cancelled = False
        for chapter_id in page:
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
            try:
                chapter = self.chapters.get_chapter(chapter_id)
            except KeyError:
                chapter = None
            if chapter is None or chapter.is_deleted:
                try:
                    self.search.remove_orphaned_formal_manuscript_chunks(chapter_id)
                except (RuntimeError, ValueError, sqlite3.Error):
                    failed_chapters += 1
                    failures.append(
                        FormalRecoveryFailure(
                            chapter_id,
                            FormalMaintenanceFailure(
                                FormalMaintenanceFailureCode.REPAIR_FAILED
                            ),
                        )
                    )
                else:
                    removed_chapters += 1
            else:
                try:
                    content = self.chapters.read_content_exact(chapter_id)
                except KeyError:
                    pending_chapters += 1
                    failures.append(
                        FormalRecoveryFailure(
                            chapter_id,
                            FormalMaintenanceFailure(
                                FormalMaintenanceFailureCode.SOURCE_SUPERSEDED
                            ),
                        )
                    )
                except (OSError, RuntimeError, UnicodeError):
                    failed_chapters += 1
                    failures.append(
                        FormalRecoveryFailure(
                            chapter_id,
                            FormalMaintenanceFailure(
                                FormalMaintenanceFailureCode.SOURCE_UNAVAILABLE
                            ),
                        )
                    )
                else:
                    result = self.maintain_current_revision(
                        chapter_id,
                        expected_revision=chapter.revision,
                        expected_source_hash=_source_hash(content),
                    )
                    if result.status == FormalMaintenanceStatus.CURRENT:
                        current_chapters += 1
                    elif result.status == FormalMaintenanceStatus.REPAIRED:
                        repaired_chapters += 1
                    elif result.status == FormalMaintenanceStatus.REMOVED:
                        removed_chapters += 1
                    elif result.status in {
                        FormalMaintenanceStatus.PENDING,
                        FormalMaintenanceStatus.SUPERSEDED,
                    }:
                        pending_chapters += 1
                        if result.failure is None:
                            raise RuntimeError(
                                "pending formal maintenance has no failure"
                            )
                        failures.append(
                            FormalRecoveryFailure(chapter_id, result.failure)
                        )
                    else:
                        failed_chapters += 1
                        if result.failure is None:
                            raise RuntimeError(
                                "failed formal maintenance has no failure"
                            )
                        failures.append(
                            FormalRecoveryFailure(chapter_id, result.failure)
                        )
            last_processed = chapter_id
        scanned_chapters = (
            current_chapters
            + repaired_chapters
            + removed_chapters
            + pending_chapters
            + failed_chapters
        )
        next_cursor = None
        if (cancelled or has_more) and last_processed is not None:
            next_cursor = FormalRecoveryCursor(last_processed)
        elif cancelled:
            next_cursor = cursor
        return FormalRecoveryReport(
            scanned_chapters,
            current_chapters,
            repaired_chapters,
            removed_chapters,
            pending_chapters,
            failed_chapters,
            tuple(failures),
            cancelled,
            next_cursor,
        )

    def _read_current_source(
        self,
        chapter_id: str,
        expected_source: RevisionSourceIdentity,
    ) -> tuple[str, RevisionSourceIdentity] | FormalMaintenanceResult:
        try:
            chapter = self.chapters.get_chapter(chapter_id, include_deleted=False)
        except KeyError:
            return self._failed_result(
                chapter_id,
                expected_source,
                FormalMaintenanceStatus.SUPERSEDED,
                FormalMaintenanceFailureCode.SOURCE_SUPERSEDED,
            )
        try:
            content = self.chapters.read_content_exact(chapter_id)
        except KeyError:
            return self._failed_result(
                chapter_id,
                expected_source,
                FormalMaintenanceStatus.SUPERSEDED,
                FormalMaintenanceFailureCode.SOURCE_SUPERSEDED,
            )
        except (OSError, RuntimeError, UnicodeError):
            return self._failed_result(
                chapter_id,
                expected_source,
                FormalMaintenanceStatus.FAILED,
                FormalMaintenanceFailureCode.SOURCE_UNAVAILABLE,
            )
        current_source = RevisionSourceIdentity(
            chapter.revision,
            _source_hash(content),
            is_deleted=False,
        )
        if current_source != expected_source:
            return self._failed_result(
                chapter_id,
                current_source,
                FormalMaintenanceStatus.SUPERSEDED,
                FormalMaintenanceFailureCode.SOURCE_SUPERSEDED,
            )
        return content, current_source

    def _storage_failure_result(
        self,
        chapter_id: str,
        expected_source: RevisionSourceIdentity,
    ) -> FormalMaintenanceResult:
        result = self._read_current_source(chapter_id, expected_source)
        if isinstance(result, FormalMaintenanceResult):
            return result
        return self._failed_result(
            chapter_id,
            expected_source,
            FormalMaintenanceStatus.PENDING,
            FormalMaintenanceFailureCode.REPAIR_FAILED,
        )

    def _result(
        self,
        chapter_id: str,
        source: RevisionSourceIdentity,
        status: FormalMaintenanceStatus,
        chunk_count: int,
    ) -> FormalMaintenanceResult:
        return FormalMaintenanceResult(
            chapter_id,
            source,
            status,
            self.chunk_policy.version,
            chunk_count,
            recovery_required=False,
            failure=None,
        )

    def _failed_result(
        self,
        chapter_id: str,
        source: RevisionSourceIdentity,
        status: FormalMaintenanceStatus,
        code: FormalMaintenanceFailureCode,
    ) -> FormalMaintenanceResult:
        return FormalMaintenanceResult(
            chapter_id,
            source,
            status,
            self.chunk_policy.version,
            0,
            recovery_required=True,
            failure=FormalMaintenanceFailure(code),
        )


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _matches_expected_projection(
    documents: tuple[SearchDocument, ...],
    chunks: tuple[FormalManuscriptChunk, ...],
) -> bool:
    if len(documents) != len(chunks):
        return False
    return all(
        (
            document.source_id,
            document.chunk_ordinal,
            document.source_start,
            document.source_end,
            document.content,
        )
        == (
            chunk.source_id,
            chunk.ordinal,
            chunk.source_start,
            chunk.source_end,
            chunk.content,
        )
        for document, chunk in zip(documents, chunks, strict=True)
    )
