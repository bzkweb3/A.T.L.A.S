"""OpenAI implementation of the provider-independent intelligence contract."""

from openai import AsyncOpenAI, OpenAIError

from backend.app.core.config import Settings
from backend.app.intelligence.provider import AIProviderError, ChatMessage

ATLAS_INSTRUCTIONS = (
    "Você é o A.T.L.A.S., um assistente digital inteligente, cordial e objetivo. "
    "Responda em português brasileiro por padrão. Seja claro, analítico e útil. "
    "Não afirme ter executado ações externas que não foram realmente realizadas. "
    "Respeite limites, permissões e solicitações de confirmação do usuário."
)


class OpenAIProvider:
    """Adapter that connects the A.T.L.A.S. core to OpenAI's Responses API."""

    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise AIProviderError("OPENAI_API_KEY não está configurada.")
        self._api_key = settings.openai_api_key
        self._model = settings.ai_model

    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        try:
            async with AsyncOpenAI(api_key=self._api_key, timeout=45.0) as client:
                response = await client.responses.create(
                    model=self._model,
                    instructions=ATLAS_INSTRUCTIONS,
                    input=[
                        {"role": message.role, "content": message.content}
                        for message in messages
                    ],
                )
        except OpenAIError:
            raise AIProviderError(
                "Não foi possível obter uma resposta do provedor de IA."
            ) from None

        answer = (response.output_text or "").strip()
        if not answer:
            raise AIProviderError("O provedor de IA retornou uma resposta vazia.")
        return answer
