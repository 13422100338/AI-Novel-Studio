import sqlite3

import pytest

from ai_novel_studio.infrastructure.storage.migration_manager import (
    LATEST_SCHEMA_VERSION,
    MigrationManager,
    _migration_1,
    _migration_2,
    _migration_3,
    _migration_4,
)


def test_schema_v5_adds_agent_trace_tables() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _migration_1(connection)
    _migration_2(connection)
    _migration_3(connection)
    _migration_4(connection)
    connection.execute("PRAGMA user_version = 4")

    MigrationManager(connection).migrate()

    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    indexes = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }

    assert version == LATEST_SCHEMA_VERSION == 14
    assert {"agent_runs", "agent_turns", "agent_tool_calls"} <= tables
    assert "agent_runs_chapter" in indexes
    assert "agent_tool_calls_run" in indexes


def test_agent_schema_rejects_invalid_status_and_sequences() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    MigrationManager(connection).migrate()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO agent_runs(
                id, purpose, status, model_provider_id, model_id, prompt_version,
                max_iterations, max_tool_calls, max_tool_result_chars, started_at, updated_at
            ) VALUES ('r1', 'PLOT_DISCUSSION', 'BAD', 'p', 'm', 'v', 1, 0, 1, 't', 't')
            """
        )

    connection.execute(
        """
        INSERT INTO agent_runs(
            id, purpose, status, model_provider_id, model_id, prompt_version,
            max_iterations, max_tool_calls, max_tool_result_chars, started_at, updated_at
        ) VALUES ('r2', 'PLOT_DISCUSSION', 'PREPARING', 'p', 'm', 'v', 1, 0, 1, 't', 't')
        """
    )
    connection.execute(
        """
        INSERT INTO agent_turns(id, run_id, sequence, role, content, content_hash, created_at)
        VALUES ('t1', 'r2', 0, 'USER', 'hello', 'hash', 't')
        """
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO agent_turns(id, run_id, sequence, role, content, content_hash, created_at)
            VALUES ('t2', 'r2', 0, 'USER', 'again', 'hash', 't')
            """
        )
