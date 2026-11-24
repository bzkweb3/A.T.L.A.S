import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.intelligence.provider import AIProviderError, AIReply, AIStreamChunk, ChatMessage
from backend.app.main import create_app
from backend.app.persistence.task_repository import TaskConflictError, TaskRepository
from backend.app.persistence.sqlite import SQLiteDatabase
from tests.auth_helpers import owner_client


class RecoverableProvider:
    def __init__(self):
        self.fail = True
        self.fail_before_output = False
        self.calls = []

    async def generate_reply(self, messages):
        return ""

    async def stream_reply_with_metadata(self, messages: list[ChatMessage]):
        self.calls.append(messages)
        if self.fail:
            if self.fail_before_output:
                raise AIProviderError("Indisponível temporariamente.", http_status=503)
            yield AIStreamChunk(text="Trecho inicial.")
            raise AIProviderError("Indisponível temporariamente.", http_status=503)
        yield AIStreamChunk(text="Resposta retomada completa.")
        yield AIStreamChunk(reply=AIReply(
            content="Resposta retomada completa.", provider="fake", model="fake-model"
        ))


class SecondaryProvider:
    async def generate_reply(self, messages):
        return ""

    async def stream_reply_with_metadata(self, messages):
        yield AIStreamChunk(text="Resposta alternativa.")
        yield AIStreamChunk(reply=AIReply(
            content="Resposta alternativa.", provider="secondary", model="secondary-model"
        ))


class RetryableLegacyProvider:
    def __init__(self):
        self.calls = 0

    async def generate_reply(self, messages):
        return ""

    async def generate_reply_with_metadata(self, messages):
        self.calls += 1
        if self.calls == 1:
            raise AIProviderError("temporariamente indisponível", http_status=503)
        return AIReply(content="Resposta concluída após nova tentativa.", provider="fake", model="fake-model")


def _app(provider):
    return create_app(Settings(environment="test"), ai_provider=provider)


def test_failed_task_is_automatically_retried_then_explicitly_resumable(monkeypatch):
    monkeypatch.setattr("backend.app.api.chat.RETRY_BACKOFF_SECONDS", (0, 0))
    provider = RecoverableProvider()
    app = _app(provider)
    with owner_client(app) as client:
        first = client.post("/api/chat/stream", json={
            "messages": [{"role": "user", "content": "Escreva uma história identificável de teste."}],
        })
        assert first.text.count("event: retry") == 2
        assert first.text.count("event: reset") == 2
        conversation_id = next(
            json.loads(frame.split("data:", 1)[1])['conversation_id']
            for frame in first.text.split("\n\n") if frame.startswith("event: task")
        )
        task = client.get("/api/tasks/pending", params={"conversation_id": conversation_id}).json()["tasks"][0]
        assert task["status"] == "partially_completed"
        assert task["attempts"][0]["partial_text"] == "Trecho inicial."
        assert len(task["attempts"]) == 3
        assert client.get(f"/api/conversations/{conversation_id}").json()["messages"] == []

        provider.fail = False
        resumed = client.post("/api/chat/stream", json={
            "messages": [{"role": "user", "content": "tente novamente"}],
            "conversation_id": conversation_id,
        })
        assert '"resumed": true' in resumed.text
        assert "Escreva uma história identificável de teste." in provider.calls[-1][-1].content
        assert "tente novamente" not in provider.calls[1][-1].content
        completed = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
        assert [message["role"] for message in completed] == ["user", "assistant"]
        assert completed[-1]["content"] == "Resposta retomada completa."
        assert client.get("/api/tasks/pending", params={"conversation_id": conversation_id}).json()["tasks"] == []
        final_task = client.get(f"/api/tasks/{task['id']}").json()["task"]
        assert [attempt["status"] for attempt in final_task["attempts"]] == [
            "partially_completed", "partially_completed", "partially_completed", "completed",
        ]


def test_processing_task_cannot_be_claimed_twice():
    database = SQLiteDatabase(":memory:")
    repository = TaskRepository(database)
    task = repository.create([{"role": "user", "content": "solicitação"}], None)
    repository.start_attempt(task["id"])
    with pytest.raises(TaskConflictError):
        repository.start_attempt(task["id"])


