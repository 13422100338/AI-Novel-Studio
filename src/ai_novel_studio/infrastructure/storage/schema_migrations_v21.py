from __future__ import annotations

import sqlite3
from collections.abc import Callable


def _migration_21(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE harness_runs (
            id TEXT PRIMARY KEY,
            goal TEXT NOT NULL CHECK(length(trim(goal)) > 0),
            stage TEXT NOT NULL CHECK(stage IN (
                'CREATED', 'TASK_ANALYZED', 'CONTEXT_COMPILED', 'PACKAGE_READY',
                'MODEL_RUNNING', 'DRAFT_SAVED', 'AUDIT_COMPLETED', 'CHANGESET_READY',
                'WAITING_APPROVAL', 'COMPLETED', 'CANCELLED', 'INTERRUPTED',
                'FAILED', 'STALE'
            )),
            active_chapter_id TEXT REFERENCES chapters(id),
            failure_code TEXT,
            failure_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        )
        """,
        """
        CREATE TABLE harness_run_events (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES harness_runs(id),
            sequence INTEGER NOT NULL CHECK(sequence >= 0),
            event_type TEXT NOT NULL CHECK(event_type IN (
                'RUN_CREATED', 'RUN_STARTED', 'RUN_CANCELLED', 'RUN_INTERRUPTED',
                'RUN_FAILED', 'RUN_COMPLETED', 'CONTEXT_COMPILATION_STARTED',
                'CONTEXT_COMPILED', 'CONTEXT_INVALIDATED',
                'CONTEXT_EXTENSION_REQUESTED', 'CONTEXT_RECOMPILE_REQUESTED',
                'CONTEXT_HEALTH_CHANGED', 'MANUAL_CONTEXT_PIN_ADDED',
                'MANUAL_CONTEXT_PIN_REMOVED', 'COMPACTION_STARTED',
                'COMPACTION_COMPLETED', 'SKILL_DISCOVERED', 'SKILL_LOADED',
                'TOOL_SCHEMA_LOADED', 'TOOL_CALL_STARTED', 'TOOL_CALL_COMPLETED',
                'TOOL_CALL_FAILED', 'GENERATION_PACKAGE_READY',
                'CHAPTER_STREAM_STARTED', 'CHAPTER_STREAM_DELTA',
                'CHAPTER_STREAM_CHECKPOINT_SAVED', 'CHAPTER_STREAM_COMPLETED',
                'AUDIT_STARTED', 'AUDIT_COMPLETED', 'CHANGESET_READY',
                'CHANGESET_REBASED', 'CHANGESET_CONFLICTED',
                'APPROVAL_REQUESTED', 'APPROVAL_RESOLVED'
            )),
            schema_version INTEGER NOT NULL CHECK(schema_version >= 1),
            occurred_at TEXT NOT NULL,
            causation_id TEXT,
            correlation_id TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(run_id, sequence)
        )
        """,
        "CREATE INDEX harness_runs_chapter ON harness_runs(active_chapter_id, created_at)",
        "CREATE INDEX harness_run_events_run ON harness_run_events(run_id, sequence)",
    )
    for statement in statements:
        connection.execute(statement)


MIGRATIONS_V21: dict[int, Callable[[sqlite3.Connection], None]] = {21: _migration_21}
