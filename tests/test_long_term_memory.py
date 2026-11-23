from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.intelligence.provider import ChatMessage


class MemoryAwareProvider:
    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        system = next((m.content for m in messages if m.role == "system"), "")
        assert "Brendo" in system
        return "Seu nome é Brendo."


def test_explicit_name_is_remembered_and_injected_into_new_chat():
    client = TestClient(create_app(settings=Settings(environment="test"), ai_provider=MemoryAwareProvider()))
    saved = client.post("/api/memory/facts", json={"category": "profile", "key": "name", "value": "Brendo"})
    assert saved.status_code == 200
    assert client.get("/api/memory").json()["facts"][0]["value"] == "Brendo"
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Você sabe meu nome?"}]})
    assert response.status_code == 200
    assert response.json()["reply"] == "Seu nome é Brendo."


def test_name_is_extracted_from_explicit_user_statement():
    class EchoMemoryProvider:
        async def generate_reply(self, messages):
            return "Registrado."
    client = TestClient(create_app(settings=Settings(environment="test"), ai_provider=EchoMemoryProvider()))
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Meu nome é Brendo."}]})
    assert response.status_code == 200
    facts = client.get("/api/memory").json()["facts"]
    assert any(f["key"] == "name" and f["value"] == "Brendo" for f in facts)
