from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime

from ai_novel_studio.domain.agent import (
    AgentPurpose,
    AgentRun,
    AgentRunStatus,
    AgentToolCall,
    AgentToolCallStatus,
    AgentToolName,
    AgentTurn,
    AgentTurnRole,
)
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class AgentRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def create_run(
        self,
        *,
        chapter_id: str | None,
        purpose: AgentPurpose,
        status: AgentRunStatus,
        model_provider_id: str,
        model_id: str,
        prompt_version: str,
        max_iterations: int,
        max_tool_calls: int,
        max_tool_result_chars: int,
    ) -> AgentRun:
        run_id = new_id()
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO agent_runs(
                    id, chapter_id, purpose, status, model_provider_id, model_id,
                    prompt_version, max_iterations, max_tool_calls, max_tool_result_chars,
                    started_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    chapter_id,
                    purpose.value,
                    status.value,
                    model_provider_id,
                    model_id,
                    prompt_version,
                    max_iterations,
                    max_tool_calls,
                    max_tool_result_chars,
                    now,
                    now,
                ),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> AgentRun:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown agent run: {run_id}")
        return self._run_from_row(row)

    def latest_run(self) -> AgentRun | None:
        """Return the most recently updated persisted Agent run, if any."""
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs ORDER BY updated_at DESC, started_at DESC LIMIT 1"
            ).fetchone()
        return self._run_from_row(row) if row is not None else None

    def update_run_status(
        self,
        run_id: str,
        status: AgentRunStatus,
        *,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> AgentRun:
        now = _now().isoformat()
        completed_at = now if status in {
            AgentRunStatus.COMPLETED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        } else None
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                UPDATE agent_runs
                SET status = ?, updated_at = ?, completed_at = ?,
                    failure_code = ?, failure_message = ?
                WHERE id = ?
                """,
                (status.value, now, completed_at, failure_code, failure_message, run_id),
            )
        return self.get_run(run_id)

    def increment_usage(
        self,
        run_id: str,
        *,
        used_iterations_delta: int = 0,
        used_tool_calls_delta: int = 0,
    ) -> AgentRun:
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                UPDATE agent_runs
                SET used_iterations = used_iterations + ?,
                    used_tool_calls = used_tool_calls + ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (used_iterations_delta, used_tool_calls_delta, now, run_id),
            )
        return self.get_run(run_id)

    def add_turn(
        self,
        run_id: str,
        role: AgentTurnRole,
        content: str,
        *,
        omitted: bool = False,
    ) -> AgentTurn:
        turn_id = new_id()
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            sequence = self._next_sequence(connection, "agent_turns", run_id)
            connection.execute(
                """
                INSERT INTO agent_turns(
                    id, run_id, sequence, role, content, content_hash, omitted, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    run_id,
                    sequence,
                    role.value,
                    content,
                    _hash(content),
                    int(omitted),
                    now,
                ),
            )
        return self.get_turn(turn_id)

    def get_turn(self, turn_id: str) -> AgentTurn:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_turns WHERE id = ?", (turn_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown agent turn: {turn_id}")
        return self._turn_from_row(row)

    def add_tool_call(
        self,
        run_id: str,
        tool_name: AgentToolName | str,
        arguments_json: str,
        *,
        turn_id: str | None = None,
    ) -> AgentToolCall:
        call_id = new_id()
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            sequence = self._next_sequence(connection, "agent_tool_calls", run_id)
            connection.execute(
                """
                INSERT INTO agent_tool_calls(
                    id, run_id, turn_id, sequence, tool_name, arguments_json,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'REQUESTED', ?)
                """,
                (
                    call_id,
                    run_id,
                    turn_id,
                    sequence,
                    tool_name.value if isinstance(tool_name, AgentToolName) else tool_name,
                    arguments_json,
                    now,
                ),
            )
        return self.get_tool_call(call_id)

    def get_tool_call(self, call_id: str) -> AgentToolCall:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_tool_calls WHERE id = ?", (call_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown agent tool call: {call_id}")
        return self._tool_call_from_row(row)

    def complete_tool_call(
        self,
        call_id: str,
        status: AgentToolCallStatus,
        result_json: str,
        result_chars: int,
        source_refs_json: str,
        *,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> AgentToolCall:
        completed_at = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                UPDATE agent_tool_calls
                SET status = ?, result_json = ?, result_chars = ?, source_refs_json = ?,
                    failure_code = ?, failure_message = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    result_json,
                    result_chars,
                    source_refs_json,
                    failure_code,
                    failure_message,
                    completed_at,
                    call_id,
                ),
            )
        return self.get_tool_call(call_id)

    def list_turns(self, run_id: str) -> tuple[AgentTurn, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_turns WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        return tuple(self._turn_from_row(row) for row in rows)

    def list_tool_calls(self, run_id: str) -> tuple[AgentToolCall, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_tool_calls WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        return tuple(self._tool_call_from_row(row) for row in rows)

    @staticmethod
    def _next_sequence(connection: sqlite3.Connection, table: str, run_id: str) -> int:
        row = connection.execute(
            f"SELECT COALESCE(MAX(sequence), -1) + 1 FROM {table} WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> AgentRun:
        return AgentRun(
            row["id"],
            row["chapter_id"],
            AgentPurpose(row["purpose"]),
            AgentRunStatus(row["status"]),
            row["model_provider_id"],
            row["model_id"],
            row["prompt_version"],
            row["max_iterations"],
            row["max_tool_calls"],
            row["max_tool_result_chars"],
            row["used_iterations"],
            row["used_tool_calls"],
            row["input_tokens"],
            row["output_tokens"],
            row["cached_input_tokens"],
            row["reasoning_tokens"],
            row["failure_code"],
            row["failure_message"],
            datetime.fromisoformat(row["started_at"]),
            datetime.fromisoformat(row["updated_at"]),
            datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )

    @staticmethod
    def _turn_from_row(row: sqlite3.Row) -> AgentTurn:
        return AgentTurn(
            row["id"],
            row["run_id"],
            row["sequence"],
            AgentTurnRole(row["role"]),
            row["content"],
            row["content_hash"],
            bool(row["omitted"]),
            datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _tool_call_from_row(row: sqlite3.Row) -> AgentToolCall:
        return AgentToolCall(
            row["id"],
            row["run_id"],
            row["turn_id"],
            row["sequence"],
            AgentToolName(row["tool_name"])
            if row["tool_name"] in {item.value for item in AgentToolName}
            else row["tool_name"],
            row["arguments_json"],
            AgentToolCallStatus(row["status"]),
            row["result_json"],
            row["result_chars"],
            row["source_refs_json"],
            row["failure_code"],
            row["failure_message"],
            datetime.fromisoformat(row["created_at"]),
            datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )
