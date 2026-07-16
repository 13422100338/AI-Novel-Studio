from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

from ai_novel_studio.application.canon_card_context_service import (
    CanonCardCategory,
    CanonCardContextService,
)
from ai_novel_studio.application.memory_workspace_service import (
    MemoryWorkspaceField,
    MemoryWorkspaceRecord,
)
from ai_novel_studio.application.reader_knowledge_summary_service import (
    READER_SUMMARY_OVERRIDE_TITLE,
    READER_SUMMARY_RECORD_ID,
    ReaderKnowledgeSummaryService,
)
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import (
    Authority,
    Character,
    CharacterStateEvent,
    ClueAction,
    ClueType,
    KnowledgeState,
    MemoryStatus,
    ReviewStatus,
    SourceType,
    SummaryLevel,
    SummaryNode,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import (
    MODEL_RETRY_PROFILE_ID,
    SummaryRepository,
)


class ProjectMemoryWorkspaceGateway:
    """Adapter from project memory repositories to the review workspace UI."""

    _CHARACTER_CARD_PREFIX = "character-card:"

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project
        self.summaries = SummaryRepository(project)
        self.characters = CharacterMemoryRepository(project)
        self.reader_summary = ReaderKnowledgeSummaryService(project)
        self._loaded_records: dict[str, MemoryWorkspaceRecord] = {}
        self._chapter_metadata: dict[str, tuple[str, int]] = {}

    def load_before(self, chapter_id: str) -> tuple[MemoryWorkspaceRecord, ...]:
        self._chapter_metadata = self._load_chapter_metadata()
        summaries = self.summaries.list_all()
        if chapter_id != "__all__":
            summaries = tuple(
                summary for summary in summaries if self.summaries.is_before(summary, chapter_id)
            )
        records = [self._summary_record(summary) for summary in summaries]
        if chapter_id == "__all__":
            records.extend(self._character_state_records())
            records.extend(self._ledger_records())
        result = tuple(records)
        self._loaded_records = {record.id: record for record in result}
        return result

    def update_content(
        self, record_id: str, content: str, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        return self._summary_record(
            self.summaries.update_content(
                record_id,
                content,
                SourceType.HUMAN,
                expected_revision=expected_revision,
            )
        )

    def promote(self, record_id: str, expected_revision: int) -> MemoryWorkspaceRecord:
        if record_id == READER_SUMMARY_RECORD_ID:
            return self._promote_reader_summary(expected_revision)
        try:
            promoted = self._summary_record(
                self.summaries.promote(record_id, expected_revision=expected_revision)
            )
        except KeyError:
            promoted = self._promote_structured_candidate(record_id, expected_revision)
        self._loaded_records[promoted.id] = promoted
        return promoted

    def request_model_retry(
        self, record_id: str, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        retried = self._summary_record(
            self.summaries.request_model_retry(
                record_id, expected_revision=expected_revision
            )
        )
        self._loaded_records[retried.id] = retried
        return retried

    def update_fields(
        self,
        record_id: str,
        source_type: str,
        fields: dict[str, str],
        expected_revision: int,
    ) -> MemoryWorkspaceRecord:
        if expected_revision != 0:
            raise RuntimeError("结构化记忆已变化，请重新打开记忆库")
        normalized = {key: value.strip() for key, value in fields.items()}
        with self.project.database.connect() as connection, connection:
            if source_type == "CHARACTER_CARD":
                self._update_character_card(connection, record_id, normalized)
            elif source_type == "CHARACTER_STATE":
                self._update_character_state(connection, record_id, normalized)
            elif source_type == "CANON":
                self._update_canon(connection, record_id, normalized)
            elif source_type == "CLUE_EVENT":
                self._update_clue(connection, record_id, normalized)
            elif source_type == "KNOWLEDGE_EVENT":
                self._update_knowledge(connection, record_id, normalized)
            elif source_type == "READER_SUMMARY":
                self._update_reader_summary(connection, normalized)
            else:
                raise PermissionError("该记忆类型不支持结构化编辑")
        if source_type == "READER_SUMMARY":
            updated = self._reader_summary_record()
            if updated is None:  # pragma: no cover - guarded by the write above
                raise RuntimeError("读者知识摘要保存失败")
            self._loaded_records[updated.id] = updated
            return updated
        return self._reload_record(record_id)

    @staticmethod
    def _required(fields: dict[str, str], *keys: str) -> tuple[str, ...]:
        values = tuple(fields.get(key, "").strip() for key in keys)
        if any(not value for value in values):
            raise ValueError("结构化记忆的必填字段不能为空")
        return values

    @classmethod
    def _update_character_card(
        cls, connection: sqlite3.Connection, record_id: str, fields: dict[str, str]
    ) -> None:
        character_id = cls._character_id_from_card(record_id)
        character = connection.execute(
            "SELECT id FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
        if character is None:
            raise KeyError(f"不存在人物状态卡：{record_id}")

        latest = connection.execute(
            """
            SELECT e.id, e.review_status
            FROM character_state_events e
            JOIN chapters c ON c.id = e.chapter_id
            JOIN volumes v ON v.id = c.volume_id
            WHERE e.character_id = ? AND c.is_deleted = 0
            ORDER BY v.sort_index DESC, c.sort_index DESC, e.created_at DESC, e.id DESC
            LIMIT 1
            """,
            (character_id,),
        ).fetchone()
        if latest is not None and latest["review_status"] == ReviewStatus.LOCKED.value:
            raise PermissionError("锁定的人物状态卡不能修改")

        connection.execute(
            "UPDATE characters SET profile = ?, updated_at = ? WHERE id = ?",
            (fields.get("profile", ""), cls._now(), character_id),
        )
        if latest is None:
            if any(
                fields.get(key, "")
                for key in (
                    "motivation",
                    "psychology",
                    "current_goal",
                    "relationships",
                    "recent_activity",
                )
            ):
                raise ValueError("该人物尚无章节状态；请先在正文页建立人物状态")
            return
        connection.execute(
            "UPDATE character_state_events SET motivation = ?, psychology = ?, "
            "current_goal = ?, relationships = ?, recent_activity = ?, "
            "source_type = 'HUMAN', review_status = 'APPROVED' WHERE id = ?",
            (
                fields.get("motivation", ""),
                fields.get("psychology", ""),
                fields.get("current_goal", ""),
                fields.get("relationships", ""),
                fields.get("recent_activity", ""),
                latest["id"],
            ),
        )

    @classmethod
    def _update_character_state(
        cls, connection: sqlite3.Connection, record_id: str, fields: dict[str, str]
    ) -> None:
        keys = (
            "motivation",
            "psychology",
            "current_goal",
            "relationships",
            "recent_activity",
        )
        values = tuple(fields.get(key, "").strip() for key in keys)
        cursor = connection.execute(
            "UPDATE character_state_events SET motivation = ?, psychology = ?, "
            "current_goal = ?, relationships = ?, recent_activity = ?, "
            "source_type = 'HUMAN', review_status = 'APPROVED' "
            "WHERE id = ? AND review_status != 'LOCKED'",
            (*values, record_id),
        )
        cls._assert_updated(cursor.rowcount, record_id)

    @classmethod
    def _update_canon(
        cls, connection: sqlite3.Connection, record_id: str, fields: dict[str, str]
    ) -> None:
        title, detail, category_title = cls._required(
            fields, "title", "detail", "category"
        )
        category = CanonCardContextService.category_for_display_title(category_title)
        cursor = connection.execute(
            "UPDATE canon_entries SET title = ?, detail = ?, category = ?, "
            "authority = 'USER_CONFIRMED', review_status = 'APPROVED', updated_at = ? "
            "WHERE id = ? AND review_status != 'LOCKED'",
            (title, detail, category.value, cls._now(), record_id),
        )
        cls._assert_updated(cursor.rowcount, record_id)

    @classmethod
    def _update_clue(
        cls, connection: sqlite3.Connection, record_id: str, fields: dict[str, str]
    ) -> None:
        clue_type, title, clue_detail, action = cls._required(
            fields, "clue_type", "title", "clue_detail", "action"
        )
        event_detail = fields.get("event_detail", "").strip()
        ClueType(clue_type)
        ClueAction(action)
        row = connection.execute(
            "SELECT e.clue_id, e.review_status AS event_review_status, "
            "c.review_status AS clue_review_status "
            "FROM narrative_clue_events e JOIN narrative_clues c ON c.id = e.clue_id "
            "WHERE e.id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"不存在叙事线索事件：{record_id}")
        if ReviewStatus.LOCKED.value in {
            row["event_review_status"],
            row["clue_review_status"],
        }:
            raise PermissionError("锁定的叙事线索不能修改")
        connection.execute(
            "UPDATE narrative_clues SET clue_type = ?, title = ?, detail = ?, "
            "authority = 'USER_CONFIRMED', review_status = 'APPROVED', updated_at = ? "
            "WHERE id = ?",
            (clue_type, title, clue_detail, cls._now(), row["clue_id"]),
        )
        connection.execute(
            "UPDATE narrative_clue_events SET action = ?, detail = ?, "
            "source_type = 'HUMAN', review_status = 'APPROVED' WHERE id = ?",
            (action, event_detail, record_id),
        )

    @classmethod
    def _update_knowledge(
        cls, connection: sqlite3.Connection, record_id: str, fields: dict[str, str]
    ) -> None:
        title, detail, state = cls._required(fields, "title", "detail", "state")
        evidence = fields.get("evidence", "").strip()
        KnowledgeState(state)
        row = connection.execute(
            "SELECT e.knowledge_id, e.review_status AS event_review_status, "
            "i.review_status AS item_review_status "
            "FROM knowledge_state_events e JOIN knowledge_items i ON i.id = e.knowledge_id "
            "WHERE e.id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"不存在知识事件：{record_id}")
        if ReviewStatus.LOCKED.value in {
            row["event_review_status"],
            row["item_review_status"],
        }:
            raise PermissionError("锁定的知识记录不能修改")
        connection.execute(
            "UPDATE knowledge_items SET title = ?, detail = ?, authority = 'USER_CONFIRMED', "
            "review_status = 'APPROVED', updated_at = ? WHERE id = ?",
            (title, detail, cls._now(), row["knowledge_id"]),
        )
        connection.execute(
            "UPDATE knowledge_state_events SET state = ?, evidence = ?, "
            "source_type = 'HUMAN', review_status = 'APPROVED' WHERE id = ?",
            (state, evidence, record_id),
        )

    def _update_reader_summary(
        self, connection: sqlite3.Connection, fields: dict[str, str]
    ) -> None:
        (detail,) = self._required(fields, "detail")
        loaded = self._loaded_records.get(READER_SUMMARY_RECORD_ID)
        if loaded is None or loaded.source_chapter_id is None:
            raise RuntimeError("读者知识摘要缺少来源章节，无法保存")
        row = connection.execute(
            "SELECT i.id AS knowledge_id, i.review_status AS item_review_status, "
            "e.id AS event_id, e.review_status AS event_review_status "
            "FROM knowledge_items i JOIN knowledge_state_events e ON e.knowledge_id = i.id "
            "WHERE i.title = ? AND e.subject_type = 'READER' AND e.subject_id = ? "
            "ORDER BY e.created_at DESC, e.id DESC LIMIT 1",
            (READER_SUMMARY_OVERRIDE_TITLE, self.project.project.id),
        ).fetchone()
        now = self._now()
        if row is None:
            knowledge_id = new_id()
            event_id = new_id()
            connection.execute(
                "INSERT INTO knowledge_items VALUES (?, ?, ?, 'USER_CONFIRMED', "
                "'APPROVED', ?, ?)",
                (knowledge_id, READER_SUMMARY_OVERRIDE_TITLE, detail, now, now),
            )
            connection.execute(
                "INSERT INTO knowledge_state_events VALUES (?, ?, 'READER', ?, ?, "
                "'KNOWN', '作者人工维护的读者知识大摘要', 'HUMAN', 'APPROVED', ?)",
                (
                    event_id,
                    knowledge_id,
                    self.project.project.id,
                    loaded.source_chapter_id,
                    now,
                ),
            )
            return
        if ReviewStatus.LOCKED.value in {
            row["item_review_status"],
            row["event_review_status"],
        }:
            raise PermissionError("锁定的读者知识摘要不能修改")
        connection.execute(
            "UPDATE knowledge_items SET detail = ?, authority = 'USER_CONFIRMED', "
            "review_status = 'APPROVED', updated_at = ? WHERE id = ?",
            (detail, now, row["knowledge_id"]),
        )
        connection.execute(
            "UPDATE knowledge_state_events SET chapter_id = ?, state = 'KNOWN', "
            "evidence = '作者人工维护的读者知识大摘要', source_type = 'HUMAN', "
            "review_status = 'APPROVED' WHERE id = ?",
            (loaded.source_chapter_id, row["event_id"]),
        )

    def _promote_reader_summary(self, expected_revision: int) -> MemoryWorkspaceRecord:
        if expected_revision != 0:
            raise RuntimeError("读者知识摘要已变化，请重新打开记忆库")
        with self.project.database.connect() as connection, connection:
            rows = connection.execute(
                "SELECT e.id, e.knowledge_id FROM knowledge_state_events e "
                "JOIN knowledge_items i ON i.id = e.knowledge_id "
                "WHERE e.subject_type = 'READER' AND e.subject_id = ? "
                "AND (e.review_status = 'REVIEW' OR i.review_status = 'REVIEW')",
                (self.project.project.id,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE knowledge_state_events SET review_status = 'APPROVED' WHERE id = ?",
                    (row["id"],),
                )
                connection.execute(
                    "UPDATE knowledge_items SET review_status = 'APPROVED', updated_at = ? "
                    "WHERE id = ?",
                    (self._now(), row["knowledge_id"]),
                )
        updated = self._reader_summary_record()
        if updated is None:
            raise KeyError("不存在可晋升的读者知识摘要")
        self._loaded_records[updated.id] = updated
        return updated

    @staticmethod
    def _assert_updated(rowcount: int, record_id: str) -> None:
        if rowcount != 1:
            raise KeyError(f"不存在可修改的记忆记录：{record_id}")

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _reload_record(self, record_id: str) -> MemoryWorkspaceRecord:
        if record_id == READER_SUMMARY_RECORD_ID:
            record = self._reader_summary_record()
            if record is None:
                raise KeyError("读者知识摘要不存在")
            self._loaded_records[record.id] = record
            return record
        if record_id.startswith(self._CHARACTER_CARD_PREFIX):
            character_id = self._character_id_from_card(record_id)
            record = self._character_card_record(
                self.characters.get_character(character_id),
                self.characters.state_history(character_id),
            )
            self._loaded_records[record.id] = record
            return record
        for record in self.load_before("__all__"):
            if record.id == record_id:
                return record
        raise KeyError(f"修改后无法重新载入记忆记录：{record_id}")

    def _promote_structured_candidate(
        self, record_id: str, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        if expected_revision != 0:
            raise RuntimeError("结构化记忆候选已变化，请重新打开记忆库")
        if record_id.startswith(self._CHARACTER_CARD_PREFIX):
            return self._promote_character_card(record_id)
        with self.project.database.connect() as connection, connection:
            row = connection.execute(
                "SELECT review_status FROM character_state_events WHERE id = ?",
                (record_id,),
            ).fetchone()
            if row is not None:
                self._approve_review_row(
                    connection, "character_state_events", record_id, row["review_status"]
                )
            else:
                row = connection.execute(
                    "SELECT review_status FROM canon_entries WHERE id = ?", (record_id,)
                ).fetchone()
                if row is not None:
                    self._approve_review_row(
                        connection, "canon_entries", record_id, row["review_status"]
                    )
                else:
                    row = connection.execute(
                        "SELECT clue_id, review_status FROM narrative_clue_events WHERE id = ?",
                        (record_id,),
                    ).fetchone()
                    if row is not None:
                        self._approve_review_row(
                            connection,
                            "narrative_clue_events",
                            record_id,
                            row["review_status"],
                        )
                        connection.execute(
                            "UPDATE narrative_clues SET review_status = 'APPROVED' "
                            "WHERE id = ? AND review_status = 'REVIEW'",
                            (row["clue_id"],),
                        )
                    else:
                        row = connection.execute(
                            "SELECT knowledge_id, review_status "
                            "FROM knowledge_state_events WHERE id = ?",
                            (record_id,),
                        ).fetchone()
                        if row is not None:
                            self._approve_review_row(
                                connection,
                                "knowledge_state_events",
                                record_id,
                                row["review_status"],
                            )
                            connection.execute(
                                "UPDATE knowledge_items SET review_status = 'APPROVED' "
                                "WHERE id = ? AND review_status = 'REVIEW'",
                                (row["knowledge_id"],),
                            )
                        else:
                            raise KeyError(f"不存在记忆记录：{record_id}")
        cached = self._loaded_records.get(record_id)
        if cached is None:
            return self._reload_record(record_id)
        return replace(
            cached,
            review_status=ReviewStatus.APPROVED,
            status=MemoryStatus.CURRENT,
            promotable=False,
        )

    def _promote_character_card(self, record_id: str) -> MemoryWorkspaceRecord:
        character_id = self._character_id_from_card(record_id)
        with self.project.database.connect() as connection, connection:
            character = connection.execute(
                "SELECT id FROM characters WHERE id = ?", (character_id,)
            ).fetchone()
            if character is None:
                raise KeyError(f"不存在人物状态卡：{record_id}")
            pending = connection.execute(
                "SELECT COUNT(*) FROM character_state_events "
                "WHERE character_id = ? AND review_status = 'REVIEW'",
                (character_id,),
            ).fetchone()[0]
            if int(pending) == 0:
                raise PermissionError("该人物状态卡没有待审查候选")
            connection.execute(
                "UPDATE character_state_events SET review_status = 'APPROVED' "
                "WHERE character_id = ? AND review_status = 'REVIEW'",
                (character_id,),
            )
        return self._reload_record(record_id)

    @staticmethod
    def _approve_review_row(
        connection: sqlite3.Connection, table: str, record_id: str, review_status: str
    ) -> None:
        if review_status == ReviewStatus.LOCKED.value:
            raise PermissionError("锁定的记忆记录不能修改")
        if review_status != ReviewStatus.REVIEW.value:
            raise PermissionError("只有待审查候选记录可以晋升")
        statements = {
            "character_state_events": (
                "UPDATE character_state_events SET review_status = 'APPROVED' WHERE id = ?"
            ),
            "canon_entries": "UPDATE canon_entries SET review_status = 'APPROVED' WHERE id = ?",
            "narrative_clue_events": (
                "UPDATE narrative_clue_events SET review_status = 'APPROVED' WHERE id = ?"
            ),
            "knowledge_state_events": (
                "UPDATE knowledge_state_events SET review_status = 'APPROVED' WHERE id = ?"
            ),
        }
        connection.execute(statements[table], (record_id,))

    def _summary_record(self, summary: SummaryNode) -> MemoryWorkspaceRecord:
        fallback = (
            summary.model_profile_id in {
                "local-import-baseline",
                MODEL_RETRY_PROFILE_ID,
            }
            and summary.authority == Authority.MODEL_EXTRACTED
            and summary.review_status == ReviewStatus.REVIEW
        )
        return MemoryWorkspaceRecord(
            id=summary.id,
            category="压缩前文",
            title=(
                self._summary_title(summary).replace("章节摘要", "章节摘要（待模型升级）")
                if fallback
                else self._summary_title(summary)
            ),
            content=summary.content,
            source_type="SUMMARY_FALLBACK" if fallback else "SUMMARY",
            source_chapter_id=summary.source_chapter_ids[0] if summary.source_chapter_ids else None,
            source_revision=summary.source_revisions[0][1] if summary.source_revisions else None,
            source_hash=summary.content_hash,
            authority=summary.authority,
            review_status=summary.review_status,
            status=summary.status,
            revision=summary.revision,
            editable=True,
            promotable=summary.review_status == ReviewStatus.REVIEW and not fallback,
        )

    def _summary_title(self, summary: SummaryNode) -> str:
        label = {
            SummaryLevel.CHAPTER: "章节摘要",
            SummaryLevel.ARC: "情节段摘要",
            SummaryLevel.VOLUME: "卷摘要",
            SummaryLevel.BOOK: "全书摘要",
            SummaryLevel.RAW: "原文片段",
        }[summary.level]
        if summary.level == SummaryLevel.CHAPTER:
            chapter = self._chapter_metadata.get(summary.scope_id)
            if chapter is None:
                return f"{label}：{summary.scope_id}"
            return f"{label}：{chapter[0]}"
        return f"{label}：{summary.scope_id}"

    def _character_state_records(self) -> tuple[MemoryWorkspaceRecord, ...]:
        characters = self.characters.list_characters()
        histories = self.characters.state_histories(
            tuple(character.id for character in characters)
        )
        return tuple(
            self._character_card_record(character, histories.get(character.id, ()))
            for character in characters
        )

    def _character_card_record(
        self, character: Character, events: tuple[CharacterStateEvent, ...]
    ) -> MemoryWorkspaceRecord:
        latest = events[-1] if events else None
        pending = any(event.review_status == ReviewStatus.REVIEW for event in events)
        review_status = (
            ReviewStatus.REVIEW
            if pending
            else latest.review_status
            if latest is not None
            else ReviewStatus.APPROVED
        )
        authority = (
            Authority.MODEL_EXTRACTED
            if pending or (latest is not None and latest.source_type == SourceType.MODEL)
            else Authority.USER_CONFIRMED
        )
        journey = self._character_journey_text(events[:-1])
        content = self._character_card_content(character, latest, journey)
        chapter = (
            self._chapter_metadata.get(latest.chapter_id) if latest is not None else None
        )
        return MemoryWorkspaceRecord(
            id=f"{self._CHARACTER_CARD_PREFIX}{character.id}",
            category="人物状态",
            title=f"人物状态：{character.canonical_name}",
            content=content,
            source_type="CHARACTER_CARD",
            source_chapter_id=latest.chapter_id if latest is not None else None,
            source_revision=chapter[1] if chapter is not None else None,
            source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            authority=authority,
            review_status=review_status,
            status=MemoryStatus.REVIEW if pending else MemoryStatus.CURRENT,
            revision=0,
            editable=review_status != ReviewStatus.LOCKED,
            promotable=pending,
            fields=(
                MemoryWorkspaceField(
                    "profile", "性格、语言与动作特点", character.profile, multiline=True
                ),
                MemoryWorkspaceField(
                    "psychology",
                    "目前人物心理",
                    latest.psychology if latest is not None else "",
                    multiline=True,
                ),
                MemoryWorkspaceField(
                    "current_goal",
                    "目前人物目标",
                    latest.current_goal if latest is not None else "",
                    multiline=True,
                ),
                MemoryWorkspaceField(
                    "motivation",
                    "当前动机",
                    latest.motivation if latest is not None else "",
                    multiline=True,
                ),
                MemoryWorkspaceField(
                    "relationships",
                    "与其他人物的关系",
                    latest.relationships if latest is not None else "",
                    multiline=True,
                ),
                MemoryWorkspaceField(
                    "recent_activity",
                    "近期活动",
                    latest.recent_activity if latest is not None else "",
                    multiline=True,
                ),
                MemoryWorkspaceField(
                    "journey",
                    "过往心路历程（由历史状态自动汇总）",
                    journey,
                    multiline=True,
                    editable=False,
                ),
            ),
            group_key=character.id,
        )

    def _character_journey_text(
        self, events: tuple[CharacterStateEvent, ...]
    ) -> str:
        lines: list[str] = []
        for event in events:
            chapter = self._chapter_metadata.get(event.chapter_id)
            chapter_title = chapter[0] if chapter is not None else event.chapter_id
            details = "；".join(
                value
                for value in (
                    f"心理：{event.psychology}" if event.psychology else "",
                    f"目标：{event.current_goal}" if event.current_goal else "",
                    f"活动：{event.recent_activity}" if event.recent_activity else "",
                )
                if value
            )
            if details:
                lines.append(f"- {chapter_title}：{details}")
        return "\n".join(lines) if lines else "暂无可回溯的早期状态"

    @staticmethod
    def _character_card_content(
        character: Character,
        latest: CharacterStateEvent | None,
        journey: str,
    ) -> str:
        return (
            f"人物：{character.canonical_name}\n"
            f"性格、语言与动作特点：{character.profile}\n"
            f"当前心理与目标：{latest.psychology if latest else ''}；"
            f"{latest.current_goal if latest else ''}\n"
            f"当前动机：{latest.motivation if latest else ''}\n"
            f"与其他人物的关系：{latest.relationships if latest else ''}\n"
            f"近期活动：{latest.recent_activity if latest else ''}\n"
            f"过往心路历程：\n{journey}"
        )

    @classmethod
    def _character_id_from_card(cls, record_id: str) -> str:
        if not record_id.startswith(cls._CHARACTER_CARD_PREFIX):
            raise KeyError(f"无效的人物状态卡：{record_id}")
        character_id = record_id.removeprefix(cls._CHARACTER_CARD_PREFIX).strip()
        if not character_id:
            raise KeyError(f"无效的人物状态卡：{record_id}")
        return character_id

    def _ledger_records(self) -> tuple[MemoryWorkspaceRecord, ...]:
        records: list[MemoryWorkspaceRecord] = []
        with self.project.database.connect() as connection:
            for row in connection.execute(
                "SELECT * FROM canon_entries ORDER BY created_at, id"
            ).fetchall():
                canon_category = (
                    CanonCardCategory(row["category"])
                    if row["category"]
                    else CanonCardContextService.category_for_title(row["title"])
                )
                content = f"事实：{row['title']}\n\n详情：{row['detail']}"
                records.append(
                    self._readonly_record(
                        row["id"],
                        "正典事实",
                        f"正典：{row['title']}",
                        content,
                        "CANON",
                        row["source_chapter_id"],
                        Authority(row["authority"]),
                        ReviewStatus(row["review_status"]),
                        MemoryStatus(row["status"]),
                        (
                            MemoryWorkspaceField("title", "事实标题", row["title"]),
                            MemoryWorkspaceField(
                                "detail", "事实详情", row["detail"], multiline=True
                            ),
                            MemoryWorkspaceField(
                                "category",
                                "所属正典卡片",
                                canon_category.display_title,
                                choices=tuple(
                                    item.display_title for item in CanonCardCategory
                                ),
                            ),
                        ),
                        group_key=canon_category.value,
                    )
                )
            for row in connection.execute(
                """
                SELECT e.*, c.title, c.detail AS clue_detail, c.clue_type, c.authority,
                       c.status, c.review_status AS clue_review_status
                FROM narrative_clue_events e
                JOIN narrative_clues c ON c.id = e.clue_id
                ORDER BY e.created_at, e.id
                """
            ).fetchall():
                content = (
                    f"类型：{row['clue_type']}\n"
                    f"线索：{row['title']}\n"
                    f"线索说明：{row['clue_detail']}\n"
                    f"本章动作：{row['action']}\n"
                    f"本章证据：{row['detail']}"
                )
                records.append(
                    self._readonly_record(
                        row["id"],
                        "伏笔与叙事线索",
                        f"{row['action']}：{row['title']}",
                        content,
                        "CLUE_EVENT",
                        row["chapter_id"],
                        Authority(row["authority"]),
                        ReviewStatus(row["clue_review_status"]),
                        MemoryStatus(row["status"]),
                        (
                            MemoryWorkspaceField(
                                "clue_type",
                                "线索类型",
                                row["clue_type"],
                                tuple(item.value for item in ClueType),
                            ),
                            MemoryWorkspaceField("title", "线索标题", row["title"]),
                            MemoryWorkspaceField(
                                "clue_detail", "线索说明", row["clue_detail"], multiline=True
                            ),
                            MemoryWorkspaceField(
                                "action",
                                "本章动作",
                                row["action"],
                                tuple(item.value for item in ClueAction),
                            ),
                            MemoryWorkspaceField(
                                "event_detail", "本章证据", row["detail"], multiline=True
                            ),
                        ),
                    )
                )
        reader_summary = self._reader_summary_record()
        if reader_summary is not None:
            records.append(reader_summary)
        return tuple(records)

    def _reader_summary_record(self) -> MemoryWorkspaceRecord | None:
        summary = self.reader_summary.summary_all()
        if summary is None:
            return None
        return self._readonly_record(
            READER_SUMMARY_RECORD_ID,
            "读者知识",
            "读者当前知识摘要",
            summary.content,
            "READER_SUMMARY",
            summary.source_chapter_id,
            summary.authority,
            summary.review_status,
            MemoryStatus.REVIEW
            if summary.review_status == ReviewStatus.REVIEW
            else MemoryStatus.CURRENT,
            (
                MemoryWorkspaceField(
                    "detail",
                    "读者目前知道的内容",
                    summary.content,
                    multiline=True,
                ),
            ),
        )

    def _readonly_record(
        self,
        record_id: str,
        category: str,
        title: str,
        content: str,
        source_type: str,
        chapter_id: str | None,
        authority: Authority,
        review_status: ReviewStatus,
        status: MemoryStatus,
        fields: tuple[MemoryWorkspaceField, ...],
        *,
        group_key: str = "",
    ) -> MemoryWorkspaceRecord:
        source_revision: int | None = None
        if chapter_id:
            chapter = self._chapter_metadata.get(chapter_id)
            source_revision = chapter[1] if chapter is not None else None
        return MemoryWorkspaceRecord(
            id=record_id,
            category=category,
            title=title,
            content=content,
            source_type=source_type,
            source_chapter_id=chapter_id,
            source_revision=source_revision,
            source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            authority=authority,
            review_status=review_status,
            status=status,
            revision=0,
            editable=True,
            promotable=review_status == ReviewStatus.REVIEW,
            fields=fields,
            group_key=group_key,
        )

    def _load_chapter_metadata(self) -> dict[str, tuple[str, int]]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, title, revision FROM chapters WHERE is_deleted = 0"
            ).fetchall()
        return {
            str(row["id"]): (str(row["title"]), int(row["revision"]))
            for row in rows
        }
