"""Repository implementations for SQLite-backed conversations and memory facts."""

from datetime import datetime, timezone
from uuid import uuid4

from backend.app.persistence.sqlite import SQLiteDatabase


class ConversationRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

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
        with self.database.connection() as connection:
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
        with self.database.connection() as connection:
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
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT c.id, c.title, c.created_at, c.updated_at,
                          (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
                   FROM conversations c ORDER BY c.updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


class MemoryRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def remember(self, category: str, key: str, value: str, source: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO user_facts(category, fact_key, fact_value, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(category, fact_key) DO UPDATE SET
                     fact_value=excluded.fact_value, source=excluded.source, updated_at=excluded.updated_at""",
                (category, key, value, source, now, now),
            )

    def forget(self, category: str, key: str) -> bool:
        with self.database.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM user_facts WHERE category = ? AND fact_key = ?", (category, key)
            )
        return cursor.rowcount > 0

    def list_facts(self) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT category, fact_key AS key, fact_value AS value, source, updated_at "
                "FROM user_facts ORDER BY category, fact_key"
            ).fetchall()
        return [dict(row) for row in rows]
