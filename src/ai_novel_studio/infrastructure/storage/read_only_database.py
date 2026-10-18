"""SQLite adapter for novel tools; opening it cannot migrate or write a project."""

import sqlite3

from ai_novel_studio.infrastructure.storage.database import Database


class ReadOnlyDatabase(Database):
    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection
