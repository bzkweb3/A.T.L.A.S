"""Provider-independent contract for the A.T.L.A.S. intelligence layer."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str


class AIProviderError(Exception):
    """Raised when an AI provider cannot complete a request."""


class AIProvider(Protocol):
    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        """Generate an assistant response from the supplied conversation."""
