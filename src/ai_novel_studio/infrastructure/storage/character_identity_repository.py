from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import cast

from ai_novel_studio.domain.character_identity import (
    CharacterIdentityMerge,
    CharacterIdentityReviewDecision,
    CharacterIdentityReviewDecisionType,
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
from ai_novel_studio.infrastructure.storage.subject_repository import (
    merge_character_subjects,
    reverse_character_subject_merge,
)


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
            self._character(connection, source_character_id)
            self._character(connection, target_character_id)
            self._assert_merge_shape(connection, source_character_id, target_character_id)

            source_name, source_aliases = self._subject_identity(
                connection, source_character_id
            )
            target_name, target_aliases_before = self._subject_identity(
                connection, target_character_id
            )
            target_aliases_after = self._merged_aliases(
                target_name,
                target_aliases_before,
                source_name,
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
            view_subject_assertion_ids = self._ids_for(
                connection,
                "SELECT id FROM view_assertions WHERE subject_id = ? ORDER BY id",
                source_character_id,
            )
            view_viewer_assertion_ids = self._ids_for(
                connection,
                "SELECT id FROM view_assertions WHERE viewer_subject_id = ? ORDER BY id",
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
            connection.execute(
                "UPDATE view_assertions SET subject_id = ?, updated_at = ? "
                "WHERE subject_id = ?",
                (target_character_id, now, source_character_id),
            )
            connection.execute(
                "UPDATE view_assertions SET viewer_subject_id = ?, updated_at = ? "
                "WHERE viewer_subject_id = ?",
                (target_character_id, now, source_character_id),
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
            merge_character_subjects(
                connection,
                source_character_id=source_character_id,
                target_character_id=target_character_id,
                aliases=tuple(
                    alias
                    for alias in target_aliases_after
                    if alias not in target_aliases_before
                ),
                updated_at=now,
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
                    source_name,
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
            self._record_view_assertion_moves(
                connection,
                merge_id=merge_id,
                subject_assertion_ids=view_subject_assertion_ids,
                viewer_assertion_ids=view_viewer_assertion_ids,
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
            self._character(connection, merge.target_character_id)
            _, target_aliases = self._subject_identity(
                connection, merge.target_character_id
            )
            if target_aliases != merge.target_aliases_after:
                raise CharacterIdentityRepositoryError("目标人物卡在归并后又被修改，不能自动撤销")
            self._assert_rows_still_moved(connection, merge)
            view_subject_ids, view_viewer_ids = self._view_assertion_move_ids(
                connection, merge.id
            )
            self._assert_ids_point_to(
                connection,
                "view_assertions",
                "subject_id",
                view_subject_ids,
                merge.target_character_id,
            )
            self._assert_ids_point_to(
                connection,
                "view_assertions",
                "viewer_subject_id",
                view_viewer_ids,
                merge.target_character_id,
            )

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
            self._restore_view_assertion_ids(
                connection,
                "subject_id",
                view_subject_ids,
                merge.source_character_id,
                now,
            )
            self._restore_view_assertion_ids(
                connection,
                "viewer_subject_id",
                view_viewer_ids,
                merge.source_character_id,
                now,
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
            reverse_character_subject_merge(
                connection,
                source_character_id=merge.source_character_id,
                target_character_id=merge.target_character_id,
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

    def list_recent_applied(self, *, limit: int = 20) -> tuple[CharacterIdentityMerge, ...]:
        if limit < 1:
            return ()
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM character_identity_merges "
                "WHERE status = 'APPLIED' ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(self._merge(row) for row in rows)

    def set_review_decision(
        self,
        first_character_id: str,
        second_character_id: str,
        decision: CharacterIdentityReviewDecisionType,
        *,
        reason: str = "",
    ) -> CharacterIdentityReviewDecision:
        first_id, second_id = self._ordered_pair(first_character_id, second_character_id)
        now = datetime.now(UTC).isoformat()
        with self.project.database.connect() as connection, connection:
            self._character(connection, first_id)
            self._character(connection, second_id)
            connection.execute(
                """
                INSERT INTO character_identity_review_decisions (
                    first_character_id, second_character_id, decision, reason,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(first_character_id, second_character_id) DO UPDATE SET
                    decision = excluded.decision,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (first_id, second_id, decision.value, reason.strip(), now, now),
            )
        return self.get_review_decision(first_id, second_id)

    def get_review_decision(
        self, first_character_id: str, second_character_id: str
    ) -> CharacterIdentityReviewDecision:
        first_id, second_id = self._ordered_pair(first_character_id, second_character_id)
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM character_identity_review_decisions "
                "WHERE first_character_id = ? AND second_character_id = ?",
                (first_id, second_id),
            ).fetchone()
        if row is None:
            raise KeyError("不存在人物冲突审查决定")
        return self._review_decision(row)

    def list_active_review_decisions(
        self,
    ) -> tuple[CharacterIdentityReviewDecision, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM character_identity_review_decisions "
                "WHERE decision IN ('DISTINCT', 'DEFERRED') "
                "ORDER BY updated_at DESC, first_character_id, second_character_id"
            ).fetchall()
        return tuple(self._review_decision(row) for row in rows)

    @staticmethod
    def _ordered_pair(first_character_id: str, second_character_id: str) -> tuple[str, str]:
        values = first_character_id.strip(), second_character_id.strip()
        if not values[0] or not values[1]:
            raise CharacterIdentityRepositoryError("人物 ID 不能为空")
        if values[0] == values[1]:
            raise CharacterIdentityRepositoryError("不能对同一张人物卡创建冲突决定")
        return (min(values), max(values))

    @staticmethod
    def _review_decision(row: sqlite3.Row) -> CharacterIdentityReviewDecision:
        return CharacterIdentityReviewDecision(
            first_character_id=row["first_character_id"],
            second_character_id=row["second_character_id"],
            decision=CharacterIdentityReviewDecisionType(row["decision"]),
            reason=row["reason"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

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
    def _subject_identity(
        connection: sqlite3.Connection, character_id: str
    ) -> tuple[str, tuple[str, ...]]:
        row = connection.execute(
            "SELECT canonical_name FROM subjects "
            "WHERE id = ? AND type = 'CHARACTER'",
            (character_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"不存在人物主体：{character_id}")
        aliases = tuple(
            str(alias_row["alias"])
            for alias_row in connection.execute(
                "SELECT alias FROM subject_aliases WHERE subject_id = ? "
                "ORDER BY alias, id",
                (character_id,),
            ).fetchall()
        )
        return str(row["canonical_name"]), aliases

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
            sorted(
                dict.fromkeys(
                    value
                    for value in (*target_aliases, source_name, *source_aliases)
                    if value and value != target_name
                )
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
    def _record_view_assertion_moves(
        connection: sqlite3.Connection,
        *,
        merge_id: str,
        subject_assertion_ids: tuple[str, ...],
        viewer_assertion_ids: tuple[str, ...],
    ) -> None:
        connection.executemany(
            "INSERT INTO character_identity_merge_view_assertions "
            "(merge_id, assertion_id, reference_role) VALUES (?, ?, ?)",
            (
                *(
                    (merge_id, assertion_id, "SUBJECT")
                    for assertion_id in subject_assertion_ids
                ),
                *(
                    (merge_id, assertion_id, "VIEWER")
                    for assertion_id in viewer_assertion_ids
                ),
            ),
        )

    @staticmethod
    def _restore_view_assertion_ids(
        connection: sqlite3.Connection,
        column: str,
        ids: tuple[str, ...],
        value: str,
        updated_at: str,
    ) -> None:
        if not ids:
            return
        placeholders = ", ".join("?" for _ in ids)
        connection.execute(
            f"UPDATE view_assertions SET {column} = ?, updated_at = ? "
            f"WHERE id IN ({placeholders})",
            (value, updated_at, *ids),
        )

    @staticmethod
    def _view_assertion_move_ids(
        connection: sqlite3.Connection, merge_id: str
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        rows = connection.execute(
            "SELECT assertion_id, reference_role "
            "FROM character_identity_merge_view_assertions "
            "WHERE merge_id = ? ORDER BY reference_role, assertion_id",
            (merge_id,),
        ).fetchall()
        return (
            tuple(
                str(row["assertion_id"])
                for row in rows
                if row["reference_role"] == "SUBJECT"
            ),
            tuple(
                str(row["assertion_id"])
                for row in rows
                if row["reference_role"] == "VIEWER"
            ),
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
