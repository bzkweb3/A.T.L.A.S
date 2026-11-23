"""Google Gemini implementation of the provider-independent contract."""

import logging

from google import genai
from google.genai import errors, types

from backend.app.core.config import Settings
from backend.app.intelligence.provider import AIProviderError, ChatMessage

logger = logging.getLogger(__name__)

ATLAS_INSTRUCTIONS = (
    "Você é o A.T.L.A.S., um assistente digital inteligente, cordial e objetivo. "
    "Responda em português brasileiro por padrão. Seja claro, analítico e útil. "
    "Não afirme ter executado ações externas que não foram realmente realizadas. "
    "Respeite limites, permissões e solicitações de confirmação do usuário."
)

def _provider_error(status_code: int | None) -> AIProviderError:
    if status_code == 404:
        return AIProviderError(
            "O modelo Gemini configurado não foi encontrado ou não está disponível para esta chave. "
            "Confira ATLAS_AI_MODEL e os modelos liberados no Google AI Studio.",
            http_status=502,
        )
    if status_code in {401, 403}:
        return AIProviderError(
            "O Google recusou o acesso à API Gemini. Verifique a chave e as permissões no Google AI Studio.",
            http_status=502,
        )
    if status_code == 429:
        return AIProviderError(
            "O Gemini atingiu o limite de requisições ou de uso da cota. Tente novamente mais tarde.",
            http_status=503,
        )
    if status_code in {500, 502, 503, 504}:
        return AIProviderError(
            "O serviço Gemini está temporariamente indisponível. Nenhuma nova tentativa automática será feita; tente novamente em alguns instantes.",
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

    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        contents = [
            {
                "role": "model" if message.role == "assistant" else "user",
                "parts": [{"text": message.content}],
            }
            for message in messages
        ]

        # 12-second request timeout and one total attempt prevent stacked SDK/app retries.
        http_options = types.HttpOptions(
            timeout=12_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        )
        try:
            async with genai.Client(
                api_key=self._api_key,
                http_options=http_options,
            ).aio as client:
                response = await client.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config={"system_instruction": ATLAS_INSTRUCTIONS},
                )
        except errors.APIError as exc:
            status_code = getattr(exc, "code", None)
            logger.warning(
                "Falha na API Gemini; modelo=%s, código_http=%s.",
                self._model,
                status_code,
            )
            raise _provider_error(status_code) from None
        except (TimeoutError, OSError) as exc:
            logger.warning("Timeout ou falha de rede ao chamar Gemini: %s", type(exc).__name__)
            raise AIProviderError(
                "O Gemini demorou mais de 12 segundos ou está inacessível. Tente novamente.",
                http_status=504,
            ) from None

        answer = (response.text or "").strip()
        if not answer:
            raise AIProviderError("O Gemini retornou uma resposta vazia.")
        return answer
