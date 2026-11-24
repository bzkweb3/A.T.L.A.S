"""Google Gemini implementation with live model discovery and automatic failover."""

import asyncio
import logging
import time

import httpx
from google import genai
from google.genai import errors, types

from backend.app.core.config import Settings
from backend.app.core.identity import ATLAS_IDENTITY_POLICY
from backend.app.intelligence.provider import AIProviderError, AIReply, AIStreamChunk, ChatMessage

logger = logging.getLogger(__name__)

ATLAS_INSTRUCTIONS = (
    ATLAS_IDENTITY_POLICY + " "
    "Você é um assistente digital inteligente, cordial e objetivo. "
    "Responda em português brasileiro por padrão. Seja claro, analítico e útil. "
    "Você não tem busca na web nem acesso a preços ou notícias em tempo real nesta conversa. "
    "Isso não impede que você ajude com planejamento, estruturação, cálculos e modelos de documentos. "
    "Quando a tarefa depender de dados atuais, diga claramente o que precisa ser verificado; nunca invente esses dados. "
    "Não afirme ter executado ações externas que não foram realmente realizadas. "
    "Respeite limites, permissões e solicitações de confirmação do usuário."
)
EMERGENCY_FALLBACK_MODELS = (
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
)
DEPRECATED_MODEL_ALIASES = {
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash",
}
RETRYABLE_STATUS_CODES = {404, 408, 429, 500, 502, 503, 504}
MODEL_CATALOG_TTL_SECONDS = 300


def _model_sequence(primary_model: str, available_models: list[str] | None = None) -> list[str]:
    if available_models is None:
        candidates = list(EMERGENCY_FALLBACK_MODELS)
    else:
        candidates = [name.removeprefix("models/") for name in available_models
            if "flash" in name.lower()
            and name.removeprefix("models/").lower() not in DEPRECATED_MODEL_ALIASES
            and not any(term in name.lower() for term in ("image", "tts", "audio"))]
    candidates = [
        name for name in set(candidates)
        if "omni" not in name.lower() and "audio" not in name.lower()
    ]
    fallback_priority = {name: index for index, name in enumerate(EMERGENCY_FALLBACK_MODELS)}
    candidates.sort(key=lambda name: (
        fallback_priority.get(name, len(fallback_priority)),
        "preview" in name.lower(),
        name.lower(),
    ))
    # Keep failover bounded: a long list of unavailable models creates
    # unnecessary latency and repeated quota errors for a single user turn.
    return list(dict.fromkeys((primary_model, *candidates[:3])))


def _provider_error(status_code: int | None) -> AIProviderError:
    if status_code in {401, 403}:
        return AIProviderError("O Google recusou o acesso à API Gemini. Verifique a chave e as permissões no Google AI Studio.", http_status=502)
    if status_code == 429:
        return AIProviderError("O limite de uso dos modelos Gemini foi atingido. Tente novamente mais tarde.", http_status=503)
    if status_code in {404, 408, 500, 502, 503, 504}:
        return AIProviderError("Os modelos Gemini disponíveis estão temporariamente indisponíveis. Tente novamente em alguns instantes.", http_status=503)
    return AIProviderError(f"O Gemini não concluiu a solicitação (código {status_code or 'desconhecido'}). Consulte os registros do servidor.", http_status=502)


class GeminiProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise AIProviderError("GEMINI_API_KEY não está configurada.", http_status=503)
        self._api_key, self._model = settings.gemini_api_key, settings.ai_model
        self._cached_models: list[str] = []
        self._catalog_checked_at = 0.0
        self._catalog_lock = asyncio.Lock()

    async def _available_models(self, client) -> list[str]:
        now = time.monotonic()
        if self._cached_models and now - self._catalog_checked_at < MODEL_CATALOG_TTL_SECONDS:
            return self._cached_models
        async with self._catalog_lock:
            now = time.monotonic()
            if self._cached_models and now - self._catalog_checked_at < MODEL_CATALOG_TTL_SECONDS:
                return self._cached_models
            try:
                pager = await client.models.list(config={"page_size": 100})
                discovered = []
                async for item in pager:
                    actions, name = getattr(item, "supported_actions", None) or [], getattr(item, "name", None)
                    if name and "generateContent" in actions:
                        discovered.append(name)
                if discovered:
                    self._cached_models, self._catalog_checked_at = discovered, now
            except Exception as exc:
                logger.warning("Falha ao atualizar catálogo Gemini; tipo=%s", type(exc).__name__)
            return self._cached_models

    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        return (await self.generate_reply_with_metadata(messages)).content

    async def generate_reply_with_metadata(self, messages: list[ChatMessage]) -> AIReply:
        system_context = "\n\n".join(m.content for m in messages if m.role == "system")
        contents = [{"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in messages if m.role != "system"]
        http_options = types.HttpOptions(
            timeout=30_000,
            retry_options=types.HttpRetryOptions(
                attempts=2,
                initial_delay=0.5,
                max_delay=2.0,
                exp_base=2.0,
                jitter=0.2,
                http_status_codes=[408, 500, 502, 503, 504],
            ),
        )
        last_status, failures = None, []
        try:
            async with genai.Client(api_key=self._api_key, http_options=http_options).aio as client:
                # Do not make a catalog request on the healthy primary path.
                models = [self._model]
                for model in models:
                    try:
                        thinking_level = "MINIMAL" if "flash-lite" in model.lower() else "LOW"
                        system_instruction = (
                            ATLAS_INSTRUCTIONS
                            + ("\n\n" + system_context if system_context else "")
                            + "\n\nNão revele nomes internos de modelos, provedores, identificadores técnicos ou detalhes de infraestrutura. "
                            + "Se perguntarem qual modelo está ativo, explique apenas que você está usando a melhor opção disponível no momento."
                        )
                        response = await client.models.generate_content(
                            model=model,
                            contents=contents,
                            config={
                                "system_instruction": system_instruction,
                                "thinking_config": {"thinking_level": thinking_level},
                            },
                        )
                        answer = (response.text or "").strip()
                        if answer:
                            fallback = model != self._model
                            if fallback:
                                logger.warning("Gemini fallback acionado; modelo_principal=%s, modelo_utilizado=%s.", self._model, model)
                            return AIReply(content=answer, provider="gemini", model=model, fallback_used=fallback, primary_model=self._model)
                        failures.append(f"{model}: resposta vazia")
                        if model == self._model:
                            available = await self._available_models(client)
                            models.extend(name for name in _model_sequence(self._model, available or None)
                                if name not in models)
                    except errors.APIError as exc:
                        status = getattr(exc, "code", None)
                        last_status = status
                        logger.warning("Falha na API Gemini; modelo=%s, código_http=%s.", model, status)
                        if status in {401, 403} or status not in RETRYABLE_STATUS_CODES:
                            raise _provider_error(status) from None
                        failures.append(f"{model}: HTTP {status}")
                        if model == self._model:
                            available = await self._available_models(client)
                            models.extend(name for name in _model_sequence(self._model, available or None)
                                if name not in models)
                    except httpx.TimeoutException:
                        last_status = 504
                        logger.warning("Timeout na API Gemini; modelo=%s.", model)
                        failures.append(f"{model}: timeout")
                        if model == self._model:
                            available = await self._available_models(client)
                            models.extend(name for name in _model_sequence(self._model, available or None)
                                if name not in models)
                    except (httpx.RequestError, TimeoutError, OSError):
                        last_status = 502
                        logger.warning("Falha de transporte na API Gemini; modelo=%s.", model)
                        failures.append(f"{model}: timeout/rede")
                        if model == self._model:
                            available = await self._available_models(client)
                            models.extend(name for name in _model_sequence(self._model, available or None)
                                if name not in models)
        except AIProviderError:
            raise
        except httpx.TimeoutException:
            raise AIProviderError("Não foi possível conectar aos modelos Gemini. Verifique a conexão e tente novamente.", http_status=504) from None
        except (httpx.RequestError, TimeoutError, OSError):
            raise AIProviderError("Não foi possível conectar aos modelos Gemini. Verifique a conexão e tente novamente.", http_status=502) from None
        logger.error("Todos os modelos Gemini falharam; modelos=%s, falhas=%s", models if "models" in locals() else [], failures)
        raise _provider_error(last_status)

    async def stream_reply_with_metadata(self, messages: list[ChatMessage]):
        """Stream provider text; retry with another model only before emitting text."""
        system_context = "\n\n".join(m.content for m in messages if m.role == "system")
        contents = [{"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in messages if m.role != "system"]
        http_options = types.HttpOptions(
            timeout=30_000,
            retry_options=types.HttpRetryOptions(
                attempts=2, initial_delay=0.5, max_delay=2.0, exp_base=2.0,
                jitter=0.2, http_status_codes=[408, 500, 502, 503, 504],
            ),
        )
        failures: list[str] = []
        last_status: int | None = None
        models = [self._model]
        try:
            async with genai.Client(api_key=self._api_key, http_options=http_options).aio as client:
                index = 0
                while index < len(models):
                    model = models[index]
                    index += 1
                    emitted = False
                    answer_parts: list[str] = []
                    try:
                        thinking_level = "MINIMAL" if "flash-lite" in model.lower() else "LOW"
                        system_instruction = (
                            ATLAS_INSTRUCTIONS
                            + ("\n\n" + system_context if system_context else "")
                            + "\n\nN\u00e3o revele nomes internos de modelos, provedores, identificadores t\u00e9cnicos ou detalhes de infraestrutura. "
                            + "Se perguntarem qual modelo est\u00e1 ativo, explique apenas que voc\u00ea est\u00e1 usando a melhor op\u00e7\u00e3o dispon\u00edvel no momento."
                        )
                        stream = await client.models.generate_content_stream(
                            model=model,
                            contents=contents,
                            config={"system_instruction": system_instruction,
                                "thinking_config": {"thinking_level": thinking_level}},
                        )
                        async for chunk in stream:
                            text = (getattr(chunk, "text", None) or "")
                            if text:
                                emitted = True
                                answer_parts.append(text)
                                yield AIStreamChunk(text=text)
                        answer = "".join(answer_parts).strip()
                        if answer:
                            reply = AIReply(content=answer, provider="gemini", model=model,
                                fallback_used=model != self._model, primary_model=self._model)
                            if reply.fallback_used:
                                logger.warning("Gemini fallback acionado; modelo_principal=%s, modelo_utilizado=%s.", self._model, model)
                            yield AIStreamChunk(reply=reply)
                            return
                        if emitted:
                            raise AIProviderError("O Gemini encerrou uma resposta vazia.")
                        failures.append(f"{model}: resposta vazia")
                    except errors.APIError as exc:
                        status = getattr(exc, "code", None)
                        last_status = status
                        logger.warning("Falha na API Gemini; modelo=%s, c\u00f3digo_http=%s.", model, status)
                        if emitted or status in {401, 403} or status not in RETRYABLE_STATUS_CODES:
                            raise _provider_error(status) from None
                        failures.append(f"{model}: HTTP {status}")
                    except httpx.TimeoutException:
                        last_status = 504
                        if emitted:
                            raise AIProviderError("A conex\u00e3o com o Gemini foi interrompida durante a resposta.", http_status=504) from None
                        failures.append(f"{model}: timeout")
                    except (httpx.RequestError, TimeoutError, OSError):
                        last_status = 502
                        if emitted:
                            raise AIProviderError("A conex\u00e3o com o Gemini foi interrompida durante a resposta.", http_status=502) from None
                        failures.append(f"{model}: timeout/rede")
                    if index == 1:
                        available = await self._available_models(client)
                        models.extend(name for name in _model_sequence(self._model, available or None)
                            if name not in models)
        except AIProviderError:
            raise
        except httpx.TimeoutException:
            raise AIProviderError("N\u00e3o foi poss\u00edvel conectar aos modelos Gemini. Verifique a conex\u00e3o e tente novamente.", http_status=504) from None
        except (httpx.RequestError, TimeoutError, OSError):
            raise AIProviderError("N\u00e3o foi poss\u00edvel conectar aos modelos Gemini. Verifique a conex\u00e3o e tente novamente.", http_status=502) from None
        logger.error("Todos os modelos Gemini falharam; modelos=%s, falhas=%s", models, failures)
        raise _provider_error(last_status)
