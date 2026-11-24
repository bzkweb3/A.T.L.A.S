import asyncio
from types import SimpleNamespace

from openai import OpenAIError

from backend.app.core.config import Settings
from backend.app.intelligence.openai_provider import OpenAIProvider
from backend.app.intelligence.provider import AIProviderError, AIStreamChunk, ChatMessage


class FakeEventStream:
    def __init__(self, events):
        self.events = events

    def __aiter__(self):
        self.iterator = iter(self.events)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


class FakeResponses:
    def __init__(self, events=None, failure=None):
        self.events = events or []
        self.failure = failure
        self.call = None

    async def create(self, **kwargs):
        self.call = kwargs
        if self.failure:
            raise self.failure
        return FakeEventStream(self.events)


class FakeOpenAIClient:
    def __init__(self, responses):
        self.responses = responses
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.closed = True


def test_openai_stream_contract_emits_text_deltas_and_final_metadata(monkeypatch):
    responses = FakeResponses(events=[
        SimpleNamespace(type="response.output_text.delta", delta="Olá "),
        SimpleNamespace(type="response.output_text.delta", delta="A.T.L.A.S."),
        SimpleNamespace(type="response.completed"),
    ])
    client = FakeOpenAIClient(responses)
    monkeypatch.setattr(
        "backend.app.intelligence.openai_provider.AsyncOpenAI",
        lambda **kwargs: client,
    )
    provider = OpenAIProvider(Settings(
        environment="test", openai_api_key="test-key", ai_provider="openai", ai_model="fake-model"
    ))

    async def collect():
        return [event async for event in provider.stream_reply_with_metadata(
            [ChatMessage(role="user", content="teste")]
        )]

    events = asyncio.run(collect())
    assert [event.text for event in events if event.text] == ["Olá ", "A.T.L.A.S."]
    assert isinstance(events[-1], AIStreamChunk)
    assert events[-1].reply.content == "Olá A.T.L.A.S."
    assert events[-1].reply.provider == "openai"
    assert responses.call["stream"] is True
    assert client.closed is True


def test_openai_sdk_exception_is_sanitized_for_stream_consumers(monkeypatch):
    responses = FakeResponses(failure=OpenAIError("private token and endpoint details"))
    client = FakeOpenAIClient(responses)
    monkeypatch.setattr(
        "backend.app.intelligence.openai_provider.AsyncOpenAI",
        lambda **kwargs: client,
    )
    provider = OpenAIProvider(Settings(
        environment="test", openai_api_key="test-key", ai_provider="openai", ai_model="fake-model"
    ))

    async def consume():
        try:
            async for _ in provider.stream_reply_with_metadata(
                [ChatMessage(role="user", content="teste")]
            ):
                pass
        except AIProviderError as exc:
            return str(exc)
        raise AssertionError("Esperava erro de provedor sanitizado.")

    message = asyncio.run(consume())
    assert "private token" not in message
    assert "endpoint details" not in message
    assert client.closed is True


def test_openai_stream_cancellation_closes_sdk_client(monkeypatch):
    responses = FakeResponses(events=[
        SimpleNamespace(type="response.output_text.delta", delta="primeiro"),
        SimpleNamespace(type="response.output_text.delta", delta="segundo"),
    ])
    client = FakeOpenAIClient(responses)
    monkeypatch.setattr(
        "backend.app.intelligence.openai_provider.AsyncOpenAI",
        lambda **kwargs: client,
    )
    provider = OpenAIProvider(Settings(
        environment="test", openai_api_key="test-key", ai_provider="openai", ai_model="fake-model"
    ))

    async def cancel():
        stream = provider.stream_reply_with_metadata([ChatMessage(role="user", content="teste")])
        first = await anext(stream)
        assert first.text == "primeiro"
        await stream.aclose()

    asyncio.run(cancel())
    assert client.closed is True
