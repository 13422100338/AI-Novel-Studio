from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from ai_novel_studio.domain.identifiers import new_id, validate_id
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType
from ai_novel_studio.domain.occurrence import (
    Occurrence,
    OccurrenceSourceRange,
    SubjectOccurrenceLink,
    SubjectOccurrenceLinkSourceRange,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_MAX_OCCURRENCES = 100
_MAX_LINKS = 500
_MAX_RECORDS = 600
_SHA256 = re.compile(r"[0-9a-f]{64}")
_OCCURRENCE_MEMORY_TYPE = "OCCURRENCE"
_LINK_MEMORY_TYPE = "SUBJECT_OCCURRENCE_LINK"


class OccurrenceRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _CurrentSource:
    content: str
    narrative_sequence: int


class OccurrenceRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def create_model_candidates_for_chapter(
        self,
        chapter_id: str,
        *,
        expected_revision: int,
        expected_source_hash: str,
        occurrences: tuple[Occurrence, ...],
        links: tuple[SubjectOccurrenceLink, ...],
    ) -> None:
        normalized_chapter_id = _record_id(chapter_id)
        normalized_revision = _revision(expected_revision)
        normalized_hash = _source_hash(expected_source_hash)
        _candidate_batch(occurrences, links)
        try:
            with self.project.database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                source = self._current_source(
                    connection,
                    normalized_chapter_id,
                    normalized_revision,
                    normalized_hash,
                )
                _source_contract(
                    occurrences,
                    links,
                    chapter_id=normalized_chapter_id,
                    revision=normalized_revision,
                    source_hash=normalized_hash,
                    source=source,
                )
                self._require_subjects(connection, links)
                new_occurrences = self._new_occurrences(connection, occurrences)
                new_links = self._new_links(connection, links)
                self._insert_occurrences(connection, new_occurrences)
                self._insert_links(connection, new_links)
                self._insert_dependencies(
                    connection,
                    normalized_chapter_id,
                    normalized_revision,
                    normalized_hash,
                    new_occurrences,
                    new_links,
                )
                source_after = self._current_source(
                    connection,
                    normalized_chapter_id,
                    normalized_revision,
                    normalized_hash,
                )
                if source_after != source:
                    raise OccurrenceRepositoryError(
                        "occurrence candidate source is unavailable"
                    )
        except OccurrenceRepositoryError:
            raise
        except (OSError, UnicodeError, sqlite3.Error):
            raise OccurrenceRepositoryError(
                "occurrence candidate batch could not be saved"
            ) from None

    def _current_source(
        self,
        connection: sqlite3.Connection,
        chapter_id: str,
        expected_revision: int,
        expected_source_hash: str,
    ) -> _CurrentSource:
        row = connection.execute(
            """
            SELECT c.content_path, c.revision, c.content_hash,
                   1 + (
                       SELECT COUNT(*)
                       FROM chapters preceding
                       JOIN volumes preceding_volume
                         ON preceding_volume.id = preceding.volume_id
                       WHERE preceding.is_deleted = 0
                         AND (
                             preceding_volume.sort_index < volume.sort_index
                             OR (
                                 preceding_volume.sort_index = volume.sort_index
                                 AND (
                                     preceding.sort_index < c.sort_index
                                     OR (
                                         preceding.sort_index = c.sort_index
                                         AND preceding.id < c.id
                                     )
                                 )
                             )
                         )
                   ) AS narrative_sequence
            FROM chapters c
            JOIN volumes volume ON volume.id = c.volume_id
            WHERE c.id = ? AND c.is_deleted = 0
            """,
            (chapter_id,),
        ).fetchone()
        if row is None:
            raise OccurrenceRepositoryError(
                "occurrence candidate source is unavailable"
            )
        try:
            current_revision = int(row["revision"])
            narrative_sequence = int(row["narrative_sequence"])
        except (TypeError, ValueError, OverflowError):
            raise OccurrenceRepositoryError(
                "occurrence candidate source is unavailable"
            ) from None
        if (
            current_revision != expected_revision
            or str(row["content_hash"]) != expected_source_hash
        ):
            raise OccurrenceRepositoryError(
                "occurrence candidate source is unavailable"
            )
        content = self._read_exact_source(str(row["content_path"]))
        if _hash(content) != expected_source_hash:
            raise OccurrenceRepositoryError(
                "occurrence candidate source is unavailable"
            )
        return _CurrentSource(content, narrative_sequence)

    def _read_exact_source(self, content_path: str) -> str:
        try:
            manuscript_root = self.project.layout.manuscript.resolve()
            source_path = (self.project.layout.root / content_path).resolve()
            source_path.relative_to(manuscript_root)
        except (OSError, ValueError):
            raise OccurrenceRepositoryError(
                "occurrence candidate source is unavailable"
            ) from None
        if not source_path.is_file():
            raise OccurrenceRepositoryError(
                "occurrence candidate source is unavailable"
            )
        try:
            with source_path.open("r", encoding="utf-8", newline="") as stream:
                return stream.read()
        except (OSError, UnicodeError):
            raise OccurrenceRepositoryError(
                "occurrence candidate source is unavailable"
            ) from None

    @staticmethod
    def _require_subjects(
        connection: sqlite3.Connection,
        links: tuple[SubjectOccurrenceLink, ...],
    ) -> None:
        for subject_id in dict.fromkeys(link.subject_id for link in links):
            row = connection.execute(
                """
                SELECT 1 FROM subjects
                WHERE id = ? AND type = 'CHARACTER' AND active = 1
                """,
                (subject_id,),
            ).fetchone()
            if row is None:
                raise OccurrenceRepositoryError(
                    "occurrence candidate subject is unavailable"
                )

    def _new_occurrences(
        self,
        connection: sqlite3.Connection,
        occurrences: tuple[Occurrence, ...],
    ) -> tuple[Occurrence, ...]:
        new_records: list[Occurrence] = []
        for occurrence in occurrences:
            cross_kind = connection.execute(
                """
                SELECT 1 FROM subject_occurrence_links
                WHERE id = ? OR candidate_source_id = ?
                LIMIT 1
                """,
                (occurrence.id, occurrence.candidate_source_id),
            ).fetchone()
            if cross_kind is not None:
                raise OccurrenceRepositoryError(
                    "occurrence candidate replay conflicts with storage"
                )
            rows = connection.execute(
                """
                SELECT id, candidate_source_id, type_code, vocabulary_version,
                       title, summary, narrative_sequence, authority,
                       review_status, source_type, stale, source_changed,
                       created_at, updated_at
                FROM occurrences
                WHERE id = ? OR candidate_source_id = ?
                ORDER BY id
                """,
                (occurrence.id, occurrence.candidate_source_id),
            ).fetchall()
            if not rows:
                new_records.append(occurrence)
                continue
            if len(rows) != 1 or not self._same_occurrence(
                connection,
                rows[0],
                occurrence,
            ):
                raise OccurrenceRepositoryError(
                    "occurrence candidate replay conflicts with storage"
                )
        return tuple(new_records)

    def _new_links(
        self,
        connection: sqlite3.Connection,
        links: tuple[SubjectOccurrenceLink, ...],
    ) -> tuple[SubjectOccurrenceLink, ...]:
        new_records: list[SubjectOccurrenceLink] = []
        for link in links:
            cross_kind = connection.execute(
                """
                SELECT 1 FROM occurrences
                WHERE id = ? OR candidate_source_id = ?
                LIMIT 1
                """,
                (link.id, link.candidate_source_id),
            ).fetchone()
            if cross_kind is not None:
                raise OccurrenceRepositoryError(
                    "occurrence candidate replay conflicts with storage"
                )
            rows = connection.execute(
                """
                SELECT id, candidate_source_id, occurrence_id, subject_id,
                       role, subject_summary, authority, review_status,
                       source_type, stale, source_changed, created_at, updated_at
                FROM subject_occurrence_links
                WHERE id = ? OR candidate_source_id = ?
                ORDER BY id
                """,
                (link.id, link.candidate_source_id),
            ).fetchall()
            if not rows:
                new_records.append(link)
                continue
            if len(rows) != 1 or not self._same_link(
                connection,
                rows[0],
                link,
            ):
                raise OccurrenceRepositoryError(
                    "occurrence candidate replay conflicts with storage"
                )
        return tuple(new_records)

    def _same_occurrence(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        occurrence: Occurrence,
    ) -> bool:
        if (
            tuple(row)[:-2] != _occurrence_identity_values(occurrence)
            or not _stored_timestamps_are_valid(
                row["created_at"],
                row["updated_at"],
            )
        ):
            return False
        rows = connection.execute(
            """
            SELECT occurrence_id, ordinal, source_chapter_id, source_revision,
                   source_hash, semantic_window_source_id, policy_version,
                   source_start, source_end
            FROM occurrence_source_ranges
            WHERE occurrence_id = ?
            ORDER BY ordinal
            """,
            (occurrence.id,),
        ).fetchall()
        return tuple(tuple(value) for value in rows) == tuple(
            _occurrence_range_values(occurrence.id, value)
            for value in occurrence.source_ranges
        ) and self._same_dependency(
            connection,
            _OCCURRENCE_MEMORY_TYPE,
            occurrence.id,
            occurrence.source_ranges[0],
        )

    def _same_link(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        link: SubjectOccurrenceLink,
    ) -> bool:
        if (
            tuple(row)[:-2] != _link_identity_values(link)
            or not _stored_timestamps_are_valid(
                row["created_at"],
                row["updated_at"],
            )
        ):
            return False
        rows = connection.execute(
            """
            SELECT link_id, ordinal, source_chapter_id, source_revision,
                   source_hash, semantic_window_source_id, policy_version,
                   source_start, source_end
            FROM subject_occurrence_link_source_ranges
            WHERE link_id = ?
            ORDER BY ordinal
            """,
            (link.id,),
        ).fetchall()
        return tuple(tuple(value) for value in rows) == tuple(
            _link_range_values(link.id, value) for value in link.source_ranges
        ) and self._same_dependency(
            connection,
            _LINK_MEMORY_TYPE,
            link.id,
            link.source_ranges[0],
        )

    @staticmethod
    def _same_dependency(
        connection: sqlite3.Connection,
        memory_type: str,
        memory_id: str,
        source_range: OccurrenceSourceRange | SubjectOccurrenceLinkSourceRange,
    ) -> bool:
        rows = connection.execute(
            """
            SELECT memory_type, memory_id, source_chapter_id,
                   source_revision, source_hash, status
            FROM memory_dependencies
            WHERE memory_type = ? AND memory_id = ?
            """,
            (memory_type, memory_id),
        ).fetchall()
        return len(rows) == 1 and tuple(rows[0]) == (
            memory_type,
            memory_id,
            source_range.source_chapter_id,
            source_range.source_revision,
            source_range.source_hash,
            "CURRENT",
        )

    @staticmethod
    def _insert_occurrences(
        connection: sqlite3.Connection,
        occurrences: tuple[Occurrence, ...],
    ) -> None:
        for occurrence in occurrences:
            connection.execute(
                """
                INSERT INTO occurrences (
                    id, candidate_source_id, type_code, vocabulary_version,
                    title, summary, narrative_sequence, authority,
                    review_status, source_type, stale, source_changed,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _occurrence_values(occurrence),
            )
            connection.executemany(
                """
                INSERT INTO occurrence_source_ranges (
                    occurrence_id, ordinal, source_chapter_id, source_revision,
                    source_hash, semantic_window_source_id, policy_version,
                    source_start, source_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(
                    _occurrence_range_values(occurrence.id, value)
                    for value in occurrence.source_ranges
                ),
            )

    @staticmethod
    def _insert_links(
        connection: sqlite3.Connection,
        links: tuple[SubjectOccurrenceLink, ...],
    ) -> None:
        for link in links:
            connection.execute(
                """
                INSERT INTO subject_occurrence_links (
                    id, candidate_source_id, occurrence_id, subject_id,
                    role, subject_summary, authority, review_status,
                    source_type, stale, source_changed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _link_values(link),
            )
            connection.executemany(
                """
                INSERT INTO subject_occurrence_link_source_ranges (
                    link_id, ordinal, source_chapter_id, source_revision,
                    source_hash, semantic_window_source_id, policy_version,
                    source_start, source_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(
                    _link_range_values(link.id, value)
                    for value in link.source_ranges
                ),
            )

    @staticmethod
    def _insert_dependencies(
        connection: sqlite3.Connection,
        chapter_id: str,
        revision: int,
        source_hash: str,
        occurrences: tuple[Occurrence, ...],
        links: tuple[SubjectOccurrenceLink, ...],
    ) -> None:
        for memory_type, memory_id in (
            *(
                (_OCCURRENCE_MEMORY_TYPE, occurrence.id)
                for occurrence in occurrences
            ),
            *((_LINK_MEMORY_TYPE, link.id) for link in links),
        ):
            connection.execute(
                """
                INSERT INTO memory_dependencies (
                    id, memory_type, memory_id, source_chapter_id,
                    source_revision, source_hash, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'CURRENT')
                """,
                (
                    new_id(),
                    memory_type,
                    memory_id,
                    chapter_id,
                    revision,
                    source_hash,
                ),
            )


def _candidate_batch(
    occurrences: object,
    links: object,
) -> None:
    if (
        not isinstance(occurrences, tuple)
        or not isinstance(links, tuple)
        or len(occurrences) > _MAX_OCCURRENCES
        or len(links) > _MAX_LINKS
        or len(occurrences) + len(links) > _MAX_RECORDS
        or any(not isinstance(value, Occurrence) for value in occurrences)
        or any(not isinstance(value, SubjectOccurrenceLink) for value in links)
        or (links and not occurrences)
    ):
        raise ValueError("occurrence candidate batch is invalid")
    occurrence_ids = tuple(value.id for value in occurrences)
    occurrence_candidates = tuple(value.candidate_source_id for value in occurrences)
    link_ids = tuple(value.id for value in links)
    link_candidates = tuple(value.candidate_source_id for value in links)
    record_ids = occurrence_ids + link_ids
    candidate_ids = occurrence_candidates + link_candidates
    link_pairs = tuple((value.occurrence_id, value.subject_id) for value in links)
    if (
        len(set(record_ids)) != len(record_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
        or len(set(link_pairs)) != len(link_pairs)
        or any(value.occurrence_id not in occurrence_ids for value in links)
    ):
        raise ValueError("occurrence candidate batch is invalid")
    for value in (*occurrences, *links):
        if (
            value.authority is not Authority.MODEL_EXTRACTED
            or value.review_status is not ReviewStatus.REVIEW
            or value.source_type is not SourceType.MODEL
            or value.stale
            or value.source_changed
        ):
            raise ValueError("occurrence create contract is invalid")


def _source_contract(
    occurrences: tuple[Occurrence, ...],
    links: tuple[SubjectOccurrenceLink, ...],
    *,
    chapter_id: str,
    revision: int,
    source_hash: str,
    source: _CurrentSource,
) -> None:
    for occurrence in occurrences:
        if occurrence.narrative_sequence != source.narrative_sequence:
            raise ValueError("occurrence narrative sequence is invalid")
        _ranges_match_source(
            occurrence.source_ranges,
            chapter_id=chapter_id,
            revision=revision,
            source_hash=source_hash,
            content_length=len(source.content),
        )
    for link in links:
        _ranges_match_source(
            link.source_ranges,
            chapter_id=chapter_id,
            revision=revision,
            source_hash=source_hash,
            content_length=len(source.content),
        )


def _ranges_match_source(
    ranges: tuple[OccurrenceSourceRange, ...]
    | tuple[SubjectOccurrenceLinkSourceRange, ...],
    *,
    chapter_id: str,
    revision: int,
    source_hash: str,
    content_length: int,
) -> None:
    if any(
        value.source_chapter_id != chapter_id
        or value.source_revision != revision
        or value.source_hash != source_hash
        or value.source_end > content_length
        for value in ranges
    ):
        raise ValueError("occurrence source range is outside source")


def _occurrence_identity_values(occurrence: Occurrence) -> tuple[object, ...]:
    return (
        occurrence.id,
        occurrence.candidate_source_id,
        occurrence.type_code.value,
        occurrence.vocabulary_version,
        occurrence.title,
        occurrence.summary,
        occurrence.narrative_sequence,
        occurrence.authority.value,
        occurrence.review_status.value,
        occurrence.source_type.value,
        int(occurrence.stale),
        int(occurrence.source_changed),
    )


def _occurrence_values(occurrence: Occurrence) -> tuple[object, ...]:
    return (
        *_occurrence_identity_values(occurrence),
        occurrence.created_at.isoformat(),
        occurrence.updated_at.isoformat(),
    )


def _link_identity_values(link: SubjectOccurrenceLink) -> tuple[object, ...]:
    return (
        link.id,
        link.candidate_source_id,
        link.occurrence_id,
        link.subject_id,
        link.role,
        link.subject_summary,
        link.authority.value,
        link.review_status.value,
        link.source_type.value,
        int(link.stale),
        int(link.source_changed),
    )


def _link_values(link: SubjectOccurrenceLink) -> tuple[object, ...]:
    return (
        *_link_identity_values(link),
        link.created_at.isoformat(),
        link.updated_at.isoformat(),
    )


def _stored_timestamps_are_valid(created_at: object, updated_at: object) -> bool:
    if not isinstance(created_at, str) or not isinstance(updated_at, str):
        return False
    try:
        parsed_created_at = datetime.fromisoformat(created_at)
        parsed_updated_at = datetime.fromisoformat(updated_at)
        return (
            parsed_created_at.utcoffset() is not None
            and parsed_updated_at.utcoffset() is not None
            and parsed_updated_at >= parsed_created_at
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _occurrence_range_values(
    occurrence_id: str,
    value: OccurrenceSourceRange,
) -> tuple[object, ...]:
    return (
        occurrence_id,
        value.ordinal,
        value.source_chapter_id,
        value.source_revision,
        value.source_hash,
        value.semantic_window_source_id,
        value.policy_version,
        value.source_start,
        value.source_end,
    )


def _link_range_values(
    link_id: str,
    value: SubjectOccurrenceLinkSourceRange,
) -> tuple[object, ...]:
    return (
        link_id,
        value.ordinal,
        value.source_chapter_id,
        value.source_revision,
        value.source_hash,
        value.semantic_window_source_id,
        value.policy_version,
        value.source_start,
        value.source_end,
    )


def _record_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("occurrence chapter ID is invalid")
    try:
        return validate_id(value)
    except ValueError:
        raise ValueError("occurrence chapter ID is invalid") from None


def _revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("occurrence source revision is invalid")
    return value


def _source_hash(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("occurrence source hash is invalid")
    return value


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


__all__ = [
    "OccurrenceRepository",
    "OccurrenceRepositoryError",
]
