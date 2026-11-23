from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.intelligence.provider import AIProviderError, ChatMessage
from backend.app.main import create_app


class FakeProvider:
    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        assert messages[-1].content == "Olá, A.T.L.A.S."
        return "Olá! Estou funcionando."


class UnavailableProvider:
    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        raise AIProviderError(
            "O serviço Gemini está temporariamente indisponível.",
            http_status=503,
        )


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


def test_chat_returns_safe_provider_error_and_status():
    app = create_app(
        settings=Settings(environment="test", ai_model="fake-model"),
        ai_provider=UnavailableProvider(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "Olá"}]},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "O serviço Gemini está temporariamente indisponível."


def test_existing_root_and_health_routes_are_preserved():
    app = create_app(settings=Settings(environment="test"))
    client = TestClient(app)

    assert client.get("/").json()["sistema"] == "A.T.L.A.S."
    assert client.get("/health").json()["status"] == "online"



def test_diagnostics_reports_backend_and_configuration_without_calling_provider():
    app = create_app(
        settings=Settings(
            environment="test",
            ai_provider="gemini",
            gemini_api_key="test-key",
            ai_model="test-model",
        ),
        ai_provider=FakeProvider(),
    )
    client = TestClient(app)

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "online"
    assert data["provider"] == "gemini"
    assert data["model"] == "test-model"
    assert data["credential_configured"] is True
    assert data["provider_initialized"] is True
    assert data["ai_connection"] == "not_tested"


def test_diagnostics_connection_test_uses_provider():
    app = create_app(
        settings=Settings(environment="test", ai_provider="gemini", ai_model="test-model"),
        ai_provider=FakeProvider(),
    )
    client = TestClient(app)

    response = client.post("/api/diagnostics/test")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["message"] == "Conexão com o provedor de IA confirmada."
