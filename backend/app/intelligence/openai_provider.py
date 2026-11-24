"""OpenAI implementation of the provider-independent intelligence contract."""

from openai import AsyncOpenAI, OpenAIError

from backend.app.core.config import Settings
from backend.app.core.identity import ATLAS_IDENTITY_POLICY
from backend.app.intelligence.provider import AIProviderError, AIReply, AIStreamChunk, ChatMessage

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


class OpenAIProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise AIProviderError("OPENAI_API_KEY não está configurada.")
        self._api_key, self._model = settings.openai_api_key, settings.ai_model

    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        system_context = "\n\n".join(m.content for m in messages if m.role == "system")
        input_messages = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        try:
            async with AsyncOpenAI(api_key=self._api_key, timeout=45.0) as client:
                response = await client.responses.create(
                    model=self._model,
                    instructions=ATLAS_INSTRUCTIONS + ("\n\n" + system_context if system_context else ""),
                    input=input_messages,
                )
        except OpenAIError:
            raise AIProviderError("Não foi possível obter uma resposta do provedor de IA.") from None
        answer = (response.output_text or "").strip()
        if not answer:
            raise AIProviderError("O provedor de IA retornou uma resposta vazia.")
        return answer

    async def stream_reply_with_metadata(self, messages: list[ChatMessage]):
        """Stream text deltas from the Responses API using server-sent events."""
        system_context = "\n\n".join(m.content for m in messages if m.role == "system")
        input_messages = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        answer_parts: list[str] = []
        try:
            async with AsyncOpenAI(api_key=self._api_key, timeout=45.0) as client:
                stream = await client.responses.create(
                    model=self._model,
                    instructions=ATLAS_INSTRUCTIONS + ("\n\n" + system_context if system_context else ""),
                    input=input_messages,
                    stream=True,
                )
                async for event in stream:
                    event_type = getattr(event, "type", None)
                    if event_type in {"error", "response.failed"}:
                        raise AIProviderError("O provedor OpenAI n\u00e3o conseguiu concluir a resposta.")
                    if event_type == "response.output_text.delta":
                        delta = getattr(event, "delta", "")
                        if delta:
                            answer_parts.append(delta)
                            yield AIStreamChunk(text=delta)
        except AIProviderError:
            raise
        except OpenAIError:
            raise AIProviderError("N\u00e3o foi poss\u00edvel obter uma resposta do provedor de IA.") from None
        answer = "".join(answer_parts).strip()
        if not answer:
            raise AIProviderError("O provedor de IA retornou uma resposta vazia.")
        yield AIStreamChunk(reply=AIReply(content=answer, provider="openai", model=self._model))
