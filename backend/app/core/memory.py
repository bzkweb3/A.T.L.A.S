"""Conversation history service backed by the persistence repository."""

from backend.app.persistence.repositories import ConversationRepository
from backend.app.persistence.sqlite import SQLiteDatabase


class ConversationStore:
    """Application-facing service for reading and writing conversation history."""

    def __init__(self, database: str | SQLiteDatabase) -> None:
        self.database = database if isinstance(database, SQLiteDatabase) else SQLiteDatabase(database)
        self.repository = ConversationRepository(self.database)

    def save_exchange(
        self,
        messages: list[dict],
        *,
        conversation_id: str | None,
        provider: str,
        model: str,
        fallback_used: bool,
    ) -> str:
        return self.repository.save_exchange(
            messages,
            conversation_id=conversation_id,
            provider=provider,
            model=model,
            fallback_used=fallback_used,
        )

    def get_conversation(self, conversation_id: str) -> dict | None:
        return self.repository.get_conversation(conversation_id)

    def list_conversations(self, limit: int = 50) -> list[dict]:
        return self.repository.list_conversations(limit)
