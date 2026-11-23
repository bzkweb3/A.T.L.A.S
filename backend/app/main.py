from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from backend.app.api.chat import router as chat_router
from backend.app.api.conversations import memory_router, router as conversations_router
from backend.app.api.diagnostics import router as diagnostics_router
from backend.app.core.config import Settings, load_settings
from backend.app.core.memory import ConversationStore
from backend.app.core.long_term_memory import LongTermMemory
from backend.app.persistence.sqlite import SQLiteDatabase
from backend.app.intelligence.gemini_provider import GeminiProvider
from backend.app.intelligence.openai_provider import OpenAIProvider
from backend.app.intelligence.provider import AIProvider, AIProviderError

FRONTEND_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


def create_app(settings: Settings | None = None, ai_provider: AIProvider | None = None) -> FastAPI:
    app_settings = settings or load_settings()
    application = FastAPI(title="A.T.L.A.S.", description="Assistente de Tarefas, Linguagem, Automação e Sistemas", version="0.4.0")
    application.state.settings = app_settings
    database = SQLiteDatabase(app_settings.database_path)
    application.state.database = database
    application.state.memory = ConversationStore(database)
    application.state.long_term_memory = LongTermMemory(database)

    if ai_provider is not None:
        application.state.ai_provider = ai_provider
    elif app_settings.ai_provider == "gemini" and app_settings.gemini_api_key:
        try:
            application.state.ai_provider = GeminiProvider(app_settings)
        except AIProviderError:
            application.state.ai_provider = None
    elif app_settings.ai_provider == "openai" and app_settings.openai_api_key:
        try:
            application.state.ai_provider = OpenAIProvider(app_settings)
        except AIProviderError:
            application.state.ai_provider = None
    else:
        application.state.ai_provider = None

    application.include_router(chat_router)
    application.include_router(diagnostics_router)
    application.include_router(conversations_router)
    application.include_router(memory_router)

    @application.get("/")
    async def inicio():
        return {"sistema": "A.T.L.A.S.", "status": "operacional", "mensagem": "Núcleo central iniciado. A interface está disponível em /app.", "versao": "0.4.0"}

    @application.get("/app", include_in_schema=False)
    async def interface():
        return FileResponse(FRONTEND_INDEX)

    @application.get("/health")
    async def verificar_saude():
        return {"sistema": "A.T.L.A.S.", "status": "online", "horario": datetime.now(timezone.utc).isoformat()}

    return application


app = create_app()
