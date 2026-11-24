"""HTTP endpoints for conversations with the A.T.L.A.S. core."""

import asyncio
import json
import logging
import time
import unicodedata
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.app.intelligence.provider import AIProviderError, AIReply, AIStreamChunk, ChatMessage
from backend.app.persistence.task_repository import TaskConflictError
from backend.app.core.task_recovery import (
    MAX_AUTOMATIC_ATTEMPTS,
    RETRY_BACKOFF_SECONDS,
    is_retryable_provider_error,
    recover_tasks,
)

router = APIRouter(prefix="/api", tags=["conversas"])
logger = logging.getLogger(__name__)


class MessageInput(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    messages: list[MessageInput] = Field(min_length=1, max_length=20)
    conversation_id: str | None = Field(default=None, max_length=64)
    task_id: str | None = Field(default=None, max_length=64)


class ChatResponse(BaseModel):
    reply: str
    provider: str
    model: str
    fallback_used: bool = False
    primary_model: str | None = None
    conversation_id: str


@router.get("/tasks/pending")
async def pending_tasks(request: Request, conversation_id: str | None = None) -> dict:
    """Return unfinished requests for the authenticated owner to review."""
    return {"tasks": request.app.state.task_repository.pending(conversation_id)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> dict:
    task = request.app.state.task_repository.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")
    return {"task": task}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request) -> dict:
    cancel_event = request.app.state.task_cancel_events.get(task_id)
    if cancel_event is not None:
        cancel_event.set()
        return {"task_id": task_id, "status": "cancellation_requested"}
    try:
        task = request.app.state.task_repository.cancel(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.") from None
    except TaskConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"task_id": task_id, "status": task["status"]}


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request, response: Response) -> ChatResponse:
    """Generate a legacy JSON reply while persisting the same durable task state."""
    if not any(message.role == "user" for message in payload.messages):
        raise HTTPException(status_code=422, detail="Envie ao menos uma mensagem do usu\u00e1rio.")
    if payload.conversation_id and request.app.state.memory.get_conversation(payload.conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversa n\u00e3o encontrada. Inicie uma nova conversa.")

    latest = next(message.content for message in reversed(payload.messages) if message.role == "user")
    memory = request.app.state.long_term_memory
    extracted = memory.extract_explicit_facts(latest)
    facts = {(fact["category"], fact["key"]): fact["value"] for fact in memory.list_facts()}
    context = memory.build_context(latest, [
        {"role": item.role, "content": item.content} for item in payload.messages
    ])
    messages = [ChatMessage(role=item.role, content=item.content) for item in payload.messages]
    if context:
        messages.insert(0, ChatMessage(role="system", content=context))
    direct_reply = None
    if extracted:
        item = extracted[0]
        if item["key"] in {"name", "preferred_name"}:
            direct_reply = f"Prazer em falar com voc\u00ea, {item['value']}! Vou usar esse nome daqui em diante."
        elif item["key"] == "location":
            direct_reply = f"Entendido. Vou considerar que voc\u00ea mora em {item['value']}."
    normalized = " ".join(latest.lower().strip(" ?!.").split())
    if direct_reply is None and any(term in normalized for term in ("sabe meu nome", "qual meu nome", "como eu me chamo", "como me chamo", "lembra meu nome")):
        name = facts.get(("profile", "preferred_name")) or facts.get(("profile", "name"))
        direct_reply = f"Sei, {name}." if name else "Ainda n\u00e3o tenho seu nome registrado. Como gostaria que eu chamasse voc\u00ea?"
    if direct_reply is None and any(term in normalized for term in ("onde eu moro", "onde moro", "qual minha cidade", "qual cidade eu moro")):
        place = facts.get(("profile", "location"))
        direct_reply = f"Voc\u00ea me informou que mora em {place}." if place else "Ainda n\u00e3o tenho sua localiza\u00e7\u00e3o registrada."

    task_store = request.app.state.task_repository
    plain_latest = "".join(char for char in unicodedata.normalize("NFKD", latest.lower()) if not unicodedata.combining(char))
    retry = any(term in plain_latest for term in ("tente novamente", "tente de novo", "tenta de novo", "repita", "continue", "voce nao terminou", "faca de outra maneira", "use outro modelo", "retome"))
    task = task_store.get(payload.task_id) if payload.task_id else None
    if payload.task_id and task is None:
        raise HTTPException(status_code=404, detail="Solicita\u00e7\u00e3o pendente n\u00e3o encontrada.")
    if task is None and retry and payload.conversation_id:
        task = task_store.latest_resumable(payload.conversation_id)
    if task is not None:
        if payload.conversation_id and task["conversation_id"] != payload.conversation_id:
            raise HTTPException(status_code=409, detail="A solicita\u00e7\u00e3o pertence a outra conversa.")
        conversation_id = task["conversation_id"]
        messages = [ChatMessage(**item) for item in task["messages"]]
        if "outra maneira" in plain_latest:
            messages.append(ChatMessage(role="system", content="Reformule a resposta de outra maneira, mantendo a solicita\u00e7\u00e3o original."))
        provider = request.app.state.ai_provider
        if "outro modelo" in plain_latest:
            provider = next((item for item in request.app.state.ai_providers.values() if item is not request.app.state.ai_provider), provider)
    else:
        try:
            task = task_store.create([{"role": item.role, "content": item.content} for item in messages], payload.conversation_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Conversa n\u00e3o encontrada. Inicie uma nova conversa.") from None
        conversation_id = task["conversation_id"]
        provider = request.app.state.ai_provider
    try:
        task = task_store.start_attempt(task["id"])
    except TaskConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    attempt = task["active_attempt"]
    try:
        if direct_reply is not None:
            result = AIReply(content=direct_reply, provider="atlas-memory", model="local-memory")
        else:
            candidates = ([provider] if provider is not None else []) + [item for item in request.app.state.ai_providers.values() if item is not provider]
            result = None
            while True:
                try:
                    for index, candidate in enumerate(candidates):
                        try:
                            metadata = getattr(candidate, "generate_reply_with_metadata", None)
                            if callable(metadata):
                                result = await metadata(messages)
                                if index and isinstance(result, AIReply) and not result.fallback_used:
                                    result = AIReply(content=result.content, provider=result.provider, model=result.model,
                                        fallback_used=True, primary_model=request.app.state.settings.ai_model)
                            else:
                                text = await candidate.generate_reply(messages)
                                candidate_name = type(candidate).__name__.lower()
                                provider_name = "openai" if "openai" in candidate_name else "gemini" if "gemini" in candidate_name else request.app.state.settings.ai_provider
                                result = AIReply(content=text, provider=provider_name,
                                    model=getattr(candidate, "_model", request.app.state.settings.ai_model), fallback_used=index > 0,
                                    primary_model=request.app.state.settings.ai_model)
                            break
                        except AIProviderError:
                            if index == len(candidates) - 1:
                                raise
                    if result is None:
                        raise AIProviderError("A integração de IA não está configurada.", http_status=503)
                    break
                except AIProviderError as exc:
                    task_store.fail(task["id"], attempt, f"provider_http_{exc.http_status}")
                    if attempt >= MAX_AUTOMATIC_ATTEMPTS or not is_retryable_provider_error(exc):
                        raise
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)])
                    task = task_store.start_attempt(task["id"])
                    attempt = task["active_attempt"]
            if result is None:
                raise AIProviderError("A integra\u00e7\u00e3o de IA n\u00e3o est\u00e1 configurada.", http_status=503)
        task_store.complete(task["id"], attempt, result.content, result.provider, result.model, result.fallback_used)
    except AIProviderError as exc:
        task_store.fail(task["id"], attempt, f"provider_http_{exc.http_status}")
        raise HTTPException(status_code=exc.http_status, detail=str(exc), headers={"X-Atlas-Task-ID": task["id"]}) from None
    except Exception as exc:
        task_store.fail(task["id"], attempt, f"internal_{type(exc).__name__}")
        raise HTTPException(status_code=500, detail="Ocorreu uma falha ao concluir a resposta.", headers={"X-Atlas-Task-ID": task["id"]}) from None
    response.headers["X-Atlas-Task-ID"] = task["id"]
    return ChatResponse(reply=result.content, provider=result.provider, model=result.model,
        fallback_used=result.fallback_used, primary_model=result.primary_model, conversation_id=conversation_id)


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    """Stream generated text using SSE while preserving the existing chat endpoint."""
    if not any(message.role == "user" for message in payload.messages):
        raise HTTPException(status_code=422, detail="Envie ao menos uma mensagem do usu\u00e1rio.")

    provider = request.app.state.ai_provider
    if payload.conversation_id and request.app.state.memory.get_conversation(payload.conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversa n\u00e3o encontrada. Inicie uma nova conversa.")

    latest_user_text = next((m.content for m in reversed(payload.messages) if m.role == "user"), "")
    memory = request.app.state.long_term_memory
    extracted_facts = memory.extract_explicit_facts(latest_user_text)
    context = memory.build_context(latest_user_text, [
        {"role": item.role, "content": item.content} for item in payload.messages
    ])
    facts = {(fact["category"], fact["key"]): fact["value"] for fact in memory.list_facts()}
    normalized_question = " ".join(latest_user_text.lower().strip(" ?!.").split())
    direct_reply = None
    if extracted_facts:
        saved = extracted_facts[0]
        if saved["key"] in {"name", "preferred_name"}:
            direct_reply = f"Prazer em falar com voc\u00ea, {saved['value']}! Vou usar esse nome daqui em diante."
        elif saved["key"] == "location":
            direct_reply = f"Entendido. Vou considerar que voc\u00ea mora em {saved['value']}."
    if direct_reply is None and any(term in normalized_question for term in (
        "sabe meu nome", "qual meu nome", "como eu me chamo", "como me chamo",
        "lembra meu nome", "lembra como me chamo",
    )):
        name = facts.get(("profile", "preferred_name")) or facts.get(("profile", "name"))
        direct_reply = (f"Sei, {name}. \U0001f60a" if name else
            "Ainda n\u00e3o tenho seu nome registrado. Como gostaria que eu chamasse voc\u00ea?")
    if direct_reply is None and any(term in normalized_question for term in (
        "onde eu moro", "onde moro", "qual minha cidade", "qual cidade eu moro",
        "lembra onde moro", "lembra onde eu moro",
    )):
        location = facts.get(("profile", "location"))
        direct_reply = (f"Voc\u00ea me informou que mora em {location}." if location else
            "Ainda n\u00e3o tenho sua localiza\u00e7\u00e3o registrada. Se quiser, pode me contar.")

    messages = [ChatMessage(role=m.role, content=m.content) for m in payload.messages]
    if context:
        messages.insert(0, ChatMessage(role="system", content=context))

    task_store = request.app.state.task_repository
    continuation_text = "".join(
        character for character in unicodedata.normalize("NFKD", latest_user_text.lower())
        if not unicodedata.combining(character)
    )
    continuation_command = any(phrase in continuation_text for phrase in (
        "tente novamente", "tente de novo", "tenta de novo", "repita", "repete",
        "continue", "continua", "continue de onde parou", "voce nao terminou",
        "faca de outra maneira", "use outro modelo", "retome", "recomeca",
    ))
    resumed = payload.task_id is not None
    task = task_store.get(payload.task_id) if payload.task_id else None
    if payload.task_id and task is None:
        raise HTTPException(status_code=404, detail="Solicita\u00e7\u00e3o pendente n\u00e3o encontrada.")
    if task is None and continuation_command and payload.conversation_id:
        task = task_store.latest_resumable(payload.conversation_id)
        resumed = task is not None
    if task is not None:
        if payload.conversation_id and task["conversation_id"] != payload.conversation_id:
            raise HTTPException(status_code=409, detail="A solicita\u00e7\u00e3o pertence a outra conversa.")
        conversation_id = task["conversation_id"]
        messages = [ChatMessage(**item) for item in task["messages"]]
        if "outra maneira" in normalized_question:
            messages.append(ChatMessage(role="system", content="Reformule a resposta de outra maneira, mantendo a solicita\u00e7\u00e3o original."))
        if "outro modelo" in normalized_question:
            alternatives = [item for item in request.app.state.ai_providers.values() if item is not provider]
            if alternatives:
                provider = alternatives[0]
    else:
        try:
            task = task_store.create([{"role": message.role, "content": message.content} for message in messages], payload.conversation_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Conversa n\u00e3o encontrada. Inicie uma nova conversa.") from None
        conversation_id = task["conversation_id"]
    try:
        task = task_store.start_attempt(task["id"])
    except TaskConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    attempt_number = task["active_attempt"]
    cancel_event = asyncio.Event()
    request.app.state.task_cancel_events[task["id"]] = cancel_event

    async def events():
        started_at = time.perf_counter()
        first_token_ms: int | None = None
        result: AIReply | None = None
        active_attempt = attempt_number
        client_disconnected = False
        yield f"event: task\ndata: {json.dumps({'task_id': task['id'], 'conversation_id': conversation_id, 'resumed': resumed, 'prompt': task['prompt']}, ensure_ascii=False)}\n\n"
        try:
            while True:
                result = None
                emitted = False
                try:
                    if direct_reply is not None:
                        first_token_ms = round((time.perf_counter() - started_at) * 1000)
                        yield f"event: delta\ndata: {json.dumps({'text': direct_reply}, ensure_ascii=False)}\n\n"
                        result = AIReply(content=direct_reply, provider="atlas-memory", model="local-memory")
                    elif provider is None:
                        raise AIProviderError("A integracao de IA nao esta configurada.", http_status=503)
                    else:
                        candidates = [provider] + [item for item in request.app.state.ai_providers.values() if item is not provider]
                        for candidate_index, candidate in enumerate(candidates):
                            stream_method = getattr(candidate, "stream_reply_with_metadata", None)
                            if callable(stream_method):
                                provider_stream = stream_method(messages)
                                try:
                                    async for chunk in provider_stream:
                                        if cancel_event.is_set():
                                            task_store.cancel(task["id"])
                                            yield f"event: cancelled\ndata: {json.dumps({'task_id': task['id']}, ensure_ascii=False)}\n\n"
                                            return
                                        if not isinstance(chunk, AIStreamChunk):
                                            continue
                                        if chunk.text:
                                            emitted = True
                                            task_store.append_partial(task["id"], active_attempt, chunk.text)
                                            if first_token_ms is None:
                                                first_token_ms = round((time.perf_counter() - started_at) * 1000)
                                            yield f"event: delta\ndata: {json.dumps({'text': chunk.text}, ensure_ascii=False)}\n\n"
                                        if chunk.reply is not None:
                                            result = chunk.reply
                                            if candidate_index and not result.fallback_used:
                                                result = AIReply(content=result.content, provider=result.provider, model=result.model,
                                                    fallback_used=True, primary_model=request.app.state.settings.ai_model)
                                    if result is None and emitted:
                                        raise AIProviderError("A resposta do provedor foi interrompida.", http_status=503)
                                except AIProviderError:
                                    if emitted or candidate_index == len(candidates) - 1:
                                        raise
                                    logger.warning("Falha antes da resposta; tentando provedor alternativo.")
                                    continue
                                finally:
                                    close_stream = getattr(provider_stream, "aclose", None)
                                    if callable(close_stream):
                                        await close_stream()
                            else:
                                reply_text = await candidate.generate_reply(messages)
                                task_store.append_partial(task["id"], active_attempt, reply_text)
                                emitted = bool(reply_text)
                                first_token_ms = round((time.perf_counter() - started_at) * 1000)
                                yield f"event: delta\ndata: {json.dumps({'text': reply_text}, ensure_ascii=False)}\n\n"
                                candidate_name = type(candidate).__name__.lower()
                                result = AIReply(content=reply_text,
                                    provider="openai" if "openai" in candidate_name else "gemini" if "gemini" in candidate_name else request.app.state.settings.ai_provider,
                                    model=getattr(candidate, "_model", request.app.state.settings.ai_model),
                                    fallback_used=candidate_index > 0, primary_model=request.app.state.settings.ai_model)
                            if result is not None:
                                break
                        if result is None:
                            raise AIProviderError("A resposta do provedor foi encerrada sem metadados finais.")

                    if cancel_event.is_set():
                        task_store.cancel(task["id"])
                        yield f"event: cancelled\ndata: {json.dumps({'task_id': task['id']}, ensure_ascii=False)}\n\n"
                        return
                    task_store.complete(task["id"], active_attempt, result.content, result.provider,
                        result.model, result.fallback_used)
                    break
                except AIProviderError as exc:
                    task_store.fail(task["id"], active_attempt, f"provider_http_{exc.http_status}")
                    if (active_attempt >= MAX_AUTOMATIC_ATTEMPTS or not is_retryable_provider_error(exc)
                            or provider is None or cancel_event.is_set()):
                        yield f"event: error\ndata: {json.dumps({'detail': str(exc), 'status_code': exc.http_status, 'task_id': task['id']}, ensure_ascii=False)}\n\n"
                        return
                    delay = RETRY_BACKOFF_SECONDS[min(active_attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
                    yield f"event: retry\ndata: {json.dumps({'attempt': active_attempt + 1, 'delay_seconds': delay}, ensure_ascii=False)}\n\n"
                    # The previous attempt remains stored separately. Reset only
                    # the visible draft so text from attempts is never combined.
                    if emitted:
                        yield f"event: reset\ndata: {json.dumps({'task_id': task['id']}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(delay)
                    if cancel_event.is_set():
                        task_store.cancel(task["id"])
                        yield f"event: cancelled\ndata: {json.dumps({'task_id': task['id']}, ensure_ascii=False)}\n\n"
                        return
                    next_task = task_store.start_attempt(task["id"])
                    active_attempt = next_task["active_attempt"]
            done = {
                "conversation_id": conversation_id,
                "provider": result.provider,
                "model": result.model,
                "fallback_used": result.fallback_used,
                "primary_model": result.primary_model,
            }
            logger.info(
                "Chat conclu\u00eddo; provider=%s model=%s fallback=%s first_token_ms=%s total_ms=%s",
                result.provider, result.model, result.fallback_used, first_token_ms,
                round((time.perf_counter() - started_at) * 1000),
            )
            yield f"event: done\ndata: {json.dumps(done, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            client_disconnected = True
            raise
        except Exception as exc:
            task_store.fail(task["id"], active_attempt, f"internal_{type(exc).__name__}")
            logger.error("Falha inesperada no fluxo de chat; tipo=%s total_ms=%s",
                type(exc).__name__, round((time.perf_counter() - started_at) * 1000))
            yield f"event: error\ndata: {json.dumps({'detail': 'Ocorreu uma falha ao concluir a resposta.', 'task_id': task['id']}, ensure_ascii=False)}\n\n"
        finally:
            current = task_store.get(task["id"])
            if current and current["status"] == "processing":
                task_store.fail(task["id"], active_attempt, "stream_disconnected")
            if client_disconnected:
                asyncio.create_task(recover_tasks(request.app))
            request.app.state.task_cancel_events.pop(task["id"], None)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    })
