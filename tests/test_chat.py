from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.intelligence.provider import ChatMessage
from backend.app.main import create_app


class FakeProvider:
    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        assert messages[-1].content == "Olá, A.T.L.A.S."
        return "Olá! Estou funcionando."


def test_chat_returns_provider_response_without_real_api_call():
    app = create_app(
        settings=Settings(environment="test", openai_api_key=None, ai_model="fake-model"),
        ai_provider=FakeProvider(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "Olá, A.T.L.A.S."}]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "Olá! Estou funcionando.",
        "model": "fake-model",
    }


def test_chat_reports_missing_api_configuration():
    app = create_app(
        settings=Settings(environment="test", openai_api_key=None, ai_model="fake-model")
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "Olá"}]},
    )

    assert response.status_code == 503


def test_existing_root_and_health_routes_are_preserved():
    app = create_app(settings=Settings(environment="test"))
    client = TestClient(app)

    assert client.get("/").json()["sistema"] == "A.T.L.A.S."
    assert client.get("/health").json()["status"] == "online"
