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
    """Generate a reply using conversation history plus long-term user memory."""
    if not any(message.role == "user" for message in payload.messages):
        raise HTTPException(status_code=422, detail="Envie ao menos uma mensagem do usuário.")

    provider = request.app.state.ai_provider
    if provider is None:
        raise HTTPException(status_code=503, detail="A integração de IA não está configurada.")

    if payload.conversation_id and request.app.state.memory.get_conversation(payload.conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada. Inicie uma nova conversa.")

    latest_user_text = next((m.content for m in reversed(payload.messages) if m.role == "user"), "")
    extracted_facts = request.app.state.long_term_memory.extract_explicit_facts(latest_user_text)
    memory = request.app.state.long_term_memory
    context = memory.build_context()
    facts = {(fact["category"], fact["key"]): fact["value"] for fact in memory.list_facts()}

    # Answer simple personal-memory questions deterministically. This avoids
    # asking the model to rediscover facts already stored in the user's profile.
    normalized_question = " ".join(latest_user_text.lower().strip(" ?!.").split())
    direct_reply = None
    if extracted_facts:
        saved = extracted_facts[0]
        if saved["key"] in {"name", "preferred_name"}:
            direct_reply = f"Prazer em falar com você, {saved['value']}! Vou usar esse nome daqui em diante."
        elif saved["key"] == "location":
            direct_reply = f"Entendido. Vou considerar que você mora em {saved['value']}."
    asks_name = any(term in normalized_question for term in (
        "sabe meu nome", "qual meu nome", "como eu me chamo", "como me chamo",
        "lembra meu nome", "lembra como me chamo",
    ))
    asks_location = any(term in normalized_question for term in (
        "onde eu moro", "onde moro", "qual minha cidade", "qual cidade eu moro",
        "lembra onde moro", "lembra onde eu moro",
    ))
    if direct_reply is None and asks_name:
        name = facts.get(("profile", "preferred_name")) or facts.get(("profile", "name"))
        direct_reply = (
            f"Sei, {name}. 😊" if name else
            "Ainda não tenho seu nome registrado. Como gostaria que eu chamasse você?"
        )
    elif direct_reply is None and asks_location:
        location = facts.get(("profile", "location"))
        direct_reply = (
            f"Você me informou que mora em {location}." if location else
            "Ainda não tenho sua localização registrada. Se quiser, pode me contar."
        )

    messages = [ChatMessage(role=m.role, content=m.content) for m in payload.messages]
    if context:
        messages.insert(0, ChatMessage(role="system", content=context))

    try:
        if direct_reply is not None:
            conversation_id = request.app.state.memory.save_exchange(
                [m.model_dump() for m in payload.messages] + [{"role": "assistant", "content": direct_reply}],
                conversation_id=payload.conversation_id, provider="atlas-memory",
                model="local-memory", fallback_used=False,
            )
            return ChatResponse(
                reply=direct_reply, provider="atlas-memory", model="local-memory",
                fallback_used=False, primary_model=None, conversation_id=conversation_id,
            )
        metadata_method = getattr(provider, "generate_reply_with_metadata", None)
        if callable(metadata_method):
            result = await metadata_method(messages)
            if isinstance(result, AIReply):
                conversation_id = request.app.state.memory.save_exchange(
                    [m.model_dump() for m in payload.messages] + [{"role": "assistant", "content": result.content}],
                    conversation_id=payload.conversation_id, provider=result.provider,
                    model=result.model, fallback_used=result.fallback_used,
                )
                return ChatResponse(reply=result.content, provider=result.provider, model=result.model,
                    fallback_used=result.fallback_used, primary_model=result.primary_model,
                    conversation_id=conversation_id)
        reply = await provider.generate_reply(messages)
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from None

    conversation_id = request.app.state.memory.save_exchange(
        [m.model_dump() for m in payload.messages] + [{"role": "assistant", "content": reply}],
        conversation_id=payload.conversation_id, provider=request.app.state.settings.ai_provider,
        model=request.app.state.settings.ai_model, fallback_used=False,
    )
    return ChatResponse(reply=reply, provider=request.app.state.settings.ai_provider,
        model=request.app.state.settings.ai_model, primary_model=request.app.state.settings.ai_model,
        conversation_id=conversation_id)
