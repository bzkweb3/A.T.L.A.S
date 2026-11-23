"""Google Gemini implementation with automatic model failover."""

import logging

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

# Ordered by preference for the current development stage.
DEFAULT_FALLBACK_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash-lite",
)
RETRYABLE_STATUS_CODES = {404, 408, 429, 500, 502, 503, 504}


def _model_sequence(primary_model: str) -> list[str]:
    """Return the configured model followed by unique fallback models."""
    return list(dict.fromkeys((primary_model, *DEFAULT_FALLBACK_MODELS)))


def _provider_error(status_code: int | None) -> AIProviderError:
    if status_code in {401, 403}:
        return AIProviderError(
            "O Google recusou o acesso à API Gemini. Verifique a chave e as permissões no Google AI Studio.",
            http_status=502,
        )
    if status_code == 429:
        return AIProviderError(
            "Todos os modelos Gemini disponíveis atingiram limites de uso. Tente novamente mais tarde.",
            http_status=503,
        )
    if status_code in {404, 408, 500, 502, 503, 504}:
        return AIProviderError(
            "Nenhum dos modelos Gemini disponíveis conseguiu atender à solicitação. Tente novamente em alguns instantes.",
            http_status=503,
        )
    return AIProviderError(
        f"O Gemini não concluiu a solicitação (código {status_code or 'desconhecido'}). Consulte os registros do servidor.",
        http_status=502,
    )


class GeminiProvider:
    """Adapter that connects the A.T.L.A.S. core to Google's Gemini API."""

    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise AIProviderError("GEMINI_API_KEY não está configurada.", http_status=503)
        self._api_key = settings.gemini_api_key
        self._model = settings.ai_model
        self._models = _model_sequence(self._model)

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
            timeout=10_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        )
        last_status: int | None = None
        failures: list[str] = []

        try:
            async with genai.Client(
                api_key=self._api_key,
                http_options=http_options,
            ).aio as client:
                for model in self._models:
                    try:
                        response = await client.models.generate_content(
                            model=model,
                            contents=contents,
                            config={"system_instruction": ATLAS_INSTRUCTIONS},
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
            self._models,
            failures,
        )
        raise _provider_error(last_status)
