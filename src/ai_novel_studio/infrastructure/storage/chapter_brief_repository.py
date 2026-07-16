from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from ai_novel_studio.core.brief.source_fingerprint import (
    BriefSourceSnapshot,
    compute_source_fingerprint,
)
from ai_novel_studio.domain.generation import (
    BriefSource,
    BriefStatus,
    ChapterBrief,
    CreationMode,
)
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class StaleBriefError(RuntimeError):
    pass


class ImmutableBriefError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class BriefDraftData:
    chapter_id: str
    mode: CreationMode
    dramatic_purpose: str
    target_length: int
    story_date: str
    pov_character_id: str | None
    hard_events: tuple[str, ...]
    soft_goals: tuple[str, ...]
    prohibited_changes: tuple[str, ...]
    creative_freedom: tuple[str, ...]
    participants: tuple[str, ...]
    knowledge: tuple[str, ...]
    clue_actions: tuple[str, ...]
    style_rules: tuple[str, ...]
    warnings: tuple[str, ...]

    @classmethod
    def from_brief(cls, brief: ChapterBrief) -> BriefDraftData:
        return cls(
            brief.chapter_id,
            brief.mode,
            brief.dramatic_purpose,
            brief.target_length,
            brief.story_date,
            brief.pov_character_id,
            brief.hard_events,
            brief.soft_goals,
            brief.prohibited_changes,
            brief.creative_freedom,
            brief.participants,
            brief.knowledge,
            brief.clue_actions,
            brief.style_rules,
            brief.warnings,
        )


def _now() -> datetime:
    return datetime.now(UTC)


