from __future__ import annotations

import sqlite3
from datetime import datetime

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.subject import Subject, SubjectAlias, SubjectType
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def register_character_subject(
    connection: sqlite3.Connection,
    *,
    character_id: str,
    canonical_name: str,
    aliases: tuple[str, ...],
    created_at: str,
    updated_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO subjects (
            id, type, canonical_name, active, created_at, updated_at
        ) VALUES (?, 'CHARACTER', ?, 1, ?, ?)
        """,
        (character_id, canonical_name, created_at, updated_at),
    )
    registry_aliases = tuple(
        dict.fromkeys(
            alias.strip()
            for alias in aliases
            if alias.strip() and alias.strip() != canonical_name
        )
    )
    for alias in registry_aliases:
        connection.execute(
            """
            INSERT INTO subject_aliases (
                id, subject_id, alias, source_id, confirmed
            ) VALUES (?, ?, ?, ?, 1)
            """,
            (new_id(), character_id, alias, character_id),
        )


def merge_character_subjects(
    connection: sqlite3.Connection,
    *,
    source_character_id: str,
    target_character_id: str,
    aliases: tuple[str, ...],
    updated_at: str,
) -> None:
    source_cursor = connection.execute(
        "UPDATE subjects SET active = 0, updated_at = ? "
        "WHERE id = ? AND type = 'CHARACTER' AND active = 1",
        (updated_at, source_character_id),
    )
    target_cursor = connection.execute(
        "UPDATE subjects SET updated_at = ? "
        "WHERE id = ? AND type = 'CHARACTER' AND active = 1",
        (updated_at, target_character_id),
    )
    if source_cursor.rowcount != 1 or target_cursor.rowcount != 1:
        raise KeyError("character subject is missing or inactive")
    for alias in tuple(dict.fromkeys(value.strip() for value in aliases if value.strip())):
        connection.execute(
            """
            INSERT INTO subject_aliases (
                id, subject_id, alias, source_id, confirmed
            ) VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(subject_id, alias) DO NOTHING
            """,
            (new_id(), target_character_id, alias, source_character_id),
        )


def reverse_character_subject_merge(
    connection: sqlite3.Connection,
    *,
    source_character_id: str,
    target_character_id: str,
    updated_at: str,
) -> None:
    source_cursor = connection.execute(
        "UPDATE subjects SET active = 1, updated_at = ? "
        "WHERE id = ? AND type = 'CHARACTER' AND active = 0",
        (updated_at, source_character_id),
    )
    target_cursor = connection.execute(
        "UPDATE subjects SET updated_at = ? "
        "WHERE id = ? AND type = 'CHARACTER' AND active = 1",
        (updated_at, target_character_id),
    )
    if source_cursor.rowcount != 1 or target_cursor.rowcount != 1:
        raise KeyError("character subject merge state is inconsistent")
    connection.execute(
        "DELETE FROM subject_aliases WHERE subject_id = ? AND source_id = ?",
        (target_character_id, source_character_id),
    )


class SubjectRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def get(self, subject_id: str) -> Subject:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM subjects WHERE id = ?", (subject_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown subject: {subject_id}")
        return self._subject(row)

    def list_aliases(self, subject_id: str) -> tuple[SubjectAlias, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM subject_aliases WHERE subject_id = ? "
                "ORDER BY alias, id",
                (subject_id,),
            ).fetchall()
        return tuple(self._alias(row) for row in rows)

    def list_active_characters(self) -> tuple[Subject, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM subjects "
                "WHERE type = 'CHARACTER' AND active = 1 "
                "ORDER BY created_at, id"
            ).fetchall()
        return tuple(self._subject(row) for row in rows)

    def resolve_character_name(self, name: str) -> tuple[Subject, ...]:
        normalized = name.strip()
        if not normalized:
            return ()
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT s.*
                FROM subjects s
                LEFT JOIN subject_aliases a ON a.subject_id = s.id
                WHERE s.type = 'CHARACTER'
                  AND s.active = 1
                  AND (s.canonical_name = ? OR a.alias = ?)
                ORDER BY s.created_at, s.id
                """,
                (normalized, normalized),
            ).fetchall()
        return tuple(self._subject(row) for row in rows)

    @staticmethod
    def _subject(row: sqlite3.Row) -> Subject:
        return Subject(
            id=str(row["id"]),
            type=SubjectType(str(row["type"])),
            canonical_name=str(row["canonical_name"]),
            active=bool(row["active"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _alias(row: sqlite3.Row) -> SubjectAlias:
        return SubjectAlias(
            id=str(row["id"]),
            subject_id=str(row["subject_id"]),
            alias=str(row["alias"]),
            source_id=str(row["source_id"]),
            confirmed=bool(row["confirmed"]),
        )
