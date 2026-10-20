import sqlite3
from collections.abc import Callable


def _migration_27(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE outline_chapter_links (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES outline_documents(id),
            chapter_id TEXT NOT NULL,
            chapter_title TEXT NOT NULL,
            source_revision INTEGER NOT NULL CHECK(source_revision >= 1),
            source_line INTEGER NOT NULL CHECK(source_line >= 1),
            source_column INTEGER NOT NULL CHECK(source_column >= 0),
            source_quote TEXT NOT NULL CHECK(length(source_quote) > 0),
            confirmed_fingerprint TEXT CHECK(
                confirmed_fingerprint IS NULL OR (
                    length(confirmed_fingerprint) = 64
                    AND confirmed_fingerprint NOT GLOB '*[^0-9a-f]*'
                )
            ),
            is_active INTEGER NOT NULL CHECK(is_active IN (0, 1)),
            reviews_json TEXT NOT NULL CHECK(json_valid(reviews_json))
        )
        """
    )
    # Deliberately no chapter FK/cascade: removal of a chapter must retain link history.
    connection.execute(
        "CREATE INDEX outline_links_document ON outline_chapter_links(document_id, is_active)"
    )


MIGRATIONS_V27: dict[int, Callable[[sqlite3.Connection], None]] = {27: _migration_27}
