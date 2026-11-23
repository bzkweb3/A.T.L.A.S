"""Google Gemini implementation of the provider-independent contract."""

from google import genai
from google.genai import errors

from backend.app.core.config import Settings
from backend.app.intelligence.provider import AIProviderError, ChatMessage

ATLAS_INSTRUCTIONS = (
    "Você é o A.T.L.A.S., um assistente digital inteligente, cordial e objetivo. "
    "Responda em português brasileiro por padrão. Seja claro, analítico e útil. "
    "Não afirme ter executado ações externas que não foram realmente realizadas. "
    "Respeite limites, permissões e solicitações de confirmação do usuário."
)


class GeminiProvider:
    """Adapter that connects the A.T.L.A.S. core to Google's Gemini API."""

    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise AIProviderError("GEMINI_API_KEY não está configurada.")
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

        try:
            async with genai.Client(api_key=self._api_key).aio as client:
                response = await client.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config={"system_instruction": ATLAS_INSTRUCTIONS},
                )
        except errors.APIError:
            raise AIProviderError(
                "Não foi possível obter uma resposta do provedor Gemini."
            ) from None

        answer = (response.text or "").strip()
        if not answer:
            raise AIProviderError("O Gemini retornou uma resposta vazia.")
        return answer
