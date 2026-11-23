import asyncio
from types import SimpleNamespace

import httpx
from google.genai import errors

from backend.app.core.config import Settings
from backend.app.intelligence.gemini_provider import (
    GeminiProvider,
    _model_sequence,
)
from backend.app.intelligence.provider import AIProviderError, ChatMessage


class FakePager:
    def __init__(self, items):
        self.items = items

    def __aiter__(self):
        self._iterator = iter(self.items)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration


class FakeModels:
    def __init__(self, outcomes, catalog=None):
        self.outcomes = iter(outcomes)
        self.called_models = []
        self.catalog = catalog or [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-2.5-flash-lite", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-embedding-001", supported_actions=["embedContent"]),
        ]

    async def list(self, config=None):
        return FakePager(self.catalog)

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


def test_model_sequence_uses_only_live_text_generation_models():
    assert _model_sequence(
        "gemini-3.8-flash",
        [
            "models/gemini-2.5-flash",
            "models/gemini-2.5-flash-lite",
            "models/gemini-3.5-flash",
            "models/gemini-3.5-flash-lite",
            "models/gemini-3.6-flash",
            "models/gemini-embedding-001",
            "models/gemini-3.1-flash-tts",
        ],
    ) == [
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash-lite",
    ]


def test_gemini_provider_uses_discovered_fallback_after_temporary_unavailability(monkeypatch):
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
        "gemini-2.5-flash-lite",
    ]


def test_gemini_provider_converts_httpx_timeout_to_provider_error(monkeypatch):
    models = FakeModels([
        httpx.ReadTimeout("request timed out"),
        httpx.ReadTimeout("request timed out"),
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
        raise AssertionError("Era esperado AIProviderError para timeout HTTPX.")
    except AIProviderError as exc:
        assert exc.http_status == 503

    assert models.called_models == ["gemini-3.8-flash", "gemini-2.5-flash-lite"]


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
