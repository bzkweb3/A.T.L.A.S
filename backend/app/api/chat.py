"""HTTP endpoints for conversations with the A.T.L.A.S. core."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.app.intelligence.provider import AIProviderError, AIReply, ChatMessage

router = APIRouter(prefix="/api", tags=["conversas"])


class MessageInput(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    messages: list[MessageInput] = Field(min_length=1, max_length=20)
    conversation_id: str | None = Field(default=None, max_length=64)


class ChatResponse(BaseModel):
    reply: str
    provider: str
    model: str
    fallback_used: bool = False
    primary_model: str | None = None
    conversation_id: str


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Return an AI response and the exact model used for this request."""

    if not any(message.role == "user" for message in payload.messages):
        raise HTTPException(status_code=422, detail="Envie ao menos uma mensagem do usuário.")

    provider = request.app.state.ai_provider
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail="A integração de IA não está configurada. Configure a chave do provedor selecionado.",
        )

    if payload.conversation_id and request.app.state.memory.get_conversation(payload.conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada. Inicie uma nova conversa.")

    messages = [ChatMessage(role=message.role, content=message.content) for message in payload.messages]

    try:
        metadata_method = getattr(provider, "generate_reply_with_metadata", None)
        if callable(metadata_method):
            result = await metadata_method(messages)
            if isinstance(result, AIReply):
                conversation_id = request.app.state.memory.save_exchange(
                    [message.model_dump() for message in payload.messages] + [{"role": "assistant", "content": result.content}],
                    conversation_id=payload.conversation_id,
                    provider=result.provider,
                    model=result.model,
                    fallback_used=result.fallback_used,
                )
                return ChatResponse(
                    reply=result.content,
                    provider=result.provider,
                    model=result.model,
                    fallback_used=result.fallback_used,
                    primary_model=result.primary_model,
                    conversation_id=conversation_id,
                )
        reply = await provider.generate_reply(messages)
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from None

    conversation_id = request.app.state.memory.save_exchange(
        [message.model_dump() for message in payload.messages] + [{"role": "assistant", "content": reply}],
        conversation_id=payload.conversation_id,
        provider=request.app.state.settings.ai_provider,
        model=request.app.state.settings.ai_model,
        fallback_used=False,
    )
    return ChatResponse(
        reply=reply,
        provider=request.app.state.settings.ai_provider,
        model=request.app.state.settings.ai_model,
        primary_model=request.app.state.settings.ai_model,
        conversation_id=conversation_id,
    )