def compute_brief_content_hash(data: BriefDraftData) -> str:
    payload = {
        "chapter_id": data.chapter_id,
        "mode": data.mode.value,
        "dramatic_purpose": data.dramatic_purpose,
        "target_length": data.target_length,
        "story_date": data.story_date,
        "pov_character_id": data.pov_character_id,
        "hard_events": data.hard_events,
        "soft_goals": data.soft_goals,
        "prohibited_changes": data.prohibited_changes,
        "creative_freedom": data.creative_freedom,
        "participants": data.participants,
        "knowledge": data.knowledge,
        "clue_actions": data.clue_actions,
        "style_rules": data.style_rules,
        "warnings": data.warnings,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ChapterBriefRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def create_draft(
        self,
        data: BriefDraftData,
        sources: tuple[BriefSourceSnapshot, ...],
        *,
        cloned_from_id: str | None = None,
    ) -> ChapterBrief:
        now = _now()
        brief_id = new_id()
        fingerprint = compute_source_fingerprint(sources)
        content_hash = compute_brief_content_hash(data)
        with self.project.database.connect() as connection, connection:
            chapter = connection.execute(
                "SELECT id FROM chapters WHERE id = ? AND is_deleted = 0", (data.chapter_id,)
            ).fetchone()
            if chapter is None:
                raise KeyError(f"unknown active chapter: {data.chapter_id}")
            connection.execute(
                """
                INSERT INTO chapter_briefs (
                    id, chapter_id, mode, status, revision, dramatic_purpose,
                    target_length, story_date, pov_character_id, hard_events_json,
                    soft_goals_json, prohibited_changes_json, creative_freedom_json,
                    participants_json, knowledge_json, clue_actions_json, style_rules_json,
                    warnings_json, source_fingerprint, content_hash, cloned_from_id,
                    created_at, updated_at, frozen_at
                ) VALUES (
                    ?, ?, ?, 'DRAFT', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, NULL
                )
                """,
                self._draft_values(brief_id, data, fingerprint, content_hash, cloned_from_id, now),
            )
            self._insert_sources(connection, brief_id, sources)
        return self.get(brief_id)

    def update_draft(
        self,
        brief_id: str,
        data: BriefDraftData,
        *,
        expected_revision: int,
    ) -> ChapterBrief:
        existing = self.get(brief_id)
        if existing.status != BriefStatus.DRAFT:
            raise ImmutableBriefError("冻结、过期或归档的 Brief 不能直接修改")
        if existing.chapter_id != data.chapter_id:
            raise ValueError("Brief 不能移动到其他章节")
        now = _now().isoformat()
        values = self._content_values(data)
        with self.project.database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE chapter_briefs SET
                    mode = ?, dramatic_purpose = ?, target_length = ?, story_date = ?,
                    pov_character_id = ?, hard_events_json = ?, soft_goals_json = ?,
                    prohibited_changes_json = ?, creative_freedom_json = ?,
                    participants_json = ?, knowledge_json = ?, clue_actions_json = ?,
                    style_rules_json = ?, warnings_json = ?, content_hash = ?,
                    revision = revision + 1, updated_at = ?
                WHERE id = ? AND status = 'DRAFT' AND revision = ?
                """,
                (*values, compute_brief_content_hash(data), now, brief_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise StaleBriefError(
                    f"Brief 修订已变化，提交修订为 {expected_revision}"
                )
        return self.get(brief_id)

    def freeze(self, brief_id: str, *, expected_revision: int) -> ChapterBrief:
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            row = connection.execute(
                "SELECT chapter_id FROM chapter_briefs WHERE id = ?", (brief_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown Brief: {brief_id}")
            connection.execute(
                """
                UPDATE chapter_briefs SET status = 'ARCHIVED', revision = revision + 1,
                    updated_at = ?
                WHERE chapter_id = ? AND status = 'FROZEN' AND id != ?
                """,
                (now, row["chapter_id"], brief_id),
            )
            cursor = connection.execute(
                """
                UPDATE chapter_briefs SET status = 'FROZEN', revision = revision + 1,
                    frozen_at = ?, updated_at = ?
                WHERE id = ? AND status = 'DRAFT' AND revision = ?
                """,
                (now, now, brief_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise StaleBriefError(
                    f"Brief 修订已变化，提交修订为 {expected_revision}"
                )
        return self.get(brief_id)

    def mark_stale_for_source(
        self,
        source_type: str,
        source_id: str,
        source_revision: int,
        source_hash: str,
    ) -> tuple[str, ...]:
        with self.project.database.connect() as connection, connection:
            rows = connection.execute(
                """
                SELECT b.id FROM chapter_briefs b
                JOIN brief_sources s ON s.brief_id = b.id
                WHERE b.status = 'FROZEN' AND s.source_type = ? AND s.source_id = ?
                  AND (s.source_revision != ? OR s.source_hash != ?)
                ORDER BY b.id
                """,
                (source_type, source_id, source_revision, source_hash),
            ).fetchall()
            affected = tuple(row["id"] for row in rows)
            if affected:
                placeholders = ",".join("?" for _ in affected)
                connection.execute(
                    f"""
                    UPDATE chapter_briefs SET status = 'STALE', revision = revision + 1,
                        updated_at = ? WHERE id IN ({placeholders})
                    """,
                    (_now().isoformat(), *affected),
                )
        return affected

    def get(self, brief_id: str) -> ChapterBrief:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM chapter_briefs WHERE id = ?", (brief_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown Brief: {brief_id}")
        return self._brief(row)

    def list_for_chapter(
        self, chapter_id: str, status: BriefStatus | None = None
    ) -> tuple[ChapterBrief, ...]:
        sql = "SELECT * FROM chapter_briefs WHERE chapter_id = ?"
        parameters: tuple[object, ...] = (chapter_id,)
        if status is not None:
            sql += " AND status = ?"
            parameters += (status.value,)
        sql += " ORDER BY created_at, id"
        with self.project.database.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return tuple(self._brief(row) for row in rows)

    def list_sources(self, brief_id: str) -> tuple[BriefSource, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM brief_sources WHERE brief_id = ? ORDER BY rowid", (brief_id,)
            ).fetchall()
        return tuple(self._source(row) for row in rows)

    @staticmethod
    def _insert_sources(
        connection: sqlite3.Connection,
        brief_id: str,
        sources: tuple[BriefSourceSnapshot, ...],
    ) -> None:
        for source in sources:
            connection.execute(
                "INSERT INTO brief_sources VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id(),
                    brief_id,
                    source.source_type,
                    source.source_id,
                    source.source_revision,
                    source.source_hash,
                    int(source.required),
                ),
            )

    @classmethod
    def _draft_values(
        cls,
        brief_id: str,
        data: BriefDraftData,
        fingerprint: str,
        content_hash: str,
        cloned_from_id: str | None,
        now: datetime,
    ) -> tuple[object, ...]:
        return (
            brief_id,
            data.chapter_id,
            data.mode.value,
            data.dramatic_purpose,
            data.target_length,
            data.story_date,
            data.pov_character_id,
            *cls._json_values(data),
            fingerprint,
            content_hash,
            cloned_from_id,
            now.isoformat(),
            now.isoformat(),
        )

    @classmethod
    def _content_values(cls, data: BriefDraftData) -> tuple[object, ...]:
        return (
            data.mode.value,
            data.dramatic_purpose,
            data.target_length,
            data.story_date,
            data.pov_character_id,
            *cls._json_values(data),
        )

    @staticmethod
    def _json_values(data: BriefDraftData) -> tuple[str, ...]:
        return tuple(
            json.dumps(value, ensure_ascii=False)
            for value in (
                data.hard_events,
                data.soft_goals,
                data.prohibited_changes,
                data.creative_freedom,
                data.participants,
                data.knowledge,
                data.clue_actions,
                data.style_rules,
                data.warnings,
            )
        )

    @staticmethod
    def _brief(row: sqlite3.Row) -> ChapterBrief:
        return ChapterBrief(
            row["id"],
            row["chapter_id"],
            CreationMode(row["mode"]),
            BriefStatus(row["status"]),
            int(row["revision"]),
            row["dramatic_purpose"],
            int(row["target_length"]),
            row["story_date"],
            row["pov_character_id"],
            tuple(json.loads(row["hard_events_json"])),
            tuple(json.loads(row["soft_goals_json"])),
            tuple(json.loads(row["prohibited_changes_json"])),
            tuple(json.loads(row["creative_freedom_json"])),
            tuple(json.loads(row["participants_json"])),
            tuple(json.loads(row["knowledge_json"])),
            tuple(json.loads(row["clue_actions_json"])),
            tuple(json.loads(row["style_rules_json"])),
            tuple(json.loads(row["warnings_json"])),
            row["source_fingerprint"],
            row["content_hash"],
            row["cloned_from_id"],
            datetime.fromisoformat(row["created_at"]),
            datetime.fromisoformat(row["updated_at"]),
            datetime.fromisoformat(row["frozen_at"]) if row["frozen_at"] else None,
        )

    @staticmethod
    def _source(row: sqlite3.Row) -> BriefSource:
        return BriefSource(
            row["id"],
            row["brief_id"],
            row["source_type"],
            row["source_id"],
            int(row["source_revision"]),
            row["source_hash"],
            bool(row["required"]),
        )
