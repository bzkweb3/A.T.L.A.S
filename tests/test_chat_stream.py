import asyncio
import json

from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app.api.chat import ChatRequest, MessageInput, chat_stream
from backend.app.core.config import Settings
from backend.app.intelligence.provider import AIProviderError, AIReply, AIStreamChunk, ChatMessage
from backend.app.main import create_app
from tests.auth_helpers import owner_client


class StreamingProvider:
    def __init__(self, failure=None):
        self.failure = failure
        self.closed = asyncio.Event()
        self.resume = asyncio.Event()

    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        return "Resposta legada."

    async def stream_reply_with_metadata(self, messages: list[ChatMessage]):
        try:
            if self.failure == "before":
                raise AIProviderError("Falha temporária do provedor.", http_status=503)
            yield AIStreamChunk(text="Primeiro ")
            if self.failure == "after":
                raise AIProviderError("Falha temporária do provedor.", http_status=503)
            yield AIStreamChunk(text="segundo trecho.")
            yield AIStreamChunk(reply=AIReply(
                content="Primeiro segundo trecho.", provider="fake", model="fake-model"
            ))
        finally:
            self.closed.set()


def _app(provider):
    return create_app(
        settings=Settings(environment="test", ai_provider="gemini", ai_model="fake-model"),
        ai_provider=provider,
    )


def _scope(app):
    return {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/chat/stream", "raw_path": b"/api/chat/stream",
        "query_string": b"", "headers": [], "client": ("test", 1234),
        "server": ("test", 80), "app": app,
    }


def _payload():
    return ChatRequest(messages=[MessageInput(role="user", content="teste de streaming")])


def _events(response_text):
    parsed = []
    for frame in response_text.replace("\r\n", "\n").split("\n\n"):
        if not frame.strip():
            continue
        event_name = next((line[6:].strip() for line in frame.splitlines() if line.startswith("event:")), None)
        data = next((line[5:].strip() for line in frame.splitlines() if line.startswith("data:")), "{}")
        parsed.append((event_name, json.loads(data)))
    return parsed


def test_stream_route_sends_deltas_then_done_and_persists_only_complete_exchange(caplog):
    provider = StreamingProvider()
    app = _app(provider)
    with owner_client(app) as client:
        response = client.post("/api/chat/stream", json={
            "messages": [{"role": "user", "content": "private-prompt-marker"}],
        })
        assert response.status_code == 200
        events = _events(response.text)
        assert [data["text"] for name, data in events if name == "delta"] == [
            "Primeiro ", "segundo trecho."
        ]
        assert events[-1][0] == "done"
        assert events[-1][1]["provider"] == "fake"
        assert len(client.get("/api/conversations").json()["conversations"]) == 1
        assert "private-prompt-marker" not in caplog.text
        assert "test-key" not in caplog.text
    assert provider.closed.is_set()


def test_stream_route_reports_failure_before_first_delta_without_saving():
    app = _app(StreamingProvider(failure="before"))
    with owner_client(app) as client:
        response = client.post("/api/chat/stream", json={
            "messages": [{"role": "user", "content": "teste"}],
        })
        events = _events(response.text)
        assert not any(name == "delta" for name, _ in events)
        assert events[-1][0] == "error"
        assert events[-1][1]["detail"] == "Falha temporária do provedor."
        assert events[-1][1]["task_id"]
        assert len(client.get("/api/conversations").json()["conversations"]) == 1
        tasks = client.get("/api/tasks/pending").json()["tasks"]
        assert tasks[0]["status"] == "failed"
        assert tasks[0]["prompt"] == "teste"


def test_stream_route_retries_failure_after_delta_without_mixing_attempts(monkeypatch):
    monkeypatch.setattr("backend.app.api.chat.RETRY_BACKOFF_SECONDS", (0, 0))
    app = _app(StreamingProvider(failure="after"))
    with owner_client(app) as client:
        response = client.post("/api/chat/stream", json={
            "messages": [{"role": "user", "content": "teste"}],
        })
        events = _events(response.text)
        assert [data["text"] for name, data in events if name == "delta"] == ["Primeiro "] * 3
        assert sum(name == "retry" for name, _ in events) == 2
        assert sum(name == "reset" for name, _ in events) == 2
        assert events[-1][0] == "error"
        assert len(client.get("/api/conversations").json()["conversations"]) == 1
        task = client.get("/api/tasks/pending").json()["tasks"][0]
        assert task["status"] == "partially_completed"
        assert [attempt["partial_text"] for attempt in task["attempts"]] == ["Primeiro "] * 3


def test_streaming_is_progressive_and_cancellation_closes_provider_iterator():
    provider = StreamingProvider()
    app = _app(provider)

    async def exercise():
        response = await chat_stream(_payload(), Request(_scope(app)))
        iterator = response.body_iterator
        task_event = await anext(iterator)
        assert "event: task" in task_event
        first = await anext(iterator)
        assert '"text": "Primeiro "' in first
        assert not provider.closed.is_set()
        await iterator.aclose()
        assert provider.closed.is_set()
        assert app.state.memory.get_conversation(app.state.task_repository.pending()[0]["conversation_id"])["messages"] == []
        assert app.state.task_repository.pending()[0]["status"] == "partially_completed"

    asyncio.run(exercise())


def test_existing_non_streaming_chat_endpoint_remains_compatible():
    provider = StreamingProvider()
    app = _app(provider)
    with owner_client(app) as client:
        response = client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "teste legado"}],
        })
    assert response.status_code == 200
    assert response.json()["reply"] == "Resposta legada."
