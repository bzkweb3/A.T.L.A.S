"""SQLite-backed conversation history for the A.T.L.A.S. core."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4


class ConversationStore:
    """Persist conversations and messages in a local SQLite database."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._keeper = None
        if database_path == ":memory:":
            self.database_path = f"file:atlas-{uuid4()}?mode=memory&cache=shared"
            self._keeper = sqlite3.connect(self.database_path, uri=True)
        else:
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, uri=self.database_path.startswith("file:"))
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    provider TEXT,
                    model TEXT,
                    fallback_used INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_conversation "
                "ON messages(conversation_id, id)"
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def save_exchange(
        self,
        messages: list[dict],
        *,
        conversation_id: str | None,
        provider: str,
        model: str,
        fallback_used: bool,
    ) -> str:
        user_message = next((item for item in reversed(messages) if item["role"] == "user"), None)
        assistant_message = messages[-1] if messages and messages[-1]["role"] == "assistant" else None
        if user_message is None or assistant_message is None:
            raise ValueError("Uma troca precisa conter mensagem do usuário e resposta do assistente.")

        now = self._now()
        with self._connection() as connection:
            if conversation_id is None:
                conversation_id = str(uuid4())
                title = user_message["content"].strip().replace("\n", " ")[:80] or "Nova conversa"
                connection.execute(
                    "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (conversation_id, title, now, now),
                )
            elif connection.execute(
                "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone() is None:
                raise KeyError(conversation_id)

            connection.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
                (conversation_id, user_message["content"], now),
            )
            connection.execute(
                """INSERT INTO messages
                   (conversation_id, role, content, provider, model, fallback_used, created_at)
                   VALUES (?, 'assistant', ?, ?, ?, ?, ?)""",
                (conversation_id, assistant_message["content"], provider, model, int(fallback_used), now),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
            )
        return conversation_id

    def get_conversation(self, conversation_id: str) -> dict | None:
        with self._connect() as connection:
            conversation = connection.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                return None
            messages = connection.execute(
                """SELECT role, content, provider, model, fallback_used, created_at
                   FROM messages WHERE conversation_id = ? ORDER BY id""",
                (conversation_id,),
            ).fetchall()
        return {
            "id": conversation["id"],
            "title": conversation["title"],
            "created_at": conversation["created_at"],
            "updated_at": conversation["updated_at"],
            "messages": [dict(message) for message in messages],
        }

    def list_conversations(self, limit: int = 50) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT c.id, c.title, c.created_at, c.updated_at,
                          (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
                   FROM conversations c ORDER BY c.updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
