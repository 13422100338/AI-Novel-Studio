import sqlite3
from collections.abc import Callable

LATEST_SCHEMA_VERSION = 2


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
            source_chapter_id TEXT REFERENCES chapters(id),
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


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migration_1,
    2: _migration_2,
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
