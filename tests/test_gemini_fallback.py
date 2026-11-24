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
        self.catalog_calls = 0
        self.catalog = catalog or [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-2.5-flash-lite", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-3.6-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-3.5-flash-lite", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-embedding-001", supported_actions=["embedContent"]),
        ]

    async def list(self, config=None):
        self.catalog_calls += 1
        return FakePager(self.catalog)

    async def generate_content(self, *, model, contents, config):
        self.called_models.append(model)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)

    async def generate_content_stream(self, *, model, contents, config):
        self.called_models.append(model)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeAsyncStream([
            part if isinstance(part, Exception) else SimpleNamespace(text=part)
            for part in outcome
        ])


class FakeAsyncStream:
    def __init__(self, chunks):
        self.chunks = chunks

    def __aiter__(self):
        self._iterator = iter(self.chunks)
        return self

    async def __anext__(self):
        try:
            chunk = next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration
        if isinstance(chunk, Exception):
            raise chunk
        return chunk


class FakeClient:
    def __init__(self, models):
        self.models = models
        self.aio = self
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.closed = True
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
        "gemini-3.6-flash",
    ]


def test_gemini_provider_converts_httpx_timeout_to_provider_error(monkeypatch):
    models = FakeModels([
        httpx.ReadTimeout("request timed out"),
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

    assert models.called_models == [
        "gemini-3.8-flash",
        "gemini-3.6-flash",
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


def test_gemini_stream_contract_emits_deltas_and_avoids_catalog_on_primary_success(monkeypatch):
    from backend.app.intelligence.provider import AIStreamChunk

    models = FakeModels([["Parcial ", "completa."]])
    fake_client = FakeClient(models)
    monkeypatch.setattr(
        "backend.app.intelligence.gemini_provider.genai.Client",
        lambda **kwargs: fake_client,
    )
    provider = GeminiProvider(
        Settings(environment="test", gemini_api_key="test-key", ai_model="gemini-3.8-flash")
    )

    async def collect():
        return [event async for event in provider.stream_reply_with_metadata(
            [ChatMessage(role="user", content="teste")]
        )]

    events = asyncio.run(collect())

    assert [event.text for event in events if event.text] == ["Parcial ", "completa."]
    assert isinstance(events[-1], AIStreamChunk)
    assert events[-1].reply.content == "Parcial completa."
    assert events[-1].reply.provider == "gemini"
    assert models.catalog_calls == 0


def test_gemini_stream_falls_back_before_first_delta_but_not_after(monkeypatch):
    models = FakeModels([
        errors.ServerError(503, {"error": {"message": "private upstream detail"}}, None),
        ["Resposta alternativa."],
    ])
    fake_client = FakeClient(models)
    monkeypatch.setattr(
        "backend.app.intelligence.gemini_provider.genai.Client",
        lambda **kwargs: fake_client,
    )
    provider = GeminiProvider(
        Settings(environment="test", gemini_api_key="test-key", ai_model="gemini-3.8-flash")
    )

    async def collect():
        return [event async for event in provider.stream_reply_with_metadata(
            [ChatMessage(role="user", content="teste")]
        )]

    events = asyncio.run(collect())
    assert models.called_models == ["gemini-3.8-flash", "gemini-3.6-flash"]
    assert events[-1].reply.fallback_used is True

    models_after_delta = FakeModels([
        ["Parcial.", errors.ServerError(503, {"error": {"message": "private upstream detail"}}, None)],
    ])
    fake_client_after_delta = FakeClient(models_after_delta)
    monkeypatch.setattr(
        "backend.app.intelligence.gemini_provider.genai.Client",
        lambda **kwargs: fake_client_after_delta,
    )
    provider_after_delta = GeminiProvider(
        Settings(environment="test", gemini_api_key="test-key", ai_model="gemini-3.8-flash")
    )

    async def fail_after_delta():
        result = []
        try:
            async for event in provider_after_delta.stream_reply_with_metadata(
                [ChatMessage(role="user", content="teste")]
            ):
                result.append(event)
        except AIProviderError as exc:
            assert "private upstream detail" not in str(exc)
            return result
        raise AssertionError("Falha do provedor deveria interromper o streaming.")

    partial_events = asyncio.run(fail_after_delta())
    assert [event.text for event in partial_events] == ["Parcial."]
    assert models_after_delta.called_models == ["gemini-3.8-flash"]


def test_gemini_stream_cancellation_closes_sdk_client(monkeypatch):
    models = FakeModels([["primeiro", "segundo"]])
    fake_client = FakeClient(models)
    monkeypatch.setattr(
        "backend.app.intelligence.gemini_provider.genai.Client",
        lambda **kwargs: fake_client,
    )
    provider = GeminiProvider(
        Settings(environment="test", gemini_api_key="test-key", ai_model="gemini-3.8-flash")
    )

    async def cancel():
        stream = provider.stream_reply_with_metadata([ChatMessage(role="user", content="teste")])
        first = await anext(stream)
        assert first.text == "primeiro"
        await stream.aclose()

    asyncio.run(cancel())
    assert fake_client.closed is True
