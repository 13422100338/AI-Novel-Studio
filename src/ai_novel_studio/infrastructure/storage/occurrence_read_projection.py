from __future__ import annotations

import sqlite3
from datetime import datetime

from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType
from ai_novel_studio.domain.occurrence import (
    Occurrence,
    OccurrenceSourceRange,
    OccurrenceType,
    SubjectOccurrenceLink,
    SubjectOccurrenceLinkSourceRange,
)

_OCCURRENCE_COLUMNS = """
    id, candidate_source_id, type_code, vocabulary_version,
    title, summary, narrative_sequence, authority, review_status,
    source_type, stale, source_changed, created_at, updated_at
"""
_LINK_COLUMNS = """
    id, candidate_source_id, occurrence_id, subject_id, role,
    subject_summary, authority, review_status, source_type, stale,
    source_changed, created_at, updated_at
"""
_OCCURRENCE_MEMORY_TYPE = "OCCURRENCE"
_LINK_MEMORY_TYPE = "SUBJECT_OCCURRENCE_LINK"
_CURRENT_DEPENDENCY_STATUSES = frozenset({"CURRENT", "STALE"})


class _OccurrenceReadIntegrityError(RuntimeError):
    _MESSAGES = frozenset(
        {
            "stored occurrence is invalid",
            "stored occurrence link is invalid",
            "occurrence records could not be read",
        }
    )

    def __init__(self, message: str) -> None:
        if message not in self._MESSAGES:
            message = "occurrence records could not be read"
        super().__init__(message)


def _select_occurrence_rows_by_ids(
    connection: sqlite3.Connection,
    ids: tuple[str, ...],
) -> tuple[sqlite3.Row, ...]:
    return _select_rows_by_ids(
        connection,
        table="occurrences",
        columns=_OCCURRENCE_COLUMNS,
        ids=ids,
    )


def _select_link_rows_by_ids(
    connection: sqlite3.Connection,
    ids: tuple[str, ...],
) -> tuple[sqlite3.Row, ...]:
    return _select_rows_by_ids(
        connection,
        table="subject_occurrence_links",
        columns=_LINK_COLUMNS,
        ids=ids,
    )


def _hydrate_records(
    connection: sqlite3.Connection,
    occurrence_rows: tuple[sqlite3.Row, ...] | list[sqlite3.Row],
    link_rows: tuple[sqlite3.Row, ...] | list[sqlite3.Row],
) -> tuple[dict[str, Occurrence], dict[str, SubjectOccurrenceLink]]:
    try:
        occurrence_ids = tuple(_stored_text(row["id"]) for row in occurrence_rows)
    except (KeyError, TypeError, ValueError):
        raise _OccurrenceReadIntegrityError("stored occurrence is invalid") from None
    try:
        link_ids = tuple(_stored_text(row["id"]) for row in link_rows)
        subject_ids = tuple(
            dict.fromkeys(_stored_text(row["subject_id"]) for row in link_rows)
        )
    except (KeyError, TypeError, ValueError):
        raise _OccurrenceReadIntegrityError(
            "stored occurrence link is invalid"
        ) from None
    occurrence_ranges = _occurrence_ranges(connection, occurrence_ids)
    link_ranges = _link_ranges(connection, link_ids)
    dependencies = _dependencies(connection, occurrence_ids, link_ids)
    subject_types = _subject_types(connection, subject_ids)
    occurrences = _hydrate_occurrences(
        occurrence_rows,
        occurrence_ranges,
        dependencies,
    )
    links = _hydrate_links(
        link_rows,
        link_ranges,
        dependencies,
        subject_types,
        occurrences,
    )
    return occurrences, links


def _select_rows_by_ids(
    connection: sqlite3.Connection,
    *,
    table: str,
    columns: str,
    ids: tuple[str, ...],
) -> tuple[sqlite3.Row, ...]:
    if not ids:
        return ()
    placeholders = ", ".join("?" for _value in ids)
    rows = connection.execute(
        f"SELECT {columns} FROM {table} WHERE id IN ({placeholders}) ORDER BY id",
        ids,
    ).fetchall()
    return tuple(rows)


def _hydrate_occurrences(
    rows: tuple[sqlite3.Row, ...] | list[sqlite3.Row],
    ranges: dict[str, tuple[OccurrenceSourceRange, ...]],
    dependencies: dict[tuple[str, str], tuple[sqlite3.Row, ...]],
) -> dict[str, Occurrence]:
    occurrences: dict[str, Occurrence] = {}
    for row in rows:
        try:
            record_id = _stored_text(row["id"])
            occurrence = Occurrence(
                id=record_id,
                candidate_source_id=_stored_text(row["candidate_source_id"]),
                type_code=OccurrenceType(_stored_text(row["type_code"])),
                vocabulary_version=_stored_text(row["vocabulary_version"]),
                title=_stored_text(row["title"]),
                summary=_stored_text(row["summary"]),
                narrative_sequence=_stored_integer(row["narrative_sequence"]),
                authority=Authority(_stored_text(row["authority"])),
                review_status=ReviewStatus(_stored_text(row["review_status"])),
                source_type=SourceType(_stored_text(row["source_type"])),
                stale=_stored_boolean(row["stale"]),
                source_changed=_stored_boolean(row["source_changed"]),
                source_ranges=ranges.get(record_id, ()),
                created_at=datetime.fromisoformat(_stored_text(row["created_at"])),
                updated_at=datetime.fromisoformat(_stored_text(row["updated_at"])),
            )
            _require_dependency(
                dependencies,
                _OCCURRENCE_MEMORY_TYPE,
                occurrence.id,
                occurrence.source_ranges[0],
            )
            if record_id in occurrences:
                raise ValueError
        except (IndexError, KeyError, TypeError, ValueError, OverflowError):
            raise _OccurrenceReadIntegrityError("stored occurrence is invalid") from None
        occurrences[record_id] = occurrence
    return occurrences


