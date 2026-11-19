"""A.T.L.A.S. API entry point."""

from datetime import datetime, timezone

from fastapi import FastAPI

from backend.app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    description="Assistente de Tarefas, Linguagem, Automação e Sistemas",
    version=settings.app_version,
)


@app.get("/", tags=["system"])
async def inicio() -> dict[str, str]:
    return {
        "sistema": settings.app_name,
        "status": "operacional",
        "mensagem": "Núcleo central iniciado.",
        "versao": settings.app_version,
    }


@app.get("/health", tags=["system"])
async def verificar_saude() -> dict[str, str]:
    return {
        "sistema": settings.app_name,
        "status": "online",
        "ambiente": settings.environment,
        "horario": datetime.now(timezone.utc).isoformat(),
    }
