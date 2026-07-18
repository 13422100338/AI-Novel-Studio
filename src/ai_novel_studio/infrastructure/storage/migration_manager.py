import json
import sqlite3
from collections.abc import Callable

LATEST_SCHEMA_VERSION = 15


def _json_string_tuple(value: object, field: str) -> tuple[str, ...]:
    try:
        payload = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"{field} must be a JSON string list") from error
    if not isinstance(payload, list) or not all(
        isinstance(item, str) for item in payload
    ):
        raise ValueError(f"{field} must be a JSON string list")
    return tuple(dict.fromkeys(item.strip() for item in payload if item.strip()))


def _migration_1(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            format_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE volumes (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            synopsis TEXT NOT NULL DEFAULT '',
            sort_index INTEGER NOT NULL CHECK(sort_index >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE chapters (
            id TEXT PRIMARY KEY,
            volume_id TEXT NOT NULL REFERENCES volumes(id),
            declared_number TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            synopsis TEXT NOT NULL DEFAULT '',
            content_path TEXT NOT NULL UNIQUE,
            content_hash TEXT NOT NULL,
            sort_index INTEGER NOT NULL CHECK(sort_index >= 0),
            revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
            memory_status TEXT NOT NULL DEFAULT 'pending',
            is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0, 1)),
            deleted_content_path TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE chapter_versions (
            id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL REFERENCES chapters(id),
            revision INTEGER NOT NULL CHECK(revision >= 0),
            content_snapshot_path TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            UNIQUE(chapter_id, revision)
        )
        """,
        "CREATE INDEX chapters_volume_order ON chapters(volume_id, sort_index)",
    )
    for statement in statements:
        connection.execute(statement)


def _migration_2(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE characters (
            id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            profile TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE character_state_events (
            id TEXT PRIMARY KEY,
            character_id TEXT NOT NULL REFERENCES characters(id),
            chapter_id TEXT NOT NULL REFERENCES chapters(id),
            motivation TEXT NOT NULL DEFAULT '',
            psychology TEXT NOT NULL DEFAULT '',
            current_goal TEXT NOT NULL DEFAULT '',
            relationships TEXT NOT NULL DEFAULT '',
            recent_activity TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            source_type TEXT NOT NULL,
            review_status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE knowledge_items (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            authority TEXT NOT NULL,
            review_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE knowledge_state_events (
            id TEXT PRIMARY KEY,
            knowledge_id TEXT NOT NULL REFERENCES knowledge_items(id),
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            chapter_id TEXT NOT NULL REFERENCES chapters(id),
            state TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL,
            review_status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE canon_entries (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            source_chapter_id TEXT REFERENCES chapters(id) ON DELETE SET NULL,
            source_paragraph_id TEXT,
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            authority TEXT NOT NULL,
            status TEXT NOT NULL,
            review_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE narrative_clues (
            id TEXT PRIMARY KEY,
            clue_type TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            authority TEXT NOT NULL,
            status TEXT NOT NULL,
            review_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE narrative_clue_events (
            id TEXT PRIMARY KEY,
            clue_id TEXT NOT NULL REFERENCES narrative_clues(id),
            chapter_id TEXT NOT NULL REFERENCES chapters(id),
            action TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL,
            review_status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE summary_nodes (
            id TEXT PRIMARY KEY,
            level TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            content TEXT NOT NULL,
            source_chapter_ids_json TEXT NOT NULL,
            source_revisions_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            model_profile_id TEXT,
            authority TEXT NOT NULL,
            review_status TEXT NOT NULL,
            status TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE style_rules (
            id TEXT PRIMARY KEY,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            rule_text TEXT NOT NULL,
            limit_per_chapter INTEGER,
            limit_per_volume INTEGER,
            limit_per_book INTEGER,
            authority TEXT NOT NULL,
            review_status TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE style_samples (
            id TEXT PRIMARY KEY,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            source_type TEXT NOT NULL,
            authority TEXT NOT NULL,
            review_status TEXT NOT NULL,
            immutable INTEGER NOT NULL CHECK(immutable IN (0, 1)),
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE memory_dependencies (
            id TEXT PRIMARY KEY,
            memory_type TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            source_chapter_id TEXT NOT NULL REFERENCES chapters(id),
            source_revision INTEGER NOT NULL,
            source_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(memory_type, memory_id, source_chapter_id)
        )
        """,
        """
        CREATE TABLE memory_documents (
            id TEXT PRIMARY KEY,
            document_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            chapter_id TEXT REFERENCES chapters(id),
            volume_id TEXT REFERENCES volumes(id),
            source_revision INTEGER NOT NULL DEFAULT 0,
            source_hash TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            participants TEXT NOT NULL DEFAULT '',
            pinned_weight REAL NOT NULL DEFAULT 0,
            review_status TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(document_type, source_id)
        )
        """,
        """
        CREATE VIRTUAL TABLE memory_fts USING fts5(
            document_id UNINDEXED,
            title,
            content,
            participants,
            tokenize='trigram'
        )
        """,
        """
        CREATE TABLE context_manifests (
            id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL REFERENCES chapters(id),
            run_id TEXT,
            content_path TEXT NOT NULL UNIQUE,
            input_token_limit INTEGER NOT NULL,
            estimated_input_tokens INTEGER NOT NULL,
            output_token_limit INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX character_states_timeline ON "
        "character_state_events(character_id, chapter_id, created_at)",
        "CREATE INDEX knowledge_states_timeline ON "
        "knowledge_state_events(subject_type, subject_id, chapter_id, created_at)",
        "CREATE INDEX clue_events_timeline ON "
        "narrative_clue_events(clue_id, chapter_id, created_at)",
        "CREATE INDEX summaries_scope ON summary_nodes(level, scope_id, status, review_status)",
        "CREATE INDEX dependencies_source ON memory_dependencies(source_chapter_id, status)",
        "CREATE INDEX memory_documents_chapter ON "
        "memory_documents(chapter_id, status, review_status)",
    )
    for statement in statements:
        connection.execute(statement)


def _migration_3(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE chapter_requirements (
            id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL UNIQUE REFERENCES chapters(id),
            content TEXT NOT NULL,
            is_locked INTEGER NOT NULL CHECK(is_locked IN (0, 1)),
            revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE chapter_briefs (
            id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL REFERENCES chapters(id),
            mode TEXT NOT NULL CHECK(mode IN ('BASIC', 'STANDARD', 'STRICT')),
            status TEXT NOT NULL CHECK(status IN ('DRAFT', 'FROZEN', 'STALE', 'ARCHIVED')),
            revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
            dramatic_purpose TEXT NOT NULL,
            target_length INTEGER NOT NULL CHECK(target_length > 0),
            story_date TEXT NOT NULL DEFAULT '',
            pov_character_id TEXT,
            hard_events_json TEXT NOT NULL DEFAULT '[]',
            soft_goals_json TEXT NOT NULL DEFAULT '[]',
            prohibited_changes_json TEXT NOT NULL DEFAULT '[]',
            creative_freedom_json TEXT NOT NULL DEFAULT '[]',
            participants_json TEXT NOT NULL DEFAULT '[]',
            knowledge_json TEXT NOT NULL DEFAULT '[]',
            clue_actions_json TEXT NOT NULL DEFAULT '[]',
            style_rules_json TEXT NOT NULL DEFAULT '[]',
            warnings_json TEXT NOT NULL DEFAULT '[]',
            source_fingerprint TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            cloned_from_id TEXT REFERENCES chapter_briefs(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            frozen_at TEXT
        )
        """,
        """
        CREATE TABLE brief_sources (
            id TEXT PRIMARY KEY,
            brief_id TEXT NOT NULL REFERENCES chapter_briefs(id),
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_revision INTEGER NOT NULL CHECK(source_revision >= 0),
            source_hash TEXT NOT NULL,
            required INTEGER NOT NULL CHECK(required IN (0, 1)),
            UNIQUE(brief_id, source_type, source_id)
        )
        """,
        """
        CREATE TABLE generation_runs (
            id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL REFERENCES chapters(id),
            mode TEXT NOT NULL CHECK(mode IN ('BASIC', 'STANDARD', 'STRICT')),
            status TEXT NOT NULL CHECK(status IN (
                'PREPARING', 'READY', 'STREAMING', 'PARTIAL',
                'COMPLETED', 'FAILED', 'ACCEPTED', 'DISCARDED'
            )),
            brief_id TEXT REFERENCES chapter_briefs(id),
            brief_revision INTEGER CHECK(brief_revision >= 0),
            context_manifest_id TEXT REFERENCES context_manifests(id),
            model_provider_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            output_token_limit INTEGER NOT NULL CHECK(output_token_limit > 0),
            prompt_version TEXT NOT NULL,
            accepted_chapter_revision INTEGER CHECK(accepted_chapter_revision >= 0),
            input_tokens INTEGER CHECK(input_tokens >= 0),
            output_tokens INTEGER CHECK(output_tokens >= 0),
            cached_input_tokens INTEGER CHECK(cached_input_tokens >= 0),
            reasoning_tokens INTEGER CHECK(reasoning_tokens >= 0),
            failure_code TEXT,
            failure_message TEXT,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            accepted_at TEXT
        )
        """,
        """
        CREATE TABLE generation_checkpoints (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES generation_runs(id),
            sequence INTEGER NOT NULL CHECK(sequence >= 0),
            text_path TEXT NOT NULL UNIQUE,
            content_hash TEXT NOT NULL,
            finish_reason TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(run_id, sequence)
        )
        """,
        "CREATE INDEX chapter_briefs_status ON chapter_briefs(chapter_id, status, revision)",
        "CREATE INDEX brief_sources_lookup ON brief_sources(source_type, source_id)",
        "CREATE INDEX generation_runs_chapter ON generation_runs(chapter_id, started_at)",
        """
        CREATE UNIQUE INDEX generation_one_active_writer
        ON generation_runs(chapter_id)
        WHERE status IN ('PREPARING', 'READY', 'STREAMING')
        """,
    )
    for statement in statements:
        connection.execute(statement)


def _migration_4(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE audit_runs (
            id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL REFERENCES chapters(id),
            target_kind TEXT NOT NULL CHECK(target_kind IN (
                'GENERATED_DRAFT', 'FORMAL_CHAPTER'
            )),
            target_id TEXT NOT NULL,
            target_revision INTEGER NOT NULL CHECK(target_revision >= 0),
            target_hash TEXT NOT NULL,
            mode TEXT NOT NULL CHECK(mode IN ('BASIC', 'STANDARD', 'STRICT')),
            status TEXT NOT NULL CHECK(status IN (
                'PREPARING', 'RULE_CHECKED', 'MODEL_CHECKED', 'COMPLETED', 'FAILED'
            )),
            model_provider_id TEXT,
            model_id TEXT,
            prompt_version TEXT NOT NULL,
            input_tokens INTEGER CHECK(input_tokens >= 0),
            output_tokens INTEGER CHECK(output_tokens >= 0),
            cached_input_tokens INTEGER CHECK(cached_input_tokens >= 0),
            reasoning_tokens INTEGER CHECK(reasoning_tokens >= 0),
            failure_code TEXT,
            failure_message TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT
        )
        """,
        """
        CREATE TABLE audit_findings (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES audit_runs(id),
            category TEXT NOT NULL CHECK(category IN (
                'STYLE', 'REQUIREMENT', 'CHARACTER', 'KNOWLEDGE',
                'CLUE', 'CANON', 'TIMELINE', 'FORMAT'
            )),
            severity TEXT NOT NULL CHECK(severity IN (
                'INFO', 'WARNING', 'ERROR', 'BLOCKER'
            )),
            source TEXT NOT NULL CHECK(source IN ('DETERMINISTIC', 'MODEL')),
            location_json TEXT NOT NULL,
            evidence TEXT NOT NULL,
            explanation TEXT NOT NULL,
            related_source_json TEXT NOT NULL,
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            status TEXT NOT NULL CHECK(status IN (
                'OPEN', 'ACCEPTED_REPAIR', 'REJECTED',
                'FALSE_POSITIVE', 'CONVERTED_TO_CANON'
            )),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE repair_proposals (
            id TEXT PRIMARY KEY,
            finding_id TEXT NOT NULL REFERENCES audit_findings(id),
            target_revision INTEGER NOT NULL CHECK(target_revision >= 0),
            target_hash TEXT NOT NULL,
            strategy TEXT NOT NULL CHECK(strategy IN (
                'REPLACE_TEXT', 'INSERT_TEXT', 'DELETE_TEXT', 'NOTE_ONLY'
            )),
            target_text TEXT NOT NULL DEFAULT '',
            replacement_text TEXT NOT NULL DEFAULT '',
            patch_json TEXT NOT NULL,
            explanation TEXT NOT NULL,
            risk_note TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN (
                'DRAFT', 'VALIDATED', 'APPLIED', 'REJECTED', 'STALE', 'INVALID'
            )),
            created_at TEXT NOT NULL,
            applied_at TEXT
        )
        """,
        """
        CREATE TABLE provenance_events (
            id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL REFERENCES chapters(id),
            chapter_revision_before INTEGER NOT NULL CHECK(chapter_revision_before >= 0),
            chapter_revision_after INTEGER NOT NULL CHECK(chapter_revision_after >= 0),
            event_type TEXT NOT NULL CHECK(event_type IN (
                'REPAIR_APPLIED', 'FINDING_REJECTED',
                'FALSE_POSITIVE', 'CANON_NOTE_CREATED'
            )),
            source_audit_run_id TEXT REFERENCES audit_runs(id),
            source_finding_id TEXT REFERENCES audit_findings(id),
            source_repair_id TEXT REFERENCES repair_proposals(id),
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX audit_runs_chapter ON audit_runs(chapter_id, started_at)",
        "CREATE INDEX audit_runs_target ON audit_runs(target_kind, target_id, target_revision)",
        "CREATE INDEX audit_findings_run_status ON audit_findings(run_id, status, severity)",
        "CREATE INDEX repair_proposals_finding ON repair_proposals(finding_id, status)",
        "CREATE INDEX provenance_events_chapter ON provenance_events(chapter_id, created_at)",
    )
    for statement in statements:
        connection.execute(statement)


def _migration_5(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE agent_runs (
            id TEXT PRIMARY KEY,
            chapter_id TEXT REFERENCES chapters(id),
            purpose TEXT NOT NULL CHECK(purpose IN (
                'PLOT_DISCUSSION', 'REVISION_PLAN', 'AUDIT_EXPLANATION'
            )),
            status TEXT NOT NULL CHECK(status IN (
                'PREPARING', 'RUNNING', 'WAITING_FOR_MODEL', 'WAITING_FOR_TOOL',
                'COMPLETED', 'FAILED', 'CANCELLED'
            )),
            model_provider_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            max_iterations INTEGER NOT NULL CHECK(max_iterations > 0),
            max_tool_calls INTEGER NOT NULL CHECK(max_tool_calls >= 0),
            max_tool_result_chars INTEGER NOT NULL CHECK(max_tool_result_chars > 0),
            used_iterations INTEGER NOT NULL DEFAULT 0 CHECK(used_iterations >= 0),
            used_tool_calls INTEGER NOT NULL DEFAULT 0 CHECK(used_tool_calls >= 0),
            input_tokens INTEGER CHECK(input_tokens >= 0),
            output_tokens INTEGER CHECK(output_tokens >= 0),
            cached_input_tokens INTEGER CHECK(cached_input_tokens >= 0),
            reasoning_tokens INTEGER CHECK(reasoning_tokens >= 0),
            failure_code TEXT,
            failure_message TEXT,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        )
        """,
        """
        CREATE TABLE agent_turns (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES agent_runs(id),
            sequence INTEGER NOT NULL CHECK(sequence >= 0),
            role TEXT NOT NULL CHECK(role IN ('SYSTEM', 'USER', 'ASSISTANT', 'TOOL')),
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            omitted INTEGER NOT NULL DEFAULT 0 CHECK(omitted IN (0, 1)),
            created_at TEXT NOT NULL,
            UNIQUE(run_id, sequence)
        )
        """,
        """
        CREATE TABLE agent_tool_calls (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES agent_runs(id),
            turn_id TEXT REFERENCES agent_turns(id),
            sequence INTEGER NOT NULL CHECK(sequence >= 0),
            tool_name TEXT NOT NULL,
            arguments_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN (
                'REQUESTED', 'VALIDATED', 'EXECUTED', 'REJECTED', 'FAILED', 'OMITTED'
            )),
            result_json TEXT NOT NULL DEFAULT '{}',
            result_chars INTEGER NOT NULL DEFAULT 0 CHECK(result_chars >= 0),
            source_refs_json TEXT NOT NULL DEFAULT '[]',
            failure_code TEXT,
            failure_message TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(run_id, sequence)
        )
        """,
        "CREATE INDEX agent_runs_chapter ON agent_runs(chapter_id, started_at)",
        "CREATE INDEX agent_turns_run ON agent_turns(run_id, sequence)",
        "CREATE INDEX agent_tool_calls_run ON agent_tool_calls(run_id, sequence)",
    )
    for statement in statements:
        connection.execute(statement)


def _migration_6(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            summarized_through_sequence INTEGER NOT NULL DEFAULT -1
                CHECK(summarized_through_sequence >= -1),
            summary_revision INTEGER NOT NULL DEFAULT 0 CHECK(summary_revision >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE chat_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES chat_sessions(id),
            sequence INTEGER NOT NULL CHECK(sequence >= 0),
            chapter_id TEXT REFERENCES chapters(id),
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(session_id, sequence)
        )
        """,
        "CREATE INDEX chat_messages_session ON chat_messages(session_id, sequence)",
    )
    for statement in statements:
        connection.execute(statement)


def _migration_7(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE chapter_context_pins (
            id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            context_category TEXT NOT NULL CHECK(context_category IN ('MEMORY', 'HISTORY')),
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            source_chapter_id TEXT REFERENCES chapters(id),
            source_revision INTEGER CHECK(source_revision IS NULL OR source_revision >= 0),
            source_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(chapter_id, source_type, source_id)
        )
        """,
        "CREATE INDEX chapter_context_pins_chapter ON chapter_context_pins(chapter_id, created_at)",
    )
    for statement in statements:
        connection.execute(statement)


def _migration_8(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE project_guidance (
            project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            highest_system_prompt TEXT NOT NULL DEFAULT '',
            revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
            updated_at TEXT NOT NULL
        )
        """
    )


def _migration_9(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        ALTER TABLE canon_entries ADD COLUMN category TEXT
        CHECK(category IS NULL OR category IN (
            'WORLD', 'CHARACTER_IDENTITY', 'ITEM_ABILITY', 'ORGANIZATION'
        ))
        """
    )


def _migration_10(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE character_identity_merges (
            id TEXT PRIMARY KEY,
            source_character_id TEXT NOT NULL REFERENCES characters(id),
            target_character_id TEXT NOT NULL REFERENCES characters(id),
            source_canonical_name TEXT NOT NULL,
            source_aliases_json TEXT NOT NULL,
            target_aliases_before_json TEXT NOT NULL,
            target_aliases_after_json TEXT NOT NULL,
            moved_state_event_ids_json TEXT NOT NULL,
            moved_knowledge_event_ids_json TEXT NOT NULL,
            moved_briefs_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('APPLIED', 'REVERSED')),
            created_at TEXT NOT NULL,
            reversed_at TEXT,
            CHECK(source_character_id != target_character_id),
            CHECK(length(trim(source_canonical_name)) > 0),
            CHECK(length(trim(reason)) > 0),
            CHECK(
                (status = 'APPLIED' AND reversed_at IS NULL) OR
                (status = 'REVERSED' AND reversed_at IS NOT NULL)
            )
        )
        """,
        """
        CREATE UNIQUE INDEX character_identity_one_active_source
        ON character_identity_merges(source_character_id)
        WHERE status = 'APPLIED'
        """,
        """
        CREATE INDEX character_identity_active_target
        ON character_identity_merges(target_character_id, status)
        """,
    )
    for statement in statements:
        connection.execute(statement)


def _migration_11(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE character_identity_review_decisions (
            first_character_id TEXT NOT NULL REFERENCES characters(id),
            second_character_id TEXT NOT NULL REFERENCES characters(id),
            decision TEXT NOT NULL CHECK(decision IN ('DISTINCT', 'DEFERRED', 'REOPENED')),
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(first_character_id, second_character_id),
            CHECK(first_character_id < second_character_id)
        )
        """,
        """
        CREATE INDEX character_identity_review_decision_status
        ON character_identity_review_decisions(decision, updated_at)
        """,
    )
    for statement in statements:
        connection.execute(statement)


def _migration_12(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE subjects (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK(type = 'CHARACTER'),
            canonical_name TEXT NOT NULL CHECK(length(trim(canonical_name)) > 0),
            active INTEGER NOT NULL CHECK(active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX subjects_type_active_name
        ON subjects(type, active, canonical_name)
        """,
        """
        CREATE TABLE subject_aliases (
            id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            alias TEXT NOT NULL CHECK(length(trim(alias)) > 0),
            source_id TEXT NOT NULL CHECK(length(trim(source_id)) > 0),
            confirmed INTEGER NOT NULL CHECK(confirmed IN (0, 1)),
            UNIQUE(subject_id, alias)
        )
        """,
        """
        CREATE INDEX subject_aliases_lookup
        ON subject_aliases(alias, subject_id)
        """,
    )
    for statement in statements:
        connection.execute(statement)

    rows = connection.execute(
        """
        SELECT c.*,
               CASE WHEN EXISTS (
                   SELECT 1 FROM character_identity_merges m
                   WHERE m.source_character_id = c.id AND m.status = 'APPLIED'
               ) THEN 0 ELSE 1 END AS subject_active
        FROM characters c
        ORDER BY c.created_at, c.id
        """
    ).fetchall()
    for row in rows:
        connection.execute(
            """
            INSERT INTO subjects (
                id, type, canonical_name, active, created_at, updated_at
            ) VALUES (?, 'CHARACTER', ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["canonical_name"],
                row["subject_active"],
                row["created_at"],
                row["updated_at"],
            ),
        )
        aliases = tuple(
            alias
            for alias in _json_string_tuple(
                row["aliases_json"], "characters.aliases_json"
            )
            if alias != row["canonical_name"]
        )
        for index, alias in enumerate(aliases):
            connection.execute(
                """
                INSERT INTO subject_aliases (
                    id, subject_id, alias, source_id, confirmed
                ) VALUES (?, ?, ?, ?, 1)
                """,
                (f"subject-alias:{row['id']}:{index}", row["id"], alias, row["id"]),
            )

    merge_rows = connection.execute(
        """
        SELECT source_character_id, target_character_id,
               target_aliases_before_json, target_aliases_after_json
        FROM character_identity_merges
        WHERE status = 'APPLIED'
        ORDER BY created_at, id
        """
    ).fetchall()
    for row in merge_rows:
        aliases_before = set(
            _json_string_tuple(
                row["target_aliases_before_json"],
                "character_identity_merges.target_aliases_before_json",
            )
        )
        aliases_after = _json_string_tuple(
            row["target_aliases_after_json"],
            "character_identity_merges.target_aliases_after_json",
        )
        for alias in aliases_after:
            if alias in aliases_before:
                continue
            cursor = connection.execute(
                "UPDATE subject_aliases SET source_id = ? "
                "WHERE subject_id = ? AND alias = ?",
                (row["source_character_id"], row["target_character_id"], alias),
            )
            if cursor.rowcount != 1:
                raise ValueError("active character merge aliases are inconsistent")


def _migration_13(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE view_assertions (
            id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL REFERENCES subjects(id),
            view_type TEXT NOT NULL CHECK(view_type IN (
                'WORLD_TRUTH', 'CHARACTER_VIEW', 'READER_VIEW', 'AUTHOR_PLAN'
            )),
            viewer_subject_id TEXT REFERENCES subjects(id),
            epistemic_status TEXT CHECK(epistemic_status IN (
                'KNOWS', 'BELIEVES', 'SUSPECTS', 'MISBELIEVES', 'UNAWARE'
            )),
            content TEXT NOT NULL CHECK(length(trim(content)) > 0),
            valid_from_sequence INTEGER CHECK(valid_from_sequence >= 0),
            valid_to_sequence INTEGER CHECK(valid_to_sequence >= 0),
            story_time_label TEXT,
            narrative_visible_from_sequence INTEGER
                CHECK(narrative_visible_from_sequence >= 0),
            narrative_visible_to_sequence INTEGER
                CHECK(narrative_visible_to_sequence >= 0),
            authority TEXT NOT NULL CHECK(authority IN (
                'USER_CONFIRMED', 'OUTLINE', 'AUDITED',
                'MODEL_EXTRACTED', 'INFERRED'
            )),
            review_status TEXT NOT NULL CHECK(review_status IN (
                'REVIEW', 'APPROVED', 'REJECTED', 'LOCKED'
            )),
            source_type TEXT NOT NULL CHECK(source_type IN (
                'HUMAN', 'MODEL', 'IMPORT', 'SYSTEM'
            )),
            source_id TEXT NOT NULL CHECK(length(trim(source_id)) > 0),
            source_revision INTEGER NOT NULL CHECK(source_revision >= 0),
            stale INTEGER NOT NULL CHECK(stale IN (0, 1)),
            source_changed INTEGER NOT NULL CHECK(source_changed IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(valid_from_sequence IS NULL OR valid_to_sequence IS NULL
                  OR valid_from_sequence <= valid_to_sequence),
            CHECK(narrative_visible_from_sequence IS NULL
                  OR narrative_visible_to_sequence IS NULL
                  OR narrative_visible_from_sequence
                     <= narrative_visible_to_sequence),
            CHECK(
                (view_type = 'CHARACTER_VIEW'
                 AND viewer_subject_id IS NOT NULL
                 AND epistemic_status IS NOT NULL)
                OR
                (view_type != 'CHARACTER_VIEW'
                 AND viewer_subject_id IS NULL
                 AND epistemic_status IS NULL)
            ),
            CHECK(view_type != 'READER_VIEW'
                  OR narrative_visible_from_sequence IS NOT NULL)
        )
        """,
        """
        CREATE INDEX view_assertions_context_lookup
        ON view_assertions(
            view_type, viewer_subject_id, subject_id, stale, source_changed
        )
        """,
        """
        CREATE INDEX view_assertions_narrative_visibility
        ON view_assertions(
            narrative_visible_from_sequence, narrative_visible_to_sequence
        )
        """,
    )
    for statement in statements:
        connection.execute(statement)


def _migration_14(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE character_identity_merge_view_assertions (
            merge_id TEXT NOT NULL REFERENCES character_identity_merges(id),
            assertion_id TEXT NOT NULL REFERENCES view_assertions(id),
            reference_role TEXT NOT NULL CHECK(reference_role IN ('SUBJECT', 'VIEWER')),
            PRIMARY KEY(merge_id, assertion_id, reference_role)
        )
        """,
        """
        CREATE INDEX character_identity_merge_view_assertion_lookup
        ON character_identity_merge_view_assertions(assertion_id, merge_id)
        """,
    )
    for statement in statements:
        connection.execute(statement)


def _migration_15(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE INDEX view_assertions_source_revision "
        "ON view_assertions(source_id, source_revision)"
    )


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migration_1,
    2: _migration_2,
    3: _migration_3,
    4: _migration_4,
    5: _migration_5,
    6: _migration_6,
    7: _migration_7,
    8: _migration_8,
    9: _migration_9,
    10: _migration_10,
    11: _migration_11,
    12: _migration_12,
    13: _migration_13,
    14: _migration_14,
    15: _migration_15,
}


class MigrationManager:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def migrate(self) -> None:
        current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if current > LATEST_SCHEMA_VERSION:
            raise RuntimeError(
                f"project uses newer schema {current}; supported version is {LATEST_SCHEMA_VERSION}"
            )
        with self._connection:
            # sqlite3 does not implicitly start a transaction for DDL.  Begin one
            # explicitly so schema changes and their version records roll back
            # together if any migration fails.
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for version in range(current + 1, LATEST_SCHEMA_VERSION + 1):
                MIGRATIONS[version](self._connection)
                self._connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
                )
                self._connection.execute(f"PRAGMA user_version = {version}")
