"""Google Gemini implementation with live model discovery and automatic failover."""

import asyncio
import logging
import time

from google import genai
from google.genai import errors, types

from backend.app.core.config import Settings
from backend.app.intelligence.provider import AIProviderError, AIReply, ChatMessage

logger = logging.getLogger(__name__)

ATLAS_INSTRUCTIONS = (
    "Você é o A.T.L.A.S., um assistente digital inteligente, cordial e objetivo. "
    "Responda em português brasileiro por padrão. Seja claro, analítico e útil. "
    "Não afirme ter executado ações externas que não foram realmente realizadas. "
    "Respeite limites, permissões e solicitações de confirmação do usuário."
)

# Used only if the model catalog cannot be read. The catalog is the source of truth.
EMERGENCY_FALLBACK_MODELS = ("gemini-2.5-flash", "gemini-2.5-flash-lite")
RETRYABLE_STATUS_CODES = {404, 408, 429, 500, 502, 503, 504}
MODEL_CATALOG_TTL_SECONDS = 300


def _model_sequence(primary_model: str, available_models: list[str] | None = None) -> list[str]:
    """Prefer the configured model, then currently listed text-generation Flash models."""
    if available_models is None:
        candidates = list(EMERGENCY_FALLBACK_MODELS)
    else:
        candidates = [
            name.removeprefix("models/")
            for name in available_models
            if "flash" in name.lower()
            and not any(term in name.lower() for term in ("image", "tts", "audio"))
        ]
    # Full Flash models are preferred to Lite models; names sort newest-first as a tie-break.
    candidates = sorted(
        set(candidates),
        key=lambda name: ("-flash-lite" in name.lower(), name.lower()),
        reverse=False,
    )
    return list(dict.fromkeys((primary_model, *candidates)))


def _provider_error(status_code: int | None) -> AIProviderError:
    if status_code in {401, 403}:
        return AIProviderError(
            "O Google recusou o acesso à API Gemini. Verifique a chave e as permissões no Google AI Studio.",
            http_status=502,
        )
    if status_code == 429:
        return AIProviderError(
            "O limite de uso dos modelos Gemini foi atingido. Tente novamente mais tarde.",
            http_status=503,
        )
    if status_code in {404, 408, 500, 502, 503, 504}:
        return AIProviderError(
            "Os modelos Gemini disponíveis estão temporariamente indisponíveis. Tente novamente em alguns instantes.",
            http_status=503,
        )
    return AIProviderError(
        f"O Gemini não concluiu a solicitação (código {status_code or 'desconhecido'}). Consulte os registros do servidor.",
        http_status=502,
    )


class GeminiProvider:
    """Adapter that discovers usable models and fails over without user intervention."""

    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise AIProviderError("GEMINI_API_KEY não está configurada.", http_status=503)
        self._api_key = settings.gemini_api_key
        self._model = settings.ai_model
        self._cached_models: list[str] = []
        self._catalog_checked_at = 0.0
        self._catalog_lock = asyncio.Lock()

    async def _available_models(self, client) -> list[str]:
        """Read Google's live model catalog and cache it briefly."""
        now = time.monotonic()
        if self._cached_models and now - self._catalog_checked_at < MODEL_CATALOG_TTL_SECONDS:
            return self._cached_models

        async with self._catalog_lock:
            now = time.monotonic()
            if self._cached_models and now - self._catalog_checked_at < MODEL_CATALOG_TTL_SECONDS:
                return self._cached_models
            try:
                pager = await client.models.list(config={"page_size": 100})
                discovered: list[str] = []
                async for item in pager:
                    actions = getattr(item, "supported_actions", None) or []
                    name = getattr(item, "name", None)
                    if name and "generateContent" in actions:
                        discovered.append(name)
                if discovered:
                    self._cached_models = discovered
                    self._catalog_checked_at = now
            except Exception as exc:
                logger.warning(
                    "Não foi possível atualizar o catálogo Gemini; usando catálogo em cache/emergência. tipo=%s",
                    type(exc).__name__,
                )
            return self._cached_models

    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        result = await self.generate_reply_with_metadata(messages)
        return result.content

    async def generate_reply_with_metadata(self, messages: list[ChatMessage]) -> AIReply:
        contents = [
            {
                "role": "model" if message.role == "assistant" else "user",
                "parts": [{"text": message.content}],
            }
            for message in messages
        ]
        http_options = types.HttpOptions(
            timeout=12_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        )
        last_status: int | None = None
        failures: list[str] = []

        try:
            async with genai.Client(
                api_key=self._api_key,
                http_options=http_options,
            ).aio as client:
                available = await self._available_models(client)
                models = _model_sequence(self._model, available or None)
                for model in models:
                    try:
                        response = await client.models.generate_content(
                            model=model,
                            contents=contents,
                            config={
                                "system_instruction": (
                                    ATLAS_INSTRUCTIONS
                                    + f"\n\nMETADADOS INTERNOS DE EXECUÇÃO: o modelo que está gerando esta resposta é {model}. "
                                    + "Se o usuário perguntar qual modelo está respondendo, informe exatamente esse identificador. "
                                    + "Não diga apenas o nome da família Gemini e não invente versões."
                                )
                            },
                        )
                        answer = (response.text or "").strip()
                        if answer:
                            fallback_used = model != self._model
                            if fallback_used:
                                logger.warning(
                                    "Gemini fallback acionado; modelo_principal=%s, modelo_utilizado=%s.",
                                    self._model,
                                    model,
                                )
                            return AIReply(
                                content=answer,
                                provider="gemini",
                                model=model,
                                fallback_used=fallback_used,
                                primary_model=self._model,
                            )
                        failures.append(f"{model}: resposta vazia")
                        logger.warning("Gemini retornou resposta vazia; modelo=%s.", model)
                    except errors.APIError as exc:
                        status_code = getattr(exc, "code", None)
                        last_status = status_code
                        logger.warning(
                            "Falha na API Gemini; modelo=%s, código_http=%s.",
                            model,
                            status_code,
                        )
                        if status_code in {401, 403} or status_code not in RETRYABLE_STATUS_CODES:
                            raise _provider_error(status_code) from None
                        failures.append(f"{model}: HTTP {status_code}")
                    except (TimeoutError, OSError) as exc:
                        logger.warning(
                            "Timeout ou falha de rede no Gemini; modelo=%s, tipo=%s.",
                            model,
                            type(exc).__name__,
                        )
                        failures.append(f"{model}: timeout/rede")
        except AIProviderError:
            raise
        except (TimeoutError, OSError) as exc:
            logger.warning("Falha de conexão com a API Gemini: %s", type(exc).__name__)
            raise AIProviderError(
                "Não foi possível conectar aos modelos Gemini. Verifique a conexão e tente novamente.",
                http_status=504,
            ) from None

        logger.error(
            "Todos os modelos Gemini falharam; modelos=%s, falhas=%s.",
            models if "models" in locals() else [],
            failures,
        )
        raise _provider_error(last_status)
