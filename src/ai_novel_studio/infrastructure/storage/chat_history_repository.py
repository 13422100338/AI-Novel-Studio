from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@dataclass(frozen=True, slots=True)
class ChatSession:
    id: str
    title: str
    summary: str
    summarized_through_sequence: int
    summary_revision: int


@dataclass(frozen=True, slots=True)
class ChatMessage:
    id: str
    session_id: str
    sequence: int
    chapter_id: str | None
    role: str
    content: str


class ChatHistoryRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def get_or_create_default(self) -> ChatSession:
        with self.project.database.connect() as connection, connection:
            row = connection.execute(
                "SELECT * FROM chat_sessions ORDER BY created_at, id LIMIT 1"
            ).fetchone()
            if row is None:
                now = datetime.now(UTC).isoformat()
                session_id = new_id()
                connection.execute(
                    "INSERT INTO chat_sessions VALUES (?, ?, '', -1, 0, ?, ?)",
                    (session_id, "剧情商讨", now, now),
                )
                row = connection.execute(
                    "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
                ).fetchone()
        if row is None:  # pragma: no cover - guarded by transaction above
            raise RuntimeError("无法创建项目聊天会话")
        return self._session(row)

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        chapter_id: str | None,
    ) -> ChatMessage:
        normalized = content.strip()
        if role not in {"user", "assistant"} or not normalized:
            raise ValueError("聊天消息必须包含有效角色和正文")
        with self.project.database.connect() as connection, connection:
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), -1) + 1 FROM chat_messages "
                    "WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
            )
            message_id = new_id()
            connection.execute(
                "INSERT INTO chat_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    session_id,
                    sequence,
                    chapter_id,
                    role,
                    normalized,
                    hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return ChatMessage(message_id, session_id, sequence, chapter_id, role, normalized)

    def list_messages(self, session_id: str) -> tuple[ChatMessage, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY sequence",
                (session_id,),
            ).fetchall()
        return tuple(self._message(row) for row in rows)

    def update_summary(
        self,
        session_id: str,
        summary: str,
        *,
        through_sequence: int,
        expected_revision: int,
    ) -> ChatSession:
        if not summary.strip() or through_sequence < 0:
            raise ValueError("聊天摘要和覆盖序号不能为空")
        with self.project.database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE chat_sessions SET summary = ?, summarized_through_sequence = ?,
                    summary_revision = summary_revision + 1, updated_at = ?
                WHERE id = ? AND summary_revision = ?
                """,
                (
                    summary.strip(),
                    through_sequence,
                    datetime.now(UTC).isoformat(),
                    session_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("聊天摘要已经被其他操作更新")
            row = connection.execute(
                "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:  # pragma: no cover
            raise KeyError(session_id)
        return self._session(row)

    @staticmethod
    def _session(row: sqlite3.Row) -> ChatSession:
        return ChatSession(
            row["id"], row["title"], row["summary"],
            row["summarized_through_sequence"], row["summary_revision"]
        )

    @staticmethod
    def _message(row: sqlite3.Row) -> ChatMessage:
        return ChatMessage(
            row["id"], row["session_id"], row["sequence"], row["chapter_id"],
            row["role"], row["content"]
        )
