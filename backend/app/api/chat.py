"""HTTP endpoints for conversations with the A.T.L.A.S. core."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.app.intelligence.provider import AIProviderError, ChatMessage

router = APIRouter(prefix="/api", tags=["conversas"])


class MessageInput(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    messages: list[MessageInput] = Field(min_length=1, max_length=20)


class ChatResponse(BaseModel):
    reply: str
    model: str


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Return an AI response; conversation history is supplied by the client."""

    if not any(message.role == "user" for message in payload.messages):
        raise HTTPException(status_code=422, detail="Envie ao menos uma mensagem do usuário.")

    provider = request.app.state.ai_provider
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail="A integração de IA não está configurada. Configure a chave do provedor selecionado.",
        )

    messages = [
        ChatMessage(role=message.role, content=message.content)
        for message in payload.messages
    ]

    try:
        reply = await provider.generate_reply(messages)
    except AIProviderError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail=str(exc),
        ) from None

    return ChatResponse(reply=reply, model=request.app.state.settings.ai_model)
