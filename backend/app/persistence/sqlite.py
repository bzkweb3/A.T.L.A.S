"""SQLite connection management and initial schema for local persistence."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4

_SCHEMA_VERSION = 4


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
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize_schema(self) -> None:
        """Apply every schema upgrade required by the current application version."""
        with self.connection() as connection:
            # The sqlite3 connection context manager only commits an open
            # transaction; DDL alone does not reliably start one. Begin
            # explicitly so schema changes and user_version roll back together.
            connection.execute("BEGIN IMMEDIATE")
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
                current_version = 2
            if current_version < 3:
                self._migrate_to_version_3(connection)
                connection.execute("PRAGMA user_version = 3")
                current_version = 3
            if current_version < 4:
                self._migrate_to_version_4(connection)
                connection.execute("PRAGMA user_version = 4")

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

    @staticmethod
    def _migrate_to_version_3(connection: sqlite3.Connection) -> None:
        """Add owner authentication, device registry, sessions and login throttling."""
        connection.execute(
            """CREATE TABLE auth_owner (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                password_changed_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE auth_devices (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                user_agent TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                revoked_at TEXT
            )"""
        )
        connection.execute(
            """CREATE TABLE auth_sessions (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL REFERENCES auth_devices(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            )"""
        )
        connection.execute(
            "CREATE INDEX idx_auth_sessions_device ON auth_sessions(device_id, revoked_at)"
        )
        connection.execute(
            """CREATE TABLE auth_login_throttle (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                window_started_at TEXT,
                lock_level INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT
            )"""
        )

    @staticmethod
    def _migrate_to_version_4(connection: sqlite3.Connection) -> None:
        """Add durable chat tasks and isolated execution attempts."""
        connection.execute(
            """CREATE TABLE conversation_tasks (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                prompt TEXT NOT NULL,
                messages_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN (
                    'pending', 'processing', 'partially_completed', 'completed', 'failed', 'cancelled'
                )),
                active_attempt INTEGER NOT NULL DEFAULT 0,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            )"""
        )
        connection.execute(
            "CREATE INDEX idx_conversation_tasks_pending "
            "ON conversation_tasks(conversation_id, status, updated_at DESC)"
        )
        connection.execute(
            """CREATE TABLE task_attempts (
                task_id TEXT NOT NULL REFERENCES conversation_tasks(id) ON DELETE CASCADE,
                attempt_number INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN (
                    'processing', 'partially_completed', 'completed', 'failed', 'cancelled'
                )),
                partial_text TEXT NOT NULL DEFAULT '',
                provider TEXT,
                model TEXT,
                error_code TEXT,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                PRIMARY KEY(task_id, attempt_number)
            )"""
        )