def test_server_restart_automatically_recovers_inflight_task(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.core.task_recovery.RETRY_BACKOFF_SECONDS", (0, 0))
    path = str(tmp_path / "tasks.sqlite")
    first_database = SQLiteDatabase(path)
    first_repository = TaskRepository(first_database)
    task = first_repository.create([{"role": "user", "content": "pedido interrompido"}], None)
    first_repository.start_attempt(task["id"])
    first_repository.append_partial(task["id"], 1, "parte")

    provider = RecoverableProvider()
    provider.fail = False
    restarted_app = create_app(Settings(environment="test", database_path=path), ai_provider=provider)
    recovered = restarted_app.state.task_repository.get(task["id"])
    assert recovered["status"] == "partially_completed"
    assert recovered["attempts"][0]["partial_text"] == "parte"
    assert recovered["attempts"][0]["error_code"] == "server_interrupted"
    with TestClient(restarted_app):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            recovered = restarted_app.state.task_repository.get(task["id"])
            if recovered["status"] == "completed":
                break
            time.sleep(0.01)
    assert recovered["status"] == "completed"
    assert provider.calls
    assert recovered["attempts"][-1]["partial_text"] == "Resposta retomada completa."


def test_new_request_does_not_replace_or_reuse_previous_pending_task():
    database = SQLiteDatabase(":memory:")
    repository = TaskRepository(database)
    first = repository.create([{"role": "user", "content": "pedido anterior"}], None)
    second = repository.create([{"role": "user", "content": "pedido novo e diferente"}], first["conversation_id"])
    assert first["id"] != second["id"]
    assert [task["prompt"] for task in repository.pending(first["conversation_id"])] == [
        "pedido novo e diferente", "pedido anterior",
    ]


@pytest.mark.parametrize("command", [
    "tente novamente", "continue de onde parou", "você não terminou",
    "faça de outra maneira", "use outro modelo",
])
def test_contextual_continuation_phrases_resume_the_last_pending_task(command):
    provider = RecoverableProvider()
    app = _app(provider)
    with owner_client(app) as client:
        first = client.post("/api/chat/stream", json={
            "messages": [{"role": "user", "content": "pedido original de continuidade"}],
        })
        task_event = next(frame for frame in first.text.split("\n\n") if frame.startswith("event: task"))
        conversation_id = json.loads(task_event.split("data:", 1)[1])["conversation_id"]
        provider.fail = False
        response = client.post("/api/chat/stream", json={
            "messages": [{"role": "user", "content": command}],
            "conversation_id": conversation_id,
        })
        assert '"resumed": true' in response.text
        assert any(message.content == "pedido original de continuidade" for message in provider.calls[-1])


def test_pre_output_failure_uses_secondary_provider_without_changing_task():
    primary = RecoverableProvider()
    primary.fail_before_output = True
    app = _app(primary)
    secondary = SecondaryProvider()
    app.state.ai_providers["secondary"] = secondary
    with owner_client(app) as client:
        response = client.post("/api/chat/stream", json={
            "messages": [{"role": "user", "content": "solicitação com fallback"}],
        })
        assert 'event: done' in response.text
        assert "Resposta alternativa." in response.text
        task = client.get("/api/tasks/pending").json()["tasks"]
        assert task == []
        conversation_id = json.loads(next(
            frame for frame in response.text.split("\n\n") if frame.startswith("event: task")
        ).split("data:", 1)[1])["conversation_id"]
        message = client.get(f"/api/conversations/{conversation_id}").json()["messages"][-1]
        assert message["provider"] == "secondary"
        assert message["fallback_used"] == 1


def test_legacy_json_chat_retries_provider_error_and_persists_completion(monkeypatch):
    monkeypatch.setattr("backend.app.api.chat.RETRY_BACKOFF_SECONDS", (0, 0))
    provider = RetryableLegacyProvider()
    app = _app(provider)
    with owner_client(app) as client:
        response = client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "pedido pelo endpoint legado"}],
        })
        assert response.status_code == 200
        assert response.json()["reply"] == "Resposta concluída após nova tentativa."
        assert provider.calls == 2
        task = app.state.task_repository.pending()
        assert task == []
        persisted = app.state.task_repository.get(response.headers["X-Atlas-Task-ID"])
        assert [attempt["status"] for attempt in persisted["attempts"]] == ["failed", "completed"]


def test_explicit_cancel_marks_task_cancelled_and_removes_it_from_pending():
    app = _app(RecoverableProvider())
    task = app.state.task_repository.create([{"role": "user", "content": "cancelar"}], None)
    with owner_client(app) as client:
        response = client.post(f"/api/tasks/{task['id']}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert client.get("/api/tasks/pending").json()["tasks"] == []
