from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

from ai_novel_studio.application.memory_workspace_service import (
    MemoryWorkspaceField,
    MemoryWorkspaceRecord,
)
from ai_novel_studio.domain.memory import (
    Authority,
    CharacterStateEvent,
    ClueAction,
    ClueType,
    KnowledgeState,
    MemoryStatus,
    ReviewStatus,
    SourceType,
    StyleScope,
    SummaryLevel,
    SummaryNode,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


class ProjectMemoryWorkspaceGateway:
    """Adapter from project memory repositories to the review workspace UI."""

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project
        self.summaries = SummaryRepository(project)
        self.characters = CharacterMemoryRepository(project)
        self.chapters = ChapterRepository(project)
        self._loaded_records: dict[str, MemoryWorkspaceRecord] = {}

    def load_before(self, chapter_id: str) -> tuple[MemoryWorkspaceRecord, ...]:
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
        try:
            promoted = self._summary_record(
                self.summaries.promote(record_id, expected_revision=expected_revision)
            )
        except KeyError:
            promoted = self._promote_structured_candidate(record_id, expected_revision)
        self._loaded_records[promoted.id] = promoted
        return promoted

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
            if source_type == "CHARACTER_STATE":
                self._update_character_state(connection, record_id, normalized)
            elif source_type == "CANON":
                self._update_canon(connection, record_id, normalized)
            elif source_type == "CLUE_EVENT":
                self._update_clue(connection, record_id, normalized)
            elif source_type == "KNOWLEDGE_EVENT":
                self._update_knowledge(connection, record_id, normalized)
            elif source_type == "STYLE_RULE":
                self._update_style_rule(connection, record_id, normalized)
            else:
                raise PermissionError("该记忆类型不支持结构化编辑")
        return self._reload_record(record_id)

    @staticmethod
    def _required(fields: dict[str, str], *keys: str) -> tuple[str, ...]:
        values = tuple(fields.get(key, "").strip() for key in keys)
        if any(not value for value in values):
            raise ValueError("结构化记忆的必填字段不能为空")
        return values

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
        title, detail = cls._required(fields, "title", "detail")
        cursor = connection.execute(
            "UPDATE canon_entries SET title = ?, detail = ?, authority = 'USER_CONFIRMED', "
            "review_status = 'APPROVED', updated_at = ? "
            "WHERE id = ? AND review_status != 'LOCKED'",
            (title, detail, cls._now(), record_id),
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

    @classmethod
    def _update_style_rule(
        cls, connection: sqlite3.Connection, record_id: str, fields: dict[str, str]
    ) -> None:
        scope_type, scope_id, rule_type, rule_text = cls._required(
            fields, "scope_type", "scope_id", "rule_type", "rule_text"
        )
        StyleScope(scope_type)
        cursor = connection.execute(
            "UPDATE style_rules SET scope_type = ?, scope_id = ?, rule_type = ?, "
            "rule_text = ?, authority = 'USER_CONFIRMED', review_status = 'APPROVED' "
            ", updated_at = ? WHERE id = ? AND review_status != 'LOCKED'",
            (scope_type, scope_id, rule_type, rule_text, cls._now(), record_id),
        )
        cls._assert_updated(cursor.rowcount, record_id)

    @staticmethod
    def _assert_updated(rowcount: int, record_id: str) -> None:
        if rowcount != 1:
            raise KeyError(f"不存在可修改的记忆记录：{record_id}")

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _reload_record(self, record_id: str) -> MemoryWorkspaceRecord:
        for record in self.load_before("__all__"):
            if record.id == record_id:
                return record
        raise KeyError(f"修改后无法重新载入记忆记录：{record_id}")

    def _promote_structured_candidate(
        self, record_id: str, expected_revision: int
    ) -> MemoryWorkspaceRecord:
        if expected_revision != 0:
            raise RuntimeError("结构化记忆候选已变化，请重新打开记忆库")
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
                            row = connection.execute(
                                "SELECT review_status FROM style_rules WHERE id = ?",
                                (record_id,),
                            ).fetchone()
                            if row is None:
                                raise KeyError(f"不存在记忆记录：{record_id}")
                            self._approve_review_row(
                                connection, "style_rules", record_id, row["review_status"]
                            )
        cached = self._loaded_records.get(record_id)
        if cached is None:
            return self._reload_record(record_id)
        return replace(
            cached,
            review_status=ReviewStatus.APPROVED,
            status=MemoryStatus.CURRENT,
            promotable=False,
        )

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
            "style_rules": "UPDATE style_rules SET review_status = 'APPROVED' WHERE id = ?",
        }
        connection.execute(statements[table], (record_id,))

    def _summary_record(self, summary: SummaryNode) -> MemoryWorkspaceRecord:
        fallback = (
            summary.model_profile_id == "local-import-baseline"
            and summary.authority == Authority.MODEL_EXTRACTED
            and summary.review_status == ReviewStatus.REVIEW
            and summary.revision == 0
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
            try:
                chapter = self.chapters.get_chapter(summary.scope_id)
            except KeyError:
                return f"{label}：{summary.scope_id}"
            return f"{label}：{chapter.title}"
        return f"{label}：{summary.scope_id}"

    def _character_state_records(self) -> tuple[MemoryWorkspaceRecord, ...]:
        records: list[MemoryWorkspaceRecord] = []
        for character in self.characters.list_characters():
            for event in self.characters.state_history(character.id):
                records.append(self._character_state_record(character.canonical_name, event))
        return tuple(records)

    def _character_state_record(
        self, character_name: str, event: CharacterStateEvent
    ) -> MemoryWorkspaceRecord:
        try:
            chapter = self.chapters.get_chapter(event.chapter_id)
            chapter_title = chapter.title
            source_revision = chapter.revision
        except KeyError:
            chapter_title = event.chapter_id
            source_revision = None
        content = (
            f"人物：{character_name}\n"
            f"动机：{event.motivation}\n"
            f"心理：{event.psychology}\n"
            f"目标：{event.current_goal}\n"
            f"关系：{event.relationships}\n"
            f"最近活动：{event.recent_activity}"
        )
        status = (
            MemoryStatus.REVIEW
            if event.review_status == ReviewStatus.REVIEW
            else MemoryStatus.CURRENT
        )
        authority = (
            Authority.MODEL_EXTRACTED
            if event.source_type == SourceType.MODEL
            else Authority.USER_CONFIRMED
        )
        return MemoryWorkspaceRecord(
            id=event.id,
            category="人物状态",
            title=f"人物状态：{character_name} / {chapter_title}",
            content=content,
            source_type="CHARACTER_STATE",
            source_chapter_id=event.chapter_id,
            source_revision=source_revision,
            source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            authority=authority,
            review_status=event.review_status,
            status=status,
            revision=0,
            editable=True,
            promotable=event.review_status == ReviewStatus.REVIEW,
            fields=(
                MemoryWorkspaceField("motivation", "当前动机", event.motivation, multiline=True),
                MemoryWorkspaceField("psychology", "心理状态", event.psychology, multiline=True),
                MemoryWorkspaceField(
                    "current_goal", "当前目标", event.current_goal, multiline=True
                ),
                MemoryWorkspaceField(
                    "relationships", "人物关系", event.relationships, multiline=True
                ),
                MemoryWorkspaceField(
                    "recent_activity", "最近活动", event.recent_activity, multiline=True
                ),
            ),
        )

    def _ledger_records(self) -> tuple[MemoryWorkspaceRecord, ...]:
        records: list[MemoryWorkspaceRecord] = []
        with self.project.database.connect() as connection:
            for row in connection.execute(
                "SELECT * FROM canon_entries ORDER BY created_at, id"
            ).fetchall():
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
                        ),
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
            for row in connection.execute(
                """
                SELECT e.*, i.title, i.detail, i.authority,
                       i.review_status AS item_review_status, c.canonical_name
                FROM knowledge_state_events e
                JOIN knowledge_items i ON i.id = e.knowledge_id
                LEFT JOIN characters c
                  ON e.subject_type = 'CHARACTER' AND c.id = e.subject_id
                ORDER BY e.created_at, e.id
                """
            ).fetchall():
                subject = row["canonical_name"] if row["subject_type"] == "CHARACTER" else "读者"
                category = "人物知识" if row["subject_type"] == "CHARACTER" else "读者知识"
                content = (
                    f"认知主体：{subject}\n"
                    f"知识状态：{row['state']}\n"
                    f"知识：{row['title']}\n"
                    f"详情：{row['detail']}\n"
                    f"证据：{row['evidence']}"
                )
                records.append(
                    self._readonly_record(
                        row["id"],
                        category,
                        f"{subject}：{row['title']}",
                        content,
                        "KNOWLEDGE_EVENT",
                        row["chapter_id"],
                        Authority(row["authority"]),
                        ReviewStatus(row["item_review_status"]),
                        MemoryStatus.REVIEW
                        if row["item_review_status"] == "REVIEW"
                        else MemoryStatus.CURRENT,
                        (
                            MemoryWorkspaceField("title", "知识标题", row["title"]),
                            MemoryWorkspaceField(
                                "detail", "知识详情", row["detail"], multiline=True
                            ),
                            MemoryWorkspaceField(
                                "state",
                                "认知状态",
                                row["state"],
                                tuple(item.value for item in KnowledgeState),
                            ),
                            MemoryWorkspaceField(
                                "evidence", "认知证据", row["evidence"], multiline=True
                            ),
                        ),
                    )
                )
            for row in connection.execute(
                "SELECT * FROM style_rules ORDER BY created_at, id"
            ).fetchall():
                content = (
                    f"适用范围：{row['scope_type']} / {row['scope_id']}\n"
                    f"规则类型：{row['rule_type']}\n\n{row['rule_text']}"
                )
                records.append(
                    self._readonly_record(
                        row["id"],
                        "文风候选",
                        f"文风：{row['rule_type']}",
                        content,
                        "STYLE_RULE",
                        row["scope_id"] if row["scope_type"] == "CHAPTER" else None,
                        Authority(row["authority"]),
                        ReviewStatus(row["review_status"]),
                        MemoryStatus(row["status"]),
                        (
                            MemoryWorkspaceField(
                                "scope_type",
                                "适用层级",
                                row["scope_type"],
                                tuple(item.value for item in StyleScope),
                            ),
                            MemoryWorkspaceField("scope_id", "范围 ID", row["scope_id"]),
                            MemoryWorkspaceField("rule_type", "规则类型", row["rule_type"]),
                            MemoryWorkspaceField(
                                "rule_text", "规则正文", row["rule_text"], multiline=True
                            ),
                        ),
                    )
                )
        return tuple(records)

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
    ) -> MemoryWorkspaceRecord:
        source_revision: int | None = None
        if chapter_id:
            try:
                source_revision = self.chapters.get_chapter(chapter_id).revision
            except KeyError:
                source_revision = None
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
        )
