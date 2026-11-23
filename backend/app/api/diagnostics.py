"""Operational diagnostics for the A.T.L.A.S. application."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from backend.app.intelligence.provider import AIProviderError, ChatMessage

router = APIRouter(prefix="/api", tags=["diagnosticos"])


@router.get("/diagnostics")
async def diagnostics(request: Request) -> dict:
    """Report local configuration without exposing credentials or calling the AI API."""

    settings = request.app.state.settings
    provider = request.app.state.ai_provider
    key_configured = (
        bool(settings.gemini_api_key)
        if settings.ai_provider == "gemini"
        else bool(settings.openai_api_key)
    )
    return {
        "system": "A.T.L.A.S.",
        "backend": "online",
        "provider": settings.ai_provider,
        "model": settings.ai_model,
        "credential_configured": key_configured,
        "provider_initialized": provider is not None,
        "ai_connection": "not_tested",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/diagnostics/test")
async def test_ai_connection(request: Request) -> dict:
    """Perform an explicit, minimal live request to the configured AI provider."""

    provider = request.app.state.ai_provider
    settings = request.app.state.settings
    checked_at = datetime.now(timezone.utc).isoformat()

    if provider is None:
        return {
            "success": False,
            "provider": settings.ai_provider,
            "model": settings.ai_model,
            "message": "O provedor não foi inicializado. Confira a chave e a configuração.",
            "checked_at": checked_at,
        }

    try:
        await provider.generate_reply(
            [ChatMessage(role="user", content="Responda somente: conexão estabelecida.")]
        )
    except AIProviderError as exc:
        return {
            "success": False,
            "provider": settings.ai_provider,
            "model": settings.ai_model,
            "message": str(exc),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    return {
        "success": True,
        "provider": settings.ai_provider,
        "model": settings.ai_model,
        "message": "Conexão com o provedor de IA confirmada.",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
