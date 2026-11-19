
from datetime import datetime, timezone

from fastapi import FastAPI

from backend.app.core.config import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the HTTP application with its configuration supplied up front."""

    app_settings = settings or load_settings()
    application = FastAPI(
        title="A.T.L.A.S.",
        description="Assistente de Tarefas, Linguagem, Automação e Sistemas",
        version="0.1.0",
    )
    application.state.settings = app_settings

    @application.get("/")
    async def inicio():
        return {
            "sistema": "A.T.L.A.S.",
            "status": "operacional",
            "mensagem": "Núcleo central iniciado.",
            "versao": "0.1.0",
        }

    @application.get("/health")
    async def verificar_saude():
        return {
            "sistema": "A.T.L.A.S.",
            "status": "online",
            "horario": datetime.now(timezone.utc).isoformat(),
        }

    return application


app = create_app()
