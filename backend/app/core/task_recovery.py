"""Bounded automatic recovery for interrupted, text-only chat tasks."""

import asyncio
import logging

from backend.app.intelligence.provider import AIProviderError, AIReply, AIStreamChunk, ChatMessage

logger = logging.getLogger(__name__)

MAX_AUTOMATIC_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1.0, 2.0)
RETRYABLE_PROVIDER_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


def is_retryable_provider_error(error: AIProviderError) -> bool:
    return error.http_status in RETRYABLE_PROVIDER_STATUSES


async def recover_tasks(application) -> None:
    """Retry eligible persisted chat tasks after startup, with bounded backoff.

    Tasks are ordinary text generation requests. This runner must not be reused
    for tools or tasks that can cause external side effects.
    """
    repository = application.state.task_repository
    primary = application.state.ai_provider
    candidates = ([primary] if primary is not None else []) + [
        provider for provider in application.state.ai_providers.values() if provider is not primary
    ]
    unique_candidates = []
    for provider in candidates:
        if all(provider is not existing for existing in unique_candidates):
            unique_candidates.append(provider)
    candidates = unique_candidates
    for task in repository.pending():
        if task["status"] not in {"failed", "partially_completed", "pending"}:
            continue
        while task["attempt_count"] < MAX_AUTOMATIC_ATTEMPTS and candidates:
            if task["attempt_count"]:
                delay_index = min(task["attempt_count"] - 1, len(RETRY_BACKOFF_SECONDS) - 1)
                await asyncio.sleep(RETRY_BACKOFF_SECONDS[delay_index])
            try:
                task = repository.start_attempt(task["id"])
            except Exception:
                # A live request may have claimed it after the scan.
                break
            attempt = task["active_attempt"]
            try:
                messages = [ChatMessage(**item) for item in task["messages"]]
                result = None
                last_error = None
                for provider_index, provider in enumerate(candidates):
                    try:
                        stream = getattr(provider, "stream_reply_with_metadata", None)
                        if callable(stream):
                            text = ""
                            metadata = None
                            async for chunk in stream(messages):
                                if not isinstance(chunk, AIStreamChunk):
                                    continue
                                if chunk.text:
                                    text += chunk.text
                                    repository.append_partial(task["id"], attempt, chunk.text)
                                if chunk.reply is not None:
                                    metadata = chunk.reply
                            if metadata is None:
                                raise AIProviderError("O provedor encerrou sem resposta final.", http_status=503)
                            result = AIReply(
                                content=metadata.content or text,
                                provider=metadata.provider,
                                model=metadata.model,
                                fallback_used=metadata.fallback_used or provider_index > 0,
                                primary_model=metadata.primary_model,
                            )
                        else:
                            content = await provider.generate_reply(messages)
                            name = type(provider).__name__.lower()
                            result = AIReply(
                                content=content,
                                provider="openai" if "openai" in name else "gemini" if "gemini" in name else application.state.settings.ai_provider,
                                model=getattr(provider, "_model", application.state.settings.ai_model),
                                fallback_used=provider_index > 0,
                                primary_model=application.state.settings.ai_model,
                            )
                        break
                    except AIProviderError as exc:
                        last_error = exc
                        continue
                if result is None:
                    raise last_error or AIProviderError("Nenhum provedor disponível.", http_status=503)
                repository.complete(task["id"], attempt, result.content, result.provider, result.model, result.fallback_used)
                logger.info("Solicitação interrompida recuperada; task_id=%s tentativa=%s", task["id"], attempt)
                break
            except AIProviderError as exc:
                repository.fail(task["id"], attempt, f"provider_http_{exc.http_status}")
                task = repository.get(task["id"])
                if not is_retryable_provider_error(exc):
                    break
            except Exception as exc:
                repository.fail(task["id"], attempt, f"internal_{type(exc).__name__}")
                logger.warning("Recuperação automática falhou; task_id=%s tipo=%s", task["id"], type(exc).__name__)
                task = repository.get(task["id"])
