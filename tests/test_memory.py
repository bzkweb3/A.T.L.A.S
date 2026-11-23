from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app

from tests.test_chat import FakeProvider


def test_chat_is_saved_and_can_be_restored_after_app_restart(tmp_path):
    database_path = str(tmp_path / "atlas-test.db")
    settings = Settings(environment="test", ai_model="fake-model", database_path=database_path)

    first_client = TestClient(create_app(settings=settings, ai_provider=FakeProvider()))
    response = first_client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "Olá, A.T.L.A.S."}]},
    )

    assert response.status_code == 200
    conversation_id = response.json()["conversation_id"]
    saved = first_client.get(f"/api/conversations/{conversation_id}")

    assert saved.status_code == 200
    assert [message["role"] for message in saved.json()["messages"]] == ["user", "assistant"]
    assert saved.json()["messages"][0]["content"] == "Olá, A.T.L.A.S."

    second_client = TestClient(create_app(settings=settings, ai_provider=FakeProvider()))
    restored = second_client.get(f"/api/conversations/{conversation_id}")

    assert restored.status_code == 200
    assert restored.json()["id"] == conversation_id
    assert restored.json()["messages"][1]["content"] == "Olá! Estou funcionando."


def test_conversation_endpoint_returns_404_for_unknown_id():
    client = TestClient(create_app(settings=Settings(environment="test")))

    response = client.get("/api/conversations/does-not-exist")

    assert response.status_code == 404
