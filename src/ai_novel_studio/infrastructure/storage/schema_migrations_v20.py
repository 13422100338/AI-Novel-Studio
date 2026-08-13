from __future__ import annotations

import sqlite3
from collections.abc import Callable


def _migration_20(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE occurrences (
            id TEXT PRIMARY KEY,
            candidate_source_id TEXT NOT NULL UNIQUE
                CHECK(length(candidate_source_id) BETWEEN 1 AND 512)
                CHECK(candidate_source_id = trim(candidate_source_id)),
            type_code TEXT NOT NULL
                CHECK(length(type_code) BETWEEN 1 AND 100)
                CHECK(type_code = trim(type_code)),
            vocabulary_version TEXT NOT NULL
                CHECK(length(vocabulary_version) BETWEEN 1 AND 100)
                CHECK(vocabulary_version = trim(vocabulary_version)),
            title TEXT NOT NULL
                CHECK(length(title) BETWEEN 1 AND 500)
                CHECK(length(trim(title)) > 0)
                CHECK(title = trim(title)),
            summary TEXT NOT NULL
                CHECK(length(summary) BETWEEN 1 AND 4000)
                CHECK(length(trim(summary)) > 0)
                CHECK(summary = trim(summary)),
            narrative_sequence INTEGER NOT NULL
                CHECK(narrative_sequence >= 1),
            authority TEXT NOT NULL CHECK(authority = 'MODEL_EXTRACTED'),
            review_status TEXT NOT NULL CHECK(review_status IN (
                'REVIEW', 'APPROVED', 'REJECTED', 'LOCKED'
            )),
            source_type TEXT NOT NULL CHECK(source_type = 'MODEL'),
            stale INTEGER NOT NULL CHECK(stale IN (0, 1)),
            source_changed INTEGER NOT NULL CHECK(source_changed IN (0, 1)),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            updated_at TEXT NOT NULL CHECK(length(trim(updated_at)) > 0)
        )
        """,
        """
        CREATE TABLE occurrence_source_ranges (
            occurrence_id TEXT NOT NULL
                REFERENCES occurrences(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL
                CHECK(ordinal BETWEEN 0 AND 9999),
            source_chapter_id TEXT NOT NULL REFERENCES chapters(id),
            source_revision INTEGER NOT NULL CHECK(source_revision >= 0),
            source_hash TEXT NOT NULL
                CHECK(length(source_hash) = 64)
                CHECK(source_hash NOT GLOB '*[^0-9a-f]*'),
            semantic_window_source_id TEXT NOT NULL
                CHECK(length(semantic_window_source_id) BETWEEN 1 AND 512)
                CHECK(semantic_window_source_id = trim(semantic_window_source_id)),
            policy_version TEXT NOT NULL
                CHECK(length(policy_version) BETWEEN 1 AND 100)
                CHECK(policy_version = trim(policy_version)),
            source_start INTEGER NOT NULL
                CHECK(source_start BETWEEN 0 AND 19999999),
            source_end INTEGER NOT NULL
                CHECK(source_end > source_start AND source_end <= 20000000),
            PRIMARY KEY(occurrence_id, ordinal),
            UNIQUE(
                occurrence_id,
                source_chapter_id,
                source_revision,
                source_hash,
                semantic_window_source_id,
                policy_version,
                source_start,
                source_end
            )
        )
        """,
        """
        CREATE TABLE subject_occurrence_links (
            id TEXT PRIMARY KEY,
            candidate_source_id TEXT NOT NULL UNIQUE
                CHECK(length(candidate_source_id) BETWEEN 1 AND 512)
                CHECK(candidate_source_id = trim(candidate_source_id)),
            occurrence_id TEXT NOT NULL REFERENCES occurrences(id),
            subject_id TEXT NOT NULL REFERENCES subjects(id),
            role TEXT NOT NULL
                CHECK(length(role) BETWEEN 1 AND 100)
                CHECK(length(trim(role)) > 0)
                CHECK(role = trim(role)),
            subject_summary TEXT NOT NULL
                CHECK(length(subject_summary) BETWEEN 1 AND 2000)
                CHECK(length(trim(subject_summary)) > 0)
                CHECK(subject_summary = trim(subject_summary)),
            authority TEXT NOT NULL CHECK(authority = 'MODEL_EXTRACTED'),
            review_status TEXT NOT NULL CHECK(review_status IN (
                'REVIEW', 'APPROVED', 'REJECTED', 'LOCKED'
            )),
            source_type TEXT NOT NULL CHECK(source_type = 'MODEL'),
            stale INTEGER NOT NULL CHECK(stale IN (0, 1)),
            source_changed INTEGER NOT NULL CHECK(source_changed IN (0, 1)),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            updated_at TEXT NOT NULL CHECK(length(trim(updated_at)) > 0),
            UNIQUE(occurrence_id, subject_id)
        )
        """,
        """
        CREATE TABLE subject_occurrence_link_source_ranges (
            link_id TEXT NOT NULL
                REFERENCES subject_occurrence_links(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL
                CHECK(ordinal BETWEEN 0 AND 9999),
            source_chapter_id TEXT NOT NULL REFERENCES chapters(id),
            source_revision INTEGER NOT NULL CHECK(source_revision >= 0),
            source_hash TEXT NOT NULL
                CHECK(length(source_hash) = 64)
                CHECK(source_hash NOT GLOB '*[^0-9a-f]*'),
            semantic_window_source_id TEXT NOT NULL
                CHECK(length(semantic_window_source_id) BETWEEN 1 AND 512)
                CHECK(semantic_window_source_id = trim(semantic_window_source_id)),
            policy_version TEXT NOT NULL
                CHECK(length(policy_version) BETWEEN 1 AND 100)
                CHECK(policy_version = trim(policy_version)),
            source_start INTEGER NOT NULL
                CHECK(source_start BETWEEN 0 AND 19999999),
            source_end INTEGER NOT NULL
                CHECK(source_end > source_start AND source_end <= 20000000),
            PRIMARY KEY(link_id, ordinal),
            UNIQUE(
                link_id,
                source_chapter_id,
                source_revision,
                source_hash,
                semantic_window_source_id,
                policy_version,
                source_start,
                source_end
            )
        )
        """,
        """
        CREATE INDEX occurrences_review_queue
        ON occurrences(
            review_status,
            stale,
            source_changed,
            narrative_sequence,
            id
        )
        """,
        """
        CREATE INDEX occurrence_source_ranges_source
        ON occurrence_source_ranges(
            source_chapter_id,
            source_revision,
            occurrence_id
        )
        """,
        """
        CREATE INDEX subject_occurrence_links_subject_history
        ON subject_occurrence_links(
            subject_id,
            review_status,
            stale,
            source_changed,
            occurrence_id
        )
        """,
        """
        CREATE INDEX subject_occurrence_link_source_ranges_source
        ON subject_occurrence_link_source_ranges(
            source_chapter_id,
            source_revision,
            link_id
        )
        """,
    )
    for statement in statements:
        connection.execute(statement)


MIGRATIONS_V20: dict[int, Callable[[sqlite3.Connection], None]] = {
    20: _migration_20,
}
