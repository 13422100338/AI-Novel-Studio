from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import (
    Authority,
    Character,
    CharacterStateEvent,
    KnowledgeItem,
    KnowledgeState,
    KnowledgeStateEvent,
    KnowledgeSubject,
    ReviewStatus,
    SourceType,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.subject_repository import (
    register_character_subject,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


class MemoryConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KnowledgeSnapshotEntry:
    item: KnowledgeItem
    event: KnowledgeStateEvent
    conflicting_events: tuple[KnowledgeStateEvent, ...] = ()


class CharacterMemoryRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def create_character(
        self,
        canonical_name: str,
        aliases: tuple[str, ...] = (),
        profile: str = "",
    ) -> Character:
        character = Character(new_id(), canonical_name, aliases, profile)
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO characters VALUES (?, ?, ?, ?, ?, ?)",
                (
                    character.id,
                    character.canonical_name,
                    json.dumps(character.aliases, ensure_ascii=False),
                    character.profile,
                    now,
                    now,
                ),
            )
            register_character_subject(
                connection,
                character_id=character.id,
                canonical_name=character.canonical_name,
                aliases=character.aliases,
                created_at=now,
                updated_at=now,
            )
        return character

    def get_character(self, character_id: str) -> Character:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT s.id, s.canonical_name, c.profile, a.alias
                FROM subjects s
                JOIN characters c ON c.id = s.id
                LEFT JOIN subject_aliases a ON a.subject_id = s.id
                WHERE s.id = ? AND s.type = 'CHARACTER'
                ORDER BY a.alias, a.id
                """,
                (character_id,),
            ).fetchall()
        if not rows:
            raise KeyError(f"unknown character: {character_id}")
        first = rows[0]
        aliases = tuple(str(row["alias"]) for row in rows if row["alias"] is not None)
        return Character(first["id"], first["canonical_name"], aliases, first["profile"])

    def list_characters(self) -> tuple[Character, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT s.id, s.canonical_name, c.profile, a.alias
                FROM subjects s
                JOIN characters c ON c.id = s.id
                LEFT JOIN subject_aliases a ON a.subject_id = s.id
                WHERE s.type = 'CHARACTER' AND s.active = 1
                ORDER BY s.created_at, s.id, a.alias, a.id
                """
            ).fetchall()
        characters: list[Character] = []
        current_id = ""
        canonical_name = ""
        profile = ""
        aliases: list[str] = []
        for row in rows:
            row_id = str(row["id"])
            if current_id and row_id != current_id:
                characters.append(
                    Character(current_id, canonical_name, tuple(aliases), profile)
                )
                aliases = []
            current_id = row_id
            canonical_name = str(row["canonical_name"])
            profile = str(row["profile"])
            if row["alias"] is not None:
                aliases.append(str(row["alias"]))
        if current_id:
            characters.append(Character(current_id, canonical_name, tuple(aliases), profile))
        return tuple(characters)

    def update_character_profile(self, character_id: str, profile: str) -> Character:
        with self.project.database.connect() as connection, connection:
            cursor = connection.execute(
                "UPDATE characters SET profile = ?, updated_at = ? WHERE id = ?",
                (profile, _now().isoformat(), character_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown character: {character_id}")
        return self.get_character(character_id)

    def append_state(
        self,
        character_id: str,
        chapter_id: str,
        *,
        motivation: str,
        psychology: str,
        current_goal: str,
        relationships: str,
        recent_activity: str,
        confidence: float,
        source_type: SourceType,
        review_status: ReviewStatus,
    ) -> CharacterStateEvent:
        event = CharacterStateEvent(
            id=new_id(),
            character_id=character_id,
            chapter_id=chapter_id,
            motivation=motivation,
            psychology=psychology,
            current_goal=current_goal,
            relationships=relationships,
            recent_activity=recent_activity,
            confidence=confidence,
            source_type=source_type,
            review_status=review_status,
            created_at=_now(),
        )
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO character_state_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.character_id,
                    event.chapter_id,
                    event.motivation,
                    event.psychology,
                    event.current_goal,
                    event.relationships,
                    event.recent_activity,
                    event.confidence,
                    event.source_type.value,
                    event.review_status.value,
                    event.created_at.isoformat(),
                ),
            )
        return event

    def state_history(self, character_id: str) -> tuple[CharacterStateEvent, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.* FROM character_state_events e
                JOIN chapters c ON c.id = e.chapter_id
                JOIN volumes v ON v.id = c.volume_id
                WHERE e.character_id = ? AND c.is_deleted = 0
                ORDER BY v.sort_index, c.sort_index, e.created_at, e.id
                """,
                (character_id,),
            ).fetchall()
        return tuple(self._state(row) for row in rows)

    def state_histories(
        self, character_ids: tuple[str, ...]
    ) -> dict[str, tuple[CharacterStateEvent, ...]]:
        unique_ids = tuple(dict.fromkeys(value for value in character_ids if value))
        if not unique_ids:
            return {}
        placeholders = ", ".join("?" for _ in unique_ids)
        with self.project.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT e.* FROM character_state_events e
                JOIN chapters c ON c.id = e.chapter_id
                JOIN volumes v ON v.id = c.volume_id
                WHERE e.character_id IN ({placeholders})
                  AND c.is_deleted = 0
                ORDER BY e.character_id, v.sort_index, c.sort_index, e.created_at, e.id
                """,
                unique_ids,
            ).fetchall()
        grouped: dict[str, list[CharacterStateEvent]] = {}
        for row in rows:
            grouped.setdefault(str(row["character_id"]), []).append(self._state(row))
        return {character_id: tuple(events) for character_id, events in grouped.items()}

    def state_histories_before_many(
        self,
        character_ids: tuple[str, ...],
        chapter_id: str,
        *,
        inclusive: bool = False,
    ) -> dict[str, tuple[CharacterStateEvent, ...]]:
        """Return reviewed state history before a chapter in one database query."""
        unique_ids = tuple(dict.fromkeys(value for value in character_ids if value))
        if not unique_ids:
            return {}
        comparison = "<=" if inclusive else "<"
        placeholders = ", ".join("?" for _ in unique_ids)
        with self.project.database.connect() as connection:
            target = connection.execute(
                "SELECT 1 FROM chapters WHERE id = ? AND is_deleted = 0", (chapter_id,)
            ).fetchone()
            if target is None:
                raise KeyError(f"unknown chapter: {chapter_id}")
            rows = connection.execute(
                f"""
                WITH target AS (
                    SELECT v.sort_index AS volume_order, c.sort_index AS chapter_order
                    FROM chapters c JOIN volumes v ON v.id = c.volume_id
                    WHERE c.id = ? AND c.is_deleted = 0
                )
                SELECT e.*, v.sort_index AS volume_order, c.sort_index AS chapter_order
                FROM character_state_events e
                JOIN chapters c ON c.id = e.chapter_id
                JOIN volumes v ON v.id = c.volume_id
                CROSS JOIN target t
                WHERE e.character_id IN ({placeholders})
                  AND c.is_deleted = 0
                  AND e.review_status IN ('APPROVED', 'LOCKED')
                  AND ((v.sort_index < t.volume_order) OR
                       (v.sort_index = t.volume_order AND
                        c.sort_index {comparison} t.chapter_order))
                ORDER BY e.character_id, v.sort_index, c.sort_index, e.created_at, e.id
                """,
                (chapter_id, *unique_ids),
            ).fetchall()
        grouped: dict[str, list[CharacterStateEvent]] = {}
        for row in rows:
            grouped.setdefault(str(row["character_id"]), []).append(self._state(row))
        return {character_id: tuple(events) for character_id, events in grouped.items()}

    def state_candidates_before(
        self,
        character_id: str,
        chapter_id: str,
        *,
        inclusive: bool = False,
    ) -> tuple[CharacterStateEvent, ...]:
        rows = self._temporal_rows(
            "character_state_events",
            "character_id",
            character_id,
            chapter_id,
            inclusive=inclusive,
        )
        if not rows:
            return ()
        latest_position = (rows[0]["volume_order"], rows[0]["chapter_order"])
        return tuple(
            self._state(row)
            for row in rows
            if (row["volume_order"], row["chapter_order"]) == latest_position
        )

    def state_candidates_before_many(
        self,
        character_ids: tuple[str, ...],
        chapter_id: str,
        *,
        inclusive: bool = False,
    ) -> dict[str, tuple[CharacterStateEvent, ...]]:
        unique_ids = tuple(dict.fromkeys(value for value in character_ids if value))
        if not unique_ids:
            return {}
        comparison = "<=" if inclusive else "<"
        placeholders = ", ".join("?" for _ in unique_ids)
        with self.project.database.connect() as connection:
            target = connection.execute(
                "SELECT 1 FROM chapters WHERE id = ? AND is_deleted = 0", (chapter_id,)
            ).fetchone()
            if target is None:
                raise KeyError(f"unknown chapter: {chapter_id}")
            rows = connection.execute(
                f"""
                WITH target AS (
                    SELECT v.sort_index AS volume_order, c.sort_index AS chapter_order
                    FROM chapters c JOIN volumes v ON v.id = c.volume_id
                    WHERE c.id = ? AND c.is_deleted = 0
                )
                SELECT e.*, v.sort_index AS volume_order, c.sort_index AS chapter_order
                FROM character_state_events e
                JOIN chapters c ON c.id = e.chapter_id
                JOIN volumes v ON v.id = c.volume_id
                CROSS JOIN target t
                WHERE e.character_id IN ({placeholders})
                  AND c.is_deleted = 0
                  AND e.review_status IN ('APPROVED', 'LOCKED')
                  AND ((v.sort_index < t.volume_order) OR
                       (v.sort_index = t.volume_order AND
                        c.sort_index {comparison} t.chapter_order))
                ORDER BY e.character_id, v.sort_index DESC, c.sort_index DESC,
                         e.created_at DESC, e.id
                """,
                (chapter_id, *unique_ids),
            ).fetchall()
        latest_positions: dict[str, tuple[int, int]] = {}
        grouped: dict[str, list[CharacterStateEvent]] = {}
        for row in rows:
            character_id = str(row["character_id"])
            position = (int(row["volume_order"]), int(row["chapter_order"]))
            latest = latest_positions.setdefault(character_id, position)
            if position == latest:
                grouped.setdefault(character_id, []).append(self._state(row))
        return {character_id: tuple(events) for character_id, events in grouped.items()}

    def state_before(
        self,
        character_id: str,
        chapter_id: str,
        *,
        inclusive: bool = False,
    ) -> CharacterStateEvent | None:
        candidates = self.state_candidates_before(
            character_id, chapter_id, inclusive=inclusive
        )
        if len(candidates) > 1:
            raise MemoryConflictError("同一时间边界存在多个人物状态")
        return candidates[0] if candidates else None

    def create_knowledge_item(
        self,
        title: str,
        detail: str,
        authority: Authority,
        review_status: ReviewStatus,
    ) -> KnowledgeItem:
        if not title.strip() or not detail.strip():
            raise ValueError("知识标题和详情不能为空")
        item = KnowledgeItem(new_id(), title.strip(), detail.strip(), authority, review_status)
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO knowledge_items VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    item.id,
                    item.title,
                    item.detail,
                    item.authority.value,
                    item.review_status.value,
                    now,
                    now,
                ),
            )
        return item

    def append_knowledge_event(
        self,
        knowledge_id: str,
        subject_type: KnowledgeSubject,
        subject_id: str,
        chapter_id: str,
        state: KnowledgeState,
        evidence: str,
        source_type: SourceType,
        review_status: ReviewStatus,
    ) -> KnowledgeStateEvent:
        if subject_type == KnowledgeSubject.READER and subject_id != self.project.project.id:
            raise ValueError("读者知识 subject_id 必须是当前项目 ID")
        if subject_type == KnowledgeSubject.CHARACTER:
            self.get_character(subject_id)
        event = KnowledgeStateEvent(
            new_id(),
            knowledge_id,
            subject_type,
            subject_id,
            chapter_id,
            state,
            evidence,
            source_type,
            review_status,
            _now(),
        )
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO knowledge_state_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.knowledge_id,
                    event.subject_type.value,
                    event.subject_id,
                    event.chapter_id,
                    event.state.value,
                    event.evidence,
                    event.source_type.value,
                    event.review_status.value,
                    event.created_at.isoformat(),
                ),
            )
        return event

    def get_knowledge_entry(self, event_id: str) -> KnowledgeSnapshotEntry:
        with self.project.database.connect() as connection:
            row = connection.execute(
                """
                SELECT e.*, i.title, i.detail, i.authority,
                    i.review_status AS item_review_status
                FROM knowledge_state_events e
                JOIN knowledge_items i ON i.id = e.knowledge_id
                WHERE e.id = ?
                """,
                (event_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown knowledge event: {event_id}")
        return KnowledgeSnapshotEntry(
            self._knowledge_item(row),
            self._knowledge_event(row),
        )

    def knowledge_before(
        self,
        subject_type: KnowledgeSubject,
        subject_id: str,
        chapter_id: str,
        *,
        inclusive: bool = False,
    ) -> tuple[KnowledgeSnapshotEntry, ...]:
        comparison = "<=" if inclusive else "<"
        with self.project.database.connect() as connection:
            rows = connection.execute(
                f"""
                WITH target AS (
                    SELECT v.sort_index AS volume_order, c.sort_index AS chapter_order
                    FROM chapters c JOIN volumes v ON v.id = c.volume_id WHERE c.id = ?
                )
                SELECT e.*, i.title, i.detail, i.authority,
                    i.review_status AS item_review_status,
                    v.sort_index AS volume_order, c.sort_index AS chapter_order
                FROM knowledge_state_events e
                JOIN knowledge_items i ON i.id = e.knowledge_id
                JOIN chapters c ON c.id = e.chapter_id
                JOIN volumes v ON v.id = c.volume_id
                CROSS JOIN target t
                WHERE e.subject_type = ? AND e.subject_id = ?
                  AND e.review_status IN ('APPROVED', 'LOCKED')
                  AND i.review_status IN ('APPROVED', 'LOCKED')
                  AND ((v.sort_index < t.volume_order) OR
                       (v.sort_index = t.volume_order AND
                        c.sort_index {comparison} t.chapter_order))
                ORDER BY e.knowledge_id, v.sort_index DESC, c.sort_index DESC,
                         e.created_at DESC, e.id
                """,
                (chapter_id, subject_type.value, subject_id),
            ).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest.setdefault(row["knowledge_id"], row)
        return tuple(
            KnowledgeSnapshotEntry(self._knowledge_item(row), self._knowledge_event(row))
            for _, row in sorted(latest.items())
        )

    def latest_knowledge_entries(
        self,
        subject_type: KnowledgeSubject,
        subject_id: str,
        *,
        include_review: bool = False,
    ) -> tuple[KnowledgeSnapshotEntry, ...]:
        statuses = "'APPROVED', 'LOCKED', 'REVIEW'" if include_review else "'APPROVED', 'LOCKED'"
        with self.project.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT e.*, i.title, i.detail, i.authority,
                    i.review_status AS item_review_status,
                    v.sort_index AS volume_order, c.sort_index AS chapter_order
                FROM knowledge_state_events e
                JOIN knowledge_items i ON i.id = e.knowledge_id
                JOIN chapters c ON c.id = e.chapter_id
                JOIN volumes v ON v.id = c.volume_id
                WHERE e.subject_type = ? AND e.subject_id = ?
                  AND e.review_status IN ({statuses})
                  AND i.review_status IN ({statuses})
                  AND c.is_deleted = 0
                ORDER BY e.knowledge_id, v.sort_index DESC, c.sort_index DESC,
                         e.created_at DESC, e.id
                """,
                (subject_type.value, subject_id),
            ).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest.setdefault(row["knowledge_id"], row)
        ordered = sorted(
            latest.values(),
            key=lambda row: (
                int(row["volume_order"]),
                int(row["chapter_order"]),
                row["created_at"],
                row["id"],
            ),
        )
        return tuple(
            KnowledgeSnapshotEntry(self._knowledge_item(row), self._knowledge_event(row))
            for row in ordered
        )

    def _temporal_rows(
        self,
        table: str,
        subject_column: str,
        subject_id: str,
        chapter_id: str,
        *,
        inclusive: bool,
    ) -> list[sqlite3.Row]:
        comparison = "<=" if inclusive else "<"
        with self.project.database.connect() as connection:
            target = connection.execute(
                "SELECT 1 FROM chapters WHERE id = ? AND is_deleted = 0", (chapter_id,)
            ).fetchone()
            if target is None:
                raise KeyError(f"unknown chapter: {chapter_id}")
            return connection.execute(
                f"""
                WITH target AS (
                    SELECT v.sort_index AS volume_order, c.sort_index AS chapter_order
                    FROM chapters c JOIN volumes v ON v.id = c.volume_id
                    WHERE c.id = ? AND c.is_deleted = 0
                )
                SELECT e.*, v.sort_index AS volume_order, c.sort_index AS chapter_order
                FROM {table} e
                JOIN chapters c ON c.id = e.chapter_id
                JOIN volumes v ON v.id = c.volume_id
                CROSS JOIN target t
                WHERE e.{subject_column} = ?
                  AND c.is_deleted = 0
                  AND e.review_status IN ('APPROVED', 'LOCKED')
                  AND ((v.sort_index < t.volume_order) OR
                       (v.sort_index = t.volume_order AND
                        c.sort_index {comparison} t.chapter_order))
                ORDER BY v.sort_index DESC, c.sort_index DESC, e.created_at DESC, e.id
                """,
                (chapter_id, subject_id),
            ).fetchall()

    @staticmethod
    def _state(row: sqlite3.Row) -> CharacterStateEvent:
        return CharacterStateEvent(
            row["id"],
            row["character_id"],
            row["chapter_id"],
            row["motivation"],
            row["psychology"],
            row["current_goal"],
            row["relationships"],
            row["recent_activity"],
            float(row["confidence"]),
            SourceType(row["source_type"]),
            ReviewStatus(row["review_status"]),
            _time(row["created_at"]),
        )

    @staticmethod
    def _knowledge_item(row: sqlite3.Row) -> KnowledgeItem:
        return KnowledgeItem(
            row["knowledge_id"],
            row["title"],
            row["detail"],
            Authority(row["authority"]),
            ReviewStatus(row["item_review_status"]),
        )

    @staticmethod
    def _knowledge_event(row: sqlite3.Row) -> KnowledgeStateEvent:
        return KnowledgeStateEvent(
            row["id"],
            row["knowledge_id"],
            KnowledgeSubject(row["subject_type"]),
            row["subject_id"],
            row["chapter_id"],
            KnowledgeState(row["state"]),
            row["evidence"],
            SourceType(row["source_type"]),
            ReviewStatus(row["review_status"]),
            _time(row["created_at"]),
        )
