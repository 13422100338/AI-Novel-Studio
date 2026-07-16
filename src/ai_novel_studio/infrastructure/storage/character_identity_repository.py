from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import cast

from ai_novel_studio.domain.character_identity import (
    CharacterIdentityMerge,
    CharacterMergeStatus,
    MovedBriefReference,
)
from ai_novel_studio.domain.generation import CreationMode
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    BriefDraftData,
    compute_brief_content_hash,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class CharacterIdentityRepositoryError(RuntimeError):
    pass


class CharacterIdentityRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def apply_merge(
        self, source_character_id: str, target_character_id: str, *, reason: str
    ) -> CharacterIdentityMerge:
        if not reason.strip():
            raise CharacterIdentityRepositoryError("人物归并原因不能为空")
        now = datetime.now(UTC).isoformat()
        merge_id = new_id()
        with self.project.database.connect() as connection, connection:
            source = self._character(connection, source_character_id)
            target = self._character(connection, target_character_id)
            self._assert_merge_shape(connection, source_character_id, target_character_id)

            source_aliases = self._text_tuple(source["aliases_json"])
            target_aliases_before = self._text_tuple(target["aliases_json"])
            target_aliases_after = self._merged_aliases(
                target["canonical_name"],
                target_aliases_before,
                source["canonical_name"],
                source_aliases,
            )
            state_ids = self._ids_for(
                connection,
                "SELECT id FROM character_state_events WHERE character_id = ? ORDER BY id",
                source_character_id,
            )
            knowledge_ids = self._ids_for(
                connection,
                "SELECT id FROM knowledge_state_events "
                "WHERE subject_type = 'CHARACTER' AND subject_id = ? ORDER BY id",
                source_character_id,
            )
            brief_rows = connection.execute(
                "SELECT * FROM chapter_briefs WHERE pov_character_id = ? ORDER BY id",
                (source_character_id,),
            ).fetchall()

            connection.execute(
                "UPDATE characters SET aliases_json = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(target_aliases_after, ensure_ascii=False),
                    now,
                    target_character_id,
                ),
            )
            connection.execute(
                "UPDATE character_state_events SET character_id = ? WHERE character_id = ?",
                (target_character_id, source_character_id),
            )
            connection.execute(
                "UPDATE knowledge_state_events SET subject_id = ? "
                "WHERE subject_type = 'CHARACTER' AND subject_id = ?",
                (target_character_id, source_character_id),
            )
            moved_briefs = tuple(
                self._move_brief(
                    connection,
                    row,
                    pov_character_id=target_character_id,
                    updated_at=now,
                )
                for row in brief_rows
            )
            connection.execute(
                """
                INSERT INTO character_identity_merges (
                    id, source_character_id, target_character_id, source_canonical_name,
                    source_aliases_json, target_aliases_before_json,
                    target_aliases_after_json, moved_state_event_ids_json,
                    moved_knowledge_event_ids_json, moved_briefs_json, reason, status,
                    created_at, reversed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'APPLIED', ?, NULL)
                """,
                (
                    merge_id,
                    source_character_id,
                    target_character_id,
                    source["canonical_name"],
                    json.dumps(source_aliases, ensure_ascii=False),
                    json.dumps(target_aliases_before, ensure_ascii=False),
                    json.dumps(target_aliases_after, ensure_ascii=False),
                    json.dumps(state_ids),
                    json.dumps(knowledge_ids),
                    self._briefs_json(moved_briefs),
                    reason.strip(),
                    now,
                ),
            )
        return self.get(merge_id)

    def reverse_merge(self, merge_id: str) -> CharacterIdentityMerge:
        now = datetime.now(UTC).isoformat()
        with self.project.database.connect() as connection, connection:
            row = connection.execute(
                "SELECT * FROM character_identity_merges WHERE id = ?", (merge_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"不存在人物归并记录：{merge_id}")
            merge = self._merge(row)
            if merge.status != CharacterMergeStatus.APPLIED:
                raise CharacterIdentityRepositoryError("该人物归并已经撤销")
            target = self._character(connection, merge.target_character_id)
            if self._text_tuple(target["aliases_json"]) != merge.target_aliases_after:
                raise CharacterIdentityRepositoryError("目标人物卡在归并后又被修改，不能自动撤销")
            self._assert_rows_still_moved(connection, merge)

            connection.execute(
                "UPDATE characters SET aliases_json = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(merge.target_aliases_before, ensure_ascii=False),
                    now,
                    merge.target_character_id,
                ),
            )
            self._restore_ids(
                connection,
                "character_state_events",
                "character_id",
                merge.moved_state_event_ids,
                merge.source_character_id,
            )
            self._restore_ids(
                connection,
                "knowledge_state_events",
                "subject_id",
                merge.moved_knowledge_event_ids,
                merge.source_character_id,
            )
            for moved in merge.moved_briefs:
                current = connection.execute(
                    "SELECT * FROM chapter_briefs WHERE id = ?", (moved.id,)
                ).fetchone()
                if current is None:  # pragma: no cover - checked above in the transaction
                    raise CharacterIdentityRepositoryError("待撤销的 Brief 已不存在")
                self._move_brief(
                    connection,
                    current,
                    pov_character_id=merge.source_character_id,
                    updated_at=now,
                )
            connection.execute(
                "UPDATE character_identity_merges "
                "SET status = 'REVERSED', reversed_at = ? WHERE id = ?",
                (now, merge.id),
            )
        return self.get(merge_id)

    def get(self, merge_id: str) -> CharacterIdentityMerge:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM character_identity_merges WHERE id = ?", (merge_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"不存在人物归并记录：{merge_id}")
        return self._merge(row)

    @staticmethod
    def _character(connection: sqlite3.Connection, character_id: str) -> sqlite3.Row:
        row = cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT * FROM characters WHERE id = ?", (character_id,)
            ).fetchone(),
        )
        if row is None:
            raise KeyError(f"不存在人物卡：{character_id}")
        return row

    @staticmethod
    def _assert_merge_shape(
        connection: sqlite3.Connection, source_character_id: str, target_character_id: str
    ) -> None:
        active_source = connection.execute(
            "SELECT 1 FROM character_identity_merges "
            "WHERE source_character_id = ? AND status = 'APPLIED'",
            (source_character_id,),
        ).fetchone()
        if active_source is not None:
            raise CharacterIdentityRepositoryError("来源人物卡已经归并")
        hidden_target = connection.execute(
            "SELECT 1 FROM character_identity_merges "
            "WHERE source_character_id = ? AND status = 'APPLIED'",
            (target_character_id,),
        ).fetchone()
        if hidden_target is not None:
            raise CharacterIdentityRepositoryError("目标人物卡已经归并到其他人物")
        source_has_children = connection.execute(
            "SELECT 1 FROM character_identity_merges "
            "WHERE target_character_id = ? AND status = 'APPLIED'",
            (source_character_id,),
        ).fetchone()
        if source_has_children is not None:
            raise CharacterIdentityRepositoryError("来源人物卡已有归并成员，请直接选择最终主卡")

    @staticmethod
    def _merged_aliases(
        target_name: str,
        target_aliases: tuple[str, ...],
        source_name: str,
        source_aliases: tuple[str, ...],
    ) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                value
                for value in (*target_aliases, source_name, *source_aliases)
                if value and value != target_name
            )
        )

    @staticmethod
    def _ids_for(
        connection: sqlite3.Connection, sql: str, character_id: str
    ) -> tuple[str, ...]:
        return tuple(
            str(row["id"])
            for row in connection.execute(sql, (character_id,)).fetchall()
        )

    @classmethod
    def _move_brief(
        cls,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        pov_character_id: str,
        updated_at: str,
    ) -> MovedBriefReference:
        data = cls._brief_data(row, pov_character_id)
        revision_after = int(row["revision"]) + 1
        content_hash_after = compute_brief_content_hash(data)
        cursor = connection.execute(
            "UPDATE chapter_briefs SET pov_character_id = ?, content_hash = ?, "
            "revision = ?, updated_at = ? WHERE id = ? AND revision = ?",
            (
                pov_character_id,
                content_hash_after,
                revision_after,
                updated_at,
                row["id"],
                row["revision"],
            ),
        )
        if cursor.rowcount != 1:
            raise CharacterIdentityRepositoryError("Brief 在人物归并期间发生变化")
        return MovedBriefReference(str(row["id"]), revision_after, content_hash_after)

    @staticmethod
    def _brief_data(row: sqlite3.Row, pov_character_id: str) -> BriefDraftData:
        return BriefDraftData(
            chapter_id=row["chapter_id"],
            mode=CreationMode(row["mode"]),
            dramatic_purpose=row["dramatic_purpose"],
            target_length=int(row["target_length"]),
            story_date=row["story_date"],
            pov_character_id=pov_character_id,
            hard_events=tuple(json.loads(row["hard_events_json"])),
            soft_goals=tuple(json.loads(row["soft_goals_json"])),
            prohibited_changes=tuple(json.loads(row["prohibited_changes_json"])),
            creative_freedom=tuple(json.loads(row["creative_freedom_json"])),
            participants=tuple(json.loads(row["participants_json"])),
            knowledge=tuple(json.loads(row["knowledge_json"])),
            clue_actions=tuple(json.loads(row["clue_actions_json"])),
            style_rules=tuple(json.loads(row["style_rules_json"])),
            warnings=tuple(json.loads(row["warnings_json"])),
        )

    @classmethod
    def _assert_rows_still_moved(
        cls, connection: sqlite3.Connection, merge: CharacterIdentityMerge
    ) -> None:
        cls._assert_ids_point_to(
            connection,
            "character_state_events",
            "character_id",
            merge.moved_state_event_ids,
            merge.target_character_id,
        )
        cls._assert_ids_point_to(
            connection,
            "knowledge_state_events",
            "subject_id",
            merge.moved_knowledge_event_ids,
            merge.target_character_id,
            extra=" AND subject_type = 'CHARACTER'",
        )
        for brief in merge.moved_briefs:
            row = connection.execute(
                "SELECT pov_character_id, revision, content_hash FROM chapter_briefs WHERE id = ?",
                (brief.id,),
            ).fetchone()
            if (
                row is None
                or row["pov_character_id"] != merge.target_character_id
                or int(row["revision"]) != brief.revision_after
                or row["content_hash"] != brief.content_hash_after
            ):
                raise CharacterIdentityRepositoryError("Brief 在归并后又被修改，不能自动撤销")

    @staticmethod
    def _assert_ids_point_to(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        ids: tuple[str, ...],
        expected_id: str,
        *,
        extra: str = "",
    ) -> None:
        if not ids:
            return
        placeholders = ", ".join("?" for _ in ids)
        count = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE id IN ({placeholders}) "
                f"AND {column} = ?{extra}",
                (*ids, expected_id),
            ).fetchone()[0]
        )
        if count != len(ids):
            raise CharacterIdentityRepositoryError("人物引用在归并后又被修改，不能自动撤销")

    @staticmethod
    def _restore_ids(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        ids: tuple[str, ...],
        value: str,
    ) -> None:
        if not ids:
            return
        placeholders = ", ".join("?" for _ in ids)
        connection.execute(
            f"UPDATE {table} SET {column} = ? WHERE id IN ({placeholders})",
            (value, *ids),
        )

    @staticmethod
    def _text_tuple(payload: str) -> tuple[str, ...]:
        values = json.loads(payload)
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise CharacterIdentityRepositoryError("人物归并记录中的文本列表无效")
        return tuple(dict.fromkeys(value for value in values if value))

    @staticmethod
    def _briefs_json(values: tuple[MovedBriefReference, ...]) -> str:
        return json.dumps(
            [
                {
                    "id": value.id,
                    "revision_after": value.revision_after,
                    "content_hash_after": value.content_hash_after,
                }
                for value in values
            ],
            ensure_ascii=False,
            sort_keys=True,
        )

    @classmethod
    def _merge(cls, row: sqlite3.Row) -> CharacterIdentityMerge:
        raw_briefs = json.loads(row["moved_briefs_json"])
        if not isinstance(raw_briefs, list):
            raise CharacterIdentityRepositoryError("人物归并记录中的 Brief 列表无效")
        try:
            briefs = tuple(
                MovedBriefReference(
                    str(item["id"]),
                    int(item["revision_after"]),
                    str(item["content_hash_after"]),
                )
                for item in raw_briefs
                if isinstance(item, dict)
            )
        except (KeyError, TypeError, ValueError) as error:
            raise CharacterIdentityRepositoryError(
                "人物归并记录中的 Brief 条目无效"
            ) from error
        if len(briefs) != len(raw_briefs):
            raise CharacterIdentityRepositoryError("人物归并记录中的 Brief 条目无效")
        return CharacterIdentityMerge(
            id=row["id"],
            source_character_id=row["source_character_id"],
            target_character_id=row["target_character_id"],
            source_canonical_name=row["source_canonical_name"],
            source_aliases=cls._text_tuple(row["source_aliases_json"]),
            target_aliases_before=cls._text_tuple(row["target_aliases_before_json"]),
            target_aliases_after=cls._text_tuple(row["target_aliases_after_json"]),
            moved_state_event_ids=cls._text_tuple(row["moved_state_event_ids_json"]),
            moved_knowledge_event_ids=cls._text_tuple(
                row["moved_knowledge_event_ids_json"]
            ),
            moved_briefs=briefs,
            reason=row["reason"],
            status=CharacterMergeStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            reversed_at=(
                datetime.fromisoformat(row["reversed_at"])
                if row["reversed_at"]
                else None
            ),
        )
