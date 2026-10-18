from __future__ import annotations

import sqlite3
from collections.abc import Callable


def _migration_24(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE harness_model_request_manifests (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES harness_runs(id),
            step_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('AGENT', 'CHAPTER_DRAFT', 'COMPACTION')),
            provider_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            prompt_revision TEXT NOT NULL,
            project_constitution_revision INTEGER,
            project_policy_revision INTEGER,
            writing_profile_revision INTEGER,
            toolset_revision INTEGER,
            skill_revisions_json TEXT NOT NULL DEFAULT '[]',
            editor_snapshot_revision INTEGER,
            context_manifest_id TEXT,
            conversation_summary_revision INTEGER,
            global_prefix_hash TEXT NOT NULL,
            project_prefix_hash TEXT NOT NULL,
            run_prefix_hash TEXT NOT NULL,
            source_artifacts_json TEXT NOT NULL DEFAULT '[]',
            input_token_estimate INTEGER,
            cached_input_tokens INTEGER,
            cache_status TEXT NOT NULL CHECK(
                cache_status IN ('ACCURATE', 'ESTIMATED', 'UNKNOWN')
            ),
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX harness_manifests_run "
        "ON harness_model_request_manifests(run_id, created_at)",
    )
    for statement in statements:
        connection.execute(statement)


MIGRATIONS_V24: dict[int, Callable[[sqlite3.Connection], None]] = {24: _migration_24}
