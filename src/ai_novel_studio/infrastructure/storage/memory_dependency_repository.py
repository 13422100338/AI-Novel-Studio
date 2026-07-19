from __future__ import annotations

import sqlite3


class MemoryDependencyRepository:
    @staticmethod
    def invalidate_in_connection(
        connection: sqlite3.Connection,
        chapter_id: str,
        new_revision: int,
        new_hash: str,
    ) -> tuple[tuple[str, str], ...]:
        rows = connection.execute(
            """
            SELECT memory_type, memory_id FROM memory_dependencies
            WHERE source_chapter_id = ? AND status != 'STALE'
              AND (source_revision != ? OR source_hash != ?)
            """,
            (chapter_id, new_revision, new_hash),
        ).fetchall()
        affected = tuple((row["memory_type"], row["memory_id"]) for row in rows)
        connection.execute(
            """
            UPDATE memory_dependencies SET status = 'STALE'
            WHERE source_chapter_id = ? AND (source_revision != ? OR source_hash != ?)
            """,
            (chapter_id, new_revision, new_hash),
        )
        for memory_type, memory_id in affected:
            if memory_type == "SUMMARY":
                connection.execute(
                    "UPDATE summary_nodes SET status = 'STALE' WHERE id = ?",
                    (memory_id,),
                )
            elif memory_type == "SEARCH":
                connection.execute(
                    "UPDATE memory_documents SET status = 'STALE' WHERE id = ?",
                    (memory_id,),
                )
                connection.execute(
                    """
                    UPDATE memory_embeddings
                    SET status = 'STALE', updated_at = CURRENT_TIMESTAMP
                    WHERE document_id = ? AND status != 'STALE'
                    """,
                    (memory_id,),
                )
            elif memory_type == "MANIFEST":
                connection.execute(
                    "UPDATE context_manifests SET status = 'STALE' WHERE id = ?",
                    (memory_id,),
                )
        return affected
