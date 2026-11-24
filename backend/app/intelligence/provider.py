"""Provider-independent contract for the A.T.L.A.S. intelligence layer."""

from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class AIReply:
    """A generated answer plus trustworthy execution metadata."""

    content: str
    provider: str
    model: str
    fallback_used: bool = False
    primary_model: str | None = None


@dataclass(frozen=True, slots=True)
class AIStreamChunk:
    """A streamed text delta or the final reply metadata event."""

    text: str = ""
    reply: AIReply | None = None


class AIProviderError(Exception):
    """Raised when an AI provider cannot complete a request."""

    def __init__(self, message: str, *, http_status: int = 502) -> None:
        super().__init__(message)
        self.http_status = http_status


class AIProvider(Protocol):
    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        """Generate an assistant response from the supplied conversation."""

    def stream_reply_with_metadata(self, messages: list[ChatMessage]) -> AsyncIterator[AIStreamChunk]:
        """Stream text deltas, ending with an AIStreamChunk containing reply metadata."""
