from datetime import datetime, timezone

from fastapi import FastAPI

app = FastAPI(
    title="A.T.L.A.S.",
    description="Assistente de Tarefas, Linguagem, Automação e Sistemas",
    version="0.1.0"
)


@app.get("/")
async def inicio():
    return {
        "sistema": "A.T.L.A.S.",
        "status": "operacional",
        "mensagem": "Núcleo central iniciado.",
        "versao": "0.1.0"
    }


@app.get("/health")
async def verificar_saude():
    return {
        "sistema": "A.T.L.A.S.",
        "status": "online",
        "horario": datetime.now(timezone.utc).isoformat()
    }
