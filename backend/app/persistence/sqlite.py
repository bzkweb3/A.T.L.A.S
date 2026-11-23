"""SQLite connection management and initial schema for local persistence."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4

_SCHEMA_VERSION = 2


class SQLiteDatabase:
    """Own SQLite connections and initialize the application's local schema."""

    def __init__(self, database_path: str) -> None:
        self._keeper: sqlite3.Connection | None = None
        if database_path == ":memory:":
            self.database_path = f"file:atlas-{uuid4()}?mode=memory&cache=shared"
            self._uri = True
            self._keeper = sqlite3.connect(self.database_path, uri=True)
        else:
            self.database_path = database_path
            self._uri = database_path.startswith("file:")
            if not self._uri:
                Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize_schema()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured connection and reliably commit, roll back, and close it."""
        connection = sqlite3.connect(self.database_path, uri=self._uri, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize_schema(self) -> None:
        """Apply every schema upgrade required by the current application version."""
        with self.connection() as connection:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version > _SCHEMA_VERSION:
                raise RuntimeError(
                    "O banco A.T.L.A.S. foi criado por uma versão mais recente da aplicação. "
                    "Atualize o sistema antes de abrir esse banco."
                )
            if current_version < 1:
                self._migrate_to_version_1(connection)
                connection.execute("PRAGMA user_version = 1")
                current_version = 1
            if current_version < 2:
                self._migrate_to_version_2(connection)
                connection.execute("PRAGMA user_version = 2")

    @staticmethod
    def _migrate_to_version_1(connection: sqlite3.Connection) -> None:
        """Create the initial schema, preserving any tables from the unversioned MVP."""
        connection.execute(
            """CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                fallback_used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation "
            "ON messages(conversation_id, id)"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS user_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                fact_key TEXT NOT NULL,
                fact_value TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'conversation',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(category, fact_key)
            )"""
        )

    @staticmethod
    def _migrate_to_version_2(connection: sqlite3.Connection) -> None:
        """Add data classification while keeping existing facts personal by default."""
        connection.execute(
            "ALTER TABLE user_facts ADD COLUMN classification TEXT NOT NULL DEFAULT 'personal' "
            "CHECK(classification IN ('general', 'personal', 'sensitive'))"
        )