def _hydrate_links(
    rows: tuple[sqlite3.Row, ...] | list[sqlite3.Row],
    ranges: dict[str, tuple[SubjectOccurrenceLinkSourceRange, ...]],
    dependencies: dict[tuple[str, str], tuple[sqlite3.Row, ...]],
    subject_types: dict[str, str],
    occurrences: dict[str, Occurrence],
) -> dict[str, SubjectOccurrenceLink]:
    links: dict[str, SubjectOccurrenceLink] = {}
    for row in rows:
        try:
            record_id = _stored_text(row["id"])
            link = SubjectOccurrenceLink(
                id=record_id,
                candidate_source_id=_stored_text(row["candidate_source_id"]),
                occurrence_id=_stored_text(row["occurrence_id"]),
                subject_id=_stored_text(row["subject_id"]),
                role=_stored_text(row["role"]),
                subject_summary=_stored_text(row["subject_summary"]),
                authority=Authority(_stored_text(row["authority"])),
                review_status=ReviewStatus(_stored_text(row["review_status"])),
                source_type=SourceType(_stored_text(row["source_type"])),
                stale=_stored_boolean(row["stale"]),
                source_changed=_stored_boolean(row["source_changed"]),
                source_ranges=ranges.get(record_id, ()),
                created_at=datetime.fromisoformat(_stored_text(row["created_at"])),
                updated_at=datetime.fromisoformat(_stored_text(row["updated_at"])),
            )
            parent = occurrences[link.occurrence_id]
            if subject_types.get(link.subject_id) != "CHARACTER":
                raise ValueError
            parent_source = parent.source_ranges[0]
            link_source = link.source_ranges[0]
            if (
                link_source.source_chapter_id,
                link_source.source_revision,
                link_source.source_hash,
            ) != (
                parent_source.source_chapter_id,
                parent_source.source_revision,
                parent_source.source_hash,
            ):
                raise ValueError
            _require_dependency(
                dependencies,
                _LINK_MEMORY_TYPE,
                link.id,
                link.source_ranges[0],
            )
            if record_id in links:
                raise ValueError
        except (IndexError, KeyError, TypeError, ValueError, OverflowError):
            raise _OccurrenceReadIntegrityError(
                "stored occurrence link is invalid"
            ) from None
        links[record_id] = link
    return links


def _occurrence_ranges(
    connection: sqlite3.Connection,
    occurrence_ids: tuple[str, ...],
) -> dict[str, tuple[OccurrenceSourceRange, ...]]:
    if not occurrence_ids:
        return {}
    placeholders = ", ".join("?" for _value in occurrence_ids)
    rows = connection.execute(
        f"""
        SELECT occurrence_id, ordinal, source_chapter_id, source_revision,
               source_hash, semantic_window_source_id, policy_version,
               source_start, source_end
        FROM occurrence_source_ranges
        WHERE occurrence_id IN ({placeholders})
        ORDER BY occurrence_id, ordinal
        """,
        occurrence_ids,
    ).fetchall()
    grouped: dict[str, list[OccurrenceSourceRange]] = {
        record_id: [] for record_id in occurrence_ids
    }
    try:
        for row in rows:
            record_id = _stored_text(row["occurrence_id"])
            grouped[record_id].append(
                OccurrenceSourceRange(
                    ordinal=_stored_integer(row["ordinal"], allow_zero=True),
                    source_chapter_id=_stored_text(row["source_chapter_id"]),
                    source_revision=_stored_integer(
                        row["source_revision"], allow_zero=True
                    ),
                    source_hash=_stored_text(row["source_hash"]),
                    semantic_window_source_id=_stored_text(
                        row["semantic_window_source_id"]
                    ),
                    policy_version=_stored_text(row["policy_version"]),
                    source_start=_stored_integer(row["source_start"], allow_zero=True),
                    source_end=_stored_integer(row["source_end"]),
                )
            )
    except (KeyError, TypeError, ValueError, OverflowError):
        raise _OccurrenceReadIntegrityError("stored occurrence is invalid") from None
    return {key: tuple(value) for key, value in grouped.items()}


def _link_ranges(
    connection: sqlite3.Connection,
    link_ids: tuple[str, ...],
) -> dict[str, tuple[SubjectOccurrenceLinkSourceRange, ...]]:
    if not link_ids:
        return {}
    placeholders = ", ".join("?" for _value in link_ids)
    rows = connection.execute(
        f"""
        SELECT link_id, ordinal, source_chapter_id, source_revision,
               source_hash, semantic_window_source_id, policy_version,
               source_start, source_end
        FROM subject_occurrence_link_source_ranges
        WHERE link_id IN ({placeholders})
        ORDER BY link_id, ordinal
        """,
        link_ids,
    ).fetchall()
    grouped: dict[str, list[SubjectOccurrenceLinkSourceRange]] = {
        record_id: [] for record_id in link_ids
    }
    try:
        for row in rows:
            record_id = _stored_text(row["link_id"])
            grouped[record_id].append(
                SubjectOccurrenceLinkSourceRange(
                    ordinal=_stored_integer(row["ordinal"], allow_zero=True),
                    source_chapter_id=_stored_text(row["source_chapter_id"]),
                    source_revision=_stored_integer(
                        row["source_revision"], allow_zero=True
                    ),
                    source_hash=_stored_text(row["source_hash"]),
                    semantic_window_source_id=_stored_text(
                        row["semantic_window_source_id"]
                    ),
                    policy_version=_stored_text(row["policy_version"]),
                    source_start=_stored_integer(row["source_start"], allow_zero=True),
                    source_end=_stored_integer(row["source_end"]),
                )
            )
    except (KeyError, TypeError, ValueError, OverflowError):
        raise _OccurrenceReadIntegrityError(
            "stored occurrence link is invalid"
        ) from None
    return {key: tuple(value) for key, value in grouped.items()}


def _dependencies(
    connection: sqlite3.Connection,
    occurrence_ids: tuple[str, ...],
    link_ids: tuple[str, ...],
) -> dict[tuple[str, str], tuple[sqlite3.Row, ...]]:
    predicates: list[str] = []
    parameters: list[object] = []
    if occurrence_ids:
        placeholders = ", ".join("?" for _value in occurrence_ids)
        predicates.append(
            f"(memory_type = '{_OCCURRENCE_MEMORY_TYPE}' "
            f"AND memory_id IN ({placeholders}))"
        )
        parameters.extend(occurrence_ids)
    if link_ids:
        placeholders = ", ".join("?" for _value in link_ids)
        predicates.append(
            f"(memory_type = '{_LINK_MEMORY_TYPE}' "
            f"AND memory_id IN ({placeholders}))"
        )
        parameters.extend(link_ids)
    if not predicates:
        return {}
    rows = connection.execute(
        f"""
        SELECT memory_type, memory_id, source_chapter_id,
               source_revision, source_hash, status
        FROM memory_dependencies
        WHERE {" OR ".join(predicates)}
        ORDER BY memory_type, memory_id, id
        """,
        tuple(parameters),
    ).fetchall()
    grouped: dict[tuple[str, str], list[sqlite3.Row]] = {}
    try:
        for row in rows:
            key = (
                _stored_text(row["memory_type"]),
                _stored_text(row["memory_id"]),
            )
            grouped.setdefault(key, []).append(row)
    except (KeyError, TypeError, ValueError):
        raise _OccurrenceReadIntegrityError(
            "occurrence records could not be read"
        ) from None
    return {key: tuple(value) for key, value in grouped.items()}


def _subject_types(
    connection: sqlite3.Connection,
    subject_ids: tuple[str, ...],
) -> dict[str, str]:
    if not subject_ids:
        return {}
    placeholders = ", ".join("?" for _value in subject_ids)
    rows = connection.execute(
        f"SELECT id, type FROM subjects WHERE id IN ({placeholders}) ORDER BY id",
        subject_ids,
    ).fetchall()
    try:
        return {
            _stored_text(row["id"]): _stored_text(row["type"]) for row in rows
        }
    except (KeyError, TypeError, ValueError):
        raise _OccurrenceReadIntegrityError(
            "stored occurrence link is invalid"
        ) from None


def _require_dependency(
    dependencies: dict[tuple[str, str], tuple[sqlite3.Row, ...]],
    memory_type: str,
    memory_id: str,
    source_range: OccurrenceSourceRange | SubjectOccurrenceLinkSourceRange,
) -> None:
    rows = dependencies.get((memory_type, memory_id), ())
    if len(rows) != 1:
        raise ValueError
    row = rows[0]
    if (
        _stored_text(row["source_chapter_id"]) != source_range.source_chapter_id
        or _stored_integer(row["source_revision"], allow_zero=True)
        != source_range.source_revision
        or _stored_text(row["source_hash"]) != source_range.source_hash
        or _stored_text(row["status"]) not in _CURRENT_DEPENDENCY_STATUSES
    ):
        raise ValueError


def _stored_boolean(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int) or value not in {0, 1}:
        raise ValueError
    return bool(value)


def _stored_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError
    return value


def _stored_integer(value: object, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError
    return value
