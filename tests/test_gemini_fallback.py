import asyncio
from types import SimpleNamespace

from google.genai import errors

from backend.app.core.config import Settings
from backend.app.intelligence.gemini_provider import (
    DEFAULT_FALLBACK_MODELS,
    GeminiProvider,
    _model_sequence,
)
from backend.app.intelligence.provider import AIProviderError, ChatMessage


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.called_models = []

    async def generate_content(self, *, model, contents, config):
        self.called_models.append(model)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


class FakeClient:
    def __init__(self, models):
        self.models = models
        self.aio = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def test_model_sequence_uses_primary_then_unique_fallbacks():
    assert _model_sequence("gemini-3.8-flash") == [
        "gemini-3.8-flash",
        *DEFAULT_FALLBACK_MODELS,
    ]
    assert _model_sequence("gemini-3.5-flash-lite") == [
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash-lite",
    ]


def test_gemini_provider_uses_fallback_after_temporary_unavailability(monkeypatch):
    models = FakeModels([
        errors.ServerError(503, {"error": {"message": "busy"}}, None),
        "Resposta pelo modelo alternativo.",
    ])
    fake_client = FakeClient(models)
    monkeypatch.setattr(
        "backend.app.intelligence.gemini_provider.genai.Client",
        lambda **kwargs: fake_client,
    )
    provider = GeminiProvider(
        Settings(environment="test", gemini_api_key="test-key", ai_model="gemini-3.8-flash")
    )

    answer = asyncio.run(
        provider.generate_reply([ChatMessage(role="user", content="Olá")])
    )

    assert answer == "Resposta pelo modelo alternativo."
    assert models.called_models == [
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
    ]


def test_gemini_provider_stops_fallback_when_credentials_are_rejected(monkeypatch):
    models = FakeModels([
        errors.APIError(403, {"error": {"message": "forbidden"}}, None),
        "Não deve ser usado.",
    ])
    fake_client = FakeClient(models)
    monkeypatch.setattr(
        "backend.app.intelligence.gemini_provider.genai.Client",
        lambda **kwargs: fake_client,
    )
    provider = GeminiProvider(
        Settings(environment="test", gemini_api_key="test-key", ai_model="gemini-3.8-flash")
    )

    try:
        asyncio.run(provider.generate_reply([ChatMessage(role="user", content="Olá")]))
        raise AssertionError("Era esperado AIProviderError.")
    except AIProviderError:
        pass

    assert models.called_models == ["gemini-3.8-flash"]
