import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse

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
from backend.app.api.auth import require_authenticated, router as auth_router
from backend.app.core.auth import AuthService
from backend.app.core.local_security import LocalSecurityMiddleware
from backend.app.persistence.auth_repository import AuthRepository
from backend.app.persistence.task_repository import TaskRepository
from backend.app.core.task_recovery import recover_tasks

FRONTEND_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


def create_app(settings: Settings | None = None, ai_provider: AIProvider | None = None) -> FastAPI:
    app_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        # Recovery is limited to persisted, ordinary text generation tasks.
        application.state.task_recovery_handle = asyncio.create_task(recover_tasks(application))
        try:
            yield
        finally:
            recovery = application.state.task_recovery_handle
            if recovery is not None and not recovery.done():
                recovery.cancel()
                try:
                    await recovery
                except asyncio.CancelledError:
                    pass
            application.state.task_recovery_handle = None

    application = FastAPI(title="A.T.L.A.S.", description="Assistente de Tarefas, Linguagem, Automação e Sistemas", version="0.4.0", lifespan=lifespan)
    application.state.settings = app_settings
    database = SQLiteDatabase(app_settings.database_path)
    application.state.database = database
    application.state.auth_repository = AuthRepository(database)
    application.state.auth_service = AuthService(application.state.auth_repository)
    application.state.memory = ConversationStore(database)
    application.state.long_term_memory = LongTermMemory(database)
    application.state.task_repository = TaskRepository(database)
    application.state.task_repository.recover_interrupted()
    application.state.task_cancel_events = {}

    providers = {}
    if ai_provider is not None:
        application.state.ai_provider = ai_provider
        providers[app_settings.ai_provider] = ai_provider
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

    # Use another already-configured provider as a pre-output fallback. Each
    # provider gets its own model default; secrets stay inside provider objects.
    if ai_provider is None:
        if app_settings.ai_provider != "gemini" and app_settings.gemini_api_key:
            try:
                providers["gemini"] = GeminiProvider(replace(app_settings, ai_provider="gemini", ai_model="gemini-3.8-flash"))
            except AIProviderError:
                pass
        if app_settings.ai_provider != "openai" and app_settings.openai_api_key:
            try:
                providers["openai"] = OpenAIProvider(replace(app_settings, ai_provider="openai", ai_model="gpt-5.5"))
            except AIProviderError:
                pass
    if application.state.ai_provider is not None:
        providers[app_settings.ai_provider] = application.state.ai_provider
    elif providers:
        application.state.ai_provider = next(iter(providers.values()))
    application.state.ai_providers = providers
    application.state.task_recovery_handle = None

    application.add_middleware(LocalSecurityMiddleware)
    application.include_router(auth_router)
    application.include_router(chat_router, dependencies=[Depends(require_authenticated)])
    application.include_router(diagnostics_router, dependencies=[Depends(require_authenticated)])
    application.include_router(conversations_router, dependencies=[Depends(require_authenticated)])
    application.include_router(memory_router, dependencies=[Depends(require_authenticated)])

    @application.get("/")
    async def inicio():
        return {"sistema": "A.T.L.A.S.", "status": "operacional", "mensagem": "Núcleo central iniciado. A interface está disponível em /app.", "versao": "0.4.0"}

    @application.get("/app", include_in_schema=False)
    async def interface(request: Request):
        if application.state.auth_repository.get_session(request.cookies.get("atlas_session", "")) is None:
            return RedirectResponse("/login", status_code=303)
        return FileResponse(FRONTEND_INDEX)

    @application.get("/login", include_in_schema=False)
    async def login_interface():
        return FileResponse(FRONTEND_INDEX.parent / "login.html")

    @application.get("/health")
    async def verificar_saude():
        return {"sistema": "A.T.L.A.S.", "status": "online", "horario": datetime.now(timezone.utc).isoformat()}

    return application


app = create_app()
